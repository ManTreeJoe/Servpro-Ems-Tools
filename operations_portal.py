"""Lightweight browser host for Operations Hub.

Local mode binds to loopback. Shared LAN mode requires an explicit access key:
  python operations_portal.py --share --key <office-secret>
"""
from __future__ import annotations

import argparse
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import json
import mimetypes
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from browser_tools import BrowserToolHost, json_safe
from operations_hub import OperationsHub


ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "operations_web_assets"
HOME_ASSETS = ROOT / "home_web_assets"
SHARED_ASSETS = ROOT / "web_shared"
TOOL_ASSET_FOLDERS = {
    path.name for path in ROOT.glob("*_web_assets") if path.is_dir()
}
ROOT_STATIC_FILES = {
    "linguar_hub.png", "linguar_hub_trial.png", "linguar_hub.ico",
    "linguar_hub_trial.ico",
}


class OperationsHandler(SimpleHTTPRequestHandler):
    hub = OperationsHub()
    tools = BrowserToolHost()
    access_key = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ASSETS), **kwargs)

    def _authorized(self):
        if not self.access_key:
            return True
        return self.headers.get("X-Operations-Key", "") == self.access_key

    def _local_request(self):
        remote = str(self.client_address[0] or "")
        return remote in {"127.0.0.1", "::1"} or remote.startswith("::ffff:127.")

    def _json(self, payload, status=200):
        body = json.dumps(json_safe(payload), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, path: Path, *, inject_browser_bridge=False):
        """Serve one allowlisted UI asset without exposing the project tree."""
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError):
            self.send_error(404)
            return
        allowed_roots = (ASSETS.resolve(), HOME_ASSETS.resolve(),
                         SHARED_ASSETS.resolve()) + tuple(
            (ROOT / folder).resolve() for folder in TOOL_ASSET_FOLDERS)
        allowed_file = resolved.name in ROOT_STATIC_FILES and resolved.parent == ROOT.resolve()
        if not allowed_file and not any(
                root == resolved or root in resolved.parents for root in allowed_roots):
            self.send_error(404)
            return
        body = resolved.read_bytes()
        if inject_browser_bridge:
            marker = b'<script src="app.js'
            injection = b'<script src="/web_shared/browser_bridge.js?v=20260901a"></script>\n'
            if marker in body:
                body = body.replace(marker, injection + marker, 1)
        mime = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{mime}; charset=utf-8" if mime.startswith("text/") or mime in {"application/javascript", "application/json"} else mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store" if resolved.suffix in {".html", ".js"} else "private, max-age=300")
        self.end_headers()
        self.wfile.write(body)

    def _static_path(self, request_path: str):
        """Map public browser-tool URLs to the small set of UI directories."""
        clean = request_path.split("?", 1)[0]
        if clean in {"/tools", "/tools/", "/tools/index.html"}:
            return HOME_ASSETS / "index.html", True
        if clean.startswith("/tools/"):
            relative = clean[len("/tools/"):]
            return HOME_ASSETS / relative, False
        if clean.startswith("/web_shared/"):
            return SHARED_ASSETS / clean[len("/web_shared/"):], False
        parts = [part for part in clean.strip("/").split("/") if part]
        if parts and parts[0] in TOOL_ASSET_FOLDERS:
            return ROOT.joinpath(*parts), False
        if len(parts) == 1 and parts[0] in ROOT_STATIC_FILES:
            return ROOT / parts[0], False
        return None

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/tools":
            target = "/tools/" + (f"?{parsed.query}" if parsed.query else "")
            self.send_response(302)
            self.send_header("Location", target)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if parsed.path.startswith("/api/"):
            if not self._authorized():
                self._json({"ok": False, "error": "Access key required"}, 401)
                return
            try:
                if parsed.path == "/api/bootstrap":
                    force = parse_qs(parsed.query).get("force", ["0"])[0] == "1"
                    self._json(self.hub.bootstrap(force))
                    return
                if parsed.path == "/api/client":
                    name = parse_qs(parsed.query).get("name", [""])[0]
                    self._json(self.hub.client_account(name))
                    return
                if parsed.path == "/api/job":
                    query = parse_qs(parsed.query)
                    self._json(self.hub.job_context(
                        query.get("client", [""])[0],
                        query.get("card_id", [""])[0],
                        query.get("division", ["EMS"])[0]))
                    return
                if parsed.path == "/api/health":
                    self._json({"ok": True})
                    return
                if parsed.path == "/api/connections":
                    self._json(self.hub.connections())
                    return
                if parsed.path == "/api/field-note-templates":
                    division = parse_qs(parsed.query).get("division", ["EMS"])[0]
                    self._json(self.hub.field_note_templates(division))
                    return
                if parsed.path == "/api/tools":
                    self._json(self.tools.catalog())
                    return
                if parsed.path == "/api/operations-tools":
                    self._json(self.hub.tool_routes())
                    return
            except Exception as ex:
                self._json({"ok": False,
                            "error": f"{type(ex).__name__}: {ex}"}, 500)
                return
            self._json({"ok": False, "error": "Not found"}, 404)
            return
        if parsed.path == "/":
            self.path = "/index.html"
        static = self._static_path(parsed.path)
        if static:
            path, inject_browser_bridge = static
            self._serve_file(path, inject_browser_bridge=inject_browser_bridge)
            return
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self._json({"ok": False, "error": "Not found"}, 404)
            return
        if not self._authorized():
            self._json({"ok": False, "error": "Access key required"}, 401)
            return
        try:
            length = min(int(self.headers.get("Content-Length", "0") or 0),
                         1024 * 1024)
            payload = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(payload, dict):
                raise ValueError("Request body must be an object")
        except (ValueError, json.JSONDecodeError) as ex:
            self._json({"ok": False, "error": f"Invalid request: {ex}"}, 400)
            return
        try:
            if parsed.path == "/api/tool-call":
                method = str(payload.get("method") or "")
                args = payload.get("args") if isinstance(payload.get("args"), list) else []
                self._json(self.tools.call(
                    method, args, local_request=self._local_request()))
                return
            if parsed.path == "/api/account-sign-in":
                self._json(self.hub.account_sign_in(
                    str(payload.get("email") or ""),
                    str(payload.get("password") or "")))
                return
            if parsed.path == "/api/account-sign-out":
                self._json(self.hub.account_sign_out())
                return
            if parsed.path == "/api/connection-action":
                self._json(self.hub.begin_connection(
                    str(payload.get("provider") or "")))
                return
            if parsed.path == "/api/job-action":
                if not self._local_request():
                    self._json({
                        "ok": False,
                        "error": "That action uses files or apps on the Hub PC and is available only on that PC.",
                        "local_only": True,
                    }, 403)
                    return
                self._json(self.hub.job_action(
                    payload.get("action", ""), payload.get("job", {})))
                return
            if parsed.path == "/api/requirement":
                self._json(self.hub.set_job_requirement(
                    payload.get("client", ""), payload.get("requirement_key", ""),
                    payload.get("state", ""), payload.get("note", ""),
                    payload.get("details", {}), payload.get("card_id", ""),
                    payload.get("division", "EMS")))
                return
            if parsed.path == "/api/job-update":
                self._json(self.hub.save_job_update(
                    payload.get("client", ""), payload.get("entry", {})))
                return
            if parsed.path == "/api/field-note":
                self._json(self.hub.save_field_note(
                    payload.get("client", ""), payload.get("note_type", ""),
                    payload.get("values", {}), payload.get("division", "EMS"),
                    payload.get("source_id", "")))
                return
            if parsed.path == "/api/job-log-import":
                self._json(self.hub.import_job_log(
                    payload.get("client", ""), payload.get("card_id", "")))
                return
        except Exception as ex:
            self._json({"ok": False,
                        "error": f"{type(ex).__name__}: {ex}"}, 500)
            return
        self._json({"ok": False, "error": "Not found"}, 404)

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
