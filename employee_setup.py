"""Employee setup, derived from current evidence, never a configured marker.

Only the optional skip decision is stored here. Account, name and folder
progress lives in its existing settings/session stores. Provider probes are
reads; no project creation, uploads, queue flushes or backend switching.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def _scope(cfg, access):
    import paths
    import config
    value = [str(paths.DATA_DIR), getattr(paths, "CHANNEL", ""),
             cfg.get("supabase_url", ""),
             (access.get("identity") or {}).get("id", ""),
             config.active_department()]
    return hashlib.sha256(json.dumps(value).encode()).hexdigest()


def _progress_path():
    import paths
    return Path(paths.data("employee_setup_choices.json"))


def _choices():
    try:
        value = json.loads(_progress_path().read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _read_folder(value):
    if not value or not os.path.isabs(value):
        return False
    try:
        with os.scandir(value) as entries:
            next(entries, None)
        return True
    except OSError:
        return False


def status(api):
    import config
    import account_access
    import supabase_client as sb
    cfg = config.load() or {}
    access = account_access.current_access()
    user = access.get("identity") or {}
    active = config.active_department() or ""
    # Never infer employee assignment from local config or owner-email fallback.
    assigned = list(access.get("departments") or []) if not access.get("error") else []
    signed = bool(access.get("signed_in"))
    steps = []

    def step(key, title, done, detail, help, optional=False, skipped=False):
        steps.append(dict(key=key, title=title, done=bool(done), detail=detail,
                          help=help, optional=optional, skipped=skipped))

    step("signin", "Sign in", signed, user.get("email") or "Not signed in",
         "Use your work email and this workspace's password. Ask your administrator for access if sign-in fails.")
    step("profile_name", "Your display name", signed and bool(str(user.get("display_name") or "").strip()),
         user.get("display_name") or "Name still needed", "Enter the name coworkers should see on comments and updates.")
    step("franchise", "Assigned franchise", active in assigned,
         active if active in assigned else (access.get("error") or "No assigned franchise selected"),
         "Choose an assignment returned by the server. If none appears, ask your administrator to assign you, then check again.")
    trello_ok = False
    if signed and active in assigned:
        try:
            import trello_client
            me = trello_client._call("/members/me", params={"fields": "id,fullName,username"})
            trello_ok = isinstance(me, dict) and bool(me.get("id"))
        except Exception:
            pass
    step("trello", "Connect Trello", trello_ok,
         "Account verified with Trello" if trello_ok else "Trello has not passed its account check",
         "Select Connect Trello, approve access in your browser, then check again. If authorization is unavailable, ask your administrator to configure the work connection; do not enter API keys.")
    skipped = bool(_choices().get(_scope(cfg, access), {}).get("companycam_skipped"))
    cc_ok = False
    if signed and active in assigned and not skipped:
        try:
            import companycam_api as cc
            # Require the personal connection before probing; saved status alone
            # is not success. GET /projects verifies read access, not write access.
            personal = sb.external_connection_status("companycam", active) or {}
            if personal.get("status") == "connected" and cc.cloud_gateway_available():
                rows = cc._call("/projects", params={"per_page": 1}, method="GET", _max_retries=0)
                cc_ok = isinstance(rows, list)
        except Exception:
            pass
    step("companycam", "CompanyCam (optional)", cc_ok,
         "Read access verified" if cc_ok else ("Skipped for now" if skipped else "Read access not verified"),
         "Connect your work account in the browser, then check again. You may skip this connection. Setup never creates a project or uploads a photo.", True, skipped)
    jobs = str(cfg.get("audit_base") or "").strip()
    runs = str(cfg.get("runs_dir") or "").strip()
    jobs_ok, runs_ok = _read_folder(jobs), _read_folder(runs)
    step("folders", "Shared folders", active in assigned and jobs_ok and runs_ok,
         "Both folders can be read" if jobs_ok and runs_ok else "Cannot read: " + ", ".join(
             name for name, ok in [("job folder", jobs_ok), ("Daily Run folder", runs_ok)] if not ok),
         "Connect to the office network or VPN. Choose the shared job root and Daily Run folder for this franchise; no files will be written.")
    live_ok = False
    if all(s["done"] for s in steps if not s["optional"]):
        try:
            # A real authenticated, RLS-filtered read. Empty results are valid.
            import ems_db
            rows = sb.rest("GET", "jobs", params={"select": "canon_key", "limit": "1"})
            live_ok = isinstance(rows, list) and ems_db.backend_name() == "supabase"
        except Exception:
            pass
    step("live_data", "Check shared data", live_ok,
         "Shared jobs read successfully; no records were changed" if live_ok else "Shared job access has not passed verification",
         "Finish the required steps, then check again. If this fails, check your network and ask your administrator to verify this workspace's shared database and permissions. Setup will not switch environments.")
    return dict(ok=True, steps=steps, all_done=all(s["done"] or s["skipped"] for s in steps),
                done=sum(s["done"] or s["skipped"] for s in steps), total=len(steps),
                active_franchise=active, departments=assigned,
                folders={"job_root": jobs, "runs_dir": runs},
                is_admin=bool(access.get("is_admin")), is_owner=bool(access.get("is_owner")))


def action(api, name, values=None):
    """Narrow wizard commands; never expose arbitrary Settings.save."""
    import account_access
    import config
    values = values if isinstance(values, dict) else {}
    if name == "signin":
        result = api.supabase_sign_in_password(values.get("email", ""), values.get("password", ""))
        return {**result, "reload": bool(result.get("ok"))}
    access = account_access.current_access()
    if not access.get("signed_in") or access.get("error"):
        return {"ok": False, "error": "Sign in and verify server access before continuing."}
    if name == "name":
        return api.save_my_display_name(values.get("name", ""))
    if name == "franchise":
        key = values.get("key")
        if not key or key not in access.get("departments", []):
            return {"ok": False, "error": "That franchise is not assigned by the server. Ask your administrator for access."}
        if not config.set_active_department(key):
            return {"ok": False, "error": "Your assigned franchise needs its local profile installed by your administrator."}
        from settings_web import _invalidate
        _invalidate("setup franchise changed")
        return {"ok": True, "reload": True}
    if config.active_department() not in access.get("departments", []):
        return {"ok": False, "error": "Choose a server-assigned franchise first."}
    if name in ("trello", "companycam"):
        return api.open_user_connection(name)
    if name == "skip_companycam":
        cfg = config.load() or {}
        choices = _choices()
        choices[_scope(cfg, access)] = {"companycam_skipped": True}
        target = _progress_path()
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(choices), encoding="utf-8")
        temp.replace(target)
        return {"ok": True}
    if name == "folders":
        jobs, runs = str(values.get("job_root") or "").strip(), str(values.get("runs_dir") or "").strip()
        if not _read_folder(jobs) or not _read_folder(runs):
            return {"ok": False, "error": "Both folders must be readable. Check your office network or VPN and choose the folders again."}
        return api.save_my_franchise_folders(config.active_department(), jobs, runs)
    return {"ok": False, "error": "Unknown setup action."}
