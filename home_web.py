"""Linguar Hub — unified web shell.

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
import os, sys, time, threading
from pathlib import Path as _Path
import webview

import persistence

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

# Keep the Windows mutex handle alive for the lifetime of the process.
_INSTANCE_MUTEX = None


def _set_windows_app_identity(is_trial=False):
    """Give each channel its own taskbar group and icon-cache identity."""
    if os.name != "nt":
        return
    try:
        import ctypes
        # Refresh the Windows icon cache. The first Linguar AUMIDs were
        # briefly shipped while the executable still carried wrench.ico;
        # Windows keeps that association even after the EXE icon changes.
        app_id = ("Servpro.LinguarHub.Trial.2026.2"
                  if is_trial else "Servpro.LinguarHub.Main.2026.2")
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


def _instance_mutex_name():
    """Keep Main and Trial single-instance within their own channels.

    Both channels intentionally share settings and job data, but they are
    separate installed applications and must be able to run side by side.
    """
    try:
        import paths as _paths
        channel = "Trial" if getattr(_paths, "IS_TRIAL", False) else "Main"
    except Exception:
        channel = "Main"
    return f"Local\\LinguarHub.{channel}.SingleInstance"


def _claim_single_instance():
    """Return False when another copy of this app channel is running.

    Main and Trial use different mutex names so they can run side by side.
    Source and installed builds in the same channel still share a mutex.
    Fail open if Windows cannot create the mutex so an OS API failure never
    turns into an unexplained launch failure.
    """
    global _INSTANCE_MUTEX
    if os.name != "nt":
        return True
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_mutex = kernel32.CreateMutexW
        create_mutex.argtypes = (wintypes.LPVOID, wintypes.BOOL,
                                 wintypes.LPCWSTR)
        create_mutex.restype = wintypes.HANDLE
        handle = create_mutex(None, False, _instance_mutex_name())
        if not handle:
            return True
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            return False
        _INSTANCE_MUTEX = handle
        return True
    except Exception:
        return True


def _show_already_running():
    """Explain a blocked second launch without requiring pywebview startup."""
    try:
        import ctypes
        try:
            import paths as _paths
            app_name = "Linguar Hub Trial" if getattr(
                _paths, "IS_TRIAL", False) else "Linguar Hub"
        except Exception:
            app_name = "Linguar Hub"
        ctypes.windll.user32.MessageBoxW(
            0,
            f"{app_name} is already running. Close the open window before "
            "starting another copy.",
            app_name,
            0x30,
        )
    except Exception:
        pass


def _ensure_root_index():
    """Write the root-level redirect once at startup. Idempotent."""
    body = (
        '<!DOCTYPE html><html><head>'
        '<meta http-equiv="refresh" '
        'content="0; url=home_web_assets/index.html">'
        '<title>Linguar Hub</title>'
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
    ("Work", [
        ("pipeline",    "▦", "Jobs"),
        ("clients",     "👥", "Clients"),
        ("snapshot",    "📸", "Snapshot"),
        ("run_doc_editor", "📋", "Daily Run Editor"),
        ("photo_folders","📷", "Photo Folders"),
    ]),
    ("Reports", [
        ("apa",         "📊", "APA"),
        ("exceptions",  "⚠", "Exceptions"),
        ("notifications", "🔔", "Notifications"),
        ("hygiene",     "⚠", "Hygiene"),
        ("disputes",    "⚖", "Billing Disputes"),
        ("wc_audit",    "🗂", "WC Audit"),
    ]),
    ("Reference", [
        ("spreadsheet", "📒", "Spreadsheets"),
        ("job_notes",   "🗒", "Job Notes"),
        ("multi_unit",  "🏢", "Multi-Unit"),
        ("cheat_sheet", "📝", "Cheat Sheet"),
        ("resources",   "📚", "Forms & Resources"),
    ]),
    ("System", [
        ("automations", "⚡", "Automations"),
        ("health",      "●", "System Health"),
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
    # Daily Run is launched as a Jobs subview, but its mature audit workspace
    # remains addressable for browser deep links and the embedded workspace.
    if key == "daily_run":
        return "../audit_web_assets/index.html?surface=daily"
    folder = ASSET_FOLDER.get(key, f"{key}_web_assets")
    return f"../{folder}/index.html"


# Sub-Api class names per tool key — used so HomeApi can instantiate
# them and auto-bind their methods with a tool-name prefix.
SUB_MODULES = {
    "health":      "health_web",
    "exceptions":  "exceptions_web",
    "run_doc_editor": "run_doc_editor_web",
    "audit":       "audit_web",
    "clients":     "clients_web",
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
    "resources":   "resources_web",
    "automations": "automations_web",
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
        self._hotkey = None
        self._counts_cache = None
        self._counts_lock = threading.Lock()
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

    # ── Health, for every panel ──────────────────────────────────────
    #
    # Unprefixed on HomeApi on purpose: the iframe shim falls back to the
    # bare name, so one shared banner script reaches these from every
    # panel without each panel growing its own copy.

    def health_state(self, force=False):
        try:
            import web_health
            return web_health.state(force=bool(force))
        except Exception as ex:
            # The health check must never be the thing that breaks.
            return {"ok": True, "problems": [],
                    "error": f"{type(ex).__name__}: {ex}"}

    def appearance_preferences(self):
        """Safe, unprefixed preference used by the shell and every iframe."""
        from web_appearance import preferences
        return preferences()

    def log_js_error(self, source="", message="", detail=""):
        try:
            import web_health
            return web_health.log_js_error(source, message, detail)
        except Exception:
            return {"ok": False}

    def track_events(self, events: list) -> dict:
        """Shared privacy-safe usage sink for the shell and every panel.

        The iframe bridge falls back to unprefixed HomeApi methods, so panels
        do not each need their own copy of this plumbing.
        """
        try:
            import usage_tracker as _ut
            return _ut.record(events or [])
        except Exception as ex:
            return {"ok": False, "written": 0, "error": str(ex)}

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

    def preflight(self):
        """Run the setup checks and return them as data.

        The checks already existed as `trial_preflight.py`, which meant
        they only ran when somebody remembered to open a terminal on a
        new PC. Nobody does that, and the first sign of a machine that
        was never checked is two offices disagreeing about the job list.

        Read-only — it never switches the backend.
        """
        try:
            import trial_preflight
            rows = trial_preflight.run_checks()
        except Exception as ex:
            return {"ok": False, "checks": [],
                    "error": f"{type(ex).__name__}: {ex}"}
        fails = [r for r in rows if r["state"] == "fail"]
        warns = [r for r in rows if r["state"] == "warn"]
        return {"ok": not fails, "checks": rows,
                "fails": len(fails), "warns": len(warns),
                "total": len(rows)}

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
            # Resolve this process's own visible top-level window. Looking up
            # the caption "Linguar Hub" can focus the wrong copy when a live
            # and test build are open together, and misses TRIAL/test titles.
            hwnd_box = []
            this_pid = os.getpid()
            enum_proc_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                             wintypes.LPARAM)

            @enum_proc_t
            def _find_ours(candidate, _lparam):
                pid = wintypes.DWORD()
                u.GetWindowThreadProcessId(candidate, ctypes.byref(pid))
                if pid.value == this_pid and u.IsWindowVisible(candidate):
                    length = u.GetWindowTextLengthW(candidate)
                    if length:
                        hwnd_box.append(candidate)
                        return False
                return True

            u.EnumWindows(_find_ours, 0)
            hwnd = hwnd_box[0] if hwnd_box else 0
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

    def hotkey_status(self):
        if not self._hotkey:
            return {"supported": os.name == "nt", "enabled": False,
                    "registered": False, "error": "Hotkey service not started"}
        return self._hotkey.status()

    # ── Top-level methods used by the shell itself ───────────────────
    def header(self):
        import paths as _paths
        now = _dt.datetime.now()
        h = now.hour
        if h < 12:    greet = "Good morning"
        elif h < 17:  greet = "Good afternoon"
        else:         greet = "Good evening"
        return {
            "greeting": greet,
            "date":     now.strftime("%A, %B %d"),
            "time":     now.strftime("%I:%M %p").lstrip("0"),
            # Panel to reopen on launch. Ships INSIDE header() rather than
            # as its own call so the restore can run synchronously right
            # after the sidebar renders. A separate round trip would leave
            # a window where the user has already clicked something and the
            # late reply yanks them somewhere else.
            "last_panel": self.get_last_panel(),
            "work_environment": self.active_work_environment(),
            "is_trial": bool(getattr(_paths, "IS_TRIAL", False)),
        }

    def active_work_environment(self) -> str:
        """Return the user's active job division, separate from franchise."""
        try:
            from ems_db_common import normalize_division
            return normalize_division(
                persistence.get("home_work_environment", "EMS"))
        except Exception:
            return "EMS"

    def work_environment_state(self):
        """State for the EMS / Contents / Recon shell switcher."""
        try:
            from ems_db_common import DIVISIONS
            labels = {"EMS": "EMS", "CONTENTS": "Contents", "RECON": "Recon"}
            return {
                "ok": True,
                "active": self.active_work_environment(),
                "environments": [
                    {"key": key, "label": labels.get(key, key.title())}
                    for key in DIVISIONS
                ],
            }
        except Exception as ex:
            return {"ok": False, "active": "EMS", "error": str(ex)}

    def switch_work_environment(self, value: str):
        """Persist the active division without changing folders or franchise."""
        try:
            from ems_db_common import DIVISIONS, normalize_division
            requested = str(value or "").strip().upper()
            if requested not in DIVISIONS:
                return {"ok": False,
                        "error": f"unknown work environment '{value}'"}
            active = normalize_division(requested)
            if active == self.active_work_environment():
                return {"ok": True, "unchanged": True, "active": active}
            persistence.set_value("home_work_environment", active)
            return {"ok": True, "active": active, "reload": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def get_last_panel(self) -> str:
        """Key of the panel that was open when the app last closed, or ""
        for none.

        Returns "" when that panel has since been hidden or failed to
        import, so a stale value can't strand the user on a dead tab.
        """
        try:
            key = (persistence.get("home_last_panel") or "").strip()
        except Exception:
            return ""
        # Daily Run now lives inside Jobs. Migrate either historic panel key
        # to Jobs so an upgrade cannot restore a sidebar destination that no
        # longer exists; the Daily Run workspace remains available from Jobs.
        if key in {"audit", "daily_run"}:
            key = "pipeline"
        if not key:
            return ""
        if key in getattr(self, "_failed_subs", {}):
            return ""
        known = {k for _group, items in NAV_GROUPS for k, _icon, _name in items}
        if key not in known:
            return ""
        try:
            if not self._is_panel_visible(key):
                return ""
        except Exception:
            return ""
        return key

    def set_last_panel(self, key: str) -> dict:
        """Remember the open panel. Called on every navigation; failures
        are swallowed because losing this is a nuisance, never an error."""
        try:
            persistence.set_value("home_last_panel", (key or "").strip())
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── Per-panel UI state (which tab, which filter) ─────────────────
    # Deliberately LOCAL, in state.json, never the shared job index: where
    # you left the Audit tab is yours, not a team fact. When the job graph
    # moves to a shared backend this stays exactly where it is.
    #
    # Panels reach these through the iframe shim's fall-through to the
    # un-prefixed HomeApi, so no per-panel wiring is needed — a new panel
    # gets persistence by calling get_ui_state/set_ui_state with its key.

    @staticmethod
    def _ui_state_key(panel: str) -> str:
        """Storage key for a panel's UI state, scoped to the active
        department.

        Saved state is mostly ABOUT JOBS — the selected row, the search
        term, the filter, which tab. None of that survives a franchise
        change with its meaning intact, so a single shared key meant
        switching IE→OC restored IE's selection into OC's board and read
        as the panel being wrong. Scoping also gives each franchise its
        own place to come back to, which is the point: switch away, switch
        back, land where you left off.
        """
        panel = (panel or "").strip()
        try:
            import config
            dept = (config.active_department() or "").strip()
        except Exception:
            dept = ""
        return f"{dept}:{panel}" if dept else panel

    def get_ui_state(self, panel: str) -> dict:
        """Saved UI state for one panel ({} when nothing is stored)."""
        try:
            all_state = persistence.get("ui_state") or {}
            val = all_state.get(self._ui_state_key(panel))
            # Fall back to the pre-scoping key so nobody's remembered
            # position is thrown away by the upgrade. Read-only: the next
            # write lands under the scoped key and the legacy one is left
            # for whichever department claims it first.
            if not isinstance(val, dict):
                val = all_state.get((panel or "").strip())
            return val if isinstance(val, dict) else {}
        except Exception:
            return {}

    def set_ui_state(self, panel: str, patch: dict) -> dict:
        """Merge `patch` into one panel's saved UI state.

        Merge rather than replace so a panel can persist one field at a
        time without having to know (or clobber) the others.
        """
        panel = (panel or "").strip()
        if not panel or not isinstance(patch, dict):
            return {"ok": False, "error": "panel and patch required"}
        try:
            key = self._ui_state_key(panel)
            all_state = dict(persistence.get("ui_state") or {})
            cur = dict(all_state.get(key) or {})
            if not cur:
                # Seed from the legacy unscoped entry so the first write
                # after the upgrade doesn't drop the other remembered
                # fields this patch isn't touching.
                cur = dict(all_state.get(panel) or {})
            cur.update(patch)
            all_state[key] = cur
            persistence.set_value("ui_state", all_state)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

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

    # Panels hidden by default. Hidden, not removed: every one of these
    # still works and Settings → panel visibility turns any of them back
    # on. The sidebar is meant to be the handful of tools used daily, and
    # fifteen entries made the three that matter harder to reach.
    #
    #   photo_folders — superseded by CompanyCam; photos no longer land
    #                   in dated folders by hand.
    #   job_notes     — data-only; the timeline and expected files surface
    #                   in the audit/snapshot hover popover instead.
    #   the rest      — periodic or reference tools, not part of the
    #                   daily run: pulled up when wanted, not lived in.
    #
    # Deliberately still visible: audit, apa, snapshot, pipeline,
    # cheat_sheet (+ settings, which is pinned and never hideable).
    _PANELS_HIDDEN_BY_DEFAULT = {
        "photo_folders",
        "notifications",
        "hygiene",
        "kpi",
        "disputes",
        "wc_audit",
        "spreadsheet",
        "job_notes",
        "multi_unit",
    }

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

    def counts(self, force=False):
        """Live counts per sidebar item — best-effort, cheap reads."""
        now = time.monotonic()
        if not force and self._counts_cache:
            cached_at, cached = self._counts_cache
            if now - cached_at < 60:
                return dict(cached)
        if not self._counts_lock.acquire(blocking=False):
            return dict(self._counts_cache[1]) if self._counts_cache else {}
        try:
            return self._compute_counts()
        finally:
            self._counts_lock.release()

    def _compute_counts(self):
        """One serialized sidebar-count pass. See :meth:`counts`."""
        out = {}
        try:
            import run_doc as _rag
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
        self._counts_cache = (time.monotonic(), dict(out))
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
            departments = config.list_departments()
            try:
                import supabase_client
                if supabase_client.is_configured() and supabase_client.is_signed_in():
                    access = supabase_client.rpc("my_app_access") or {}
                    if not access.get("is_admin"):
                        allowed = {str(v).upper() for v in
                                   (access.get("departments") or [])}
                        departments = [d for d in departments
                                       if str(d.get("key") or "").upper() in allowed]
            except Exception:
                pass
            return {
                "ok": True,
                "enabled": bool(departments),
                "active": config.active_department(),
                "departments": departments,
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
            state = self.department_state()
            allowed = {str(d.get("key") or "") for d in
                       (state.get("departments") or [])}
            if key not in allowed:
                return {"ok": False,
                        "error": "That franchise is not assigned to your account."}
            if not config.set_active_department(key):
                return {"ok": False, "error": f"unknown department '{key}'"}
            _invalidate_scoped_caches()
            return {"ok": True, "switched_to": key, "reload": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}


def _invalidate_scoped_caches():
    """Drop every process-lifetime cache scoped to the active department.

    Delegates to `cache_bust`, which Settings-save uses too. This list used
    to live here and had already fallen behind — it didn't know about the
    department→root map or the storage-backend selection, so a department
    switch kept serving the previous department's folder roots."""
    try:
        import cache_bust
        # keep_path_keyed: the year index and parsed run-docs are keyed by
        # absolute path, and the two franchises have entirely different
        # roots, so neither can serve the other's entry. Re-scanning the
        # share on every switch was the slow part of going back and forth.
        cache_bust.invalidate_all("department switch", keep_path_keyed=True)
    except Exception:
        pass


def main(argv=None):
    # Quick Import — the stripped-down tool for general office users opens
    # from the SAME exe via a `--quickimport` shortcut, so simple users get a
    # dedicated launcher and never see the full suite.
    import sys as _sys
    _argv = argv if argv is not None else _sys.argv[1:]
    if not _claim_single_instance():
        _show_already_running()
        return
    if "--quickimport" in _argv:
        import quickimport_web
        quickimport_web.main()
        return
    _ensure_root_index()
    import paths as _paths
    _set_windows_app_identity(getattr(_paths, "IS_TRIAL", False))
    # Dated copies of state.json / ems_jobs.db / config.json before the
    # app touches any of them. Threaded, and swallows everything — a
    # backup that can break startup is worse than no backup.
    try:
        import data_backup
        data_backup.start_background()
    except Exception:
        pass
    api = HomeApi()
    win = webview.create_window(
        title=("Linguar Hub — TRIAL" if getattr(_paths, "IS_TRIAL", False)
               else "Linguar Hub"),
        url=ROOT_INDEX_HTML,    # served as http://127.0.0.1:port/_ems_root_index.html
        js_api=api,
        width=1480, height=900,
        min_size=(960, 600),
    )
    api.attach(win)
    try:
        import global_hotkey
        api._hotkey = global_hotkey.Manager(api.focus_window)
        api._hotkey.start()
    except Exception:
        api._hotkey = None
    # http_server=True serves the parent dir of the URL — by rooting
    # at scripts/, every <tool>_web_assets/ folder is reachable as a
    # sibling. Same-origin everywhere → iframe shim's
    # window.parent.pywebview access works.
    try:
        taskbar_icon = _paths.resource(
            "linguar_hub_trial.ico" if getattr(_paths, "IS_TRIAL", False)
            else "linguar_hub.ico")
        webview.start(debug=False, http_server=True, icon=taskbar_icon)
    finally:
        if api._hotkey:
            api._hotkey.stop()


if __name__ == "__main__":
    main()
