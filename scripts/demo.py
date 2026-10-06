"""One-command end-to-end demo (Windows / Mac / Linux). Starts the mock store itself.

  python scripts/demo.py            # connector demo, no API key needed
  python scripts/demo.py --agent    # also runs the OpenAI agent (needs OPENAI_API_KEY)
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from connector import tools  # noqa: E402
from connector.client import WooAuthError, WooClient  # noqa: E402
from mock_server import mock_woocommerce  # noqa: E402


def show(title, obj, limit=700):
    print(f"\n=== {title} ===")
    print(json.dumps(obj, indent=1, default=str)[:limit])


def main():
    store = mock_woocommerce.start()
    url = f"http://127.0.0.1:{store.server_port}"
    print(f"Mock WooCommerce running at {url}")

    client = WooClient(url, "ck_demo_key", "cs_demo_secret", rps=1000, backoff_base=0.05)
    tools.set_client(client)
    print(f"Auth mode used: {client.auth_mode} (OAuth 1.0a over HTTP, Basic over HTTPS)")

    # 1. Bad credentials are rejected
    try:
        WooClient(url, "ck_demo_key", "wrong", rps=1000).ping()
    except WooAuthError as e:
        print(f"\n=== Bad credentials ===\nRejected as expected: {e}")

    # 2. list / get / search primitives
    show("list_orders (on-hold, 2 per page)", tools.call_tool("list_orders", {"status": "on-hold", "per_page": 2}))
    show("get_order 5001", tools.call_tool("get_order", {"order_id": 5001}))
    show("search_orders 'khan'", tools.call_tool("search_orders", {"query": "khan", "per_page": 2}))
    show("search_products sku=SKU-1003", tools.call_tool("search_products", {"sku": "SKU-1003"}))
    show("get_low_stock_products (<=3)", tools.call_tool("get_low_stock_products", {"threshold": 3}), 900)

    # 3. Errors come back as clean messages, not stack traces
    show("get_order 999999 (missing)", tools.call_tool("get_order", {"order_id": 999999}))
    show("refund_order (not a tool)", tools.call_tool("refund_order", {}))

    # 4. Rate-limit handling: server allows 3 req/sec, we fire 10
    store.rate_limit, store.window = 3, 1.0
    for _ in range(10):
        client.ping()
    print(f"\n=== Rate limiting ===\n10 requests against a 3 req/sec limit all succeeded.")
    print(f"Server returned 429 {client.stats['rate_limited']} times; client retried {client.stats['retries']} times.")
    store.rate_limit = None

    # 5. Optional LLM agent
    if "--agent" in sys.argv:
        from agent.openai_agent import run_agent
        if not os.getenv("OPENAI_API_KEY"):
            print("\nSet OPENAI_API_KEY first, e.g.  $env:OPENAI_API_KEY='sk-...'")
        else:
            q = "Which products are out of stock or nearly out, and are any on-hold orders waiting on them?"
            print(f"\n=== OpenAI agent ===\nQ: {q}")
            print("A:", run_agent(q))

    store.shutdown()
    print("\nDemo complete.")


if __name__ == "__main__":
    main()
