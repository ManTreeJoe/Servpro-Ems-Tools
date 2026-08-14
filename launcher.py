"""
Linguar Hub — single-window launcher.

Two modes (selected by argv):
  - With "--tool <name> [args...]" → dispatches to that tool's main() and exits.
    This is how the launcher.exe spawns standalone tool windows when needed.
  - Otherwise → shows the launcher window: left sidebar of tools, right pane
    hosts the active panel.

Tools converted to ToolPanel are embedded inline. Tools still inheriting from
tk.Tk are launched as subprocess windows via paths.spawn_tool until they're
converted. As we migrate each tool, flip its `mode` field below.
"""
import os
import sys
import ctypes
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# DPI awareness MUST be set before any Tk window is created — without
# it, Windows bitmap-scales the app on 4K / high-DPI displays which
# makes everything look tiny + blurry.
import dpi_scaling as _dpi_scaling
_dpi_scaling.enable_dpi_awareness()

# Widget scaler — monkey-patches tk.BaseWidget.__init__ so EVERY widget
# created from this point on has its font size + padx/pady multiplied
# by the configured scale. This is the only way to make actual
# elements (not just fonts, not just the window) bigger by a fixed
# factor on Tk. Installed at module load BEFORE the launcher's
# ctk.CTk() root is constructed so even the chrome scales.
try:
    import config as _cfg_early
    _scale_from_cfg = _cfg_early.load().get("ui_scale")
    if _scale_from_cfg is None or str(_scale_from_cfg).lower() == "auto":
        # No explicit override → laptop-friendly default. Small
        # 14"-class screens have small pixels even at 1920×1080, and
        # 1.0 default rendered the app unreadable on them. Users on
        # 27" monitors can dial down with Ctrl+- + restart.
        _scale_from_cfg = 1.5
    _dpi_scaling.install_widget_scaler(float(_scale_from_cfg))
except Exception:
    pass

import paths

# CustomTkinter — modern rounded widgets for the launcher chrome only.
# Panels remain plain tk.Frame so existing tools work unchanged; ctk widgets
# coexist with tk widgets in the same window without issue.
try:
    import customtkinter as ctk
    _HAVE_CTK = True
    # Honor the user's Settings → Appearance choice. Default "system"
    # so a fresh install matches the Win11 light/dark mode without any
    # configuration. Falls back to "light" for older configs that
    # predate the setting.
    # Theme reads the same `appearance` config key + handles
    # "system" resolution + sets ctk.set_appearance_mode for us.
    # Default is now 'dark' (the rebrand default).
    try:
        import theme as _theme
        _resolved = _theme.apply_appearance()
        ctk.set_appearance_mode(
            "Dark" if _resolved == "dark" else "Light")
    except Exception:
        ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("green")
except ImportError:
    ctk = None
    _HAVE_CTK = False


# ── Logging breadcrumb ──────────────────────────────────────────────────────
def _log_swallowed(component, message):
    """Best-effort warn into ems.log without crashing if logging itself
    is broken. Used at catch-sites that previously did `except: pass` so
    swallowed errors leave a breadcrumb the user can find via
    Settings → Open data folder → ems.log."""
    try:
        import ems_log
        ems_log.warn(component, message)
    except Exception:
        pass


# ── Crash handler ───────────────────────────────────────────────────────────
def _install_crash_handler():
    import traceback

    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            import ems_log
            ems_log.error("uncaught", msg.strip())
        except Exception:
            pass
        try:
            import tkinter as _tk
            from tkinter import messagebox as _mb
            root = _tk._default_root
            if root is None:
                root = _tk.Tk(); root.withdraw()
            _mb.showerror(
                "Linguar Hub — Error",
                f"Something went wrong:\n\n{exc_value}\n\n"
                f"Details have been written to the log\n"
                f"(Settings → Open data folder → ems.log).")
        except Exception:
            sys.stderr.write(msg)

    sys.excepthook = _hook
    try:
        import tkinter as _tk
        _tk.Tk.report_callback_exception = lambda self, *a: _hook(*a)
    except Exception as ex:
        _log_swallowed("crash_handler",
                       f"failed to install Tk callback hook: {ex}")


_install_crash_handler()


# ── Centralize messagebox.showerror through ems_log ─────────────────────────
def _install_error_dialog_logging():
    """Wrap every messagebox.showerror call so it also lands in ems.log,
    without touching the dozens of existing call sites."""
    try:
        from tkinter import messagebox as _mb
    except Exception:
        return
    if getattr(_mb, "_ems_logging_installed", False):
        return
    _mb._ems_logging_installed = True
    _orig = _mb.showerror

    def _wrap(title=None, message=None, **kw):
        try:
            import ems_log
            ems_log.error("dialog", f"{title}: {message}")
        except Exception:
            pass
        return _orig(title=title, message=message, **kw)

    _mb.showerror = _wrap


_install_error_dialog_logging()


# ── Tool dispatch (--tool X) for subprocess launches ────────────────────────
TOOLS = {
    "launcher":       None,
    "run_audit":      "run_audit_gui",
    "audit_web":      "audit_web",
    "daily_photos":   "daily_photos_gui",
    "apa_monitor":    "apa_monitor_gui",
    "apa_web":        "apa_web",
    "snapshot":       "snapshot_gui",
    "print_audit":    "print_audit_gui",
    "sort_files":     "sort_files_gui",
    "cheat_sheet":    "cheat_sheet_gui",
    "new_job":        "new_job_gui",
    "job_notes":      "job_notes_gui",
    "initial_upload": "initial_upload_queue",
    "spreadsheet":    "spreadsheet_gui",
    "multi_unit":     "multi_unit_gui",
    "hygiene":        "hygiene_gui",
    "kpi":            "kpi_gui",
    "dispute_tracker": "dispute_tracker_gui",
    "wc_audit":       "wc_audit_gui",
    "pipeline":       "pipeline_gui",
    # Pywebview spike — opens Pipeline as a web-rendered window via
    # `--tool pipeline_web`. Runs in a subprocess (webview.start()
    # blocks the main thread). Tk version stays available via
    # `--tool pipeline` until the migration is complete.
    "pipeline_web":   "pipeline_web",
    "kpi_web":        "kpi_web",
    "disputes_web":   "disputes_web",
    "job_notes_web":  "job_notes_web",
    "cheat_sheet_web": "cheat_sheet_web",
    "hygiene_web":    "hygiene_web",
    "snapshot_web":   "snapshot_web",
    "wc_audit_web":   "wc_audit_web",
    "multi_unit_web": "multi_unit_web",
    "spreadsheet_web": "spreadsheet_web",
    "settings_web":   "settings_web",
    "home_web":       "home_web",
    "photo_folders_web": "photo_folders_web",
    "settings":       "settings_gui",
}


def _dispatch():
    if "--tool" not in sys.argv:
        return False
    idx = sys.argv.index("--tool")
    if idx + 1 >= len(sys.argv):
        return False
    tool = sys.argv[idx + 1]
    extra = sys.argv[idx + 2:]
    sys.argv = [sys.argv[0]] + extra
    if tool == "launcher" or tool not in TOOLS:
        return False
    # Record which tools get opened (usage analytics — tool name only).
    try:
        import usage_tracker as _ut
        _ut.record_event("launcher", "launch", tool)
    except Exception:
        pass
    mod = __import__(TOOLS[tool])
    mod.main()
    return True


if _dispatch():
    sys.exit(0)


# ── Launcher window ─────────────────────────────────────────────────────────
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Servpro.EMS.Tools")

from theme import (WHITE, BG, TEXT_DARK, TEXT_GRAY, TEXT_MUTED, BORDER,
                    SURFACE_2, GREEN_LIGHT, GREEN, NEUTRAL_HOVER)
from tool_panel import LoadingOverlay, attach_tooltip
from ui_buttons import icon_button
from state_hub import hub as _state_hub


# Sidebar tool registry. mode = "embed" (lazy-instantiate ToolPanel) or
# "spawn" (subprocess.Popen via paths.spawn_tool).
# Tool groups reflect the job lifecycle — what a file goes through
# from intake to closeout. Sidebar renders these as visual headers;
# top-strip mode inserts thin vertical separators between groups.
# Order here is authoritative; iteration order of NAV_TOOLS picks up
# group sequence automatically.
NAV_GROUP_DAILY      = "DAILY ROUTINE"
NAV_GROUP_LIFECYCLE  = "LIFECYCLE"
NAV_GROUP_MONITORING = "MONITORING"
NAV_GROUP_REFERENCE  = "REFERENCE"
NAV_GROUP_SYSTEM     = "SYSTEM"

# Key of the panel the launcher opens to on startup (and warms first).
# Must be an `embed`-mode entry so it renders inside the launcher chrome.
LANDING_KEY = "apa_monitor"

NAV_TOOLS = [
    # Daily routine — the morning workflow.
    {"key": "run_audit",    "group": NAV_GROUP_DAILY,
        "label": "Audit",            "icon": "🔎", "desc": "Daily Run · Backlog · SP Recent", "mode": "embed",
        "module": "run_audit_gui",   "class": "RunAuditApp"},
    # Pywebview spike — biggest block yet. Card-grid triage view of
    # today's run-doc audit. Read-only in Phase 1: shows flagged /
    # OK / aging / missing items per job, opens OD folder / Trello
    # card / Tk audit for per-row work that's not implemented in web
    # yet (smart import, scope dialog, comments).
    {"key": "audit_web",    "group": NAV_GROUP_DAILY,
        "label": "Audit (web)",      "icon": "🌐",
        "desc": "Card-grid audit triage — filter chips, search, per-job actions; READ-ONLY in phase 1, opens Tk for editing",
        "mode": "spawn",
        "module": "audit_web",       "class": None},
    {"key": "daily_photos", "group": NAV_GROUP_DAILY,
        "label": "Photo Folders",    "icon": "📷", "desc": "Create SharePoint photo folders",  "mode": "embed",
        "module": "daily_photos_gui","class": "App"},
    {"key": "apa_monitor",  "group": NAV_GROUP_DAILY,
        "label": "APA Monitor",      "icon": "📊", "desc": "Track APA jobs by section",        "mode": "embed",
        "module": "apa_monitor_gui", "class": "APAMonitorApp"},
    # Pywebview spike — APA Monitor rendered as a kanban-style web
    # view. Phase 1 is read-only: parses today's .docx and shows
    # sections as horizontal columns. Date picker steps through
    # recent working days. Phase 2 will add item editing + save.
    {"key": "apa_web",      "group": NAV_GROUP_DAILY,
        "label": "APA Monitor (web)", "icon": "🌐",
        "desc": "Same APA data as a kanban-style web view — date picker, search, filters; READ-ONLY in phase 1",
        "mode": "spawn",
        "module": "apa_web",         "class": None},
    # Lifecycle endpoints — intake (New Job) and closeout (Snapshot).
    {"key": "new_job",      "group": NAV_GROUP_LIFECYCLE,
        "label": "New EMS Job",      "icon": "➕", "desc": "Create folder structure for a new client job", "mode": "embed",
        "module": "new_job_gui",     "class": "NewJobApp"},
    {"key": "snapshot",     "group": NAV_GROUP_LIFECYCLE,
        "label": "EMS Snapshot",     "icon": "📸", "desc": "Generate handoff PDF + audit",     "mode": "embed",
        "module": "snapshot_gui",    "class": "SnapshotApp"},
    {"key": "snapshot_web", "group": NAV_GROUP_LIFECYCLE,
        "label": "Snapshot (web)",   "icon": "🌐",
        "desc": "Recent snapshot PDFs + closeout queue. Generation still in Tk.",
        "mode": "spawn", "module": "snapshot_web", "class": None},
    # Monitoring — ongoing in-flight health checks.
    {"key": "hygiene",      "group": NAV_GROUP_MONITORING,
        "label": "Hygiene",          "icon": "⚠", "desc": "Trello card hygiene + handoff + closeout watcher", "mode": "embed",
        "module": "hygiene_gui",     "class": "HygieneApp"},
    {"key": "hygiene_web",  "group": NAV_GROUP_MONITORING,
        "label": "Hygiene (web)",    "icon": "🌐",
        "desc": "Same hygiene scan rendered as collapsible sections — reads the cached scan, run scans in Tk for now",
        "mode": "spawn", "module": "hygiene_web", "class": None},
    {"key": "kpi",          "group": NAV_GROUP_MONITORING,
        "label": "KPI",              "icon": "📈", "desc": "Weekly metrics + repeat offenders",       "mode": "embed",
        "module": "kpi_gui",         "class": "KPIApp"},
    # Pywebview spike — KPI rendered in an Edge WebView2 window with
    # the same backend (kpi_metrics). Side-by-side with the Tk
    # version during the migration.
    {"key": "kpi_web",      "group": NAV_GROUP_MONITORING,
        "label": "KPI (web)",        "icon": "🌐",
        "desc": "Same KPI dashboard, rendered as a web view — DPI-scaled, modern HTML controls",
        "mode": "spawn",
        "module": "kpi_web",         "class": None},
    {"key": "dispute_tracker", "group": NAV_GROUP_MONITORING,
        "label": "Inquiries & Disputes", "icon": "⚖", "desc": "Audit inquiries & disputes tracker — auto-seeded from APA + Email, manual edits in-app", "mode": "embed",
        "module": "dispute_tracker_gui", "class": "DisputeTrackerApp"},
    {"key": "disputes_web", "group": NAV_GROUP_MONITORING,
        "label": "Inquiries & Disputes (web)", "icon": "🌐",
        "desc": "Inquiries & disputes table with status filter chips + sortable columns + Trello jump",
        "mode": "spawn", "module": "disputes_web", "class": None},
    {"key": "wc_audit",     "group": NAV_GROUP_MONITORING,
        "label": "WC Audit",         "icon": "🗂", "desc": "Monthly WorkCenter audit — classify rows by Trello status, send to Sam", "mode": "embed",
        "module": "wc_audit_gui",    "class": "WCMonthlyAuditApp"},
    {"key": "wc_audit_web", "group": NAV_GROUP_MONITORING,
        "label": "WC Audit (web)",   "icon": "🌐",
        "desc": "Last WC classification summary + workbook opener",
        "mode": "spawn", "module": "wc_audit_web", "class": None},
    {"key": "pipeline",     "group": NAV_GROUP_MONITORING,
        "label": "Pipeline",         "icon": "🛤", "desc": "Every job from card-created to paid — stage filter chips + stalled-job coloring", "mode": "embed",
        "module": "pipeline_gui",    "class": "PipelineApp"},
    # Pywebview spike — same Pipeline data rendered in an Edge
    # WebView2 window. Runs as a subprocess (mode="spawn") because
    # webview.start() takes over the calling thread. Sidebar shows
    # both side-by-side during the migration so behavior can be
    # A/B compared.
    {"key": "pipeline_web", "group": NAV_GROUP_MONITORING,
        "label": "Pipeline (web)",   "icon": "🌐",
        "desc": "Same Pipeline data, rendered in a browser window — DPI scaling Just Works, Ctrl+= zooms everything",
        "mode": "spawn",
        "module": "pipeline_web",    "class": None},
    # Reference — viewers + ad-hoc lookups, used any time of day.
    {"key": "spreadsheet",  "group": NAV_GROUP_REFERENCE,
        "label": "Spreadsheets",     "icon": "📒", "desc": "Multi-workbook viewer + reconcile (Snapshots, more as added)", "mode": "embed",
        "module": "spreadsheet_gui", "class": "SpreadsheetApp"},
    {"key": "spreadsheet_web","group": NAV_GROUP_REFERENCE,
        "label": "Spreadsheets (web)","icon": "🌐",
        "desc": "Workbook launcher — opens registered workbooks in Excel",
        "mode": "spawn", "module": "spreadsheet_web", "class": None},
    {"key": "job_notes",    "group": NAV_GROUP_REFERENCE,
        "label": "Job Notes",        "icon": "🗒", "desc": "Trello notes per client + timeline",        "mode": "embed",
        "module": "job_notes_gui",   "class": "JobNotesApp"},
    {"key": "job_notes_web","group": NAV_GROUP_REFERENCE,
        "label": "Job Notes (web)",  "icon": "🌐",
        "desc": "Two-pane note viewer — list of saved notes left, full text right",
        "mode": "spawn", "module": "job_notes_web", "class": None},
    {"key": "multi_unit",   "group": NAV_GROUP_REFERENCE,
        "label": "Multi-Unit",       "icon": "🏢", "desc": "Linked siblings for commercial properties spanning multiple units", "mode": "embed",
        "module": "multi_unit_gui",  "class": "MultiUnitApp"},
    {"key": "multi_unit_web","group": NAV_GROUP_REFERENCE,
        "label": "Multi-Unit (web)", "icon": "🌐",
        "desc": "Linked sibling groups — read-only viewer",
        "mode": "spawn", "module": "multi_unit_web", "class": None},
    {"key": "cheat_sheet",  "group": NAV_GROUP_REFERENCE,
        "label": "Cheat Sheet",      "icon": "📝", "desc": "Workflow reference",               "mode": "embed",
        "module": "cheat_sheet_gui", "class": "CheatSheetApp"},
    {"key": "cheat_sheet_web","group": NAV_GROUP_REFERENCE,
        "label": "Cheat Sheet (web)","icon": "🌐",
        "desc": "Markdown reference rendered as styled web pages with TOC + search",
        "mode": "spawn", "module": "cheat_sheet_web", "class": None},
    {"key": "resources_web","group": NAV_GROUP_REFERENCE,
        "label": "Resources",        "icon": "📚",
        "desc": "Search the share's reference material — forms, COIs, "
                "vendors, templates: everything that isn't a job",
        "mode": "spawn", "module": "resources_web", "class": None},
    # System — config + low-volume utilities.
    {"key": "sort_files",   "group": NAV_GROUP_SYSTEM,
        "label": "Sort Files",       "icon": "📁", "desc": "Move downloads into job folders",  "mode": "embed",
        "module": "sort_files_gui",  "class": "SortFilesApp"},
    # Settings is a modal dialog rather than a panel — handled by
    # _activate_entry's "dialog" branch.
    {"key": "settings",     "group": NAV_GROUP_SYSTEM,
        "label": "Settings",         "icon": "⚙", "desc": "Configure paths and preferences",           "mode": "dialog"},
    {"key": "settings_web", "group": NAV_GROUP_SYSTEM,
        "label": "Settings (web)",   "icon": "🌐",
        "desc": "Web-rendered config form — same backend as the Tk dialog",
        "mode": "spawn", "module": "settings_web", "class": None},
]


SIDEBAR_BG     = WHITE
# Hover & active row tints — pulled from the theme so they flip with
# light/dark. SURFACE_2 = one shade brighter than the sidebar; GREEN_LIGHT
# = a green-tinted accent that's dark in dark mode, light in light mode.
SIDEBAR_HOVER  = SURFACE_2
SIDEBAR_ACTIVE = GREEN_LIGHT
SIDEBAR_W      = 220   # width of the left rail when in sidebar mode
RESPONSIVE_NAV_THRESHOLD = 1100   # below this width we use the top strip
HEADER_H       = 48    # slim top bar
TOOLSTRIP_H    = 52    # horizontal tool row beneath the header


_LauncherBase = ctk.CTk if _HAVE_CTK else tk.Tk


class LauncherApp(_LauncherBase):
    def __init__(self):
        super().__init__()
        # DPI-matched scaling — runs after the Tk root exists. Reads
        # the screen DPI and bumps tk.scaling + ctk's widget/window
        # scaling so the app feels the same physical size on a 4K
        # laptop @ 200% as on a 27" monitor @ 100%. No-op on standard-
        # DPI screens (scale stays at 1.0).
        try:
            _dpi_scaling.apply_window_scaling(self)
        except Exception:
            pass
        # Ctrl + / Ctrl - / Ctrl 0 keyboard scaling — live adjustment
        # while the launcher is open. Each press bumps the scale by
        # 0.1, persists to config.json, and shows a status-bar toast
        # so the user can see the value. Useful for bouncing between
        # a small high-DPI laptop and an external 27" monitor without
        # restarting the app.
        def _on_scale_change(scale):
            try:
                from tool_panel import show_toast as _toast
                _toast(self,
                        f"UI scale: {scale:.2f}",
                        kind="info", duration=1400)
            except Exception:
                pass
        try:
            _dpi_scaling.bind_scale_shortcuts(
                self, on_change=_on_scale_change)
        except Exception:
            pass
        # Suffix the title with " · ALPHA" when the alpha flag is on so
        # the user can see at a glance which mode the running instance
        # is in (in case multiple windows are open across machines).
        try:
            import config as _cfg
            _alpha_suffix = "  ·  ALPHA" if _cfg.is_alpha_enabled() else ""
        except Exception as ex:
            _log_swallowed("launcher", f"alpha-flag read failed: {ex}")
            _alpha_suffix = ""
        self.title(
            f"SERVPRO  ·  Linguar Hub  ·  v{paths.VERSION}{_alpha_suffix}")
        # Restore last window size/position; fall back to default on first run.
        try:
            import persistence as _persistence
            saved_geo = _persistence.get_geometry("launcher")
        except Exception as ex:
            _log_swallowed("launcher", f"saved geometry load failed: {ex}")
            saved_geo = None
        self.geometry(saved_geo or "1180x760")
        # Generous lower bound so the slim chrome (header + toolstrip +
        # status bar) and at least a sliver of panel content stay visible.
        # The toolstrip itself scrolls horizontally, so width can go small.
        self.minsize(480, 360)
        self.configure(bg=BG)

        # Apply the ttk style overrides so Treeview / Combobox / Spinbox
        # / tk.Text / tk.Entry pick up the current (dark) palette. Must
        # happen after the root window exists since ttk.Style() needs
        # one. Safe to call again from a Settings toggle later.
        try:
            import theme as _theme
            _theme.apply_ttk_theme(self)
        except Exception:
            pass

        # Title-bar icon. iconbitmap() is the Windows-native path; on some
        # Tk builds it silently rejects ICO files that contain a 256x256
        # PNG-compressed entry, leaving the window with the default Tk
        # feather. PIL+iconphoto is more tolerant, so try it first and
        # fall back to iconbitmap if PIL isn't available. Any failure is
        # logged (the silent except hid this exact bug for weeks).
        icon = paths.resource("wrench.ico")
        if os.path.isfile(icon):
            ok = False
            try:
                from PIL import Image, ImageTk
                img = Image.open(icon)
                self._icon_photo = ImageTk.PhotoImage(img)
                self.iconphoto(True, self._icon_photo)
                ok = True
            except Exception as ex:
                try:
                    import ems_log
                    ems_log.warn("launcher",
                                 f"iconphoto load failed for {icon}: {ex}")
                except Exception:
                    pass
            if not ok:
                try:
                    self.iconbitmap(default=icon)
                    self.iconbitmap(icon)
                except Exception as ex:
                    try:
                        import ems_log
                        ems_log.warn("launcher",
                                     f"iconbitmap load failed for {icon}: {ex}")
                    except Exception:
                        pass
        else:
            try:
                import ems_log
                ems_log.warn("launcher",
                             f"icon file missing: {icon}")
            except Exception:
                pass

        # Lazy-loaded panels keyed by tool key
        self._panels = {}
        self._sidebar_rows = {}  # key → frame for highlight management
        # Notification badge widgets keyed by tool key. Populated by
        # `_make_toolstrip_button` + `_make_sidebar_row`; refreshed
        # periodically via `_refresh_tool_badges`.
        self._tool_badges: dict = {}
        self._badge_refresh_after = None
        self._current_key = None
        # Responsive nav state — "top" = horizontal strip, "side" = left
        # sidebar. Decided by window width vs RESPONSIVE_NAV_THRESHOLD.
        self._nav_mode = None
        self._nav_frame = None
        self._nav_resize_after = None
        # Navigation history — list of (key, cli_args) tuples. Pushed when
        # _show_panel switches AWAY from a panel; popped by _go_back().
        self._history = []
        self._back_btn = None  # populated in _build_ui

        self._title_var = tk.StringVar(value="Linguar Hub")

        self._build_ui()

        # Startup loading overlay — covers the content area for the
        # ~1-2 second window between launcher chrome painting and the
        # landing panel rendering. Brief by design now: the heavy
        # 14-panel preload sweep was retired in favor of a lazy /
        # background-warm hybrid (see `_first_paint_landing` +
        # `_background_warm_top_panels`), so the overlay is only up
        # long enough to disguise the landing panel's construction.
        # Other panels render lazily on click with their own per-panel
        # overlays — no global "preparing tools" lockup.
        try:
            self._startup_overlay = LoadingOverlay(
                self._content,
                message="Preparing your tools…",
                with_progress=True,
                brand="SERVPRO  ·  Linguar Hub")
            self._startup_overlay.pack(fill="both", expand=True)
            self._startup_overlay.start()
            # Paint immediately so the spinner is visible before the
            # first preload tick blocks the main thread.
            self.update_idletasks()
        except Exception:
            self._startup_overlay = None

        # The landing panel now activates AFTER the preload sweep
        # finishes (see `_finish_startup_overlay`). That way the user
        # doesn't see a panel paint, then get covered by panel-
        # construction blocking — they see one clean loading screen,
        # then the landing panel renders against a fully-warm cache.
        self._landing_pending = True

        # Keyboard shortcut for back navigation. (Mouse XButton1/back-button
        # isn't exposed by Tk on Windows in a portable way — the on-screen
        # ← button covers that case.)
        self.bind_all("<Alt-Left>", lambda e: self._go_back())

        # First badge sync — schedule after the nav is in place so
        # _tool_badges is populated. Subsequent ticks self-arm via
        # `_refresh_tool_badges`.
        self.after(800, self._refresh_tool_badges)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(120, self._maybe_show_first_run)
        # Warm caches in the background so first panel-click is instant
        self.after(250, _state_hub.start_prefetch)
        # First status refresh waits for the prefetch to populate the cache
        self.after(900, self._refresh_status)
        # Two-phase panel build (2026-05-19, was a single eager sweep):
        #   Phase 1 — `_first_paint_landing` builds + activates the
        #             landing panel (LANDING_KEY) and tears down the
        #             startup overlay. ~1-2s typical, vs. the previous
        #             ~10s eager-sweep that built every panel before the
        #             user could interact.
        #   Phase 2 — `_background_warm_top_panels` runs ~3s later and
        #             quietly instantiates the next most-used panels
        #             (audit / hygiene) one at a time. No overlay,
        #             no UI interruption — purely so the first click on
        #             those tools is instant. Everything else stays
        #             lazy: first click triggers a per-panel
        #             LoadingOverlay (sub-second for most).
        self.after(120, self._first_paint_landing)
        self.after(3000, self._background_warm_top_panels)
        # Sweep stale persistence entries for clients no longer in audit_base
        # (rate-limited to once per 24h inside persistence.cleanup_stale_keys).
        self.after(8000, self._sweep_stale_keys)

    def _sweep_stale_keys(self):
        """Background-thread the persistence sweep so the network walk over
        audit_base doesn't block the UI."""
        def _bg():
            try:
                import config as _cfg
                import persistence as _per
                base = _cfg.load().get("audit_base", "")
                report = _per.cleanup_stale_keys(base)
                if report.get("total", 0) > 0:
                    import ems_log
                    ems_log.info("cleanup",
                        f"swept {report['total']} stale persistence entries")
            except Exception as ex:
                try:
                    import ems_log
                    ems_log.warn("cleanup", f"stale sweep failed: {ex}")
                except Exception:
                    pass
        import threading
        threading.Thread(target=_bg, daemon=True).start()

    # ── UI build ────────────────────────────────────────────────────────────
    def _build_ui(self):
        if _HAVE_CTK:
            self._build_ui_ctk()
        else:
            self._build_ui_tk()

    def _build_ui_ctk(self):
        """Modern chrome — CustomTkinter rounded widgets, hover states.
        `_content` stays as a plain tk.Frame so existing ToolPanel children
        (which are tk.Frames) embed without issue."""
        # Footer first so bottom-stacked widgets layer correctly
        ctk.CTkLabel(self, text=f"Linguar Hub  ·  v{paths.VERSION}",
                     font=ctk.CTkFont("Segoe UI Variable", 11),
                     text_color="#9AA5AE"
                     ).pack(side="bottom", pady=(0, 8))

        # Status bar — slightly taller and with a hairline top border for
        # visual separation. The previous 28px felt cramped now that the
        # rest of the chrome is roomier.
        self._status_bar = ctk.CTkFrame(self, fg_color="#FCFDFD",
                                         border_width=0,
                                         corner_radius=0, height=34)
        self._status_bar.pack(side="bottom", fill="x")
        # Hairline top border
        ctk.CTkFrame(self, fg_color=BORDER, corner_radius=0,
                     height=1).pack(side="bottom", fill="x")
        self._status_run_lbl = ctk.CTkLabel(
            self._status_bar, text="Run: —",
            font=ctk.CTkFont("Segoe UI Variable", 11),
            text_color=TEXT_GRAY)
        self._status_run_lbl.pack(side="left", padx=14, pady=4)
        self._status_err_lbl = ctk.CTkLabel(
            self._status_bar, text="",
            font=ctk.CTkFont("Segoe UI Variable", 11),
            text_color=TEXT_GRAY)
        self._status_err_lbl.pack(side="left", padx=(0, 14), pady=4)
        ctk.CTkButton(self._status_bar, text="↻",
                      font=ctk.CTkFont("Fraunces", 15, "bold"),
                      width=32, height=24, corner_radius=6,
                      fg_color="transparent", hover_color="#E8F5EE",
                      text_color=TEXT_GRAY,
                      command=self._refresh_status
                      ).pack(side="right", padx=10, pady=4)

        # Header bar removed — Settings, Cheat Sheet, and Job Notes all live
        # on the toolstrip now, and the active section is obvious from the
        # toolstrip's highlight. Alt+Left still navigates back.

        # `_content` MUST be a plain tk.Frame — ToolPanel subclasses are
        # tk.Frames and embed via this parent. Build the content frame
        # BEFORE the nav so _apply_responsive_nav can repack the content
        # next to whichever nav mode wins on first paint.
        self._content = tk.Frame(self, bg=BG)
        self._apply_responsive_nav()
        self.bind("<Configure>", self._on_root_configure)

    def _build_ui_tk(self):
        """Fallback chrome (plain tk) — used when CustomTkinter isn't
        installed. Mirrors the original look so dev installs without ctk
        keep working."""
        # Footer first
        tk.Label(self, text=f"Linguar Hub  ·  v{paths.VERSION}",
                 font=("Segoe UI Variable", 7), bg=BG, fg=TEXT_MUTED).pack(side="bottom", pady=(0, 6))

        self._status_bar = tk.Frame(self, bg=WHITE,
                                     highlightbackground=BORDER,
                                     highlightthickness=1)
        self._status_bar.pack(side="bottom", fill="x")
        self._status_run_lbl = tk.Label(
            self._status_bar, text="Run: —",
            font=("Segoe UI Variable", 8), bg=WHITE, fg=TEXT_GRAY)
        self._status_run_lbl.pack(side="left", padx=10, pady=3)
        self._status_err_lbl = tk.Label(
            self._status_bar, text="",
            font=("Segoe UI Variable", 8), bg=WHITE, fg=TEXT_GRAY)
        self._status_err_lbl.pack(side="left", padx=(0, 10), pady=3)
        icon_button(self._status_bar, "↻", command=self._refresh_status,
                     tooltip="Refresh status").pack(side="right", padx=8)

        # Header bar removed — Settings, Cheat Sheet, and Job Notes all live
        # on the toolstrip now, and the active section is obvious from the
        # toolstrip's highlight. Alt+Left still navigates back.

        # `_content` is built first so _apply_responsive_nav can repack
        # it relative to whichever nav mode wins on first paint.
        self._content = tk.Frame(self, bg=BG)
        self._apply_responsive_nav()
        self.bind("<Configure>", self._on_root_configure)

    # ── Visible-tool filter (shared by top strip + left sidebar) ────────────
    def _iter_visible_tools(self):
        """Yield NAV_TOOLS entries the user wants to see. Honors the
        Sort Files / New EMS Job opt-in flags so both nav layouts stay
        in sync without duplicating the filter. Today is hard-filtered
        per user direction 2026-05-12 ("i dont use the today tab at
        all") — file kept in place so deep-link dispatch (`--tool
        today`) still works. To revive: remove the today check below.
        """
        try:
            import config as _cfg
            show_sort_files = _cfg.is_sort_files_visible()
            show_new_job    = _cfg.is_new_job_visible()
        except Exception:
            show_sort_files = False
            show_new_job    = False
        for entry in NAV_TOOLS:
            if entry["key"] == "sort_files" and not show_sort_files:
                continue
            if entry["key"] == "new_job" and not show_new_job:
                continue
            yield entry

    # ── Horizontal top toolstrip ────────────────────────────────────────────
    def _build_top_toolstrip(self, parent):
        """Slim horizontal row of tool buttons under the header.

        Wraps the buttons in a Canvas so they scroll horizontally when the
        window is too narrow to fit every tool side-by-side. Mouse-wheel
        scroll is bound to the canvas so users can swipe through the row.
        """
        wrap = tk.Frame(parent, bg=SIDEBAR_BG,
                        highlightbackground=BORDER, highlightthickness=1,
                        height=TOOLSTRIP_H)
        wrap.pack(fill="x", side="top")
        wrap.pack_propagate(False)
        # Record so _apply_responsive_nav can tear this down on mode flip.
        self._nav_frame = wrap

        canvas = tk.Canvas(wrap, bg=SIDEBAR_BG, height=TOOLSTRIP_H,
                           highlightthickness=0, bd=0)
        canvas.pack(side="top", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=SIDEBAR_BG)
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        # Thin vertical separator between lifecycle groups — sidebar
        # has full label headers; in the cramped top strip we keep it
        # to a 1px divider so width stays usable.
        last_group = None
        for entry in self._iter_visible_tools():
            grp = entry.get("group", "")
            if last_group is not None and grp != last_group:
                self._make_toolstrip_group_separator(inner)
            last_group = grp
            self._make_toolstrip_button(inner, entry)

        # Update scrollregion when content changes.
        def _on_inner_configure(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
        inner.bind("<Configure>", _on_inner_configure)

        # Cache the natural full-mode width so responsive logic has a
        # threshold to compare canvas width against.
        self._toolstrip_full_width = None
        self._toolstrip_compact = False
        self._toolstrip_resize_after = None

        def _measure_full_width():
            """Force layout in full-label mode and record the resulting
            inner-frame width, so future resizes can compare against it."""
            for b in self._toolstrip_buttons:
                if not b["title"].winfo_ismapped():
                    b["title"].pack(side="left", padx=(0, 6),
                                    fill="x", expand=True)
            inner.update_idletasks()
            self._toolstrip_full_width = inner.winfo_reqwidth()

        def _apply_mode(compact):
            """Show or hide every button's label in one pass."""
            self._toolstrip_compact = compact
            for b in self._toolstrip_buttons:
                if compact:
                    if b["title"].winfo_ismapped():
                        b["title"].pack_forget()
                else:
                    if not b["title"].winfo_ismapped():
                        b["title"].pack(side="left", padx=(0, 6),
                                        fill="x", expand=True)

        def _relayout(canvas_w):
            """Pick a layout mode based on canvas width, then size the
            inner frame so buttons spread across the full width when
            there's room (fill='x' + expand handles the distribution).

            Defensive: the after()-debounced caller can fire AFTER
            `inner` / `canvas` were destroyed — typically when the
            launcher swapped between top-strip and sidebar modes
            (≥1100px threshold) while a Configure event was still
            queued. Every widget touch is wrapped so a dead widget
            silently no-ops instead of leaking a `bad window path
            name` traceback into the error dialog."""
            try:
                if not inner.winfo_exists() or not canvas.winfo_exists():
                    return
            except tk.TclError:
                return
            if self._toolstrip_full_width is None:
                try:
                    _measure_full_width()
                except tk.TclError:
                    return
            full_w = self._toolstrip_full_width or 0
            want_compact = canvas_w < full_w + 8
            if want_compact != self._toolstrip_compact:
                try:
                    _apply_mode(want_compact)
                    inner.update_idletasks()
                except tk.TclError:
                    return
            try:
                natural_w = inner.winfo_reqwidth()
                target_w = max(canvas_w, natural_w)
                canvas.itemconfigure(inner_id, width=target_w)
            except tk.TclError:
                return

        # Keep the inner frame's height locked to the canvas height so
        # buttons centre vertically; debounce relayout on configure.
        def _on_canvas_configure(e):
            # Configure can fire on a canvas whose inner frame was
            # already destroyed by a strip↔sidebar swap. Skip silently
            # in that case so we don't schedule a relayout against a
            # dead widget (the after() would still fire, then crash).
            try:
                if not canvas.winfo_exists() or not inner.winfo_exists():
                    return
                canvas.itemconfigure(inner_id, height=e.height)
            except tk.TclError:
                return
            # Debounce — Configure fires per-pixel during a drag-resize.
            if self._toolstrip_resize_after is not None:
                try: self.after_cancel(self._toolstrip_resize_after)
                except Exception: pass
            self._toolstrip_resize_after = self.after(
                40, lambda w=e.width: _relayout(w))
        canvas.bind("<Configure>", _on_canvas_configure)

        # Mouse-wheel scrolls horizontally only when the cursor is over
        # the toolstrip (so it doesn't fight panel-internal scrolls).
        def _on_wheel(e):
            # Windows: e.delta is a multiple of 120 per notch.
            canvas.xview_scroll(int(-e.delta / 120), "units")
            return "break"
        for w in (wrap, canvas, inner):
            w.bind("<Enter>",
                   lambda _e, c=canvas: c.bind_all("<MouseWheel>", _on_wheel))
            w.bind("<Leave>",
                   lambda _e, c=canvas: c.unbind_all("<MouseWheel>"))

        self._toolstrip_canvas = canvas
        self._toolstrip_inner  = inner

    def _make_toolstrip_button(self, parent, entry):
        """Compact icon+label button used in the top toolstrip.

        Icon uses the dedicated `Segoe UI Emoji` font + a fixed-width
        holder so emoji glyphs with different baselines (📷 📊 🔎 etc.)
        line up consistently with the label text.
        """
        active = (self._current_key == entry["key"])
        bg = SIDEBAR_ACTIVE if active else SIDEBAR_BG
        btn = tk.Frame(parent, bg=bg, cursor="hand2",
                       highlightthickness=0, bd=0)
        # Spread mode (set after layout): fill="x", expand=True.
        btn.pack(side="left", padx=2, pady=2, fill="x", expand=True)

        icon = tk.Label(btn, text=entry["icon"],
                        font=("Segoe UI Emoji", 14),
                        bg=bg, fg=TEXT_DARK,
                        width=2, padx=6, pady=6, anchor="center")
        icon.pack(side="left")
        title = tk.Label(btn, text=entry["label"],
                         font=("Segoe UI Variable", 10, "bold"),
                         bg=bg, fg=TEXT_DARK, padx=2, pady=6,
                         anchor="center")
        title.pack(side="left", padx=(0, 8), fill="x", expand=True)

        # Notification badge — red pill with a count. Initially hidden;
        # `_refresh_tool_badges()` shows it when the entry's bound
        # count source returns a positive number. Tracked in
        # `self._tool_badges` so refresh logic doesn't have to walk
        # the widget tree.
        badge = tk.Label(btn, text="", font=("Segoe UI Variable", 8, "bold"),
                         bg="#A64242", fg="#FFFFFF",
                         padx=5, pady=0, bd=0, relief="flat")
        # Don't pack yet — _refresh_tool_badges flips visibility.
        self._tool_badges[entry["key"]] = badge

        widgets = [btn, icon, title]

        def _set_bg(color):
            for w in widgets:
                try: w.config(bg=color)
                except Exception: pass

        def _enter(_e=None):
            if self._current_key == entry["key"]:
                return
            _set_bg(SIDEBAR_HOVER)

        def _leave(_e=None):
            if self._current_key == entry["key"]:
                return
            _set_bg(SIDEBAR_BG)

        def _click(_e=None):
            self._activate_entry(entry)

        def _popout(_e=None):
            """Spawn this tool as a standalone window (separate process)
            so it can sit alongside the launcher."""
            try:
                import ems_log
                ems_log.info("launcher", f"popout requested: {entry['key']}")
            except Exception:
                pass
            try:
                paths.spawn_tool(entry["key"])
            except Exception as ex:
                from tkinter import messagebox
                messagebox.showerror(
                    "Couldn't open new window",
                    f"Failed to launch {entry['label']} in a new window:\n\n{ex}",
                    parent=self)
                return "break"
            self._flash_spawn_message(f"{entry['label']} → new window")
            return "break"

        def _show_menu(e):
            menu = tk.Menu(self, tearoff=0)
            menu.add_command(
                label=f"Open '{entry['label']}' in this window",
                command=lambda: self._activate_entry(entry))
            menu.add_command(
                label=f"Open '{entry['label']}' in a new window",
                command=_popout)
            try:
                menu.tk_popup(e.x_root, e.y_root)
            finally:
                menu.grab_release()
            return "break"

        for w in widgets:
            w.bind("<Enter>", _enter)
            w.bind("<Leave>", _leave)
            w.bind("<Button-1>", _click)
            # Right-click → context menu. <ButtonRelease-3> is more reliable
            # than <Button-3> on Windows because some focus juggling happens
            # on press; releasing always fires.
            w.bind("<ButtonRelease-3>", _show_menu)
            # Middle/Shift/Ctrl+click → instant popout (no menu).
            w.bind("<Button-2>", _popout)
            w.bind("<Shift-Button-1>", _popout)
            w.bind("<Control-Button-1>", _popout)
            # Hover hint: show the nav entry's `desc` text so users learn
            # what each icon does without having to click through.
            attach_tooltip(w, entry.get("desc") or entry["label"])

        # Track per-key widget refs so the responsive resize handler can
        # toggle the label off/on without rebuilding the toolstrip.
        self._sidebar_rows[entry["key"]] = (btn, widgets)
        if not hasattr(self, "_toolstrip_buttons"):
            self._toolstrip_buttons = []
        self._toolstrip_buttons.append({
            "btn":   btn,
            "icon":  icon,
            "title": title,
            "label": entry["label"],
        })

    def _set_active_row(self, key):
        for k, (row, widgets) in self._sidebar_rows.items():
            bg = SIDEBAR_ACTIVE if k == key else SIDEBAR_BG
            # Toolstrip buttons are plain tk widgets; legacy CTk sidebar
            # rows use fg_color. Try CTk first when available, fall back
            # to tk's bg property — whichever the widget actually supports.
            applied = False
            if _HAVE_CTK:
                try:
                    row.configure(fg_color=bg)
                    applied = True
                except Exception:
                    applied = False
            if not applied:
                for w in widgets:
                    try: w.config(bg=bg)
                    except Exception: pass

    # ── Left sidebar (Arc-style) ────────────────────────────────────────────
    def _build_left_sidebar(self, parent):
        """Vertical icon+label rail on the left edge. Used when the
        launcher is wide enough (≥ RESPONSIVE_NAV_THRESHOLD); narrower
        windows fall back to _build_top_toolstrip.

        Same data + activation behavior as the top strip — the only
        difference is layout direction and per-row size.
        """
        wrap = tk.Frame(parent, bg=SIDEBAR_BG,
                        highlightbackground=BORDER, highlightthickness=1,
                        width=SIDEBAR_W)
        wrap.pack(side="left", fill="y")
        wrap.pack_propagate(False)
        # Record so _apply_responsive_nav can destroy this on mode flip.
        self._nav_frame = wrap

        inner = tk.Frame(wrap, bg=SIDEBAR_BG)
        inner.pack(side="top", fill="both", expand=True, padx=4, pady=4)

        # Group label between lifecycle sections — purely visual, helps
        # new staff orient ("Daily Routine" vs "Lifecycle" vs etc.). Skip
        # the leading spacer above the first group so the sidebar starts
        # flush with the launcher chrome.
        last_group = None
        for entry in self._iter_visible_tools():
            grp = entry.get("group", "")
            if grp != last_group:
                self._make_sidebar_group_header(
                    inner, grp, first=(last_group is None))
                last_group = grp
            self._make_sidebar_row(inner, entry)

    def _make_sidebar_row(self, parent, entry):
        """One vertical-layout row in the left sidebar. Mirrors the
        click / hover / right-click behavior of _make_toolstrip_button
        so users get the same interactions in either mode."""
        active = (self._current_key == entry["key"])
        bg = SIDEBAR_ACTIVE if active else SIDEBAR_BG
        row = tk.Frame(parent, bg=bg, cursor="hand2",
                       highlightthickness=0, bd=0)
        row.pack(fill="x", padx=2, pady=1)

        icon = tk.Label(row, text=entry["icon"],
                        font=("Segoe UI Emoji", 14),
                        bg=bg, fg=TEXT_DARK,
                        width=2, padx=8, pady=6, anchor="center")
        icon.pack(side="left")
        title = tk.Label(row, text=entry["label"],
                         font=("Segoe UI Variable", 10, "bold"),
                         bg=bg, fg=TEXT_DARK, padx=4, pady=6,
                         anchor="w")
        title.pack(side="left", fill="x", expand=True)

        # Notification badge — same role as in the toolstrip variant.
        # Toolstrip's _tool_badges holds the LAST-CREATED badge for
        # each key; when the launcher swaps between toolstrip/sidebar
        # modes the old badge gets destroyed with its row, so the
        # newer assignment here wins for the current mode.
        badge = tk.Label(row, text="", font=("Segoe UI Variable", 8, "bold"),
                         bg="#A64242", fg="#FFFFFF",
                         padx=5, pady=0, bd=0, relief="flat")
        self._tool_badges[entry["key"]] = badge

        widgets = [row, icon, title]

        def _set_bg(color):
            for w in widgets:
                try: w.config(bg=color)
                except Exception: pass

        def _enter(_e=None):
            if self._current_key == entry["key"]:
                return
            _set_bg(SIDEBAR_HOVER)

        def _leave(_e=None):
            if self._current_key == entry["key"]:
                return
            _set_bg(SIDEBAR_BG)

        def _click(_e=None):
            self._activate_entry(entry)

        def _popout(_e=None):
            try:
                import ems_log
                ems_log.info("launcher", f"popout requested: {entry['key']}")
            except Exception:
                pass
            try:
                paths.spawn_tool(entry["key"])
            except Exception as ex:
                from tkinter import messagebox
                messagebox.showerror(
                    "Couldn't open new window",
                    f"Failed to launch {entry['label']} in a new window:\n\n{ex}",
                    parent=self)
                return "break"
            self._flash_spawn_message(f"{entry['label']} → new window")
            return "break"

        def _show_menu(e):
            menu = tk.Menu(self, tearoff=0)
            menu.add_command(
                label=f"Open '{entry['label']}' in this window",
                command=lambda: self._activate_entry(entry))
            menu.add_command(
                label=f"Open '{entry['label']}' in a new window",
                command=_popout)
            try:
                menu.tk_popup(e.x_root, e.y_root)
            finally:
                menu.grab_release()
            return "break"

        for w in widgets:
            w.bind("<Enter>", _enter)
            w.bind("<Leave>", _leave)
            w.bind("<Button-1>", _click)
            w.bind("<ButtonRelease-3>", _show_menu)
            w.bind("<Button-2>", _popout)
            w.bind("<Shift-Button-1>", _popout)
            w.bind("<Control-Button-1>", _popout)
            attach_tooltip(w, entry.get("desc") or entry["label"])

        # Share the same tracking dict so _set_active_row works
        # uniformly across modes — same key shape (row_frame, widgets).
        self._sidebar_rows[entry["key"]] = (row, widgets)

    def _make_sidebar_group_header(self, parent, label, *, first=False):
        """Tiny uppercase label between sidebar groups. Non-interactive
        — purely a visual cue. `first=True` skips the spacer above so
        the first group doesn't have an awkward gap at the top of the
        sidebar."""
        if not first:
            tk.Frame(parent, bg=SIDEBAR_BG, height=8).pack(fill="x")
        # NOTE: pad tuples must go on .pack() / .grid(), NOT on the
        # widget constructor — Tk treats constructor pady/padx as scalar
        # screen distances and chokes on tuples with "bad screen distance".
        tk.Label(parent, text=label,
                 font=("Segoe UI Variable", 7, "bold"),
                 bg=SIDEBAR_BG, fg=TEXT_GRAY,
                 anchor="w", padx=10
                 ).pack(fill="x", pady=(2, 1))

    def _make_toolstrip_group_separator(self, parent):
        """1px vertical line between tool groups in the top strip.
        Substitute for the sidebar's group headers — labels don't fit
        in the cramped horizontal layout, but a thin divider still
        cues the lifecycle grouping at a glance."""
        tk.Frame(parent, bg=BORDER, width=1
                 ).pack(side="left", fill="y", padx=6, pady=10)

    # ── Responsive nav switcher ─────────────────────────────────────────────
    def _apply_responsive_nav(self, width=None):
        """Pick top-strip vs left-sidebar based on the launcher's
        current width. Tears down the old nav widget and rebuilds in
        the new mode. Panels in `self._panels` are unaffected — only
        the nav widget swaps."""
        if width is None or width <= 1:
            width = self.winfo_width()
        if width <= 1:
            # winfo_width returns 1 before the window is mapped; fall
            # back to the geometry string so first paint picks a real
            # mode instead of always starting in top mode.
            try:
                geo = self.geometry()
                width = int(geo.split("+")[0].split("x")[0])
            except (ValueError, IndexError):
                width = 1180
        want = "side" if width >= RESPONSIVE_NAV_THRESHOLD else "top"
        if want == self._nav_mode and self._nav_frame is not None:
            return
        # Tear down current nav widget + clear the row tracking dict —
        # _make_*_button will repopulate on the rebuild.
        if self._nav_frame is not None:
            try: self._nav_frame.destroy()
            except tk.TclError: pass
            self._nav_frame = None
        self._sidebar_rows.clear()
        if hasattr(self, "_toolstrip_buttons"):
            self._toolstrip_buttons = []
        # Unpack the content so the nav can claim its slot on the
        # correct side (top for narrow, left for wide).
        try:
            self._content.pack_forget()
        except tk.TclError:
            pass
        if want == "side":
            self._build_left_sidebar(parent=self)
            self._content.pack(side="right", fill="both", expand=True)
        else:
            self._build_top_toolstrip(parent=self)
            self._content.pack(side="top", fill="both", expand=True)
        self._nav_mode = want
        # Reassert the active-row highlight after the rebuild — the
        # newly-created rows don't know which tool is current.
        if self._current_key:
            try: self._set_active_row(self._current_key)
            except Exception: pass

    def _on_root_configure(self, event):
        """Debounced resize handler — swap nav modes when the launcher
        crosses the responsive threshold. Ignores child <Configure>
        events (those bubble up from anywhere in the widget tree)."""
        if event.widget is not self:
            return
        if self._nav_resize_after is not None:
            try: self.after_cancel(self._nav_resize_after)
            except Exception: pass
        # 200ms debounce — drag-resize fires Configure ~per-pixel, no
        # need to swap layout that fast.
        self._nav_resize_after = self.after(
            200, lambda w=event.width:
                self._apply_responsive_nav(width=w))

    # ── Notification badges ────────────────────────────────────────────────
    _BADGE_REFRESH_MS = 30_000  # 30s — cheap persistence read, no API calls

    _BADGE_SOURCES = (
        # (tool_key, persistence_key) — only include keys that match
        # an actual NAV_TOOLS entry. The IUQ count is also published
        # to `initial_upload_visible_count` but isn't badged here
        # because the IUQ lives as a tab inside Run Audit and a
        # badge on "Audit" would conflate IUQ with Daily Run audit
        # / Backlog / SP Recent counts.
        ("hygiene",         "hygiene_action_needed_count"),
        ("dispute_tracker", "dispute_tracker_open_count"),
    )

    def _read_tool_counts(self) -> dict:
        """Return {tool_key: int} for tools that publish a live count
        to persistence. Each entry is populated by its own panel after
        scan / refresh; extend `_BADGE_SOURCES` to wire a new badge.
        """
        out: dict = {}
        try:
            import persistence as _per
            for tool_key, per_key in self._BADGE_SOURCES:
                n = _per.get(per_key)
                if isinstance(n, int) and n >= 0:
                    out[tool_key] = n
        except Exception:
            pass
        return out

    def _refresh_tool_badges(self):
        """Sync every nav button's badge to the latest persistence
        counts. Re-arms itself every _BADGE_REFRESH_MS so a count
        change written by the Hygiene scan thread propagates without
        the user having to switch tabs."""
        counts = self._read_tool_counts()
        for key, badge in list(self._tool_badges.items()):
            try:
                if not badge.winfo_exists():
                    self._tool_badges.pop(key, None)
                    continue
            except tk.TclError:
                self._tool_badges.pop(key, None)
                continue
            n = counts.get(key, 0)
            try:
                if n and n > 0:
                    badge.configure(text=str(n) if n < 100 else "99+")
                    if not badge.winfo_ismapped():
                        badge.pack(side="right", padx=(0, 6))
                else:
                    if badge.winfo_ismapped():
                        badge.pack_forget()
            except tk.TclError:
                pass
        # Re-arm
        try:
            if self._badge_refresh_after is not None:
                self.after_cancel(self._badge_refresh_after)
        except tk.TclError:
            pass
        try:
            self._badge_refresh_after = self.after(
                self._BADGE_REFRESH_MS, self._refresh_tool_badges)
        except tk.TclError:
            self._badge_refresh_after = None

    # ── Activation routing ──────────────────────────────────────────────────
    def _activate_entry(self, entry):
        if entry["mode"] == "embed":
            self._show_panel(entry["key"])
        elif entry["mode"] == "spawn":
            paths.spawn_tool(entry["key"])
            self._flash_spawn_message(entry["label"])
        elif entry["mode"] == "dialog":
            # Modal dialogs (Settings) — invoked directly, no panel swap.
            if entry["key"] == "settings":
                self._open_settings()

    def _flash_spawn_message(self, label):
        # Brief inline toast in the content area so users see something happen
        toast = tk.Label(self._content, text=f"Opening {label}…",
                         font=("Segoe UI Variable", 10), bg=BG, fg=TEXT_GRAY)
        toast.place(relx=0.5, rely=0.92, anchor="s")
        self.after(1800, toast.destroy)

    # ── Panel show/hide ─────────────────────────────────────────────────────
    def _clear_content(self):
        # Hide the active panel, but keep it instantiated for fast re-show.
        # Panels live in `_content` via place(relwidth=1, relheight=1) so a
        # swap is just place_forget + place/lift on the new one — no empty
        # gap between hide and show, no pack-driven re-layout flash.
        if self._current_key and self._current_key in self._panels:
            try:
                self._panels[self._current_key].on_hide()
            except Exception as ex:
                _log_swallowed("launcher",
                    f"on_hide failed for {self._current_key}: {ex}")
            try:
                self._panels[self._current_key].place_forget()
            except Exception as ex:
                _log_swallowed("launcher",
                    f"place_forget failed for {self._current_key}: {ex}")
        # Remove any non-panel widgets in content (welcome screen, toasts)
        for child in self._content.winfo_children():
            if child not in self._panels.values():
                try:
                    child.destroy()
                except Exception:
                    pass

    def show_tool(self, key, cli_args=()):
        """Public entry point used by panels via self.host.show_tool(key)."""
        self._show_panel(key, cli_args=cli_args)

    def _show_panel(self, key, cli_args=(), _from_back=False):
        entry = next((e for e in NAV_TOOLS if e["key"] == key), None)
        if entry is None or entry["mode"] != "embed":
            return

        # If we're already on this panel, just update args if any
        if self._current_key == key and key in self._panels:
            self._maybe_apply_cli_args(self._panels[key], cli_args)
            return

        # Honor on_hide veto from current panel
        if self._current_key and self._current_key in self._panels:
            try:
                if self._panels[self._current_key].on_hide() is False:
                    return
            except Exception as ex:
                _log_swallowed("launcher",
                    f"on_hide veto check failed for {self._current_key}: {ex}")

        # Push the panel we're leaving onto history (unless we GOT here via
        # _go_back, in which case we're popping not pushing).
        if not _from_back and self._current_key is not None:
            self._history.append((self._current_key, ()))
            # Cap history depth so we don't grow unbounded
            if len(self._history) > 32:
                self._history = self._history[-32:]

        # Switch the toolstrip highlight + title BEFORE constructing the
        # panel, then force a paint. This is the cheapest "feels fast"
        # trick — the click is acknowledged in <16ms even when the panel
        # itself takes 100-300ms to instantiate. Without this the user
        # sees a frozen UI between click and first paint of the panel.
        self._title_var.set(entry["label"])
        self._set_active_row(key)
        self.update_idletasks()

        # Hide everything in content
        self._clear_content()

        # Cached panel may have been destroyed by its own Close button
        # (snapshot's red Close on the audit step does `self.destroy()`).
        # In that case the dict entry still points to a dead widget —
        # `panel.place(...)` would raise "bad window path name". Detect
        # via winfo_exists and rebuild as if we'd never seen it.
        cached = self._panels.get(key)
        if cached is not None:
            try:
                alive = bool(cached.winfo_exists())
            except Exception:
                alive = False
            if not alive:
                self._panels.pop(key, None)

        # Lazy-instantiate target — show a spinner during the slow first load
        if key not in self._panels:
            overlay = LoadingOverlay(self._content,
                                     message=f"Loading {entry['label']}…")
            overlay.pack(fill="both", expand=True)
            overlay.start()
            # Force the spinner to paint before we kick off the slow synchronous
            # __init__ (the import + audit_jobs + parse_run_doc etc.).
            self.update_idletasks()
            try:
                mod = __import__(entry["module"])
                cls = getattr(mod, entry["class"])
                panel = cls(self._content)
                panel.host = self
                panel._title_var = self._title_var
                self._panels[key] = panel
            finally:
                overlay.stop()
                try: overlay.destroy()
                except Exception: pass

        panel = self._panels[key]
        self._maybe_apply_cli_args(panel, cli_args)
        panel.place(x=0, y=0, relwidth=1, relheight=1)
        panel.lift()
        try:
            panel.on_show()
        except Exception as ex:
            _log_swallowed("launcher", f"on_show failed for {key}: {ex}")

        self._current_key = key
        # Title + active row already pushed up front for instant
        # acknowledgment; just refresh the back button now that history
        # has settled.
        self._refresh_back_btn()

    def _go_back(self):
        if not self._history:
            return
        prev_key, prev_args = self._history.pop()
        self._show_panel(prev_key, cli_args=prev_args, _from_back=True)

    def _refresh_back_btn(self):
        if self._back_btn is None:
            return
        enabled = bool(self._history)
        if _HAVE_CTK:
            try:
                self._back_btn.configure(
                    text_color=WHITE if enabled else "#7DCBA0",
                    cursor="hand2" if enabled else "arrow",
                    state="normal" if enabled else "disabled")
            except Exception:
                pass
        else:
            self._back_btn.config(
                fg=WHITE if enabled else "#7DCBA0",
                cursor="hand2" if enabled else "arrow",
                state="normal" if enabled else "disabled")

    def _maybe_apply_cli_args(self, panel, cli_args):
        """Forward CLI-style args to a panel that knows how to consume them
        (mirrors the legacy sys.argv-based doc-path passing)."""
        if not cli_args:
            return
        if hasattr(panel, "consume_cli_args"):
            try:
                panel.consume_cli_args(cli_args)
            except Exception as ex:
                _log_swallowed("launcher",
                    f"consume_cli_args failed on {type(panel).__name__}: {ex}")

    def _show_welcome(self):
        self._clear_content()
        self._current_key = None
        self._history.clear()
        self._set_active_row(None)
        self._title_var.set("Linguar Hub")
        self._refresh_back_btn()

        if _HAVE_CTK:
            wrap = ctk.CTkFrame(self._content, fg_color=BG, corner_radius=0)
            wrap.place(relx=0.5, rely=0.5, anchor="center")
            ctk.CTkLabel(wrap, text="SERVPRO  ·  Linguar Hub",
                         font=ctk.CTkFont("Segoe UI Variable", 22, "bold"),
                         text_color=TEXT_DARK).pack()
            ctk.CTkLabel(wrap, text="Pick a tool from the toolbar to get started.",
                         font=ctk.CTkFont("Segoe UI Variable", 11),
                         text_color=TEXT_GRAY).pack(pady=(6, 4))
            ctk.CTkLabel(wrap,
                         text="↗ = opens in its own window  ·  no arrow = opens here",
                         font=ctk.CTkFont("Segoe UI Variable", 9),
                         text_color=TEXT_GRAY).pack(pady=(0, 18))
            # Subtle preload progress — fades out when preload finishes so
            # the user sees that the app is working even before they click.
            self._welcome_loading = ctk.CTkLabel(
                wrap, text="• preparing tools …",
                font=ctk.CTkFont("Segoe UI Variable", 9),
                text_color="#9AA5AE")
            self._welcome_loading.pack()
        else:
            wrap = tk.Frame(self._content, bg=BG)
            wrap.place(relx=0.5, rely=0.5, anchor="center")
            tk.Label(wrap, text="SERVPRO  ·  Linguar Hub",
                     font=("Segoe UI Variable", 18, "bold"),
                     bg=BG, fg=TEXT_DARK).pack()
            tk.Label(wrap, text="Pick a tool from the toolbar to get started.",
                     font=("Segoe UI Variable", 10), bg=BG, fg=TEXT_GRAY).pack(pady=(6, 18))
            tk.Label(wrap, text="↗ = opens in its own window  ·  no arrow = opens here",
                     font=("Segoe UI Variable", 8), bg=BG, fg=TEXT_GRAY).pack()

    # ── Two-phase panel build ──────────────────────────────────────────────
    #
    # Keys to background-warm AFTER the landing panel renders. Picked
    # because these are the ones the user actually opens most often on a
    # given day — landing on APA Monitor (LANDING_KEY), then audit /
    # hygiene are the next clicks ~80% of the time. Everything else stays
    # lazy: builds on first click with a per-panel LoadingOverlay.
    #
    # Add a key here when log-analysis shows another panel deserves it.
    _BACKGROUND_WARM_KEYS = ("run_audit", "hygiene")

    def _first_paint_landing(self):
        """Phase 1 — build + activate the landing panel (LANDING_KEY),
        tear down the startup overlay. Runs once shortly after the
        launcher window paints.

        Used to be: build all 14 panels, THEN show the landing panel.
        That produced a ~10s splash that occasionally crossed Windows'
        Not-Responding threshold. Now: only the landing panel blocks
        startup; everything else is either background-warmed (see
        `_background_warm_top_panels`) or lazy on first click."""
        if not hasattr(self, "_preload_failed"):
            self._preload_failed = set()
        # Move on if the landing panel already loaded (e.g. on_show fired
        # something that built it). Idempotent.
        if LANDING_KEY in self._panels:
            self._finish_startup_overlay()
            return
        entry = next(
            (e for e in NAV_TOOLS if e.get("key") == LANDING_KEY), None)
        if entry is None:
            # Landing entry missing from NAV_TOOLS — finish the overlay
            # anyway so the launcher isn't permanently covered. User
            # lands on the welcome screen.
            self._finish_startup_overlay()
            return
        overlay = getattr(self, "_startup_overlay", None)
        if overlay is not None:
            try:
                overlay.set_message(f"Opening {entry.get('label', '')}…")
                overlay.set_progress("")
            except Exception:
                pass
        try:
            mod = __import__(entry["module"])
            cls = getattr(mod, entry["class"])
            panel = cls(self._content)
            panel.host = self
            panel._title_var = self._title_var
            self._panels[LANDING_KEY] = panel
        except Exception as ex:
            self._preload_failed.add(LANDING_KEY)
            try:
                import ems_log
                ems_log.error("preload", f"{LANDING_KEY}: {ex}")
            except Exception:
                pass
            # Fall through to overlay teardown — Welcome screen is the
            # fallback when the landing panel can't construct.
        self._finish_startup_overlay()

    def _background_warm_top_panels(self):
        """Phase 2 — quietly instantiate the top-N most-used panels so
        first-click on those tools is instant. Runs ~3s after launch
        (after the landing panel renders + the user has had a chance to start
        interacting). No overlay, no status-bar message — purely
        opportunistic warming.

        Spaced one panel per 250ms so the main thread stays
        responsive between widget constructions. Lower priority than
        the user's actual clicks: if they navigate to a panel while
        this is running, the navigation runs to completion first
        (Tk's event ordering naturally handles this).
        """
        if not hasattr(self, "_preload_failed"):
            self._preload_failed = set()
        # Pending keys = warm targets not already in cache and not
        # known-failed. Idempotent — safe to call repeatedly.
        pending = [k for k in self._BACKGROUND_WARM_KEYS
                   if k not in self._panels
                   and k not in self._preload_failed]
        if not pending:
            # Warm complete — flash a quiet confirmation, then drop
            # the run-date status into its normal place. The status
            # bar auto-hides 60s later (see existing _hide_status_bar).
            try:
                total = len(self._BACKGROUND_WARM_KEYS) + 1  # +landing
                loaded = sum(1 for k in
                             (LANDING_KEY, *self._BACKGROUND_WARM_KEYS)
                             if k in self._panels)
                self._status_run_lbl.configure(
                    text=f"✓ Ready ({loaded}/{total} warmed)")
            except tk.TclError:
                pass
            self.after(3000, self._refresh_status)
            self.after(60000, self._hide_status_bar)
            return
        key = pending[0]
        entry = next(
            (e for e in NAV_TOOLS if e.get("key") == key), None)
        if entry is None:
            # Stale key in _BACKGROUND_WARM_KEYS — entry was removed
            # from NAV_TOOLS. Skip silently; don't keep retrying.
            self._preload_failed.add(key)
        else:
            try:
                # Quiet status hint so the user can see warming is
                # happening if they glance at the bar — no overlay,
                # no modal blocker.
                self._status_run_lbl.configure(
                    text=f"Warming {entry.get('label', key)}…")
            except tk.TclError:
                pass
            try:
                mod = __import__(entry["module"])
                cls = getattr(mod, entry["class"])
                panel = cls(self._content)
                panel.host = self
                panel._title_var = self._title_var
                self._panels[key] = panel
            except Exception as ex:
                self._preload_failed.add(key)
                try:
                    import ems_log
                    ems_log.error("preload", f"{key}: {ex}")
                except Exception:
                    pass
        # Larger gap than the old eager preload (60ms → 250ms) — these
        # builds are purely opportunistic, so we'd rather yield more
        # time to user interactions in between.
        self.after(250, self._background_warm_top_panels)

    def _finish_startup_overlay(self):
        """Tear down the loading splash and activate the landing panel.
        Called from `_first_paint_landing` once the landing panel has
        been constructed (cached in `self._panels[LANDING_KEY]`).

        Landing activation is deferred to here so the user sees one
        clean loading screen, then the landing panel renders against the
        already-cached panel. The full 14-panel preload sweep was
        retired (2026-05-19) — top panels warm in the background after
        the landing panel renders (see `_background_warm_top_panels`);
        everything else stays lazy with its own per-click overlay."""
        overlay = getattr(self, "_startup_overlay", None)
        if overlay is not None:
            try:
                overlay.stop()
            except Exception:
                pass
            try:
                overlay.pack_forget()
            except tk.TclError:
                pass
            try:
                overlay.destroy()
            except tk.TclError:
                pass
            self._startup_overlay = None
        if not getattr(self, "_landing_pending", False):
            return
        self._landing_pending = False
        try:
            entry = next(
                (e for e in NAV_TOOLS
                 if e.get("key") == LANDING_KEY), None)
            if entry is not None:
                self._activate_entry(entry)
                return
        except Exception:
            pass
        try:
            self._show_welcome()
        except Exception:
            pass

    # ── Status bar refresh ──────────────────────────────────────────────────
    def _set_status_err(self, text, color):
        """Set status-bar error label text + color, working with either
        tk.Label (fg=) or ctk.CTkLabel (text_color=)."""
        if _HAVE_CTK:
            try:
                self._status_err_lbl.configure(text=text, text_color=color)
                return
            except Exception:
                pass
        try:
            self._status_err_lbl.config(text=text, fg=color)
        except Exception:
            pass

    def _hide_status_bar(self):
        """Remove the bottom status bar so it stops eating screen space.
        Triggered 60s after preload completes. Idempotent — safe to
        call when the bar's already hidden."""
        try:
            self._status_bar.pack_forget()
        except (tk.TclError, AttributeError):
            pass
        # Stop the periodic _refresh_status reschedule from doing work
        # against a hidden widget. Errors still land in ems.log.
        self._status_hidden = True

    def _refresh_status(self):
        # Skip when the bar's been auto-hidden — configure() against a
        # pack_forget'd widget is harmless, but the os.listdir of the
        # runs_dir + ems_log scan is wasted work every minute.
        if getattr(self, "_status_hidden", False):
            return
        # Run date — pull from latest run doc via the cache
        try:
            import config as _cfg
            cfg = _cfg.load()
            runs_dir = cfg.get("runs_dir", "")
            latest = None
            if runs_dir and os.path.isdir(runs_dir):
                files = [
                    (os.path.getmtime(os.path.join(runs_dir, f)),
                     os.path.join(runs_dir, f))
                    for f in os.listdir(runs_dir)
                    if f.lower().endswith(".docx") and not f.startswith("~$")
                ]
                if files:
                    files.sort(reverse=True)
                    latest = files[0][1]
            if latest:
                _, run_date = _state_hub.parse_run_doc(latest)
                if run_date:
                    from datetime import datetime as _dt
                    try:
                        d = _dt.strptime(run_date, "%m-%d-%Y")
                        self._status_run_lbl.configure(
                            text=f"Run: {d.strftime('%a %m/%d/%y')}")
                    except ValueError:
                        self._status_run_lbl.configure(text=f"Run: {run_date}")
        except Exception as ex:
            _log_swallowed("launcher", f"run-date status refresh failed: {ex}")

        # Error count from ems.log (last 24h)
        try:
            import ems_log
            errs = ems_log.recent_errors(within_hours=24, max_lines=200)
            n = len(errs)
            if n:
                self._set_status_err(
                    f"⚠ {n} log entr{'y' if n == 1 else 'ies'} · 24h",
                    "#A6772A")
            else:
                self._set_status_err("✓ no errors · 24h", "#2C8C4D")
        except Exception:
            pass

        # Reschedule
        self.after(60000, self._refresh_status)

    # ── Settings + first-run ────────────────────────────────────────────────
    def _open_settings(self):
        import settings_gui
        settings_gui.open_settings(
            parent=self, first_run=False,
            on_save=self._on_settings_saved)

    def _on_settings_saved(self, new_cfg):
        """Hook fired after the user clicks Save in Settings. Used to
        live-apply the appearance choice across already-open tool panels
        (settings_gui itself already called theme.set_mode + the ttk
        restyle; this hook handles the launcher chrome + cached panels
        that were built before the swap)."""
        # Re-paint the launcher's own chrome with the new palette so the
        # sidebar / top strip / status bar pick up the swap without a
        # restart. The constants come from the `theme` module which
        # was already swapped by SettingsDialog._save.
        try:
            from theme import BG as _BG, WHITE as _WHITE, TEXT_DARK as _TXT
            self.configure(bg=_BG)
            # Rebuild status bar bg — direct attribute on the bar.
            for attr in ("_status_bar", "_sidebar", "_topstrip"):
                w = getattr(self, attr, None)
                if w is not None:
                    try:
                        w.configure(bg=_WHITE if attr == "_status_bar"
                                     else _BG)
                    except Exception:
                        pass
        except Exception:
            pass
        # Drop cached tool panels so they get rebuilt fresh against the
        # new palette next time the user clicks their tab. We can't
        # walk the live widget tree of every panel and re-bg= them
        # safely (each panel hardcoded bg=WHITE etc at build time);
        # tearing them down here means the user gets a clean repaint
        # on next visit rather than a half-themed Frankenstein.
        panels = getattr(self, "_panels", None)
        if isinstance(panels, dict):
            for key, panel in list(panels.items()):
                try:
                    panel.destroy()
                except Exception:
                    pass
            panels.clear()

    def _maybe_show_first_run(self):
        if not paths.is_first_run():
            return
        import settings_gui
        settings_gui.open_settings(parent=self, first_run=True)

    # ── Close ───────────────────────────────────────────────────────────────
    def _on_close(self):
        # Save the launcher's window size/position so we reopen at the
        # same place. Skip if minimized/zoomed since geometry() can return
        # an off-screen iconic position.
        try:
            import persistence as _persistence
            if self.state() == "normal":
                _persistence.set_geometry("launcher", self.geometry())
        except Exception as ex:
            _log_swallowed("launcher", f"geometry save failed: {ex}")
        # Fire on_close on all instantiated panels
        for key, panel in self._panels.items():
            try:
                panel.on_close()
            except Exception as ex:
                _log_swallowed("launcher", f"on_close failed for {key}: {ex}")
        self.destroy()


if __name__ == "__main__":
    # New default: web home replaces the Tk launcher. Pass `--tk`
    # (or run via `--tool launcher`) to bring up the legacy chrome.
    # The --tool dispatcher above already handled the launcher-key
    # case; this branch runs when no --tool was specified.
    if "--tk" in sys.argv or "--legacy" in sys.argv:
        LauncherApp().mainloop()
    else:
        import home_web
        home_web.main()
