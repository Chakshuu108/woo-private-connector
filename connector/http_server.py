"""Optional HTTP bridge for platforms that can't spawn stdio MCP servers.

  GET  /tools            -> MCP-style tool specs
  POST /tools/<name>     -> JSON body = arguments; returns JSON result
Set HTTP_TOOL_TOKEN to require 'Authorization: Bearer <token>'.
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config
from .tools import call_tool, mcp_spec


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        data = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authed(self):
        t = config.HTTP_TOOL_TOKEN
        return not t or self.headers.get("Authorization") == f"Bearer {t}"

    def do_GET(self):
        if not self._authed():
            return self._send(401, {"error": "unauthorized"})
        self._send(200, {"tools": mcp_spec()}) if self.path == "/tools" else self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._authed():
            return self._send(401, {"error": "unauthorized"})
        if not self.path.startswith("/tools/"):
            return self._send(404, {"error": "not found"})
        try:
            args = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except ValueError:
            return self._send(400, {"error": "invalid JSON"})
        self._send(200, call_tool(self.path.split("/tools/", 1)[1], args))

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("HTTP tool bridge on http://127.0.0.1:8090")
    ThreadingHTTPServer(("127.0.0.1", 8090), H).serve_forever()
