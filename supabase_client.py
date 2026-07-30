"""Supabase transport — auth + PostgREST, over stdlib urllib.

Same shape as `trello_client` / `companycam_api`: plain HTTPS, no new
dependency, nothing added to the PyInstaller build.

Why PostgREST and not a direct Postgres connection
--------------------------------------------------
A psycopg client would need the database password. This app ships as a
PyInstaller .exe, and anything inside one is extractable — that password
would grant full read/write to BOTH franchises and would bypass Row-Level
Security entirely. The publishable key here is the opposite: it identifies
the project and grants nothing on its own. What a signed-in user may see is
decided by RLS on `jobs.department` plus the `app_user_departments`
membership table. So the key that ships is worthless on its own, and the
key that matters never leaves the Supabase dashboard.

Auth is email OTP (a 6-digit code), not a password and not OAuth. Both of
those redirect through a browser, which in a pywebview desktop app means
standing up a localhost callback listener. A code the user types needs no
redirect handling at all.

Session tokens live in DATA_DIR, not config.json — they're per-machine and
short-lived, and mixing them into the config the user hand-edits invites
someone to paste one into a shared file.
"""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import config
import paths as _paths

_USER_AGENT = "EMS-Automation/1.0"
_SESSION_PATH = _paths.data("supabase_session.json")
_LOCK = threading.RLock()

# Refresh this long before the token actually expires, so a call that
# starts just under the wire doesn't land just over it.
_REFRESH_MARGIN_S = 120


class SupabaseError(RuntimeError):
    """Any non-2xx from Supabase, with the response body attached."""

    def __init__(self, status, body, url=""):
        self.status = status
        self.body = body
        self.url = url
        super().__init__(f"HTTP {status}: {body[:300]}")


class NotConfigured(RuntimeError):
    pass


class NotSignedIn(RuntimeError):
    pass


# ── Configuration ───────────────────────────────────────────────────────

def creds():
    """(project_url, publishable_key). Raises NotConfigured when unset."""
    cfg = config.load()
    url = (cfg.get("supabase_url") or "").strip().rstrip("/")
    key = (cfg.get("supabase_anon_key") or "").strip()
    if not url or not key:
        raise NotConfigured(
            "Supabase is not configured. Set supabase_url and "
            "supabase_anon_key in Settings.")
    return url, key


def is_configured() -> bool:
    try:
        creds()
        return True
    except Exception:
        return False


# ── Session storage ─────────────────────────────────────────────────────

def _read_session() -> dict:
    try:
        with open(_SESSION_PATH, encoding="utf-8") as f:
            s = json.load(f)
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_session(sess: dict) -> None:
    tmp = _SESSION_PATH + ".tmp"
    os.makedirs(os.path.dirname(_SESSION_PATH), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sess or {}, f, indent=2)
    os.replace(tmp, _SESSION_PATH)


def _store_session(payload: dict) -> dict:
    """Persist a GoTrue token response, stamping an absolute expiry.

    GoTrue returns `expires_in` (seconds from now); storing the relative
    value would make every later comparison wrong.
    """
    sess = {
        "access_token":  payload.get("access_token") or "",
        "refresh_token": payload.get("refresh_token") or "",
        "expires_at":    time.time() + float(payload.get("expires_in") or 3600),
        "user":          (payload.get("user") or {}),
    }
    _write_session(sess)
    return sess


def sign_out() -> None:
    """Drop the local session. Best-effort server revoke."""
    sess = _read_session()
    tok = sess.get("access_token")
    if tok:
        try:
            _raw("POST", "/auth/v1/logout", token=tok)
        except Exception:
            pass
    try:
        os.remove(_SESSION_PATH)
    except OSError:
        pass


def current_user() -> dict | None:
    """{'id', 'email'} for the signed-in user, or None."""
    u = (_read_session().get("user") or {})
    if not u.get("id"):
        return None
    return {"id": u.get("id"), "email": u.get("email") or ""}


def is_signed_in() -> bool:
    return bool(_read_session().get("access_token"))


# ── Low-level HTTP ──────────────────────────────────────────────────────

def _raw(method, path, *, params=None, body=None, token=None,
         extra_headers=None, _max_retries=4):
    """One HTTPS call. Retries 429/503 with backoff, honoring Retry-After.

    503 is retried only for idempotent methods: Supabase can return one
    AFTER accepting a write, and replaying a POST would duplicate a row.
    """
    url, key = creds()
    full = url + path
    if params:
        full += "?" + urllib.parse.urlencode(params, safe="*,().")
    data = None
    headers = {
        "User-Agent": _USER_AGENT,
        "apikey": key,
        "Authorization": f"Bearer {token or key}",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    headers.update(extra_headers or {})

    attempt = 0
    while True:
        req = urllib.request.Request(full, data=data, method=method,
                                     headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                break
        except urllib.error.HTTPError as ex:
            payload = ex.read().decode("utf-8", "replace")
            retryable = (ex.code == 429
                         or (ex.code == 503 and method in ("GET", "HEAD")))
            if retryable and attempt < _max_retries:
                delay = 0.0
                ra = ex.headers.get("Retry-After") if ex.headers else None
                try:
                    delay = float(ra) if ra else 0.0
                except (TypeError, ValueError):
                    delay = 0.0
                time.sleep(delay if delay > 0 else min(2 ** attempt, 8))
                attempt += 1
                continue
            raise SupabaseError(ex.code, payload, full) from None
        except urllib.error.URLError as ex:
            # Offline / DNS / TLS. Callers treat this as "backend
            # unreachable" and fall back to the local cache.
            raise SupabaseError(0, f"unreachable: {ex.reason}", full) from None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


# ── Auth (email OTP) ────────────────────────────────────────────────────

def send_login_code(email: str) -> dict:
    """Email a 6-digit sign-in code.

    `should_create_user` is False on purpose: accounts are created by an
    admin in the dashboard, so a typo'd address fails instead of silently
    minting an account (project signup is disabled for the same reason).
    """
    email = (email or "").strip()
    if not email:
        raise ValueError("email required")
    _raw("POST", "/auth/v1/otp",
         body={"email": email, "create_user": False,
               "should_create_user": False})
    return {"ok": True, "email": email}


def verify_login_code(email: str, code: str) -> dict:
    """Exchange the emailed code for a session. Returns {'id','email'}."""
    email = (email or "").strip()
    code = (code or "").strip()
    if not (email and code):
        raise ValueError("email and code required")
    payload = _raw("POST", "/auth/v1/verify",
                   body={"type": "email", "email": email, "token": code})
    if not (payload or {}).get("access_token"):
        raise SupabaseError(401, "no access_token in verify response")
    _store_session(payload)
    return current_user() or {}


def verify_magic_link(url_or_token: str, email: str = "") -> dict:
    """Sign in from the LINK in the email instead of a typed code.

    Supabase's stock email template sends `{{ .ConfirmationURL }}` — a link
    whose redirect defaults to localhost:3000, which is nothing on a
    desktop machine, so clicking it just fails. The link still carries the
    same one-time token, so pull it out and verify it directly.

    Accepts the whole URL or a bare token. Fix the template to show
    `{{ .Token }}` and the 6-digit path works instead.
    """
    raw = (url_or_token or "").strip()
    if not raw:
        raise ValueError("paste the link or token from the email")
    token = raw
    if "://" in raw or raw.startswith("?") or "token" in raw:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(raw).query)
        token = (qs.get("token_hash") or qs.get("token") or [""])[0].strip()
    if not token:
        raise ValueError("no token found in that link")
    last = None
    # Two accepted shapes, and which one applies depends on how the link
    # was minted: a HASHED token verifies on its own, a plain one must be
    # paired with the address it was sent to ("Only an email address or
    # phone number should be provided on verify"). Try both rather than
    # make the caller know which kind they were emailed.
    attempts = [{"type": "magiclink", "token_hash": token},
                {"type": "email", "token_hash": token}]
    email = (email or "").strip()
    if email:
        attempts += [{"type": "magiclink", "token": token, "email": email},
                     {"type": "email", "token": token, "email": email}]
    for body in attempts:
        try:
            payload = _raw("POST", "/auth/v1/verify", body=body)
        except SupabaseError as ex:
            last = ex
            continue
        if (payload or {}).get("access_token"):
            _store_session(payload)
            return current_user() or {}
    raise last or SupabaseError(401, "token not accepted")


def _refresh(sess: dict) -> dict:
    rt = sess.get("refresh_token")
    if not rt:
        raise NotSignedIn("no refresh token; sign in again")
    payload = _raw("POST", "/auth/v1/token",
                   params={"grant_type": "refresh_token"},
                   body={"refresh_token": rt})
    if not (payload or {}).get("access_token"):
        raise NotSignedIn("refresh failed; sign in again")
    return _store_session(payload)


def access_token() -> str:
    """A valid access token, refreshing if it's near expiry.

    Serialized: two panels refreshing at once would race, and GoTrue
    rotates refresh tokens — the loser's token would already be spent.
    """
    with _LOCK:
        sess = _read_session()
        if not sess.get("access_token"):
            raise NotSignedIn("not signed in")
        if time.time() >= float(sess.get("expires_at") or 0) - _REFRESH_MARGIN_S:
            sess = _refresh(sess)
        return sess["access_token"]


# ── PostgREST ───────────────────────────────────────────────────────────

def rest(method, table, *, params=None, body=None, prefer=None):
    """Call PostgREST as the signed-in user, so RLS applies.

    `prefer` sets the Prefer header — "return=representation" to get rows
    back, "resolution=merge-duplicates" for upsert.
    """
    headers = {}
    if prefer:
        headers["Prefer"] = prefer
    return _raw(method, f"/rest/v1/{table}", params=params, body=body,
                token=access_token(), extra_headers=headers)


def rpc(fn, args=None):
    """Call a Postgres function. Used for reads PostgREST can't express
    directly (alias-joined lookups, aggregates)."""
    return _raw("POST", f"/rest/v1/rpc/{fn}", body=args or {},
                token=access_token())


def health() -> dict:
    """Reachability + auth probe for Settings and diagnostics. Never raises."""
    out = {"configured": False, "reachable": False, "signed_in": False,
           "user": None, "error": ""}
    try:
        creds()
        out["configured"] = True
    except Exception as ex:
        out["error"] = str(ex)
        return out
    try:
        _raw("GET", "/auth/v1/health")
        out["reachable"] = True
    except Exception as ex:
        out["error"] = str(ex)
        return out
    try:
        access_token()
        out["signed_in"] = True
        out["user"] = current_user()
    except Exception as ex:
        out["error"] = str(ex)
    return out
