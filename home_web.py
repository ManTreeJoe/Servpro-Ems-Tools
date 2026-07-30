"""EMS Tools — unified web shell.

Single Pywebview window with a left sidebar of tools and a right
pane that swaps content as the user navigates. Each tool's existing
HTML/CSS/JS loads in an iframe so we don't rewrite any of the per-
tool work — we just point the iframe at `<tool>_web_assets/index.html`.

Cross-frame API access: pywebview only injects `pywebview.api` into
the parent window. The iframe shim (`web_shared/iframe_shim.js`)
loads inside each tool's HTML, creates a `pywebview` Proxy in the
iframe that forwards every method call to the parent's HomeApi
using a tool-name prefix. So `pywebview.api.reaudit_one(c)` inside
the audit iframe becomes `homeApi.audit_reaudit_one(c)` under the
hood — no per-tool JS changes needed.

This file replaces the Tk launcher as the default entry point.
"""
from __future__ import annotations
import datetime as _dt
import os, sys
from pathlib import Path as _Path
import webview

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path: sys.path.insert(0, _HERE)


ASSETS_DIR = os.path.join(_HERE, "home_web_assets")
INDEX_HTML = os.path.join(ASSETS_DIR, "index.html")
# Tiny root-level shim that redirects to the real home page. The
# whole point: pywebview's http_server serves files relative to the
# URL passed in. By rooting the URL at scripts/, the server treats
# every `<tool>_web_assets/` directory as a sibling reachable without
# `..` traversal, so iframes loading `../audit_web_assets/index.html`
# resolve cleanly under http://127.0.0.1:port/.
ROOT_INDEX_HTML = os.path.join(_HERE, "_ems_root_index.html")


def _ensure_root_index():
    """Write the root-level redirect once at startup. Idempotent."""
    body = (
        '<!DOCTYPE html><html><head>'
        '<meta http-equiv="refresh" '
        'content="0; url=home_web_assets/index.html">'
        '<title>EMS Tools</title>'
        '</head><body></body></html>\n')
    try:
        with open(ROOT_INDEX_HTML, "w", encoding="utf-8") as fh:
            fh.write(body)
    except OSError:
        pass


# Sidebar catalog — groups + per-tool metadata. Keep mapping from
# `key` to module name so the iframe-shim can derive the namespace
# from the tool's asset folder name automatically.
NAV_GROUPS = [
    ("Daily routine", [
        ("audit",       "🔎", "Audit"),
        ("apa",         "📊", "APA Monitor"),
        ("photo_folders","📷", "Photo Folders"),
    ]),
    ("Lifecycle", [
        ("snapshot",    "📸", "Snapshot"),
        ("pipeline",    "🛤", "Pipeline"),
    ]),
    ("Monitoring", [
        ("notifications", "🔔", "Notifications"),
        ("hygiene",     "⚠", "Hygiene"),
        ("kpi",         "📈", "KPI"),
        ("disputes",    "⚖", "Disputes"),
        ("wc_audit",    "🗂", "WC Audit"),
    ]),
    ("Reference", [
        ("spreadsheet", "📒", "Spreadsheets"),
        ("job_notes",   "🗒", "Job Notes"),
        ("multi_unit",  "🏢", "Multi-Unit"),
        ("cheat_sheet", "📝", "Cheat Sheet"),
    ]),
    ("System", [
        ("settings",    "⚙", "Settings"),
    ]),
]

# Map sidebar key → asset folder (used to build iframe src). When the
# tool's folder doesn't follow the `<key>_web_assets` convention,
# override here.
ASSET_FOLDER = {
    # All current tools follow the convention. Place overrides here
    # if a future panel diverges.
}


def _asset_folder_for(key: str) -> str:
    """Return the iframe src for a sidebar key.

    With pywebview's `http_server=True` mode, everything under the
    project dir is served from a same-origin http://127.0.0.1:port/
    space. The home page lives at `/home_web_assets/index.html`, so
    `../<tool>_web_assets/index.html` resolves correctly inside the
    served context. (Plain `file://` URLs hit Edge WebView2's cross-
    origin restriction when an iframe at file://.../audit_web_assets/
    tries to access window.parent.pywebview at file://.../home_web_assets/.)
    """
    folder = ASSET_FOLDER.get(key, f"{key}_web_assets")
    return f"../{folder}/index.html"


# Sub-Api class names per tool key — used so HomeApi can instantiate
# them and auto-bind their methods with a tool-name prefix.
SUB_MODULES = {
    "audit":       "audit_web",
    "disputes":    "disputes_web",
    "job_notes":   "job_notes_web",
    "cheat_sheet": "cheat_sheet_web",
    "hygiene":     "hygiene_web",
    "snapshot":    "snapshot_web",
    "wc_audit":    "wc_audit_web",
    "multi_unit":  "multi_unit_web",
    "spreadsheet": "spreadsheet_web",
    "settings":    "settings_web",
    "apa":         "apa_web",
    "pipeline":    "pipeline_web",
    "kpi":         "kpi_web",
    "photo_folders": "photo_folders_web",
    "notifications": "notifications_web",
}


class HomeApi:
    """Aggregate Api — exposes every sub-tool's methods to the JS
    side under a tool-name prefix. The iframe shim auto-prefixes
    calls so each tool's JS stays unchanged.
    """

    def __init__(self):
        self._window = None
        self._subs = {}
        self._sidebar_active = None
        # Instantiate every sub-Api at startup so state caches
        # survive across iframe navigations (e.g. audit's last-run
        # results aren't wiped when the user clicks APA Monitor then
        # back to Audit).
        self._failed_subs = {}   # key → error string, for the sidebar badge
        for key, mod_name in SUB_MODULES.items():
            try:
                mod = __import__(mod_name)
                api = mod.Api()
                self._subs[key] = api
                self._bind_methods(key, api)
            except Exception as ex:
                # Skip tools that fail to import — sidebar still works, the
                # broken one is just unavailable. Record + LOG it (stderr is
                # invisible in a windowed build, so a broken panel used to
                # be a silent dead tab); nav() flags it so the user sees ⚠.
                self._failed_subs[key] = f"{type(ex).__name__}: {ex}"
                print(f"[home_web] failed to load {mod_name}: {ex}",
                      file=sys.stderr)
                try:
                    import ems_log
                    ems_log.error("home_web",
                                  f"panel '{key}' ({mod_name}) failed to load: {ex}",
                                  exc_info=True)
                except Exception:
                    pass

    def _bind_methods(self, key: str, api):
        """Bind every public method on `api` to self with a
        `<key>_<method>` name so JS can call them via the prefixed
        proxy in each iframe."""
        for attr in dir(api):
            if attr.startswith("_"):
                continue
            if attr in ("attach",):
                continue
            method = getattr(api, attr)
            if not callable(method):
                continue
            target = f"{key}_{attr}"
            # Don't clobber if a name conflicts with a HomeApi method
            if hasattr(type(self), target):
                continue
            setattr(self, target, method)

    def attach(self, w):
        """Pywebview window handle — also forward to every sub-Api
        so background-thread emits hit the right window."""
        self._window = w
        for sub in self._subs.values():
            try:
                sub.attach(w)
            except Exception:
                pass

    # ── First-run welcome ────────────────────────────────────────────
    def first_run(self):
        """Tell the shell whether to show the one-time welcome modal.

        `show` is True until the user dismisses the welcome (drops the
        `.configured` marker) on this machine. `trello_ready` lets the
        modal tailor its copy when creds are already in place."""
        try:
            import paths as _p, config as _c
            cfg = _c.load() or {}
            return {
                "show": bool(_p.is_first_run()),
                "trello_ready": bool((cfg.get("trello_api_key") or "").strip()
                                     and (cfg.get("trello_token") or "").strip()),
            }
        except Exception:
            return {"show": False, "trello_ready": True}

    def dismiss_first_run(self):
        """Drop the `.configured` marker so the welcome doesn't reappear."""
        try:
            import paths as _p
            _p.mark_configured()
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def focus_window(self):
        """Bring the app window to the foreground. Works around a WebView2
        quirk where clicking into a text field shows the caret but leaves the
        top-level OS window un-activated (no accent border), so keystrokes
        feel 'dead' until you click the title bar. Idempotent — no-op when
        already foreground.

        The click that triggers this lands on the WebView2 *child process*,
        so our process never "received the last input" and Windows blocks a
        naive SetForegroundWindow. Two things unblock it: (1) attach the
        current foreground thread's input queue to OUR WINDOW's GUI thread
        (not the pywebview worker thread this method runs on), and (2) zero
        the foreground-lock timeout for the duration of the call."""
        if sys.platform != "win32":
            return {"ok": True}
        try:
            import ctypes
            from ctypes import wintypes
            u = ctypes.windll.user32
            hwnd = u.FindWindowW(None, "EMS Tools")
            if not hwnd:
                return {"ok": False, "error": "window not found"}
            fg = u.GetForegroundWindow()
            if fg == hwnd:
                return {"ok": True}  # already active — nothing to do

            SW_RESTORE = 9
            if u.IsIconic(hwnd):
                u.ShowWindow(hwnd, SW_RESTORE)

            # Drop the foreground-lock timeout so the activation is honored.
            SPI_GET = 0x2000  # SPI_GETFOREGROUNDLOCKTIMEOUT
            SPI_SET = 0x2001  # SPI_SETFOREGROUNDLOCKTIMEOUT
            SPIF_SENDCHANGE = 0x2
            saved = wintypes.DWORD(0)
            u.SystemParametersInfoW(SPI_GET, 0, ctypes.byref(saved), 0)
            u.SystemParametersInfoW(SPI_SET, 0, ctypes.c_void_p(0),
                                    SPIF_SENDCHANGE)

            fg_thread = u.GetWindowThreadProcessId(fg, None) if fg else 0
            tgt_thread = u.GetWindowThreadProcessId(hwnd, None)
            attached = False
            if fg_thread and tgt_thread and fg_thread != tgt_thread:
                attached = bool(u.AttachThreadInput(fg_thread, tgt_thread, True))

            u.BringWindowToTop(hwnd)
            u.SetForegroundWindow(hwnd)
            u.SetActiveWindow(hwnd)

            if attached:
                u.AttachThreadInput(fg_thread, tgt_thread, False)
            # Restore the user's original lock timeout.
            u.SystemParametersInfoW(SPI_SET, 0,
                                    ctypes.c_void_p(saved.value),
                                    SPIF_SENDCHANGE)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── Top-level methods used by the shell itself ───────────────────
    def header(self):
        now = _dt.datetime.now()
        h = now.hour
        if h < 12:    greet = "Good morning"
        elif h < 17:  greet = "Good afternoon"
        else:         greet = "Good evening"
        return {
            "greeting": greet,
            "date":     now.strftime("%A, %B %d"),
            "time":     now.strftime("%I:%M %p").lstrip("0"),
        }

    def nav(self):
        """Sidebar groups + tools — filtered by per-panel visibility.

        Each panel can be hidden via persistence key `panel_hidden_<key>`.
        Defaults below favor a clean sidebar — tools that mostly serve
        the backend (e.g. Job Notes, used by audit/snapshot hover
        popovers but rarely opened directly) default to hidden.
        Settings exposes a toggle to bring them back."""
        out = []
        for (label, items) in NAV_GROUPS:
            visible = []
            for (k, ic, n) in items:
                if not self._is_panel_visible(k):
                    continue
                visible.append({
                    "key":   k,
                    "icon":  ic,
                    "name":  n,
                    "src":   _asset_folder_for(k),
                    # True when the tool's Api failed to import — the panel
                    # is a dead tab; the sidebar shows ⚠ instead of silence.
                    "error": k in getattr(self, "_failed_subs", {}),
                })
            if visible:
                out.append({"label": label, "items": visible})
        return out

    # Panels hidden by default — Job Notes is data-only now (timeline
    # + expected files surface via the audit/snapshot hover popover).
    _PANELS_HIDDEN_BY_DEFAULT = {"job_notes"}

    def _is_panel_visible(self, key: str) -> bool:
        if key == "settings":
            return True   # Settings is pinned in the sidebar — never hideable.
        try:
            import persistence as _per
            val = _per.get(f"panel_hidden_{key}")
            if val is None:
                # No explicit setting — fall back to the default
                return key not in self._PANELS_HIDDEN_BY_DEFAULT
            return not bool(val)
        except Exception:
            return key not in self._PANELS_HIDDEN_BY_DEFAULT

    def list_panel_visibility(self) -> dict:
        """Return every panel's current visibility + its default. Used
        by the Settings panel to render the toggle list."""
        rows = []
        for (label, items) in NAV_GROUPS:
            for (k, ic, n) in items:
                if k == "settings":
                    continue   # pinned — no visibility toggle
                rows.append({
                    "key":     k,
                    "icon":    ic,
                    "name":    n,
                    "group":   label,
                    "visible": self._is_panel_visible(k),
                    "default": (k not in self._PANELS_HIDDEN_BY_DEFAULT),
                })
        return {"ok": True, "panels": rows}

    def set_panel_visibility(self, key: str, visible: bool) -> dict:
        if not key:
            return {"ok": False, "error": "key required"}
        if key == "settings":
            return {"ok": False, "error": "Settings is pinned and can't be hidden"}
        try:
            import persistence as _per
            _per.set_value(f"panel_hidden_{key}", not bool(visible))
            return {"ok": True, "key": key, "visible": bool(visible)}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def check_update(self) -> dict:
        """Best-effort update check against the repo's version.txt."""
        try:
            import update_check
            return update_check.check()
        except Exception as ex:
            return {"ok": False, "error": str(ex), "update_available": False}

    def open_url(self, url: str) -> bool:
        """Open a URL (the update download link) in the browser."""
        try:
            import dept_browser
            return dept_browser.open_url(url)
        except Exception:
            return False

    def install_update(self, url: str = "") -> dict:
        """Download the installer and launch it. The setup closes this app,
        upgrades in place, and relaunches it. Falls back to opening the release
        page in the browser if there's no direct installer link or download
        fails."""
        info = {}
        try:
            import update_check
            info = update_check.check() or {}
        except Exception:
            info = {}
        dl = (url or info.get("installer") or "").strip()
        page = info.get("url") or ""
        if not dl:
            if page:
                self.open_url(page)
                return {"ok": True, "launched": False, "opened_page": True}
            return {"ok": False, "error": "No installer link configured"}
        try:
            import os
            import shutil
            import tempfile
            import urllib.request
            name = dl.rsplit("/", 1)[-1] or "EMS-Tools-Setup.exe"
            dest = os.path.join(tempfile.gettempdir(), name)
            req = urllib.request.Request(dl, headers={"User-Agent": "EMS-Tools"})
            with urllib.request.urlopen(req, timeout=180) as r, open(dest, "wb") as f:
                shutil.copyfileobj(r, f)
            os.startfile(dest)  # noqa: launches setup detached; it closes+relaunches us
            return {"ok": True, "launched": True, "path": dest}
        except Exception as ex:
            if page:
                self.open_url(page)
            return {"ok": False, "error": str(ex), "opened_page": bool(page)}

    def counts(self):
        """Live counts per sidebar item — best-effort, cheap reads."""
        out = {}
        try:
            import run_audit_gui as _rag
            from state_hub import hub as _sh
            doc = _rag._find_run_doc_for_date(_dt.date.today())
            if doc:
                jobs, _ = _sh.parse_run_doc(doc)
                out["audit"] = len(jobs)
            else:
                out["audit"] = None
        except Exception:
            out["audit"] = None
        try:
            import apa_logic as _apa
            path = _apa.doc_path_for_today(_dt.date.today())
            if path and os.path.isfile(path):
                sections = _apa.parse_existing_doc(path)
                out["apa"] = sum(len(v or []) for v in sections.values())
            else:
                out["apa"] = 0
        except Exception:
            out["apa"] = None
        try:
            import persistence as _per
            cache = _per.get_hygiene_scan_cache(max_age_minutes=24*60)
            out["snapshot"] = len(cache[0].get("closeout") or []) if cache else 0
            if cache:
                payload, _age = cache
                out["hygiene"] = (
                    len(payload.get("hygiene") or [])
                    + len(payload.get("closeout") or [])
                    + len(payload.get("xa_apology") or []))
            else:
                out["hygiene"] = None
        except Exception:
            out["snapshot"] = None
            out["hygiene"] = None
        try:
            import ems_db
            counts = ems_db.lifecycle_counts_by_stage(paid_window_days=30) or {}
            out["pipeline"] = sum(counts.values())
        except Exception:
            out["pipeline"] = None
        try:
            import dispute_tracker as _dt2
            rows = _dt2.read_rows() or []
            out["disputes"] = len(rows)
        except Exception:
            out["disputes"] = None
        try:
            import job_notes_logic as _jn
            out["job_notes"] = len(_jn.list_saved_notes() or [])
        except Exception:
            out["job_notes"] = None
        return out

    # ── ⭐ Bookmarked clients (cross-panel) ──────────────────────────
    # Single shared list stored under persistence key
    # `starred_clients` — every panel that has a "⭐ Starred" filter
    # reads from here. Names stored case-insensitively (lower) so
    # "Smith, John" matches "smith, john" matches "SMITH, JOHN".
    def get_starred_clients(self) -> list:
        try:
            import persistence as _per
            raw = _per.get("starred_clients") or []
            if isinstance(raw, list):
                return [str(x or "").strip().lower() for x in raw if x]
        except Exception:
            pass
        return []

    def toggle_starred_client(self, client: str) -> dict:
        if not client or not str(client).strip():
            return {"ok": False, "error": "client required"}
        key = str(client).strip().lower()
        try:
            import persistence as _per
            current = set(self.get_starred_clients())
            if key in current:
                current.discard(key)
                starred = False
            else:
                current.add(key)
                starred = True
            _per.set_value("starred_clients", sorted(current))
            return {"ok": True, "client": key, "starred": starred,
                    "count": len(current)}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def is_client_starred(self, client: str) -> bool:
        if not client:
            return False
        try:
            return str(client).strip().lower() in set(self.get_starred_clients())
        except Exception:
            return False

    # ── Shared cross-tool "Open in…" resolvers ───────────────────────
    # Called from web_shared/open_in.js so a right-click on ANY panel's
    # row can open the job's Trello card / OD folder / XactAnalysis link
    # without each panel re-implementing resolution. Delegate to the
    # sub-Apis whose resolvers are already proven.
    def open_trello_for_client(self, client: str) -> dict:
        sub = self._subs.get("snapshot")
        if sub and hasattr(sub, "open_trello_for_tracked"):
            try:
                return sub.open_trello_for_tracked(client) or {"ok": False}
            except Exception as ex:
                return {"ok": False, "error": str(ex)}
        return {"ok": False, "error": "resolver unavailable"}

    def open_folder_for_client(self, client: str) -> dict:
        sub = self._subs.get("audit")
        if sub and hasattr(sub, "open_od_for_client"):
            try:
                return sub.open_od_for_client(client) or {"ok": False}
            except Exception as ex:
                return {"ok": False, "error": str(ex)}
        return {"ok": False, "error": "resolver unavailable"}

    def open_xa_for_client(self, client: str) -> dict:
        sub = self._subs.get("audit")
        if sub and hasattr(sub, "open_xa_link"):
            try:
                ok = bool(sub.open_xa_link(client))
                return {"ok": ok} if ok else {
                    "ok": False, "error": "no XA link on the pinned card"}
            except Exception as ex:
                return {"ok": False, "error": str(ex)}
        return {"ok": False, "error": "resolver unavailable"}

    def open_companycam_for_client(self, client: str) -> dict:
        """Open the CompanyCam web app searched to this client's name so
        the user can eyeball the job's photos. NO API token needed — this
        is just a browser deep-link (like the Trello card link). The full
        photo pull is gated on an admin-issued API token; see the
        SP→CompanyCam plan."""
        name = (client or "").strip()
        # Drop a trailing " - <Carrier>" so the search is the bare name.
        if " - " in name:
            name = name.split(" - ")[0].strip()
        try:
            import urllib.parse
            import webbrowser
            url = "https://app.companycam.com/projects"
            if name:
                url += "?query=" + urllib.parse.quote(name)
            webbrowser.open(url)
            return {"ok": True, "url": url}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def trello_card_hover(self, card_id: str) -> dict:
        """Cross-tool Trello card lookup — used by the shared
        web_shared/trello_hover.js helper. Delegates to the audit
        Api's `trello_card_hover` which carries the 60-second cache
        so any panel that hovers a pinned card gets the same payload
        without re-fetching."""
        if not card_id:
            return {"ok": False}
        try:
            audit_api = self._subs.get("audit")
            if audit_api and hasattr(audit_api, "trello_card_hover"):
                return audit_api.trello_card_hover(card_id) or {"ok": False}
        except Exception:
            pass
        # Fallback: inline lookup so the helper still works when the
        # audit panel hasn't been touched yet this session.
        try:
            import trello_client as tc
            card = tc.get_card(card_id) or {}
            lane = ""
            try:
                if hasattr(tc, "get_lane_name"):
                    lane = tc.get_lane_name(card.get("idBoard") or "",
                                              card.get("idList") or "") or ""
            except Exception:
                lane = ""
            last_act = card.get("dateLastActivity") or ""
            return {
                "ok":   True,
                "name": card.get("name") or "",
                "lane": lane,
                "url":  card.get("shortUrl") or f"https://trello.com/c/{card_id}",
                "labels": [l.get("name") or "" for l in (card.get("labels") or []) if l],
                "last_activity": last_act[:10] if isinstance(last_act, str) else "",
            }
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def open_tk_launcher(self):
        """Spawn the legacy Tk launcher (fallback) detached."""
        import subprocess
        try:
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--tk"]
            else:
                cmd = [sys.executable, os.path.join(_HERE, "launcher.py"), "--tk"]
            creationflags = 0x00000008 if sys.platform == "win32" else 0
            subprocess.Popen(cmd, creationflags=creationflags)
            return True
        except Exception:
            return False

    # ── Department (multi-account) switcher ──────────────────────────
    def department_state(self):
        """State for the launcher's department pill: whether multi-dept
        is on, which department is active, and the full list. Returns
        `enabled: False` when the feature is off (pill stays hidden)."""
        try:
            import config
            if not config.is_multi_dept():
                return {"ok": True, "enabled": False}
            return {
                "ok": True,
                "enabled": True,
                "active": config.active_department(),
                "departments": config.list_departments(),
            }
        except Exception as ex:
            return {"ok": False, "enabled": False, "error": str(ex)}

    def switch_department(self, key: str):
        """Switch the active department IN-PROCESS. All scoped values are
        now read lazily (config.load() is mtime-cached and re-reads after
        the write below; the logic modules resolve their roots per-call),
        so we persist the choice, drop the few workspace-scoped in-memory
        caches, and tell the web layer to reload — no relaunch needed.
        Returns {reload: True} so the JS shell does location.reload()."""
        try:
            import config
            key = (key or "").strip()
            cur = config.active_department()
            if not key or key == cur:
                return {"ok": True, "unchanged": True}
            if not config.set_active_department(key):
                return {"ok": False, "error": f"unknown department '{key}'"}
            _invalidate_scoped_caches()
            return {"ok": True, "switched_to": key, "reload": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}


def _invalidate_scoped_caches():
    """Drop the process-lifetime caches that are scoped to the active
    department, so an in-process switch doesn't serve the previous
    department's data. config.load() and the logic-module roots are
    already lazy (mtime-cached); this clears the two workspace-scoped
    caches those don't cover. Best-effort — a missing module never
    blocks the switch."""
    try:
        import trello_client
        trello_client.invalidate_caches()
    except Exception:
        pass
    try:
        import weekly_checkins            # own Estimating-board id cache
        weekly_checkins.invalidate_caches()
    except Exception:
        pass
    try:
        from state_hub import hub as _hub
        _hub._cache.clear()          # parse_run_doc etc. — re-fetch fresh
    except Exception:
        pass


def main(argv=None):
    # Quick Import — the stripped-down tool for general office users opens
    # from the SAME exe via a `--quickimport` shortcut, so simple users get a
    # dedicated launcher and never see the full suite.
    import sys as _sys
    _argv = argv if argv is not None else _sys.argv[1:]
    if "--quickimport" in _argv:
        import quickimport_web
        quickimport_web.main()
        return
    _ensure_root_index()
    import paths as _paths
    api = HomeApi()
    win = webview.create_window(
        title=("EMS Tools — TRIAL" if getattr(_paths, "IS_TRIAL", False)
               else "EMS Tools"),
        url=ROOT_INDEX_HTML,    # served as http://127.0.0.1:port/_ems_root_index.html
        js_api=api,
        width=1480, height=900,
        min_size=(960, 600),
    )
    api.attach(win)
    # http_server=True serves the parent dir of the URL — by rooting
    # at scripts/, every <tool>_web_assets/ folder is reachable as a
    # sibling. Same-origin everywhere → iframe shim's
    # window.parent.pywebview access works.
    webview.start(debug=False, http_server=True)


if __name__ == "__main__":
    main()
