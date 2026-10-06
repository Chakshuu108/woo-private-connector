import json
import subprocess
import sys

import pytest

from agent.openai_agent import run_agent
from connector import authflow, config, tools
from connector.client import WooAuthError, WooClient, WooNotFound
from mock_server import mock_woocommerce


# ---------- authentication ----------
@pytest.mark.parametrize("mode", ["oauth1", "basic"])
def test_auth_modes_work(url, mode):
    c = WooClient(url, "ck_demo_key", "cs_demo_secret", auth_mode=mode, rps=1000)
    assert c.ping()


@pytest.mark.parametrize("mode", ["oauth1", "basic"])
def test_bad_credentials_rejected(url, mode):
    c = WooClient(url, "ck_demo_key", "WRONG", auth_mode=mode, rps=1000)
    with pytest.raises(WooAuthError):
        c.ping()


def test_auto_mode_picks_scheme():
    assert WooClient("https://x.test", "k", "s").auth_mode == "basic"
    assert WooClient("http://x.test", "k", "s").auth_mode == "oauth1"


def test_authorize_flow_mints_working_keys(url, tmp_path, monkeypatch):
    monkeypatch.setattr(authflow, "CRED_FILE", tmp_path / "creds.json")
    cb = authflow.CallbackServer(url)
    import requests
    requests.get(authflow.build_authorize_url(url, cb.url), allow_redirects=False)  # "merchant approves"
    assert cb.wait(5)
    cb.close()
    saved = json.loads((tmp_path / "creds.json").read_text())
    assert saved["consumer_key"].startswith("ck_")
    assert WooClient(url, saved["consumer_key"], saved["consumer_secret"], rps=1000).ping()


# ---------- list / get / search primitives ----------
def test_list_and_paginate_orders(client):
    p1 = tools.call_tool("list_orders", {"per_page": 10})
    assert p1["count"] == 10 and p1["total"] == 25 and p1["has_more"] and p1["total_pages"] == 3
    p3 = tools.call_tool("list_orders", {"per_page": 10, "page": 3})
    assert p3["count"] == 5 and not p3["has_more"]


def test_list_orders_status_filter(client):
    r = tools.call_tool("list_orders", {"status": "on-hold", "per_page": 50})
    assert r["items"] and all(o["status"] == "on-hold" for o in r["items"])


def test_get_order_and_not_found(client):
    o = tools.call_tool("get_order", {"order_id": 5003})
    assert o["id"] == 5003 and o["items"]
    err = tools.call_tool("get_order", {"order_id": 999999})
    assert err["http_status"] == 404 and "not found" in err["error"]


def test_search_orders_by_number(client):
    r = tools.call_tool("search_orders", {"query": "5007"})
    assert [o["id"] for o in r["items"]] == [5007]


def test_product_tools(client):
    assert tools.call_tool("get_product", {"product_id": 100})["sku"] == "SKU-1000"
    assert tools.call_tool("search_products", {"sku": "SKU-1005"})["count"] == 1
    oos = tools.call_tool("list_products", {"stock_status": "outofstock", "per_page": 50})
    assert oos["items"] and all(p["stock_status"] == "outofstock" for p in oos["items"])


def test_low_stock(client):
    r = tools.call_tool("get_low_stock_products", {"threshold": 3})
    assert r["scanned"] == 30 and not r["truncated"]
    assert all(p["stock_status"] == "outofstock" or p["stock_quantity"] <= 3 for p in r["items"])


def test_invalid_args_and_unknown_tool(client):
    assert "invalid arguments" in tools.call_tool("get_order", {"order_id": "abc"})["error"]
    assert "invalid arguments" in tools.call_tool("list_orders", {"per_page": 9999})["error"]
    assert "unknown tool" in tools.call_tool("refund_order", {})["error"]


# ---------- PII ----------
def test_pii_redacted_by_default(client):
    o = tools.call_tool("get_order", {"order_id": 5001})
    assert "***@" in o["customer"]["email"] and o["customer"]["phone"].startswith("******")
    assert "address" not in o["customer"]
    listing = json.dumps(tools.call_tool("list_orders", {"per_page": 50}))
    assert "@example.com" not in listing.replace("***@example.com", "")


def test_pii_can_be_disabled(client, monkeypatch):
    monkeypatch.setattr(config, "REDACT_PII", False)
    assert "***" not in tools.call_tool("get_order", {"order_id": 5001})["customer"]["email"]


# ---------- rate limiting ----------
def test_client_recovers_from_429(url, store):
    store.rate_limit, store.window = 3, 1.0       # server allows 3 req/sec
    c = WooClient(url, "ck_demo_key", "cs_demo_secret", rps=1000, backoff_base=0.01)
    for _ in range(8):                             # burst well past the limit
        assert c.ping()
    assert c.stats["rate_limited"] > 0 and c.stats["retries"] > 0


def test_client_gives_up_eventually(url, store):
    store.rate_limit, store.window = 1, 60.0
    c = WooClient(url, "ck_demo_key", "cs_demo_secret", rps=1000, max_retries=1, backoff_base=0.01, max_backoff=0.05)
    c.ping()
    from connector.client import WooRateLimited
    with pytest.raises(WooRateLimited):
        c.ping()


def test_client_is_read_only():
    assert not any(hasattr(WooClient, m) for m in ("post", "put", "delete", "patch"))
    assert all(t.name.split("_")[0] in ("list", "get", "search") for t in tools.TOOLS)


# ---------- agent loop (LLM stubbed; real OpenAI needs a key + network) ----------
def test_agent_loop_calls_tool_then_answers(client):
    script = iter([
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "get_order", "arguments": '{"order_id": 5001}'}}]},
        {"role": "assistant", "content": "Order 5001 found."},
    ])
    seen = []

    def fake_chat(messages, tool_specs):
        seen.append(messages[-1]["role"])
        return next(script)

    assert run_agent("status of 5001?", chat=fake_chat, verbose=False) == "Order 5001 found."
    assert seen == ["user", "tool"]


# ---------- MCP over stdio (real protocol round-trip) ----------
def test_mcp_stdio_roundtrip(url):
    import asyncio

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def go():
        params = StdioServerParameters(command=sys.executable, args=["-m", "connector.mcp_server"],
                                       env={"WOO_BASE_URL": url, "WOO_RPS": "1000", "PATH": "/usr/bin:/bin"})
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                names = {t.name for t in (await s.list_tools()).tools}
                res = await s.call_tool("search_products", {"sku": "SKU-1001"})
                return names, json.loads(res.content[0].text)

    names, out = asyncio.run(go())
    assert names == {t.name for t in tools.TOOLS}
    assert out["items"][0]["sku"] == "SKU-1001"
