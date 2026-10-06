"""WooCommerce 'Authentication Endpoint' flow (/wc-auth/v1/authorize).

The merchant approves access in their own wp-admin; WooCommerce then POSTs freshly
minted read-only consumer key/secret to our callback. Keys are saved locally to
.credentials.json (git-ignored) - never printed or committed.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlencode

CRED_FILE = Path(__file__).resolve().parent.parent / ".credentials.json"


def build_authorize_url(store_url: str, callback_url: str, return_url: str = "http://127.0.0.1/",
                        app_name: str = "Agent Studio Connector", user_id: str = "agent-1") -> str:
    q = urlencode({"app_name": app_name, "scope": "read", "user_id": user_id,
                   "return_url": return_url, "callback_url": callback_url})
    return f"{store_url.rstrip('/')}/wc-auth/v1/authorize?{q}"


class CallbackServer:
    """Tiny local server that receives the key POST from WooCommerce."""

    def __init__(self, store_url: str, host="127.0.0.1", port=0, save=True):
        self.store_url, self.save, self.keys = store_url, save, None
        self.event = threading.Event()
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                if "consumer_key" in body and "consumer_secret" in body:
                    outer.keys = body
                    if outer.save:
                        CRED_FILE.write_text(json.dumps({"base_url": outer.store_url,
                                                         "consumer_key": body["consumer_key"],
                                                         "consumer_secret": body["consumer_secret"]}))
                        CRED_FILE.chmod(0o600)
                    outer.event.set()
                self.send_response(200)
                self.end_headers()

            def log_message(self, *a):
                pass

        self.httpd = HTTPServer((host, port), H)
        self.url = f"http://{host}:{self.httpd.server_port}/callback"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def wait(self, timeout=300) -> bool:
        return self.event.wait(timeout)

    def close(self):
        self.httpd.shutdown()
