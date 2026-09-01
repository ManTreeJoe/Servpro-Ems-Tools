"""Lightweight browser host for Operations Hub.

Local mode binds to loopback. Shared LAN mode requires an explicit access key:
  python operations_portal.py --share --key <office-secret>
"""
from __future__ import annotations

import argparse
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from operations_hub import OperationsHub


ASSETS = Path(__file__).resolve().parent / "operations_web_assets"


class OperationsHandler(SimpleHTTPRequestHandler):
    hub = OperationsHub()
    access_key = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ASSETS), **kwargs)

    def _authorized(self):
        if not self.access_key:
            return True
        return self.headers.get("X-Operations-Key", "") == self.access_key

    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            if not self._authorized():
                self._json({"ok": False, "error": "Access key required"}, 401)
                return
            if parsed.path == "/api/bootstrap":
                force = parse_qs(parsed.query).get("force", ["0"])[0] == "1"
                self._json(self.hub.bootstrap(force))
                return
            if parsed.path == "/api/client":
                name = parse_qs(parsed.query).get("name", [""])[0]
                self._json(self.hub.client_account(name))
                return
            if parsed.path == "/api/health":
                self._json({"ok": True})
                return
            self._json({"ok": False, "error": "Not found"}, 404)
            return
        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def end_headers(self):
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        super().end_headers()

    def log_message(self, format, *args):
        return


def main(argv=None):
    parser = argparse.ArgumentParser(description="Linguar Hub Operations browser portal")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--share", action="store_true", help="Listen on the office LAN")
    parser.add_argument("--key", default=os.environ.get("LINGUAR_OPERATIONS_KEY", ""))
    args = parser.parse_args(argv)
    if args.share and len(args.key) < 12:
        parser.error("--share requires --key with at least 12 characters")
    OperationsHandler.access_key = args.key
    host = "0.0.0.0" if args.share else "127.0.0.1"
    server = ThreadingHTTPServer((host, args.port), OperationsHandler)
    visible_host = "<this-PC>" if args.share else host
    print(f"Operations Hub: http://{visible_host}:{args.port}/")
    if args.key:
        print("Enter the configured access key when the portal opens.")
    server.serve_forever()


if __name__ == "__main__":
    main()
