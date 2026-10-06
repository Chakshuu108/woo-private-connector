"""Run the WooCommerce authorization flow and save credentials to .credentials.json.

  python scripts/woo_authorize.py --store https://your-store.com

NOTE: real WooCommerce requires an HTTPS callback_url, so expose the local callback
with a tunnel (e.g. `cloudflared tunnel --url http://127.0.0.1:PORT`) and pass
--callback-base https://<tunnel-host>. Alternative (no tunnel): create keys manually in
WooCommerce > Settings > Advanced > REST API and export WOO_CONSUMER_KEY / WOO_CONSUMER_SECRET.
"""
import argparse
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from connector.authflow import CallbackServer, build_authorize_url  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--store", required=True)
ap.add_argument("--port", type=int, default=8765)
ap.add_argument("--callback-base", help="public https base that tunnels to the local port")
a = ap.parse_args()

srv = CallbackServer(a.store, port=a.port)
cb = (a.callback_base.rstrip("/") + "/callback") if a.callback_base else srv.url
url = build_authorize_url(a.store, cb)
print("Open this URL and approve access:\n", url)
webbrowser.open(url)
print("Waiting for WooCommerce to POST the keys ...")
print("Saved to .credentials.json" if srv.wait() else "Timed out.")
srv.close()
