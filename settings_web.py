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
    ("workcenter_url",      "Workcenter URL",             "url"),
    ("show_sort_files",     "Show Sort Files in toolbar", "bool"),
    ("show_new_job",        "Show New EMS Job in toolbar","bool"),
    ("trello_api_key",      "Trello API key",             "secret"),
    ("trello_token",        "Trello token (per-user)",    "secret"),
    ("companycam_api_token", "CompanyCam access token",   "secret"),
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
]


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
    ("franchise_name",        "Franchise legal name",     "text",    "Identity"),
    ("office_phone",          "Office phone",             "text",    "Identity"),
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
                  "choices": (f[3] if len(f) > 3 else [])}
                for f in FIELDS]

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

    def save(self, values):
        if not isinstance(values, dict):
            return {"ok": False, "error": "values must be a dict"}
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
            depts = list((base.get("departments") or {}).keys()) or ["IE", "OC"]
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

    # ── Multiple-department (OC / IE) config ─────────────────────────
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
                    "is_base": (k == "IE"),
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
        """Toggle multiple-department mode. Enabling scaffolds the IE + OC
        profiles (IE inherits the current settings; OC starts blank)."""
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
                    "admin_url": "https://trello.com/power-ups/admin"}
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
            return {"ok": False, "error": "Enter the code from the email."}
        try:
            import supabase_client
            if "://" in code or "token" in code.lower():
                supabase_client.verify_magic_link(code, email=email)
            else:
                supabase_client.verify_login_code(email, code)
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
        title="Settings — EMS Tools (web)",
        url=INDEX_HTML, js_api=api,
        width=820, height=820, min_size=(560, 500))
    api.attach(win)
    webview.start(debug=False)


if __name__ == "__main__":
    main()
