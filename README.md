# WooCommerce → Agent Studio read-only connector

Lets an agent **read orders and inventory** from a WooCommerce store through an MCP server
(plus an HTTP bridge and a OpenAI-powered demo agent). Everything is read-only by construction.

```
Agent (Agent Studio / Claude / OpenAI demo)
      │  MCP over stdio  (or HTTP bridge, or OpenAI-style function calling)
      ▼
connector/tools.py   ← one registry: schemas, validation, PII masking, error envelope
      ▼
connector/client.py  ← GET-only client: auth, token-bucket throttle, 429/5xx retry
      ▼
WooCommerce REST v3  (or mock_server/ for offline demo & tests)
```

## Setup
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # note: mcp must be 1.x (pinned)
pytest -q                                # 20 tests, fully offline (uses the mock store)
python scripts/demo.py                   # one-command demo (Windows/Mac/Linux), no API key needed
```

### OpenAI demo agent
1. Paste your key into `OPENAI_API_KEY` in `connector/config.py` (or export `OPENAI_API_KEY`).
   **Reset it to the placeholder before pushing** – submission rules forbid committed keys.
2. `python scripts/demo.py --agent` or, with the mock running (`python -m mock_server.mock_woocommerce`):
   `python -m agent.openai_agent "Which products are out of stock?"`

### Connect a real store
Pick one auth route:
- **Manual keys (simplest):** WooCommerce → Settings → Advanced → REST API → Add key with **Read** permission, then
  `export WOO_BASE_URL=https://shop.example WOO_CONSUMER_KEY=ck_... WOO_CONSUMER_SECRET=cs_...`
- **Authorization flow:** `python scripts/woo_authorize.py --store https://shop.example --callback-base https://<tunnel>`
  – merchant approves in wp-admin, keys are POSTed to the callback and saved to git-ignored `.credentials.json`.
  (WooCommerce demands an HTTPS callback, hence the tunnel.)

Auth mode is automatic: **HTTPS → HTTP Basic**, **HTTP → OAuth 1.0a (HMAC-SHA256)**, as WooCommerce specifies.

### Plug into an agent
- **MCP (stdio):** command `python -m connector.mcp_server` with env `WOO_BASE_URL`, `WOO_CONSUMER_KEY`, `WOO_CONSUMER_SECRET`.
  Spec: [`mcp_tool_spec.json`](mcp_tool_spec.json). Example client config:
  ```json
  {"mcpServers": {"woocommerce": {"command": "python", "args": ["-m", "connector.mcp_server"],
    "env": {"WOO_BASE_URL": "https://shop.example", "WOO_CONSUMER_KEY": "ck_...", "WOO_CONSUMER_SECRET": "cs_..."}}}}
  ```
- **HTTP bridge** (if the platform can't spawn processes): `python -m connector.http_server`
  → `GET /tools`, `POST /tools/<name>`; set `HTTP_TOOL_TOKEN` to require a bearer token.
- **Function-calling:** [`openai_tool_spec.json`](openai_tool_spec.json). Regenerate both specs with `python scripts/export_tool_spec.py`.

## Tools
`list_orders`, `get_order`, `search_orders`, `list_products`, `get_product`, `search_products`, `get_low_stock_products`.
See [AGENT_CAPABILITIES.md](AGENT_CAPABILITIES.md) for what the agent can and cannot do.

## Rate-limit handling
1. Client-side token bucket (`WOO_RPS`, default 5/s) smooths bursts.
2. On **429 / 502 / 503 / 504** or network errors: honour `Retry-After`, else exponential backoff with jitter (capped 30s), up to `WOO_MAX_RETRIES`.
3. Persistent failure surfaces as a clean `{"error": ...}` the agent can relay – no stack traces.
Covered by `test_client_recovers_from_429` and `test_client_gives_up_eventually`.

## Assumptions & limitations
- Tested against a **mock** WooCommerce that I wrote from the public REST v3 docs; field names/behaviour were not
  verified against a live store (e.g. real `search` semantics on orders vary by WooCommerce version/plugins).
- Mock accepts OAuth1 signed with the same `oauth1.py` module the client uses, so that test proves self-consistency,
  not conformance with a real server.
- Server-side stock filtering by quantity doesn't exist in WooCommerce; `get_low_stock_products` scans (default ≤300 products) and reports `truncated`.
- Variations, refunds, coupons, and customers endpoints are not exposed. Orders are fetched, not cached.
- Customer email/phone are masked and street address omitted by default (`REDACT_PII=false` to disable – only do so deliberately).
- Single store per process; keys live in env/`.credentials.json` (0600), not a secrets manager.
- OpenAI agent path was not run here (no network to OpenAI from my build sandbox); its tool loop is tested with a stubbed LLM.
