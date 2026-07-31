"""Outlook reader — local COM preferred, Microsoft Graph fallback.

Default backend: Windows COM via outlook_local.py. Uses the
already-authenticated Outlook desktop session, so no Azure AD app
registration / admin consent / token management is required. The Graph
implementation below is kept for headless use or non-Windows machines
where Outlook desktop isn't available; switch by setting
`config["outlook_backend"]` to "graph".

Microsoft Graph API client (stdlib only, device-code auth).

ONE-TIME SETUP (~15 min):
    1. Go to https://portal.azure.com → Azure Active Directory →
       App registrations → New registration.
    2. Name: "Linguar Hub"  (or anything).
       Supported account types: "Accounts in this organizational
       directory only" (single tenant).
       Redirect URI: leave blank — device-code flow doesn't need one.
       Click Register.
    3. On the app's Overview page copy:
         - Application (client) ID
         - Directory (tenant) ID
       …into your config.json as `graph_client_id` + `graph_tenant_id`.
    4. Authentication → Advanced settings → toggle "Allow public client
       flows" to YES. Save.
    5. API permissions → Add a permission → Microsoft Graph →
       Delegated → check `Mail.Read` and `User.Read`. Grant admin
       consent (or have IT click the button).
    6. From PowerShell run `python outlook_client.py login` once. It
       prints a code + URL; sign in on any device with that code. Token
       lands in %APPDATA%\\Linguar Hub\\msgraph_token.json. Refresh
       happens automatically thereafter.

After setup, this module exposes:
    list_recent_messages(folder='inbox', since_iso=...) -> [{...}]
    get_message_body(message_id) -> str
    send_signed_in_user_email() (not implemented — read-only)

Auth uses the OAuth 2.0 device-code grant. We deliberately do NOT
ship a client secret so this can run on every employee's machine
without a per-machine secret rotation problem.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request

import config
import paths

# Local COM backend preferred. Lazy-imported on first call so a missing
# pywin32 / non-Windows install doesn't break import-time for modules
# that only ever need the Graph fallback.
_LOCAL_BACKEND = None
_LOCAL_BACKEND_CHECKED = False


def _backend_choice() -> str:
    """Return 'local' or 'graph'. Honors config["outlook_backend"] if set;
    otherwise prefers local when COM/pywin32 is available."""
    cfg = config.load() if hasattr(config, "load") else {}
    pref = (cfg.get("outlook_backend") or "").strip().lower()
    if pref in ("local", "graph"):
        return pref
    return "local" if _try_local() else "graph"


def _try_local():
    """Lazy import + caching guard for the local COM backend."""
    global _LOCAL_BACKEND, _LOCAL_BACKEND_CHECKED
    if _LOCAL_BACKEND_CHECKED:
        return _LOCAL_BACKEND is not None
    _LOCAL_BACKEND_CHECKED = True
    try:
        import outlook_local
        _LOCAL_BACKEND = outlook_local
    except Exception:
        _LOCAL_BACKEND = None
    return _LOCAL_BACKEND is not None


GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_PATH = paths.data("msgraph_token.json")
SCOPES = ("Mail.Read", "User.Read", "offline_access")


# ── Auth ────────────────────────────────────────────────────────────────

def _login_endpoints():
    cfg = config.load()
    tenant = (cfg.get("graph_tenant_id") or "").strip()
    client = (cfg.get("graph_client_id") or "").strip()
    if not tenant or not client:
        raise RuntimeError(
            "Microsoft Graph not configured. Set graph_tenant_id and "
            "graph_client_id in config.json (see outlook_client.py "
            "docstring for setup steps).")
    devcode = (f"https://login.microsoftonline.com/{tenant}"
               f"/oauth2/v2.0/devicecode")
    token = (f"https://login.microsoftonline.com/{tenant}"
             f"/oauth2/v2.0/token")
    return client, devcode, token


def _save_token(blob: dict) -> None:
    """Persist the token blob with an `expires_at` epoch second so
    callers can cheaply check freshness without having to recompute
    from the original `expires_in` after a process restart."""
    blob = dict(blob)
    if "expires_in" in blob and "expires_at" not in blob:
        blob["expires_at"] = int(time.time()) + int(blob["expires_in"])
    try:
        os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
    except OSError:
        pass
    tmp = TOKEN_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(blob, f)
    os.replace(tmp, TOKEN_PATH)


def _load_token() -> dict | None:
    try:
        with open(TOKEN_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _post_form(url: str, data: dict) -> dict:
    """POST form-encoded; return parsed JSON or raise with the body
    text so the caller sees Microsoft's error message."""
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as ex:
        try:
            err = ex.read().decode("utf-8", errors="replace")
        except Exception:
            err = str(ex)
        raise RuntimeError(f"Graph auth error {ex.code}: {err[:300]}")


def device_login(*, on_prompt=None) -> dict:
    """Run the device-code flow interactively. `on_prompt(message,
    user_code, verification_uri)` is called once with the printed
    instructions; the default prints to stdout. Blocks until the user
    completes auth on a browser, then writes the token blob to disk
    and returns it.
    """
    client_id, devcode_url, token_url = _login_endpoints()
    init = _post_form(devcode_url, {
        "client_id": client_id,
        "scope":     " ".join(SCOPES),
    })
    msg = init.get("message")
    user_code = init.get("user_code")
    uri = init.get("verification_uri")
    interval = max(2, int(init.get("interval", 5)))
    expires_in = int(init.get("expires_in", 900))
    if on_prompt is not None:
        try: on_prompt(msg, user_code, uri)
        except Exception: print(msg)
    else:
        print(msg)

    deadline = time.time() + expires_in
    while time.time() < deadline:
        time.sleep(interval)
        try:
            tok = _post_form(token_url, {
                "grant_type":   "urn:ietf:params:oauth:grant-type:device_code",
                "client_id":    client_id,
                "device_code":  init["device_code"],
            })
        except RuntimeError as ex:
            # "authorization_pending" is normal — keep polling. Anything
            # else (consent_required, expired_token, slow_down) bubbles.
            err = str(ex)
            if "authorization_pending" in err:
                continue
            if "slow_down" in err:
                interval += 5
                continue
            raise
        if "access_token" in tok:
            _save_token(tok)
            return tok
    raise RuntimeError("Device-code login timed out — restart and "
                        "complete the prompt within 15 minutes.")


def _refresh(token: dict) -> dict:
    """Use the refresh_token to mint a new access_token. Falls through
    to None if there's no refresh_token (force re-login)."""
    rt = token.get("refresh_token") if token else None
    if not rt:
        return None
    client_id, _, token_url = _login_endpoints()
    fresh = _post_form(token_url, {
        "grant_type":    "refresh_token",
        "client_id":     client_id,
        "refresh_token": rt,
        "scope":         " ".join(SCOPES),
    })
    # Refresh response may not return a new refresh_token; preserve old.
    if "refresh_token" not in fresh:
        fresh["refresh_token"] = rt
    _save_token(fresh)
    return fresh


def _access_token() -> str:
    """Return a valid access_token, refreshing or re-prompting login as
    needed. Raises RuntimeError if no auth is configured at all."""
    tok = _load_token()
    if tok is None:
        raise RuntimeError(
            "Not signed in to Microsoft Graph. Run "
            "`python outlook_client.py login` once.")
    # 60s skew buffer so a request that's about to fire doesn't race
    # the expiry mid-flight.
    if int(tok.get("expires_at", 0)) - int(time.time()) <= 60:
        try:
            tok = _refresh(tok)
        except Exception:
            tok = None
        if tok is None:
            raise RuntimeError(
                "Microsoft Graph token expired and refresh failed. "
                "Re-run `python outlook_client.py login`.")
    return tok["access_token"]


# ── Graph reads ─────────────────────────────────────────────────────────

def _get(path: str, *, params: dict | None = None) -> dict:
    qs = urllib.parse.urlencode(params or {})
    url = f"{GRAPH_BASE}{path}"
    if qs:
        url += "?" + qs
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {_access_token()}",
        "Accept":        "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def list_recent_messages(*, folder: str = "inbox",
                          since: _dt.datetime | None = None,
                          top: int = 50) -> list[dict]:
    """Return up to `top` messages from the named mail folder, newest
    first. `since` filters by `receivedDateTime >= since`. Pass a UTC
    naive datetime.

    Routes through `outlook_local` (Windows COM) when available so
    consumers don't have to think about Azure AD / Graph tokens. Falls
    back to Microsoft Graph when explicitly configured or when COM
    isn't available."""
    if _backend_choice() == "local":
        return _LOCAL_BACKEND.list_recent_messages(
            folder=folder, since=since, top=top)
    # Graph path (preserved for fallback / non-Windows / headless).
    params = {
        "$select": ("id,subject,from,toRecipients,receivedDateTime,"
                    "bodyPreview,hasAttachments,webLink"),
        "$top":    str(min(max(1, top), 200)),
        "$orderby": "receivedDateTime DESC",
    }
    if since is not None:
        iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        params["$filter"] = f"receivedDateTime ge {iso}"
    raw = _get(f"/me/mailFolders/{folder}/messages", params=params)
    return list(raw.get("value") or [])


def get_message_body(message_id: str) -> str:
    """Return the message body as plain text. Routes through
    `outlook_local` when COM is available; Graph fallback otherwise.
    Empty string on lookup failure."""
    if not message_id:
        return ""
    if _backend_choice() == "local":
        return _LOCAL_BACKEND.get_message_body(message_id)
    try:
        msg = _get(f"/me/messages/{message_id}",
                   params={"$select": "body"})
    except Exception:
        return ""
    body = msg.get("body") or {}
    text = body.get("content") or ""
    if (body.get("contentType") or "").lower() == "html":
        # Cheap HTML strip — Graph's bodyPreview is a better choice
        # for short cases; this is the fallback when the caller
        # explicitly wants the full body.
        import re
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
    return text


# ── CLI ─────────────────────────────────────────────────────────────────

def _cli(argv):
    if not argv:
        print("Usage:")
        print("  python outlook_client.py login")
        print("  python outlook_client.py whoami")
        print("  python outlook_client.py recent [--days=1] [--top=20]")
        return 1
    cmd = argv[0]
    if cmd == "login":
        try:
            device_login()
            print("✓ Signed in.")
            return 0
        except RuntimeError as ex:
            print(f"ERROR: {ex}")
            return 1
    if cmd == "whoami":
        try:
            me = _get("/me",
                      params={"$select": "displayName,mail,userPrincipalName"})
        except Exception as ex:
            print(f"ERROR: {ex}")
            return 1
        print(f"  {me.get('displayName', '?')}")
        print(f"  mail: {me.get('mail') or me.get('userPrincipalName', '')}")
        return 0
    if cmd == "recent":
        days, top = 1, 20
        for a in argv[1:]:
            if a.startswith("--days="):
                try: days = int(a.split("=", 1)[1])
                except ValueError: pass
            elif a.startswith("--top="):
                try: top = int(a.split("=", 1)[1])
                except ValueError: pass
        since = (_dt.datetime.utcnow()
                  - _dt.timedelta(days=days)).replace(microsecond=0)
        try:
            msgs = list_recent_messages(since=since, top=top)
        except Exception as ex:
            print(f"ERROR: {ex}")
            return 1
        if not msgs:
            print(f"(no messages in the last {days} day(s))")
            return 0
        for m in msgs:
            sender = ((m.get("from") or {}).get("emailAddress") or {}).get(
                "address", "")
            recv = m.get("receivedDateTime", "")[:16].replace("T", " ")
            subj = m.get("subject", "")[:80]
            print(f"  {recv}  {sender:30s}  {subj}")
        return 0
    print(f"Unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
