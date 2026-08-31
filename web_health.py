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


def invalidate_grant_cache() -> None:
    """Forget the last auth/grant result after sign-in or sign-out."""
    global _grant_cache, _grant_at
    with _lock:
        _grant_cache = {}
        _grant_at = 0.0


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


def _local_checks() -> list[dict]:
    """Fast, read-only startup checks with no network calls."""
    import os
    try:
        cfg = config.load() or {}
    except Exception:
        cfg = {}
    checks = []

    def path_check(code, label, key, kind="dir", required=True):
        value = (cfg.get(key) or "").strip()
        exists = bool(value) and (os.path.isfile(value) if kind == "file"
                                  else os.path.isdir(value))
        checks.append({"code": code, "label": label, "ok": exists,
                       "required": required, "value_set": bool(value),
                       "action": f"Settings → set {label}"})

    path_check("jobs_root", "Jobs folder", "audit_base")
    path_check("run_docs", "Run Doc folder", "runs_dir")
    path_check("snapshot_output", "Snapshot output folder", "snapshot_output")
    path_check("snapshot_template", "Snapshot template", "snapshot_template",
               kind="file")

    trello_ok = bool((cfg.get("trello_api_key") or "").strip()
                     and (cfg.get("trello_token") or "").strip())
    checks.append({"code": "trello_config", "label": "Trello",
                   "ok": trello_ok, "required": True, "value_set": trello_ok,
                   "action": "Settings → connect Trello"})

    cc_ok = bool((cfg.get("companycam_api_token") or "").strip())
    checks.append({"code": "companycam_config", "label": "CompanyCam",
                   "ok": cc_ok, "required": False, "value_set": cc_ok,
                   "action": "Settings → connect CompanyCam"})

    wc_enabled = bool(cfg.get("enable_workcenter_alpha"))
    checks.append({"code": "workcenter_config", "label": "WorkCenter",
                   "ok": wc_enabled, "required": False,
                   "value_set": wc_enabled,
                   "action": "Settings → enable WorkCenter"})
    return checks


def _backup_check() -> dict:
    try:
        import data_backup
        return data_backup.health()
    except Exception as ex:
        return {"ok": False, "checks": [], "error": str(ex)}


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

    local_checks = _local_checks()
    for check in local_checks:
        if check.get("required") and not check.get("ok"):
            problems.append({
                "code": check["code"],
                "title": f"{check['label']} is unavailable",
                "detail": "The related workflow cannot run until this "
                          "location or connection is restored.",
                "action": check.get("action") or "Open Settings",
            })

    backup = _backup_check()
    if not backup.get("ok") and not backup.get("pending"):
        bad = [c for c in backup.get("checks", []) if not c.get("ok")]
        names = ", ".join(c.get("name", "backup") for c in bad)
        problems.append({
            "code": "backup_stale",
            "title": "Backups need attention",
            "detail": (f"Backup failed or remains stale: {names}." if names else
                       "Backup status could not be verified."),
            "action": "Data & Sync Health → Retry backup",
        })

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
        "checks": local_checks,
        "backup": backup,
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
