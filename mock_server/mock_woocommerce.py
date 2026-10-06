"""Fake WooCommerce REST API (fictional data) so the connector runs & tests offline.

Implements: Basic + OAuth1 auth, pagination headers, search/status/stock filters,
429 + Retry-After rate limiting, and the /wc-auth/v1/authorize key hand-off.
Run:  python -m mock_server.mock_woocommerce   (port 8089)
"""
import base64
import json
import random
import secrets
import threading
import time
import urllib.request
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlparse

from connector import oauth1

FIRST = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Isha", "Vihaan", "Anaya", "Arjun", "Sara"]
LAST = ["Sharma", "Verma", "Singh", "Patel", "Gupta", "Mehta", "Nair", "Rao", "Khan", "Das"]
CITIES = [("Mumbai", "MH"), ("Delhi", "DL"), ("Bengaluru", "KA"), ("Hisar", "HR"), ("Pune", "MH")]
STATUSES = ["processing", "completed", "completed", "on-hold", "pending", "cancelled", "refunded"]
PRODUCTS = ["Cotton Kurta", "Silk Scarf", "Leather Wallet", "Steel Bottle", "Yoga Mat", "Desk Lamp",
            "Wireless Mouse", "Ceramic Mug", "Notebook Set", "Backpack", "Sunglasses", "Herbal Tea Box"]


def build_data(seed=7):
    rnd = random.Random(seed)
    products = []
    for i in range(30):
        base = PRODUCTS[i % len(PRODUCTS)]
        qty = rnd.choice([0, 1, 2, 3, 8, 15, 40, 120])
        products.append({
            "id": 100 + i, "name": f"{base} {'ABCDE'[i // len(PRODUCTS) + i % 3]}-{i}", "sku": f"SKU-{1000 + i}",
            "status": "publish", "price": str(rnd.randint(199, 4999)), "manage_stock": i % 7 != 0,
            "stock_quantity": qty if i % 7 != 0 else None,
            "stock_status": "outofstock" if (qty == 0 and i % 7 != 0) else "instock",
            "categories": [{"id": 1 + i % 3, "name": ["Apparel", "Home", "Accessories"][i % 3]}],
        })
    orders, now = [], datetime(2026, 9, 30, 12, 0, 0)
    for i in range(25):
        f, l = rnd.choice(FIRST), rnd.choice(LAST)
        city, state = rnd.choice(CITIES)
        items = []
        for _ in range(rnd.randint(1, 3)):
            p = rnd.choice(products)
            q = rnd.randint(1, 3)
            items.append({"id": len(items) + 1, "product_id": p["id"], "name": p["name"], "sku": p["sku"],
                          "quantity": q, "total": str(int(p["price"]) * q)})
        total = sum(int(x["total"]) for x in items)
        orders.append({
            "id": 5000 + i, "number": str(5000 + i), "status": rnd.choice(STATUSES), "currency": "INR",
            "date_created": (now - timedelta(days=i, hours=i)).isoformat(), "total": str(total),
            "total_tax": str(round(total * 0.05)), "shipping_total": "50", "discount_total": "0",
            "payment_method_title": rnd.choice(["UPI", "Credit Card", "Cash on Delivery"]),
            "customer_note": "Please deliver after 6pm" if i % 6 == 0 else "", "customer_id": i % 8,
            "billing": {"first_name": f, "last_name": l, "email": f"{f}.{l}{i}@example.com".lower(),
                        "phone": f"+91 9{rnd.randint(100000000, 999999999)}", "address_1": f"{i + 10} Demo Street",
                        "city": city, "state": state, "postcode": "100001", "country": "IN"},
            "line_items": items,
        })
    orders.sort(key=lambda o: o["date_created"], reverse=True)
    return orders, products


class MockStore(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, rate_limit=None, window=1.0):
        super().__init__(addr, Handler)
        self.orders, self.products = build_data()
        self.keys = {"ck_demo_key": "cs_demo_secret"}
        self.rate_limit, self.window, self.hits, self.lock = rate_limit, window, [], threading.Lock()
        self.request_log = []

    def over_limit(self):
        if not self.rate_limit:
            return False
        now = time.monotonic()
        with self.lock:
            self.hits = [t for t in self.hits if now - t < self.window]
            if len(self.hits) >= self.rate_limit:
                return True
            self.hits.append(now)
            return False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj, headers=None):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, str(v))
        self.end_headers()
        self.wfile.write(data)

    def _auth_ok(self, q):
        keys = self.server.keys
        h = self.headers.get("Authorization", "")
        if h.startswith("Basic "):
            try:
                k, s = base64.b64decode(h[6:]).decode().split(":", 1)
            except Exception:
                return False
            return keys.get(k) == s
        if "oauth_signature" in q:
            sig = q.pop("oauth_signature")
            secret = keys.get(q.get("oauth_consumer_key", ""))
            if secret is None:
                return False
            url = f"http://{self.headers['Host']}{urlparse(self.path).path}"
            return abs(time.time() - int(q.get("oauth_timestamp", 0))) < 300 and \
                oauth1.signature("GET", url, q, secret) == sig
        return False

    def do_GET(self):
        u = urlparse(self.path)
        q = dict(parse_qsl(u.query))
        if u.path == "/wc-auth/v1/authorize":
            return self._authorize(q)
        self.server.request_log.append(u.path)
        if self.server.over_limit():
            return self._json(429, {"message": "Too many requests"}, {"Retry-After": "1"})
        if not self._auth_ok(q):
            return self._json(401, {"code": "woocommerce_rest_cannot_view", "message": "Invalid credentials"})
        p = u.path
        if p == "/wp-json/wc/v3/orders":
            return self._list(self.server.orders, q, self._match_order)
        if p == "/wp-json/wc/v3/products":
            return self._list(self.server.products, q, self._match_product)
        for prefix, coll in (("/wp-json/wc/v3/orders/", self.server.orders), ("/wp-json/wc/v3/products/", self.server.products)):
            if p.startswith(prefix):
                hit = [x for x in coll if str(x["id"]) == p[len(prefix):]]
                return self._json(200, hit[0]) if hit else self._json(404, {"code": "not_found", "message": "Invalid ID"})
        self._json(404, {"message": "No route"})

    @staticmethod
    def _match_order(o, q):
        if q.get("status") and o["status"] != q["status"]:
            return False
        if q.get("after") and o["date_created"] <= q["after"]:
            return False
        if q.get("before") and o["date_created"] >= q["before"]:
            return False
        s = q.get("search", "").lower()
        b = o["billing"]
        return not s or s in f"{o['number']} {b['first_name']} {b['last_name']} {b['email']}".lower()

    @staticmethod
    def _match_product(p, q):
        if q.get("stock_status") and p["stock_status"] != q["stock_status"]:
            return False
        if q.get("sku") and p["sku"] != q["sku"]:
            return False
        return not q.get("search") or q["search"].lower() in p["name"].lower()

    def _list(self, coll, q, match):
        rows = [x for x in coll if match(x, q)]
        per = min(int(q.get("per_page", 10)), 100)
        page = int(q.get("page", 1))
        pages = max(1, -(-len(rows) // per))
        self._json(200, rows[(page - 1) * per: page * per], {"X-WP-Total": len(rows), "X-WP-TotalPages": pages})

    def _authorize(self, q):
        """Mimics the merchant clicking 'Approve': mint keys, POST them to callback, redirect."""
        ck, cs = "ck_" + secrets.token_hex(12), "cs_" + secrets.token_hex(12)
        self.server.keys[ck] = cs
        payload = json.dumps({"key_id": 1, "user_id": q.get("user_id"), "consumer_key": ck,
                              "consumer_secret": cs, "key_permissions": q.get("scope", "read")}).encode()
        req = urllib.request.Request(q["callback_url"], data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5).read()
        self.send_response(302)
        self.send_header("Location", q.get("return_url", "/"))
        self.end_headers()


def start(port=0, rate_limit=None, window=1.0):
    srv = MockStore(("127.0.0.1", port), rate_limit, window)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    s = MockStore(("127.0.0.1", 8089))
    print("Mock WooCommerce on http://127.0.0.1:8089  (key ck_demo_key / secret cs_demo_secret)")
    s.serve_forever()
