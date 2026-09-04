"""Trello sign-in — click, approve in the browser, done.

The normal path is sign in, click Allow, done: a one-shot loopback server
catches the token and writes it to config. Trello requires the fixed local
origin to be registered once on Linguar Hub's API key; when it is not, the UI
reveals a secure manual fallback instead of leaving the user stuck.

Why a local server is needed
----------------------------
Trello's implicit flow returns the token in the URL *fragment*
(`…/callback#token=abc`). Fragments are never sent to the server, so the
callback page is a few lines of JS that read `location.hash` and re-request
the same server with the token as a query string. That is the whole trick;
there is no way to skip it short of a full OAuth1 dance.

The API key stays in config. It is the application's public identifier, not
a secret — but it MUST be the same key the rest of the app calls with. The
old Settings button hardcoded a different key, so the token it produced
authenticated as a different application and every later call failed.
"""
from __future__ import annotations

import http.server
import socket
import threading
import urllib.parse
import webbrowser

import config

_SCOPE = "read,write,account"
_APP_NAME = "Linguar Hub"
# People commonly have to choose an account, complete MFA, or ask which
# workspace to allow.  Two minutes closed the loopback listener while the
# Trello tab was still open, leaving a correct redirect at a dead localhost
# page.  Ten minutes is still bounded but behaves like a human setup flow.
_TIMEOUT_S = 600

# FIXED port, not an ephemeral one. Trello validates `return_url` against
# the API key's Allowed Origins list, and an origin is scheme+host+PORT —
# a random port would mean whitelisting a new origin on every sign-in.
# Override with `trello_auth_port` if 8976 is taken on a machine.
_DEFAULT_PORT = 8976

_PAGE_HEAD = """<!doctype html><meta charset="utf-8">
<title>Linguar Hub — Trello</title>
<style>
 body{font:15px/1.5 system-ui,Segoe UI,sans-serif;background:#12141a;color:#e6e8ee;
      display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
 .card{background:#1b1e26;border:1px solid #2b303c;border-radius:12px;
       padding:28px 34px;text-align:center;max-width:420px}
 h1{font-size:17px;margin:0 0 8px} p{margin:6px 0;color:#98a0b3;font-size:13px}
 .ok{color:#3fb950;font-size:34px}.bad{color:#e5534b;font-size:34px}
</style>"""


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = "EMSToolsAuth/1.0"

    def log_message(self, *a):        # keep the console quiet
        pass

    def _send(self, html, code=200):
        body = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)

        if parsed.path == "/done":
            token = (qs.get("token") or [""])[0].strip()
            self.server.token = token
            if token:
                self._send(_PAGE_HEAD + """<div class="card">
                  <div class="ok">✓</div><h1>Trello connected</h1>
                  <p>You can close this tab and go back to Linguar Hub.</p>
                  </div>""")
            else:
                self._send(_PAGE_HEAD + """<div class="card">
                  <div class="bad">✕</div><h1>No token received</h1>
                  <p>Trello didn't return a token. Close this tab and try again.</p>
                  </div>""", 400)
            self.server.done.set()
            return

        # Landing page: Trello has redirected here with the token in the
        # fragment, which the server cannot see. Bounce it back as a query.
        self._send(_PAGE_HEAD + """<div class="card">
          <div class="ok">…</div><h1>Finishing sign-in</h1>
          <p>One moment.</p></div>
        <script>
          var h = (location.hash || "").replace(/^#/, "");
          location.replace("/done" + (h ? "?" + h : ""));
        </script>""")


class _Server(http.server.HTTPServer):
    daemon_threads = True

    def __init__(self, addr):
        super().__init__(addr, _Handler)
        self.token = ""
        self.done = threading.Event()


def _free_port() -> int:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def auth_port() -> int:
    try:
        return int(config.load().get("trello_auth_port") or _DEFAULT_PORT)
    except (TypeError, ValueError):
        return _DEFAULT_PORT


def allowed_origin() -> str:
    """The exact origin to add to the API key's Allowed Origins list.

    Trello rejects any `return_url` whose origin isn't registered against
    the key — the error reads "Invalid return_url. The return URL should
    match the application's allowed origins."
    """
    return f"http://localhost:{auth_port()}"


def authorize_url(api_key: str, return_url: str = "") -> str:
    """Trello's authorize page.

    Without `return_url` Trello displays the token on screen for the user
    to copy — the manual path, which needs no origin registration and is
    the fallback when the loopback origin isn't (or can't be) whitelisted.
    """
    params = {
        "expiration":    "never",
        "scope":         _SCOPE,
        "response_type": "token",
        "name":          _APP_NAME,
        "key":           api_key,
    }
    if return_url:
        params["return_url"] = return_url
        params["callback_method"] = "fragment"
    return "https://trello.com/1/authorize?" + urllib.parse.urlencode(params)


def manual_url() -> dict:
    """The copy-paste flow: open Trello, it shows the token, user pastes it
    into Settings. Always works — no Allowed Origins entry needed."""
    api_key = (config.load().get("trello_api_key") or "").strip()
    if not api_key:
        return {"ok": False, "error": "No Trello API key set."}
    return {"ok": True, "url": authorize_url(api_key)}


def save_token(token: str) -> dict:
    """Store one token for the signed-in person across their franchises.

    The user token identifies a Trello member. Franchise separation comes
    from each department's workspace/board IDs, not by making the same person
    connect again after every franchise switch. Remove old profile overrides
    so every department consistently inherits the newly authorized user.
    """
    token = (token or "").strip()
    if not token:
        return {"ok": False, "error": "empty token"}
    base = config.load_base()
    base["trello_token"] = token
    depts = base.get("departments") or {}
    for name, current in list(depts.items()):
        if isinstance(current, dict) and "trello_token" in current:
            prof = dict(current)
            prof.pop("trello_token", None)
            depts[name] = prof
    if depts:
        base["departments"] = depts
    config.save(base)
    try:
        import cache_bust
        cache_bust.invalidate_all("trello sign-in")
    except Exception:
        pass
    return {"ok": True, "scope": "user"}


def authorize(*, timeout=_TIMEOUT_S, open_browser=True) -> dict:
    """Run the whole flow. Blocks until Trello redirects back, the user
    gives up, or `timeout` expires. Returns {ok, scope} / {ok:False,error}.

    Uses the CONFIGURED api key — a token minted against a different key
    authenticates as a different application and fails every later call.
    """
    api_key = (config.load().get("trello_api_key") or "").strip()
    if not api_key:
        return {"ok": False,
                "error": "No Trello API key set. Add it in Settings first — "
                         "it identifies the app, the sign-in gets the token."}
    port = auth_port()
    try:
        srv = _Server(("127.0.0.1", port))
    except OSError:
        # A random fallback port cannot be registered in Trello's Allowed
        # Origins and is guaranteed to fail after a long wait. Send the UI
        # straight to its secure copy/paste fallback instead.
        return {
            "ok": False,
            "manual": True,
            "manual_url": authorize_url(api_key),
            "error": (
                f"The Trello sign-in listener ({allowed_origin()}) is in "
                "use. Use the fallback tab that Linguar Hub opens next."
            ),
        }
    # localhost (not 127.0.0.1): Trello compares origins as strings, and
    # "http://localhost:PORT" is what the Allowed Origins field expects.
    url = authorize_url(api_key, f"http://localhost:{port}/")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        if open_browser:
            webbrowser.open(url)
        if not srv.done.wait(timeout):
            return {"ok": False, "timeout": True, "authorize_url": url,
                    "allowed_origin": f"http://localhost:{port}",
                    "manual_url": authorize_url(api_key),
                    "error": (
                        "Trello sign-in timed out after 10 minutes. Start "
                        "again from Settings → Connect Trello. If the page said "
                        "\"Invalid return_url\", add "
                        f"http://localhost:{port} to your API key's "
                        "Allowed Origins at trello.com/apps/admin — "
                        "or use the manual token flow instead.")}
        token = srv.token
    finally:
        try:
            srv.shutdown()
            srv.server_close()
        except Exception:
            pass
    if not token:
        return {"ok": False, "error": "Trello returned no token"}
    return save_token(token)
