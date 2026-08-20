"""Is the app working right now — and if not, what is wrong, in words
somebody can act on?

Every fact here was already knowable and nowhere visible:

* the shared DB fell back to the local cache and only Settings said so,
  so a user kept working and their writes queued behind a server they
  did not know was unreachable;
* a user with no RLS grant is shown an empty job list, which reads as
  "there are no jobs" rather than "you cannot see any";
* a JS error in a panel died in a console nobody opens.

That is the pattern this whole effort has been unwinding: partial or
failed work reported as success. A banner is the cheap half of the fix —
it costs one poll and it means the failure has to be noticed.

Nothing here raises. A health check that breaks the app it is reporting
on would be its own worst bug.
"""
from __future__ import annotations

import threading
import time

import config

# The grant check is a network round trip, so it is cached. Degraded
# state is a local flag and is read fresh every time.
_GRANT_TTL_S = 300.0
_grant_cache: dict = {}
_grant_at = 0.0
_lock = threading.Lock()


def _backend_name() -> str:
    try:
        return (config.load().get("ems_db_backend") or "sqlite").strip()
    except Exception:
        return "sqlite"


def _offline_state() -> dict:
    """Degraded flag + queue depth, or empty when the offline wrapper is
    not in play (a pure-SQLite install is not 'degraded', it is local)."""
    try:
        import ems_db_offline
        return ems_db_offline.status() or {}
    except Exception:
        return {}


def grant_state(force: bool = False) -> dict:
    """Which franchises the signed-in user may actually SEE.

    RLS decides this, not the app, so an empty list means every query
    returns nothing no matter what the UI does. Cached — this is a
    network call and the banner polls.
    """
    global _grant_cache, _grant_at
    if _backend_name() != "supabase":
        return {"checked": False, "reason": "local backend"}

    with _lock:
        fresh = (time.time() - _grant_at) < _GRANT_TTL_S
        if _grant_cache and fresh and not force:
            return dict(_grant_cache)

    out: dict
    try:
        import supabase_client as sb
        if not sb.is_signed_in():
            out = {"checked": True, "ok": False, "signed_in": False,
                   "departments": []}
        else:
            user = sb.current_user() or {}
            depts = sb.rpc("my_departments") or []
            if isinstance(depts, list):
                depts = [d if isinstance(d, str) else
                         (d.get("my_departments") or "")
                         for d in depts]
            depts = [d for d in depts if d]
            out = {"checked": True, "ok": bool(depts), "signed_in": True,
                   "departments": depts, "email": user.get("email", "")}
    except Exception as ex:
        # Could not ASK. That is not the same as "no access", and saying
        # "you have no access" on a network blip would send someone to
        # chase a permission problem they do not have.
        out = {"checked": False, "reason": f"{type(ex).__name__}: {ex}"}

    with _lock:
        _grant_cache = dict(out)
        _grant_at = time.time()
    return dict(out)


def _grant_problem(grant: dict) -> dict | None:
    if not grant.get("checked"):
        return None
    if not grant.get("signed_in", True):
        return {
            "code": "signed_out",
            "title": "Not signed in to the shared database",
            "detail": "You are seeing the local copy only. Anything you "
                      "change stays on this PC until you sign in.",
            "action": "Settings → sign in",
        }
    depts = grant.get("departments") or []
    if not depts:
        return {
            "code": "no_grant",
            "title": "Your account has no franchise access yet",
            "detail": "Jobs will look empty because the database is "
                      "returning nothing — not because there are no "
                      "jobs. Somebody with admin access has to grant it.",
            "action": "Ask for an app_user_departments row",
        }
    active = ""
    try:
        active = config.active_department()
    except Exception:
        pass
    if active and active not in depts:
        return {
            "code": "wrong_grant",
            "title": f"You do not have access to {active}",
            "detail": f"This window is showing {active}, but your account "
                      f"can only see {', '.join(depts)}. Lists will look "
                      f"empty.",
            "action": "Switch franchise, or ask for access",
        }
    return None


def state(force: bool = False) -> dict:
    """Everything the banner needs, in one call.

    `problems` is ordered worst-first and each entry is written to be
    read by whoever is at the desk, not by whoever wrote the code.
    """
    problems: list[dict] = []

    off = _offline_state()
    if off.get("degraded"):
        queued = int(off.get("queued") or 0)
        problems.append({
            "code": "degraded",
            "title": "Working offline — the shared database is "
                     "unreachable",
            "detail": (
                f"{queued} change{'' if queued == 1 else 's'} waiting to "
                f"send. They go up automatically when it comes back."
                if queued else
                "You are reading the local copy. It may be out of date."),
            "action": "",
            "last_error": off.get("last_error") or "",
        })
    elif off.get("queued"):
        # Reachable again but the queue has not drained: still not a
        # finished state, and silence here would read as "all sent".
        problems.append({
            "code": "queue_pending",
            "title": f"{off['queued']} change(s) still waiting to send",
            "detail": "The database is reachable again and these send "
                      "automatically.",
            "action": "",
        })

    grant = grant_state(force=force)
    gp = _grant_problem(grant)
    if gp:
        problems.append(gp)

    return {
        "ok": not problems,
        "problems": problems,
        "degraded": bool(off.get("degraded")),
        "queued": int(off.get("queued") or 0),
        "grant": grant,
        "backend": _backend_name(),
    }


def log_js_error(source: str, message: str, detail: str = "") -> dict:
    """Record a browser-side error server-side.

    A panel that throws used to leave nothing behind: the window is a
    WebView with no console anybody opens, so the only evidence was the
    user saying "it did nothing".
    """
    try:
        import ems_log
        text = f"[{source or 'panel'}] {message}"
        if detail:
            text += f"\n{detail}"
        ems_log.error("web", text)
        return {"ok": True}
    except Exception as ex:
        return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
