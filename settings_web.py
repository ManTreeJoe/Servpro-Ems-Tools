"""Settings — Pywebview spike (config editor)."""
from __future__ import annotations
import os, sys
import webview

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path: sys.path.insert(0, _HERE)
import config

ASSETS_DIR = os.path.join(_HERE, "settings_web_assets")
INDEX_HTML = os.path.join(ASSETS_DIR, "index.html")


# Field schema mirrors settings_gui.FIELDS but kept simple — every
# value is treated as a string in the web form. Path validation lives
# at save-time.
FIELDS = [
    ("audit_base",          "Job folders root",           "dir"),
    ("runs_dir",            "Daily run docs folder",      "dir"),
    ("photos_root",         "Photos root folder",         "dir"),
    ("snapshot_template",   "Snapshot fillable PDF",      "file"),
    ("snapshot_output",     "Snapshot PDF output folder", "dir"),
    ("apa_monitor_root",    "APA Monitor docs folder",    "dir"),
    ("snapshots_root",      "Snapshot tracking workbook", "file"),
    ("dispute_tracker_path", "Dispute tracking workbook", "file"),
    ("wc_audit_dir",        "WorkCenter audit folder",    "dir"),
    ("photos_extra_roots",  "Additional photo roots",     "list"),
    ("workcenter_url",      "Workcenter URL",             "url"),
    ("enable_workcenter_alpha", "Enable WorkCenter tools", "bool"),
    ("snapshot_auto_reconcile", "Auto-reconcile snapshot tracking", "bool"),
    ("show_sort_files",     "Show Sort Files in toolbar", "bool"),
    ("show_new_job",        "Show New EMS Job in toolbar","bool"),
    ("trello_api_key",      "Trello API key",             "secret"),
    ("trello_token",        "Trello token (per-user)",    "secret"),
    ("trello_workspace_id", "Trello workspace ID",        "text"),
    ("trello_snapshot_list_id", "Trello Snapshot list ID", "text"),
    ("disputes_board_short_link", "Disputes board short link", "text"),
    ("trello_boards_exclude", "Trello boards to exclude", "list"),
    ("companycam_api_token", "CompanyCam access token",   "secret"),
    ("graph_client_id",      "Microsoft Graph client ID", "text"),
    ("graph_tenant_id",      "Microsoft Graph tenant ID", "text"),
    ("franchise_name",      "Franchise display name",     "text"),
    ("office_phone",        "Office phone",               "tel"),
    ("monthly_job_completion_quota", "Monthly completed-job quota", "text"),
    # Shared job-index backend. ONE project serves both departments —
    # Row-Level Security keyed on jobs.department is what separates IE
    # from OC, so these stay global rather than per-department.
    # The anon/publishable key is designed to be shipped in a client;
    # the service_role key must NEVER be stored here — it bypasses RLS.
    ("supabase_url",        "Supabase project URL",       "url"),
    ("supabase_anon_key",   "Supabase anon / publishable key", "secret"),
    ("appearance",          "Appearance",                 "choice", ["system","light","dark"]),
    ("ui_scale",            "UI scale",                   "choice",
                            ["auto","1.0","1.25","1.5","1.75","2.0","2.25","2.5"]),
    ("global_hotkey_enabled", "Use a shortcut to show Linguar Hub", "bool"),
    ("global_hotkey",       "Show-app shortcut",           "choice",
                            ["ctrl+alt+space", "ctrl+shift+space",
                             "alt+shift+space", "ctrl+alt+h"]),
    ("preferred_browser",   "Default browser command",    "text"),
]

_PERSONAL_FIELDS = {
    "appearance", "ui_scale", "global_hotkey_enabled", "global_hotkey",
    "preferred_browser", "show_sort_files", "show_new_job",
    # These are paths as THIS Windows machine reaches the shared storage.
    # That may be a mapped drive, a UNC server share, or a locally synced
    # OneDrive/SharePoint library. Regular users must be able to select
    # their machine's roots without gaining control of franchise settings.
    "audit_base", "runs_dir", "photos_root", "photos_extra_roots",
    "snapshot_template", "snapshot_output", "apa_monitor_root",
    "snapshots_root", "dispute_tracker_path", "wc_audit_dir",
    # Trello grants one token per person; the API key/workspace remain admin.
    "trello_token",
}

_FIELD_GROUPS = {
    "appearance": "Appearance & shortcuts", "ui_scale": "Appearance & shortcuts",
    "global_hotkey_enabled": "Appearance & shortcuts", "global_hotkey": "Appearance & shortcuts",
    "preferred_browser": "Appearance & shortcuts", "show_sort_files": "Appearance & shortcuts",
    "show_new_job": "Appearance & shortcuts",
    "audit_base": "Folders & documents", "runs_dir": "Folders & documents",
    "photos_root": "Folders & documents", "photos_extra_roots": "Folders & documents",
    "snapshot_template": "Folders & documents", "snapshot_output": "Folders & documents",
    "snapshots_root": "Folders & documents", "apa_monitor_root": "Folders & documents",
    "dispute_tracker_path": "Folders & documents", "wc_audit_dir": "Folders & documents",
    "trello_api_key": "Connections", "trello_token": "Connections",
    "trello_workspace_id": "Connections", "trello_snapshot_list_id": "Connections",
    "disputes_board_short_link": "Connections",
    "trello_boards_exclude": "Connections", "companycam_api_token": "Connections",
    "graph_client_id": "Connections", "graph_tenant_id": "Connections",
    "supabase_url": "Connections", "supabase_anon_key": "Connections",
    "workcenter_url": "Connections", "enable_workcenter_alpha": "Connections",
    "franchise_name": "Office identity", "office_phone": "Office identity",
    "monthly_job_completion_quota": "Reporting goals",
    "snapshot_auto_reconcile": "Automation",
}


# Fields a department profile can override (multi-department mode). Grouped
# for the Settings UI. Mirrors config.DEPT_OVERRIDE_KEYS (minus the two
# list-typed keys, which stay in raw config.json for advanced edits).
DEPT_FIELDS = [
    ("trello_api_key",        "Trello API key",           "secret",  "Trello"),
    ("trello_token",          "Trello token",             "secret",  "Trello"),
    ("trello_workspace_id",   "Trello workspace ID",      "text",    "Trello"),
    ("trello_snapshot_list_id","Trello snapshot list ID", "text",    "Trello"),
    ("audit_base",            "Job folders root",         "dir",     "Folders"),
    ("runs_dir",              "Daily run docs folder",    "dir",     "Folders"),
    ("photos_root",           "Photos root folder",       "dir",     "Folders"),
    ("snapshot_template",     "Snapshot fillable PDF",    "file",    "Folders"),
    ("apa_monitor_root",      "APA Monitor docs folder",  "dir",     "Folders"),
    ("snapshots_root",        "Snapshots folder",         "dir",     "Folders"),
    ("dispute_tracker_path",  "Dispute tracker workbook", "file",    "Folders"),
    # Blank = this franchise has no disputes board yet, so its tracker
    # stays a plain editable workbook and syncs from nothing.
    ("disputes_board_short_link", "Disputes board (Trello short link)",
     "text", "Trello"),
    ("franchise_name",        "Franchise legal name",     "text",    "Identity"),
    ("office_phone",          "Office phone",             "text",    "Identity"),
    # Each office has its own CompanyCam account. Blank means INHERIT the
    # base token, which is how OC's projects were being created in IE's
    # CompanyCam — the field has to exist before it can be set.
    ("companycam_api_token",  "CompanyCam access token",  "secret",
     "CompanyCam"),
]


# The ONLY keys the main Settings form may write. A key not declared in
# FIELDS did not come from that form, so it is not the form's to save.
#
# This is a second line of defence for a bug that has now bitten twice. The
# page's save loop used a global `[data-key]` selector, which also matched
# the Departments editor (showing whichever department was picked, OC by
# default) and the panel-visibility checkboxes. Clicking 💾 Save therefore
# wrote that department's values — including `trello_workspace_id` — into
# the config, which is how IE ended up searching OC's Trello workspace.
# The selector is scoped now; this makes the same mistake unwritable.
_ALLOWED_SAVE_KEYS = frozenset(f[0] for f in FIELDS)
_INITIAL_ADMIN_EMAIL = "nathan@servpro10100.com"


def _signed_in_email():
    try:
        import supabase_client
        return ((supabase_client.current_user() or {}).get("email") or "").strip().lower()
    except Exception:
        return ""


def _is_admin():
    """Server decision when available; exact bootstrap email for migration setup."""
    # The owner is the bootstrap administrator even before (or if) the
    # app_admins seed row exists. Previously an RPC response of
    # {is_admin:false} returned early and hid Admin setup from the one
    # account that needed it to finish configuration.
    if _signed_in_email() == _INITIAL_ADMIN_EMAIL:
        return True
    try:
        import supabase_client
        result = supabase_client.rpc("my_app_access")
        if isinstance(result, dict):
            return bool(result.get("is_admin"))
    except Exception:
        pass
    return _signed_in_email() == _INITIAL_ADMIN_EMAIL


def _admin_enforcement_active():
    """Account roles apply once the shared Supabase service is configured."""
    try:
        import supabase_client
        return supabase_client.is_configured()
    except Exception:
        return False


def _invalidate(reason):
    """Drop derived caches so a saved setting applies without a restart.
    Never raises — failing to clear a cache must not fail the save."""
    try:
        import cache_bust
        return cache_bust.invalidate_all(reason)
    except Exception as ex:
        return {"cleared": [], "failed": [str(ex)]}


class Api:
    def __init__(self): self._window = None
    def attach(self, w): self._window = w

    def schema(self):
        return [{"key": f[0], "label": f[1], "kind": f[2],
                  "choices": (f[3] if len(f) > 3 else []),
                  "scope": ("personal" if f[0] in _PERSONAL_FIELDS else "admin"),
                  "group": _FIELD_GROUPS.get(f[0], "Other")}
                for f in FIELDS]

    def settings_access(self):
        email = _signed_in_email()
        is_admin = _is_admin()
        departments = []
        try:
            import supabase_client
            access = supabase_client.rpc("my_app_access") or {}
            if isinstance(access, dict):
                departments = access.get("departments") or []
                is_admin = is_admin or bool(access.get("is_admin"))
        except Exception:
            pass
        return {"ok": True, "email": email, "is_admin": is_admin,
                "departments": departments}

    def _my_folder_departments(self):
        """Franchises whose machine-local roots this user may configure."""
        base = config.load_base() or {}
        configured = list((base.get("departments") or {}).keys())
        if _is_admin():
            return configured
        assigned = []
        try:
            import supabase_client
            access = supabase_client.rpc("my_app_access") or {}
            if isinstance(access, dict):
                assigned = list(access.get("departments") or [])
        except Exception:
            pass
        allowed = [key for key in configured if key in assigned]
        active = (base.get("active_department") or "").strip()
        if not allowed and active in configured:
            allowed = [active]
        return allowed

    def my_franchise_folders(self):
        """Per-PC job and run-doc roots for the user's franchises."""
        try:
            base = config.load_base() or {}
            profiles = base.get("departments") or {}
            rows = []
            for key in self._my_folder_departments():
                profile = profiles.get(key) if isinstance(profiles.get(key), dict) else {}
                job_root = str(profile.get("audit_base") or "").strip()
                runs_dir = str(profile.get("runs_dir") or "").strip()
                rows.append({
                    "key": key,
                    "label": profile.get("label") or key,
                    "active": key == (base.get("active_department") or "").strip(),
                    "job_root": job_root,
                    "runs_dir": runs_dir,
                    "job_connected": bool(job_root and os.path.isdir(job_root)),
                    "runs_connected": bool(runs_dir and os.path.isdir(runs_dir)),
                })
            return {"ok": True, "departments": rows}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def save_my_franchise_folders(self, key: str, job_root: str, runs_dir: str):
        """Save only machine-local roots for one assigned franchise."""
        key = (key or "").strip()
        if key not in self._my_folder_departments():
            return {"ok": False, "error": "That franchise is not assigned to you."}
        job_root = os.path.normpath((job_root or "").strip())
        runs_dir = os.path.normpath((runs_dir or "").strip())
        missing = []
        if not job_root or not os.path.isdir(job_root):
            missing.append("job folders root")
        if not runs_dir or not os.path.isdir(runs_dir):
            missing.append("daily run docs folder")
        if missing:
            return {"ok": False,
                    "error": "Windows cannot open the " + " and ".join(missing) + "."}
        try:
            base = config.load_base() or {}
            profiles = dict(base.get("departments") or {})
            profile = dict(profiles.get(key) or {})
            profile["audit_base"] = job_root
            profile["runs_dir"] = runs_dir
            profiles[key] = profile
            base["departments"] = profiles
            config.save(base)
            _invalidate("per-franchise local folder save")
            return {"ok": True, "key": key,
                    "message": f"{key} folders connected on this PC."}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def admin_users(self):
        if _admin_enforcement_active() and not _is_admin():
            return {"ok": False, "error": "Administrator access required."}
        try:
            import supabase_client
            rows = supabase_client.rpc("admin_list_user_access") or []
            return {"ok": True, "users": rows,
                    "franchises": [d.get("key") for d in config.list_departments()]}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def admin_set_user_franchises(self, user_id, departments):
        if not _is_admin():
            return {"ok": False, "error": "Administrator access required."}
        if not user_id or not isinstance(departments, list):
            return {"ok": False, "error": "User and franchises are required."}
        allowed = {str(d.get("key") or "").upper()
                   for d in config.list_departments()}
        selected = sorted({str(d or "").strip().upper() for d in departments
                           if str(d or "").strip().upper() in allowed})
        try:
            import supabase_client
            saved = supabase_client.rpc("admin_set_user_departments", {
                "p_user_id": user_id, "p_departments": selected}) or []
            return {"ok": True, "departments": saved}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def load(self):
        # Show what is actually IN EFFECT for the active department, so the
        # form is what-you-see-is-what-you-save: save() routes any
        # department-scoped key to the active department's profile, and
        # showing base values here would let an unrelated save copy one
        # franchise's paths into the other's profile.
        try:
            return dict(config.load() or {})
        except Exception:
            return {}

    # ── Property-management directory ───────────────────────────────
    def property_managers(self):
        try:
            import property_managers as pm
            return {"ok": True, "records": pm.list_records(),
                    "default_naming": pm.DEFAULT_NAMING}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def save_property_manager(self, values, rename_trello=False):
        try:
            import property_managers as pm
            record, old = pm.save_record(values)
            trello_updated = False
            warning = ""
            if rename_trello and record.get("template_card_id"):
                record["previous_company_name"] = (old or {}).get(
                    "company_name", "")
                new_title = pm.trello_name(record)
                import trello_client
                updated = trello_client.update_card_name(
                    record["template_card_id"], new_title)
                if updated:
                    record["template_card_name"] = (updated.get("name")
                                                    or new_title)
                    record.pop("previous_company_name", None)
                    record, _ = pm.save_record(record)
                    trello_updated = True
                else:
                    warning = "Saved here, but Trello did not accept the rename."
            return {"ok": True, "record": record,
                    "trello_updated": trello_updated, "warning": warning}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def save(self, values):
        if not isinstance(values, dict):
            return {"ok": False, "error": "values must be a dict"}
        if not _is_admin():
            attempted = set(values) - _PERSONAL_FIELDS
            if attempted:
                return {"ok": False,
                        "error": "Administrator access is required to change shared setup."}
        try:
            # Write to the BASE config (never the department-overlaid view),
            # so saving the global fields can't accidentally bake the active
            # department's overrides into the base.
            cfg = dict(config.load_base() or {})
            # ...EXCEPT for department-scoped keys while multi-dept is on.
            # Seven of this form's fields (audit_base, runs_dir, photos_root,
            # snapshot_template, apa_monitor_root, trello key/token) are also
            # DEPT_OVERRIDE_KEYS. Writing those to the base sets them for
            # every department that inherits — one franchise's paths silently
            # become another's. Route them to the ACTIVE department instead,
            # which is the franchise the user is looking at when they save.
            # Drop anything the main form has no business writing. Ignoring
            # is right rather than failing: the extra keys are a UI accident,
            # not user intent, and rejecting the whole save would block a
            # legitimate settings change. Logged + returned so it's visible.
            incoming = dict(values)
            rejected = sorted(k for k in incoming
                              if k not in _ALLOWED_SAVE_KEYS)
            values = {k: v for k, v in incoming.items()
                      if k in _ALLOWED_SAVE_KEYS}
            kinds = {f[0]: f[2] for f in FIELDS}
            for key in list(values):
                if kinds.get(key) == "list" and isinstance(values[key], str):
                    values[key] = [part.strip() for part in
                                   values[key].replace(";", "\n").splitlines()
                                   if part.strip()]
            if rejected:
                try:
                    import ems_log
                    ems_log.warn("settings",
                                 f"ignored non-form keys on save: {rejected}")
                except Exception:
                    pass
            routed = {}
            if cfg.get("multi_department_enabled"):
                active = (cfg.get("active_department") or "").strip()
                depts = cfg.get("departments") or {}
                if active and isinstance(depts.get(active), dict):
                    for k in list(values):
                        if k in config.DEPT_OVERRIDE_KEYS:
                            routed[k] = values.pop(k)
                    if routed:
                        prof = dict(depts[active])
                        prof.update(routed)
                        depts[active] = prof
                        cfg["departments"] = depts
            cfg.update(values)
            config.save(cfg)
            # Make the change live NOW. Without this, a saved setting sat
            # behind whatever each module had already derived from the old
            # config — a Trello board id, the department→root map, the
            # storage backend — so the app had to be restarted to pick it
            # up. Appearance / UI scale still need a page reload, since
            # those are applied to the DOM at render time.
            _bust = _invalidate("settings save")
            return {"ok": True, "routed_to_department": sorted(routed),
                    "ignored_keys": rejected,
                    "applied_live": True, "cache": _bust}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── Per-department browser routing ───────────────────────────────
    def get_dept_browsers(self) -> dict:
        """Current per-department browser commands + the department list."""
        try:
            base = config.load_base() or {}
            depts = list((base.get("departments") or {}).keys())
            return {"ok": True,
                    "browsers": base.get("dept_browsers") or {},
                    "departments": depts,
                    "active": (base.get("active_department") or "").strip()}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def set_dept_browser(self, dept: str, command: str) -> dict:
        """Set (or clear) the browser command for one department. `command`
        is a browser .exe path, or a template containing {url}."""
        dept = (dept or "").strip().upper()
        if not dept:
            return {"ok": False, "error": "dept required"}
        try:
            cfg = dict(config.load_base() or {})
            browsers = dict(cfg.get("dept_browsers") or {})
            if (command or "").strip():
                browsers[dept] = command.strip()
            else:
                browsers.pop(dept, None)
            cfg["dept_browsers"] = browsers
            config.save(cfg)
            return {"ok": True, "dept": dept}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── Offices ──────────────────────────────────────────────────────
    #
    # Not a fixed IE/OC pair: an install may be one office, or three.

    def add_department(self, key: str, label: str = "") -> dict:
        try:
            ok, err = config.add_department(key, label)
            return {"ok": ok, "error": err, "departments":
                    list((config.load_base().get("departments") or {}))}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def remove_department(self, key: str) -> dict:
        try:
            ok, err = config.remove_department(key)
            return {"ok": ok, "error": err, "departments":
                    list((config.load_base().get("departments") or {}))}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    # ── Multiple-franchise config ────────────────────────────────────
    def dept_config(self):
        """State for the Departments settings section: whether it's on,
        the field schema, each department's overrides, and the base values
        (shown as the 'inherits' placeholder for blank overrides)."""
        try:
            base = config.load_base()
            depts = base.get("departments") or {}
            fields = [{"key": f[0], "label": f[1], "kind": f[2], "group": f[3]}
                      for f in DEPT_FIELDS]
            keyset = [f[0] for f in DEPT_FIELDS]
            out = []
            for k, v in depts.items():
                v = v if isinstance(v, dict) else {}
                out.append({
                    "key": k,
                    "label": (v.get("label") or k),
                    # No office is special. This said `k == "IE"`, so an
                    # install that is only OC — or only LA — had a "base"
                    # department it could never be. The base is whichever
                    # one is active, or the first if none is.
                    "is_base": (k == ((base.get("active_department") or "")
                                      .strip() or next(iter(depts), ""))),
                    "overrides": {fk: v.get(fk, "") for fk in keyset},
                })
            return {
                "ok": True,
                "enabled": bool(base.get("multi_department_enabled")),
                "active": (base.get("active_department") or "").strip(),
                "fields": fields,
                "departments": out,
                "base": {fk: base.get(fk, "") for fk in keyset},
                # Cross-franchise misconfiguration (shared workspace / share,
                # or an identity inherited from the base). Offline + cheap.
                "problems": config.check_department_integrity(),
            }
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def set_multi_dept(self, enabled: bool):
        """Toggle multiple-franchise mode without inventing offices."""
        try:
            if enabled:
                config.ensure_departments_scaffold()
            base = config.load_base()
            base["multi_department_enabled"] = bool(enabled)
            config.save(base)
            _invalidate("multi-department toggle")
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def save_department(self, key: str, overrides: dict, label: str = ""):
        """Persist one department's override fields. Only whitelisted
        DEPT_FIELDS keys are written; blank values are kept (they mean
        'inherit the base'). Never touches the base flat keys."""
        key = (key or "").strip()
        if not key:
            return {"ok": False, "error": "missing department key"}
        if not isinstance(overrides, dict):
            return {"ok": False, "error": "overrides must be a dict"}
        try:
            base = config.load_base()
            depts = base.get("departments")
            if not isinstance(depts, dict):
                depts = {}
            prof = dict(depts.get(key) if isinstance(depts.get(key), dict) else {})
            if label:
                prof["label"] = label
            allowed = {f[0] for f in DEPT_FIELDS}
            for fk, val in overrides.items():
                if fk in allowed:
                    prof[fk] = ("" if val is None else str(val)).strip()
            depts[key] = prof
            base["departments"] = depts
            config.save(base)
            _invalidate("department settings save")
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def _start_dir(self, start):
        """Best initial folder for a picker, given the field's current
        value (which may be a dir, a file, or empty)."""
        s = (start or "").strip()
        if not s:
            return ""
        if os.path.isdir(s):
            return s
        parent = os.path.dirname(s)
        return parent if os.path.isdir(parent) else ""

    def pick_dir(self, start_dir: str = "") -> dict:
        """Native folder picker for a `dir` path field (e.g. the Daily
        run docs folder when its OneDrive path shifts). Returns the chosen
        absolute path so the field can be filled without typing."""
        if self._window is None:
            return {"ok": False, "error": "no window"}
        try:
            result = self._window.create_file_dialog(
                webview.FOLDER_DIALOG,
                directory=self._start_dir(start_dir),
                allow_multiple=False)
            if not result:
                return {"ok": True, "path": "", "cancelled": True}
            path = result[0] if isinstance(result, (list, tuple)) else result
            return {"ok": True, "path": str(path)}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def pick_file(self, start_dir: str = "") -> dict:
        """Native file picker for a `file` path field (e.g. the snapshot
        fillable PDF)."""
        if self._window is None:
            return {"ok": False, "error": "no window"}
        try:
            result = self._window.create_file_dialog(
                webview.OPEN_DIALOG,
                directory=self._start_dir(start_dir),
                allow_multiple=False)
            if not result:
                return {"ok": True, "path": "", "cancelled": True}
            path = result[0] if isinstance(result, (list, tuple)) else result
            return {"ok": True, "path": str(path)}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def open_data_folder(self):
        """Open the per-user EMS data folder (logs, caches, persistence
        JSON). Useful when the user needs to manually edit a config
        file or share a log with support."""
        try:
            import paths
            p = paths.DATA_DIR
            if not os.path.isdir(p):
                os.makedirs(p, exist_ok=True)
            os.startfile(p); return True
        except Exception:
            return False

    def open_config_file(self):
        """Open config.json directly in Notepad."""
        try:
            import paths, subprocess
            p = os.path.join(paths.DATA_DIR, "config.json")
            if os.path.isfile(p):
                subprocess.Popen(["notepad.exe", p])
                return True
        except Exception:
            pass
        return False

    def get_tech_roster(self) -> dict:
        """Return the parsed tech roster as a sorted list of
        (initials, full_name) pairs. Drives the rich roster editor
        inside the settings panel — no need to open Notepad just to
        add a new tech's initials."""
        try:
            import paths, json
            p = os.path.join(paths.DATA_DIR, "tech_roster.json")
            data = {}
            if os.path.isfile(p):
                with open(p, "r", encoding="utf-8") as fh:
                    data = json.load(fh) or {}
            return {"path": p, "entries": [
                {"initials": k, "full_name": v}
                for k, v in sorted((data or {}).items(),
                                    key=lambda kv: kv[0].upper())
            ]}
        except Exception as ex:
            return {"path": "", "entries": [], "error": str(ex)}

    def save_tech_roster(self, entries: list) -> dict:
        """Persist the roster from the editor. `entries` is a list of
        {initials, full_name} dicts. Trims, dedupes by initials, and
        writes back as JSON the audit/IUQ/photo-folders tools all read."""
        if not isinstance(entries, list):
            return {"ok": False, "error": "entries must be a list"}
        try:
            import paths, json
            p = os.path.join(paths.DATA_DIR, "tech_roster.json")
            out = {}
            for e in entries:
                if not isinstance(e, dict): continue
                k = (e.get("initials") or "").strip().upper()
                v = (e.get("full_name") or "").strip()
                if not k or not v: continue
                out[k] = v
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(out, fh, indent=2, sort_keys=True)
            return {"ok": True, "count": len(out)}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def open_tech_roster(self):
        """Open the tech roster JSON for direct editing. The roster
        maps tech initials → full names (FB = Fernando Baca) and is
        used across audit / IUQ / photo folders."""
        try:
            import paths, subprocess
            p = os.path.join(paths.DATA_DIR, "tech_roster.json")
            if not os.path.isfile(p):
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write('{\n  "FB": "Fernando Baca"\n}\n')
            subprocess.Popen(["notepad.exe", p])
            return True
        except Exception:
            return False

    def lookup_job_identity(self, name):
        """Read-only 'what's tied to this job?' view — the canonical job the
        `name` resolves to, its learned aliases, and every external link
        (folder / Trello / CompanyCam). Lets the user verify the auto-linking
        graph. Returns {ok, found, name, canon_key, display_name, aliases,
        links:[{type,value}]}."""
        name = (name or "").strip()
        if not name:
            return {"ok": False, "error": "type a name"}
        try:
            import ems_db
            ident = ems_db.job_identity(name)
            if not ident:
                return {"ok": True, "found": False, "name": name}
            job = ident["job"]
            links = [{"type": l.get("link_type"), "value": l.get("link_value")}
                     for l in ident.get("links", [])]
            aliases = list(ident.get("aliases", []))   # already spelling strings
            return {"ok": True, "found": True, "name": name,
                    "canon_key": job.get("canon_key", ""),
                    "display_name": job.get("display_name", ""),
                    "status": job.get("status", ""),
                    "aliases": aliases, "links": links}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def backfill_job_graph(self):
        """Seed the identity graph from existing folder + Trello pins so
        auto-linking benefits from history. Idempotent. Returns the counts."""
        try:
            import persistence
            res = persistence.backfill_job_graph()
            return {"ok": True, **res}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def authorize_trello(self):
        """Sign in to Trello — approve in the browser, token saved for you.

        The old version opened Trello's token page with a HARDCODED api key
        (4f7cf06b…) that isn't the key this install calls with, so the token
        it produced authenticated as a different application and every later
        request failed. It also required copy-pasting the token back.

        Now: uses the configured key, catches the token on a loopback
        listener, and writes it to the ACTIVE department (trello_token is
        department-scoped — writing it to the base would hand one
        franchise's token to the other).
        """
        try:
            import trello_auth
            res = trello_auth.authorize()
            if res.get("ok"):
                return {"ok": True,
                        "message": f"Trello connected ({res.get('scope')})"}
            return res
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def trello_allowed_origin(self) -> dict:
        """The origin to register against the Trello API key.

        Trello validates `return_url` against the key's Allowed Origins and
        rejects anything else with "Invalid return_url". Shown in Settings
        so the string can be copied rather than guessed."""
        try:
            import trello_auth
            return {"ok": True, "origin": trello_auth.allowed_origin(),
                    "admin_url": "https://trello.com/apps/admin"}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def authorize_trello_manual(self) -> dict:
        """Fallback: open Trello WITHOUT a return_url, so it prints the
        token for copy-paste. Needs no Allowed Origins entry, which is the
        point — it works even when the loopback origin isn't registered."""
        try:
            import trello_auth
            import webbrowser
            res = trello_auth.manual_url()
            if not res.get("ok"):
                return res
            webbrowser.open(res["url"])
            return {"ok": True, "manual": True,
                    "message": "Trello opened — copy the token it shows and "
                               "paste it into the Trello token field below."}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    # ── Cloud backend (Supabase) ────────────────────────────────────────
    #
    # Sign-in is email one-time-code, not password: there is no password to
    # leak into a config file or a build, and the session refresh token
    # lives in DATA_DIR alongside the other per-user state.
    #
    # Only the anon/publishable key is ever entered here. The service_role
    # key bypasses RLS entirely — it must never be pasted into Settings,
    # stored in config, or shipped in the .exe.

    def supabase_status(self) -> dict:
        """Configured / reachable / signed-in, plus anything waiting to
        sync, for the Settings panel."""
        try:
            import supabase_client
            import ems_db
            import ems_db_offline
            h = supabase_client.health()
            h["backend"] = ems_db.backend_name()
            h["offline"] = ems_db_offline.status()
            h["ok"] = True
            return h
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def supabase_flush_queue(self) -> dict:
        """Replay writes made while the shared database was unreachable."""
        try:
            import ems_db_offline
            res = ems_db_offline.flush_queue()
            if res["error"]:
                return {"ok": False,
                        "error": f"Sent {res['sent']}, then stopped: "
                                 f"{res['error']}"}
            return {"ok": True,
                    "message": (f"Synced {res['sent']} change(s)."
                                if res["sent"] else "Nothing waiting.")}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def supabase_send_code(self, email) -> dict:
        """Mail a 6-digit login code."""
        email = (email or "").strip()
        if not email:
            return {"ok": False, "error": "Enter your email address first."}
        try:
            import supabase_client
            supabase_client.send_login_code(email)
            return {"ok": True,
                    "message": f"Code sent to {email}. It expires in an hour."}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def supabase_sign_in_password(self, email, password) -> dict:
        """Basic email/password sign-in. The password is never persisted."""
        email = (email or "").strip()
        if not email or not password:
            return {"ok": False, "error": "Enter your email and password."}
        try:
            import supabase_client
            supabase_client.sign_in_with_password(email, password)
            _invalidate("supabase password sign-in")
            try:
                import web_health
                web_health.invalidate_grant_cache()
            except Exception:
                pass
            user = supabase_client.current_user() or {}
            return {"ok": True,
                    "message": f"Signed in as {user.get('email') or email}"}
        except Exception as ex:
            status = getattr(ex, "status", 0)
            if status in (400, 401):
                return {"ok": False, "error": "Email or password is incorrect."}
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def supabase_verify_code(self, email, code) -> dict:
        """Exchange the emailed code for a session.

        Accepts a pasted magic-LINK url too: Supabase's default template
        sends `{{ .ConfirmationURL }}`, which resolves to localhost and
        breaks, so people paste the link instead of a code. Rather than
        make that an error, detect it and verify the token out of the URL.
        """
        email = (email or "").strip()
        code = (code or "").strip()
        if not code:
            return {"ok": False, "error": "Enter the code, paste the email link, or paste the final browser address."}
        try:
            import supabase_client
            if "://" in code or "token" in code.lower():
                supabase_client.verify_magic_link(code, email=email)
            else:
                supabase_client.verify_login_code(email, code)
            _invalidate("supabase sign-in")
            try:
                import web_health
                web_health.invalidate_grant_cache()
            except Exception:
                pass
            u = supabase_client.current_user() or {}
            return {"ok": True,
                    "message": f"Signed in as {u.get('email') or email}"}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def supabase_sign_out(self) -> dict:
        """Drop the local session and fall back to SQLite.

        Leaving the backend pointed at Supabase with no session would make
        every job lookup fail rather than quietly work offline.
        """
        try:
            import supabase_client
            import ems_db
            supabase_client.sign_out()
            try:
                import web_health
                web_health.invalidate_grant_cache()
            except Exception:
                pass
            if ems_db.backend_name() == "supabase":
                self.set_db_backend("sqlite")
            return {"ok": True, "message": "Signed out — using the local "
                                           "database."}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def set_db_backend(self, name) -> dict:
        """Switch the job index between the local file and the cloud."""
        name = (name or "sqlite").strip()
        if name not in ("sqlite", "supabase"):
            return {"ok": False, "error": f"unknown backend {name!r}"}
        try:
            import supabase_client
            if name == "supabase":
                h = supabase_client.health()
                if not h["configured"]:
                    return {"ok": False, "error": "Set the Supabase URL and "
                                                  "anon key first."}
                if not h["signed_in"]:
                    return {"ok": False, "error": "Sign in to Supabase first."}
                if not h["reachable"]:
                    return {"ok": False,
                            "error": f"Can't reach Supabase: {h['error']}"}
            import ems_db
            # Base, not the department overlay: the backend is a property
            # of the install, not of the franchise being viewed.
            cfg = dict(config.load_base() or {})
            # The key is `ems_db_backend` — ems_db._resolve reads that name.
            # Writing `db_backend` saved a key nothing reads, so the switch
            # survived only until the next invalidate_backend() re-derived
            # the backend from config and silently fell back to sqlite.
            config.save({**cfg, "ems_db_backend": name})
            ems_db.use_backend(name)
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

        # Dropping the scoped caches is a best-effort side effect, and it
        # runs AFTER the switch has already been persisted. Letting it throw
        # inside the block above reported failure for a switch that had in
        # fact happened — the worst of both, since the user retries or
        # assumes nothing changed while the backend really did move.
        try:
            _invalidate(f"db backend -> {name}")
        except Exception as ex:
            try:
                import ems_log
                ems_log.warn("settings", f"cache invalidate failed: {ex}")
            except Exception:
                pass
        return {"ok": True, "backend": ems_db.backend_name(),
                "message": ("Using the shared cloud database."
                            if name == "supabase"
                            else "Using the local database.")}

    def first_run_status(self) -> dict:
        """Return a checklist for the first-run wizard: which critical
        fields are configured and which still need attention.
        Surfaced when the user opens Settings for the first time."""
        cfg = {}
        try: cfg = config.load() or {}
        except Exception: cfg = {}
        steps = []
        # 1. Job folders root
        af = cfg.get("audit_base") or ""
        steps.append({
            "key":   "audit_base",
            "label": "📁 Job folders root configured",
            "done":  bool(af) and os.path.isdir(af),
            "current": af,
        })
        # 2. Run-doc folder
        rd = cfg.get("runs_dir") or ""
        steps.append({
            "key":   "runs_dir",
            "label": "📄 Run-doc folder configured",
            "done":  bool(rd) and os.path.isdir(rd),
            "current": rd,
        })
        # 3. Photos root
        ph = cfg.get("photos_root") or ""
        steps.append({
            "key":   "photos_root",
            "label": "📷 SharePoint photos root configured",
            "done":  bool(ph) and os.path.isdir(ph),
            "current": ph,
        })
        # 4. Trello token
        tok = cfg.get("trello_token") or ""
        steps.append({
            "key":   "trello_token",
            "label": "🔑 Trello token saved",
            "done":  bool(tok),
            "current": "(set)" if tok else "",
        })
        # 5. Snapshot template
        st = cfg.get("snapshot_template") or ""
        steps.append({
            "key":   "snapshot_template",
            "label": "📸 Snapshot template PDF set",
            "done":  bool(st) and os.path.isfile(st),
            "current": st,
        })
        done_count = sum(1 for s in steps if s["done"])
        return {
            "steps":  steps,
            "done":   done_count,
            "total":  len(steps),
            "all_done": done_count == len(steps),
        }

    def employee_setup_status(self) -> dict:
        """Plain-language first-day checklist for a regular employee."""
        cfg = config.load() or {}
        access_error = ""
        try:
            import supabase_client as sb
            user = sb.current_user() or {}
            signed_in = bool(user.get("id"))
        except Exception as ex:
            user, signed_in, access = {}, False, {}
            access_error = f"Sign-in status unavailable: {ex}"
        else:
            try:
                access = sb.rpc("my_app_access") if signed_in else {}
            except Exception as ex:
                # A temporary permission/network failure must not turn a
                # perfectly valid local session into "Not signed in". Keep
                # identity and franchise access as separate setup checks.
                access = {}
                access_error = f"Could not check franchise access: {ex}"
        departments = list((access or {}).get("departments") or [])
        active = (config.active_department() or "").strip()
        trello_set = bool((cfg.get("trello_api_key") or "").strip()
                          and (cfg.get("trello_token") or "").strip())
        audit_base = (cfg.get("audit_base") or "").strip()
        runs_dir = (cfg.get("runs_dir") or "").strip()
        folders_ok = bool(audit_base and os.path.isdir(audit_base)
                          and runs_dir and os.path.isdir(runs_dir))
        steps = [
            {"key": "signin", "title": "Sign in",
             "help": "Use your SERVPRO work email and the password Nathan gave you.",
             "done": signed_in,
             "detail": user.get("email") or "Not signed in"},
            {"key": "franchise", "title": "Get your franchise",
             "help": "Nathan assigns this. You do not need to enter a code.",
             "done": bool(departments),
             "detail": (", ".join(departments) if departments
                        else (access_error or
                              "Ask Nathan to assign your franchise"))},
            {"key": "trello", "title": "Connect Trello",
             "help": "Open Trello, click Allow, then come back here.",
             "done": trello_set,
             "detail": "Connected" if trello_set else "Not connected"},
            {"key": "folders", "title": "Check the job folders",
             "help": "Your computer must be able to open the shared job and run-doc folders.",
             "done": folders_ok,
             "detail": (f"{active or 'Assigned franchise'} folders are available"
                        if folders_ok else "Shared folders are not available on this PC")},
        ]
        return {"ok": True, "steps": steps,
                "done": sum(1 for step in steps if step["done"]),
                "total": len(steps),
                "all_done": all(step["done"] for step in steps),
                "active_franchise": active,
                "is_admin": bool((access or {}).get("is_admin"))}

    def my_trello_token_page(self) -> dict:
        """The current Trello authorization URL using Linguar's API key."""
        try:
            import trello_auth
            result = trello_auth.manual_url()
            if not result.get("ok"):
                return result
            return {"ok": True, "url": result["url"]}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def portable_folder_migration(self, apply=False):
        """Admin-only preview/apply for old Nathan-specific cloud paths."""
        if not _is_admin():
            return {"ok": False, "error": "Administrator access is required."}
        try:
            import ems_db_supabase
            return ems_db_supabase.migrate_folder_links_portable(
                apply=bool(apply))
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def save_my_trello_token(self, token: str) -> dict:
        """Save only this PC/user's token; never expose shared admin setup."""
        try:
            import trello_auth
            result = trello_auth.save_token(token)
            if not result.get("ok"):
                return result
            import trello_client
            me = trello_client._call("/members/me") or {}
            return {"ok": True, "name": me.get("fullName") or me.get("username") or "Trello user"}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def trello_auth_status(self):
        """Quick connection check — does the saved token actually
        return a valid /me payload? Surfaces the username + email so
        the user can confirm they pasted the right token."""
        try:
            import trello_client as tc
            me = tc._call("/members/me") or {}
            return {"ok": True,
                    "username": me.get("username") or "",
                    "full_name": me.get("fullName") or "",
                    "email": me.get("email") or ""}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}


def main(argv=None):
    api = Api()
    win = webview.create_window(
        title="Settings — Linguar Hub (web)",
        url=INDEX_HTML, js_api=api,
        width=820, height=820, min_size=(560, 500))
    api.attach(win)
    webview.start(debug=False)


if __name__ == "__main__":
    main()
