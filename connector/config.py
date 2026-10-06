"""Central configuration.

>>> PASTE YOUR OPENAI KEY BELOW (only used by agent/openai_agent.py). <<<
Do NOT commit a real key: before `git push`, set it back to the placeholder
(or run: git update-index --skip-worktree connector/config.py).
"""
import json
import os
from pathlib import Path

# ---- OpenAI (demo agent only; the connector/MCP server itself never needs it) ----
OPENAI_API_KEY = "PASTE_YOUR_OPENAI_API_KEY_HERE"
OPENAI_MODEL = "gpt-4o-mini"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

# ---- WooCommerce ----
# Defaults point at the bundled mock store with fake credentials, so the repo
# runs out of the box. For a real store set env vars or run scripts/woo_authorize.py.
_CRED_FILE = Path(__file__).resolve().parent.parent / ".credentials.json"
_saved = json.loads(_CRED_FILE.read_text()) if _CRED_FILE.exists() else {}

WOO_BASE_URL = os.getenv("WOO_BASE_URL", _saved.get("base_url", "http://127.0.0.1:8089"))
WOO_CONSUMER_KEY = os.getenv("WOO_CONSUMER_KEY", _saved.get("consumer_key", "ck_demo_key"))
WOO_CONSUMER_SECRET = os.getenv("WOO_CONSUMER_SECRET", _saved.get("consumer_secret", "cs_demo_secret"))
# auto = HTTPS -> HTTP Basic, HTTP -> OAuth 1.0a (the WooCommerce rule). Or force: basic | oauth1
WOO_AUTH_MODE = os.getenv("WOO_AUTH_MODE", "auto")

# ---- Behaviour ----
WOO_RPS = float(os.getenv("WOO_RPS", "5"))            # client-side throttle (requests/sec)
WOO_MAX_RETRIES = int(os.getenv("WOO_MAX_RETRIES", "5"))
REDACT_PII = os.getenv("REDACT_PII", "true").lower() != "false"
HTTP_TOOL_TOKEN = os.getenv("HTTP_TOOL_TOKEN", "")    # optional bearer for connector/http_server.py


def openai_key() -> str:
    return os.getenv("OPENAI_API_KEY", OPENAI_API_KEY)
