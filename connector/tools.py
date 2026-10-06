"""Single source of truth for the agent-facing tools.

The same registry feeds: the MCP server, the HTTP bridge, the OpenAI demo agent,
and the exported tool specs. All tools are READ-ONLY.
"""
from dataclasses import dataclass
from typing import Callable

import jsonschema

from . import config
from .client import WooClient, WooError

_client: WooClient | None = None


def get_client() -> WooClient:
    global _client
    if _client is None:
        _client = WooClient()
    return _client


def set_client(c: WooClient | None):
    global _client
    _client = c


# ---------- PII handling ----------
def mask_email(e: str) -> str:
    if not e or "@" not in e:
        return ""
    local, dom = e.split("@", 1)
    return f"{local[:1]}***@{dom}"


def mask_phone(p: str) -> str:
    digits = "".join(c for c in (p or "") if c.isdigit())
    return f"******{digits[-2:]}" if len(digits) >= 2 else ""


def _customer(o: dict, redact: bool) -> dict:
    b = o.get("billing") or {}
    name = f"{b.get('first_name', '')} {b.get('last_name', '')}".strip()
    c = {"name": name, "city": b.get("city"), "state": b.get("state"), "country": b.get("country")}
    if redact:
        c.update(email=mask_email(b.get("email", "")), phone=mask_phone(b.get("phone", "")))
    else:
        c.update(email=b.get("email"), phone=b.get("phone"), address=b.get("address_1"), postcode=b.get("postcode"))
    return c


def _order_summary(o: dict, redact: bool) -> dict:
    return {
        "id": o["id"], "number": o.get("number"), "status": o.get("status"),
        "date_created": o.get("date_created"), "total": o.get("total"), "currency": o.get("currency"),
        "item_count": sum(i.get("quantity", 0) for i in o.get("line_items", [])),
        "customer": _customer(o, redact),
    }


def _order_detail(o: dict, redact: bool) -> dict:
    d = _order_summary(o, redact)
    d.update(
        payment_method=o.get("payment_method_title"),
        shipping_total=o.get("shipping_total"), discount_total=o.get("discount_total"),
        total_tax=o.get("total_tax"), customer_note=o.get("customer_note"),
        items=[{"product_id": i.get("product_id"), "name": i.get("name"), "sku": i.get("sku"),
                "quantity": i.get("quantity"), "total": i.get("total")} for i in o.get("line_items", [])],
    )
    return d


def _product(p: dict) -> dict:
    return {
        "id": p["id"], "name": p.get("name"), "sku": p.get("sku"), "status": p.get("status"),
        "price": p.get("price"), "stock_status": p.get("stock_status"),
        "manage_stock": p.get("manage_stock"), "stock_quantity": p.get("stock_quantity"),
        "categories": [c.get("name") for c in p.get("categories", [])],
    }


def _page(items, headers, page):
    total_pages = int(headers.get("X-WP-TotalPages", 1))
    return {"items": items, "count": len(items), "page": page,
            "total": int(headers.get("X-WP-Total", len(items))),
            "total_pages": total_pages, "has_more": page < total_pages}


def _pp(a):  # pagination args
    return {"page": a.get("page", 1), "per_page": min(a.get("per_page", 10), 50)}


# ---------- handlers ----------
def list_orders(a):
    p = {**_pp(a), "status": a.get("status"), "after": a.get("after"), "before": a.get("before")}
    body, h = get_client().get("/orders", p)
    return _page([_order_summary(o, config.REDACT_PII) for o in body], h, p["page"])


def get_order(a):
    body, _ = get_client().get(f"/orders/{int(a['order_id'])}")
    return _order_detail(body, config.REDACT_PII)


def search_orders(a):
    p = {**_pp(a), "search": a["query"], "status": a.get("status")}
    body, h = get_client().get("/orders", p)
    return _page([_order_summary(o, config.REDACT_PII) for o in body], h, p["page"])


def list_products(a):
    p = {**_pp(a), "stock_status": a.get("stock_status")}
    body, h = get_client().get("/products", p)
    return _page([_product(x) for x in body], h, p["page"])


def get_product(a):
    body, _ = get_client().get(f"/products/{int(a['product_id'])}")
    return _product(body)


def search_products(a):
    p = {**_pp(a), "search": a.get("query"), "sku": a.get("sku")}
    body, h = get_client().get("/products", p)
    return _page([_product(x) for x in body], h, p["page"])


def get_low_stock_products(a):
    threshold, cap = a.get("threshold", 5), a.get("max_scan", 300)
    found, scanned, page, truncated = [], 0, 1, False
    while True:
        body, h = get_client().get("/products", {"page": page, "per_page": 100})
        for x in body:
            scanned += 1
            qty = x.get("stock_quantity")
            if x.get("stock_status") == "outofstock" or (x.get("manage_stock") and qty is not None and qty <= threshold):
                found.append(_product(x))
        if page >= int(h.get("X-WP-TotalPages", 1)):
            break
        if scanned >= cap:
            truncated = True
            break
        page += 1
    found.sort(key=lambda p: (p["stock_quantity"] is None, p["stock_quantity"] or 0))
    return {"items": found, "count": len(found), "threshold": threshold, "scanned": scanned, "truncated": truncated}


# ---------- registry ----------
@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    handler: Callable


def _s(props, required=()):
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


_PAGE = {"page": {"type": "integer", "minimum": 1, "default": 1},
         "per_page": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10}}
_STATUS = {"type": "string", "enum": ["pending", "processing", "on-hold", "completed", "cancelled", "refunded", "failed"]}

TOOLS = [
    Tool("list_orders", "List recent orders (newest first), optionally filtered by status or ISO-8601 date range. Returns summaries.",
         _s({"status": _STATUS, "after": {"type": "string", "description": "ISO-8601 e.g. 2025-01-31T00:00:00"},
             "before": {"type": "string"}, **_PAGE}), list_orders),
    Tool("get_order", "Get full details for one order by its numeric order ID, including line items.",
         _s({"order_id": {"type": "integer"}}, ["order_id"]), get_order),
    Tool("search_orders", "Free-text search over orders (order number, customer name or email).",
         _s({"query": {"type": "string", "minLength": 1}, "status": _STATUS, **_PAGE}, ["query"]), search_orders),
    Tool("list_products", "List products with stock info; optionally filter by stock status.",
         _s({"stock_status": {"type": "string", "enum": ["instock", "outofstock", "onbackorder"]}, **_PAGE}), list_products),
    Tool("get_product", "Get one product (price, SKU, stock) by numeric product ID.",
         _s({"product_id": {"type": "integer"}}, ["product_id"]), get_product),
    Tool("search_products", "Search products by name keyword or exact SKU.",
         _s({"query": {"type": "string"}, "sku": {"type": "string"}, **_PAGE}), search_products),
    Tool("get_low_stock_products", "Inventory check: products that are out of stock or at/below a stock threshold.",
         _s({"threshold": {"type": "integer", "minimum": 0, "default": 5},
             "max_scan": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 300}}), get_low_stock_products),
]
BY_NAME = {t.name: t for t in TOOLS}


def call_tool(name: str, args: dict | None) -> dict:
    """Validate, execute, and ALWAYS return a JSON-able dict (errors become {'error':...})."""
    args = args or {}
    tool = BY_NAME.get(name)
    if not tool:
        return {"error": f"unknown tool '{name}'"}
    try:
        jsonschema.validate(args, tool.schema)
    except jsonschema.ValidationError as e:
        return {"error": f"invalid arguments: {e.message}"}
    try:
        return tool.handler(args)
    except WooError as e:
        return {"error": str(e), "http_status": e.status}
    except Exception as e:  # never leak a stack trace to the model
        return {"error": f"unexpected error: {type(e).__name__}"}


def mcp_spec() -> list[dict]:
    return [{"name": t.name, "description": t.description, "inputSchema": t.schema} for t in TOOLS]


def openai_spec() -> list[dict]:
    return [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.schema}} for t in TOOLS]
