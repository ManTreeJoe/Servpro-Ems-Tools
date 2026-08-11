import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
import os
import re
import threading
import zipfile
import webbrowser
import audit_export

import ctk_helpers as ctkh
import paths
import config
import persistence
from job_widgets import CommercialToggle
from tool_panel import (ToolPanel, run_standalone,
                         ResponsiveActionBar, ScrollableFrame,
                         ResponsiveSnap, attach_tooltip)
from ui_buttons import (done_button, secondary_button, danger_button,
                          warn_button, send_button, icon_button)

# Job-folder + run-doc roots. Resolved lazily from config each access so a
# Settings change or department (OC/IE) switch is reflected without a
# restart — this module is imported at process start by photo_folders_web,
# so a frozen value here would cross-wire OC/IE. `daily_photos_gui.RUNS_DIR`
# / `.AUDIT_BASE` still work via the module __getattr__ below.
def _runs_dir():
    return config.load().get("runs_dir") or ""




def __getattr__(name):
    # PHOTOS_ROOT delegates to sharepoint (single lazy source); RUNS_DIR /
    # AUDIT_BASE resolve fresh from config.
    if name == "PHOTOS_ROOT":
        return sharepoint._photos_root()
    if name == "RUNS_DIR":
        return _runs_dir()
    if name == "AUDIT_BASE":
        return _audit_base()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# SharePoint helpers live in `sharepoint.py` now. Import the module (for the
# lazy `sharepoint.PHOTOS_ROOT`) plus the pure helpers this file calls.
import sharepoint
# The pure folder-resolution helpers live in daily_photos_logic now,
# so photo_folders_web can use them without importing this Tk module.
# Imported back rather than duplicated: two copies of an extracted
# function is how the multi_unit extraction went wrong.
from daily_photos_logic import (  # noqa: F401
    _client_match_tokens, _photo_folder_path,
    _resolve_tech_root_folder, make_folders,
    _client_from_sp_name, _audit_base, _find_od_folder_for_client,
)
from sharepoint import (
    _IMAGE_EXTS, _long_path, _file_fingerprint, _date_variants,
    _build_sp_match, find_sharepoint_folders_for_client,
    list_image_names_in_tree, list_image_fingerprints_in_tree,
    list_image_sizes_in_tree,
)

# UNIT_RE matches "unit/apt/suite #" in run-doc lines — local because only
# the run-doc parser uses it. DOCUSKETCH_RE lives in audit_logic since all
# three GUIs (this, run_audit, snapshot) import the same pattern.
UNIT_RE   = re.compile(r'(?:unit|apt\.?|suite|#)\s*#?\s*(\w+)', re.IGNORECASE)
DOWNLOADS = os.path.join(os.environ["USERPROFILE"], "Downloads")

# Form/commercial helpers — single source of truth in audit_logic, used
# here by the per-job flagged-items renderer (the "Comm." cascade).
from audit_logic import is_commercial_form as _is_commercial_form
from audit_logic import audit_jobs as _audit_jobs_core
from audit_logic import DOCUSKETCH_RE


def audit_jobs(client_names, year=None):
    """Thin wrapper around `audit_logic.audit_jobs` that supplies AUDIT_BASE."""
    return _audit_jobs_core(client_names, _audit_base(), year=year)

from theme import (GREEN, GREEN_DARK, WHITE, BG, TEXT_DARK, TEXT_GRAY,
                    TEXT_MUTED, BORDER, FLAG_RED, SURFACE_2,
                    NEUTRAL_HOVER,
                    SUCCESS_BG, SUCCESS_FG, SUCCESS_HOVER,
                    INFO_BG, INFO_FG, INFO_HOVER,
                    LINK_FG,
                    WARN_BG, WARN_FG, WARN_HOVER,
                    DANGER_BG, DANGER_FG, ON_ACCENT)

from audit_logic import (
    TECH_PATTERN, ABBREV, TECH_INITIALS_REVERSE as _TECH_INITIALS,
    para_is_struck, find_docs_dir,
)


# Activity detection moved to audit_logic so the run-audit photo checker
# and the daily-photos folder-creation flow can never drift apart on
# which stages map to which folders. Re-exported here for backward
# compat with `from daily_photos_gui import detect_activity` callers
# (notably tests/test_detect_activity.py).
from audit_logic import detect_activity, _ACTIVITY_PATTERNS  # noqa: F401


def _open_folder(path):
    """Open a folder in Windows Explorer; silently no-op if it can't be opened."""
    try:
        if path and os.path.isdir(path):
            os.startfile(path)
    except OSError:
        pass


# Date pattern in SP folder names like "5-3-26 Smith" or "FB 5/3/26 Smith".
# Anchored against M/D + optional separator + Y so we don't false-match a
# unit number embedded in a client name.
_SP_DATE_RE = re.compile(r'\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}')










def _photo_folder_exists(tech, run_date, client):
    """
    Check if a photo folder exists for this tech+date+client.
    Returns True = found, False = not found, None = PHOTOS_ROOT unreachable.
    """
    if not os.path.isdir(sharepoint.PHOTOS_ROOT):
        return None
    return _photo_folder_path(tech, run_date, client) is not None


# Per-card photo-folder freshness check. The `✓` badge in the daily-photos
# panel previously meant "folder exists" — but a created-but-empty or
# created-three-days-ago folder is still a problem. _photo_folder_health
# returns a small status dict so the UI can show "✓ 12·2h" (good),
# "⚠ empty" (created, no photos), or "⚠ stale" (has photos but nothing
# new in the last 24h). A tech who creates the folder but never uploads
# slips through silently otherwise.
import time as _time
_FRESH_MAX_AGE_HOURS = 24


def _photo_folder_health(path):
    """Inspect a daily-photo folder. Returns:
      {"status": "ok" | "empty" | "stale" | "missing",
       "count": int, "newest_mtime": float | None, "age_hours": float | None}
    `status` is "missing" when the path doesn't exist, "empty" when the
    folder has no image files (one level deep), "stale" when the newest
    image is older than _FRESH_MAX_AGE_HOURS, "ok" otherwise.
    Only image extensions count — random PDFs left in the folder don't
    rescue an otherwise-empty photo upload.
    """
    if not path or not os.path.isdir(path):
        return {"status": "missing", "count": 0,
                "newest_mtime": None, "age_hours": None}
    count = 0
    newest = 0.0

    def _consider(file_path):
        nonlocal count, newest
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in _IMAGE_EXTS:
            return
        count += 1
        try:
            mt = os.path.getmtime(file_path)
        except OSError:
            return
        if mt > newest:
            newest = mt

    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.is_file():
                        _consider(e.path)
                    elif e.is_dir():
                        # Same one-level-deep walk as count_images_in_folder
                        # so a tech subfolder is still counted.
                        try:
                            with os.scandir(e.path) as it2:
                                for e2 in it2:
                                    if e2.is_file():
                                        _consider(e2.path)
                        except OSError:
                            pass
                except OSError:
                    continue
    except OSError:
        return {"status": "missing", "count": 0,
                "newest_mtime": None, "age_hours": None}

    if count == 0:
        return {"status": "empty", "count": 0,
                "newest_mtime": None, "age_hours": None}
    age_hours = (_time.time() - newest) / 3600 if newest else None
    if age_hours is not None and age_hours > _FRESH_MAX_AGE_HOURS:
        status = "stale"
    else:
        status = "ok"
    return {"status": status, "count": count,
            "newest_mtime": newest, "age_hours": age_hours}


def _format_age(hours):
    """Compact age formatter for the per-card badge: "2h", "1d", "5d"."""
    if hours is None:
        return ""
    if hours < 1:
        return f"{int(hours * 60)}m"
    if hours < 48:
        return f"{int(hours)}h"
    return f"{int(hours / 24)}d"


def count_images_in_folder(path):
    """Count image/video files inside `path` (one level deep). Used by
    run_audit_gui to surface a "📷 N photos" download link per job."""
    if not path or not os.path.isdir(path):
        return 0
    n = 0
    try:
        with os.scandir(path) as it:
            for e in it:
                if e.is_file():
                    ext = os.path.splitext(e.name)[1].lower()
                    if ext in _IMAGE_EXTS:
                        n += 1
                elif e.is_dir():
                    # One level of nested folders (e.g. tech sub-folders) —
                    # don't recurse forever, but pull one level deep so a
                    # parent containing only sub-folders still reports.
                    try:
                        with os.scandir(e.path) as it2:
                            for sub in it2:
                                if sub.is_file():
                                    if (os.path.splitext(sub.name)[1].lower()
                                            in _IMAGE_EXTS):
                                        n += 1
                    except OSError:
                        pass
    except OSError:
        return 0
    return n


def find_photo_folder_for_job(techs, run_date, client):
    """Return (path, count) for the first tech with photos for this job —
    or (None, 0) if nobody has photos. Network-walk: callers should run
    this off the main thread."""
    if not os.path.isdir(sharepoint.PHOTOS_ROOT) or not techs:
        return (None, 0)
    for t in techs:
        try:
            p = _photo_folder_path(t, run_date, client)
        except Exception:
            p = None
        if p:
            n = count_images_in_folder(p)
            if n > 0:
                return (p, n)
    return (None, 0)






# ── GUI ──────────────────────────────────────────────────────────────────────

class App(ToolPanel):
    TOOL_TITLE = "Daily Photo Folders"
    TOOL_AUMID = "Servpro.EMS.DailyPhotos"

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Daily Photo Folders")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.geometry("560x520")
        ico = paths.resource("wrench.ico")
        if os.path.exists(ico):
            try:
                img = Image.open(ico)
                photo = ImageTk.PhotoImage(img)
                self.iconphoto(True, photo)
                self._icon = photo
            except Exception:
                pass

        self.doc_path          = tk.StringVar()
        self.run_date          = ""
        self.jobs              = []
        self.job_data          = []
        self._last_audit_results = None
        self._pending_populate = False
        self._folder_map       = {}   # {(tech, client): path_or_None}

        self._build_ui()
        self._restore_last_doc()

    def on_show(self):
        # If a load completed while this panel was hidden, render now.
        if self._pending_populate:
            self._pending_populate = False
            self.date_label.configure(text=f"Run date: {self.run_date}")
            self.show_loading("Rendering jobs…")
            self._populate_jobs()

    def _restore_last_doc(self):
        # Prefer a doc passed on the command line (e.g. from the launcher)
        import sys as _sys
        last = None
        for arg in _sys.argv[1:]:
            if arg and os.path.isfile(arg):
                last = arg
                break
        if not last:
            last = persistence.get("daily_photos_last_doc")
        self._load_doc(last)

    def _load_doc(self, path):
        if not path or not os.path.isfile(path):
            return
        self.doc_path.set(path)
        self.show_loading(f"Reading {os.path.basename(path)}…")

        def _bg():
            try:
                # Cached parse — state_hub keys by (path, mtime) so
                # if Run Audit already parsed the same .docx today, this
                # returns instantly. Single source of parse_run_doc lives
                # in run_audit_gui.
                from state_hub import hub as _hub
                jobs, run_date = _hub.parse_run_doc(path)
                err = None
            except Exception as ex:
                jobs, run_date, err = None, None, ex

            # Pre-scan PHOTOS_ROOT for every (tech, client) we'll need to
            # render. Each scan walks 3 levels of network share, so doing it
            # on the main thread froze the UI for several seconds the first
            # time you opened the panel. Now it runs here, and the loading
            # throbber stays animated until the bg thread is done.
            folder_map = {}
            if jobs and run_date:
                try:
                    folder_map = self._scan_folder_map(jobs, run_date)
                except Exception:
                    folder_map = {}

            def _done():
                if err:
                    self.hide_loading()
                    messagebox.showerror("Error reading file", str(err),
                                          parent=self)
                    return
                self.jobs = jobs
                self.run_date = run_date
                self._folder_map = folder_map
                # If the user switched panels while we were parsing, skip
                # the populate. on_show() will run it when we're visible.
                if not self.winfo_ismapped():
                    self._pending_populate = True
                    self.hide_loading()
                else:
                    self.date_label.configure(text=f"Run date: {self.run_date}")
                    # Keep the throbber visible — the populate is chunked and
                    # will hide_loading itself when the last chunk is rendered.
                    self._populate_jobs()
            self.after(0, _done)

        threading.Thread(target=_bg, daemon=True).start()

    def _scan_folder_map(self, jobs, run_date):
        """Return {(tech, client): path_or_None} for every (tech, client) in
        jobs. Call from a background thread — does 3 levels of os.scandir on
        the network share."""
        result = {}
        if not os.path.isdir(sharepoint.PHOTOS_ROOT):
            for job in jobs:
                for tech in job["techs"]:
                    result[(tech, job["client"])] = None
            return result
        for job in jobs:
            client = job["client"]
            for tech in job["techs"]:
                key = (tech, client)
                if key in result:
                    continue
                try:
                    result[key] = _photo_folder_path(tech, run_date, client)
                except Exception:
                    result[key] = None
        return result

    def consume_cli_args(self, cli_args):
        """Called by the launcher when another tool navigates here with a doc path."""
        for arg in cli_args:
            if arg and os.path.isfile(arg):
                if arg != self.doc_path.get():
                    self._load_doc(arg)
                return

    def _build_ui(self):
        self.build_header("SERVPRO  ·  Daily Photo Folders",
                          subtitle="Creates SharePoint photo folders from the daily run",
                          pady=14)

        # File picker — when wide, the date label snaps onto the right
        # side of this row.
        self._fp = tk.Frame(self, bg=BG, padx=20, pady=12)
        self._fp.pack(fill="x")
        self._fp_inner = tk.Frame(self._fp, bg=BG)
        self._fp_inner.pack(side="left", anchor="w")
        ctkh.h2(self._fp_inner, "Daily Run (.docx)").grid(
            row=0, column=0, sticky="w")
        ctkh.entry(self._fp_inner, textvariable=self.doc_path,
                   width=340).grid(row=0, column=1, padx=8)
        ctkh.btn(self._fp_inner, "Browse", command=self._browse,
                 kind="primary", width=80).grid(row=0, column=2)
        # Refresh — re-parses the currently loaded .docx and re-walks
        # the SharePoint folder map. Cached state_hub.parse_run_doc keys
        # by (path, mtime) so an untouched .docx is a no-op; an edited
        # one re-parses fresh. Catches techs adding their folder
        # externally — the green ✓ chip on cards updates afterwards.
        ctkh.btn(self._fp_inner, "🔄 Refresh",
                 command=self._refresh,
                 kind="secondary", width=100
                 ).grid(row=0, column=3, padx=(8, 0))
        # ⏪ / 📅 / ⏭ — icon-only trio mirroring the Run Audit panel
        # so muscle memory carries across. ⏪/⏭ walk relative to the
        # current view; 📅 resets the cursor.
        _back_btn = ctkh.btn(self._fp_inner, "⏪",
                             command=self._load_yesterday_run_doc,
                             kind="ghost", width=44)
        _back_btn.grid(row=0, column=4, padx=(4, 0))
        attach_tooltip(_back_btn, "Walk one day back (skips empty days)")

        _today_btn = ctkh.btn(self._fp_inner, "📅 Today",
                              command=self._load_today_run_doc,
                              kind="ghost", width=90)
        _today_btn.grid(row=0, column=5, padx=(4, 0))
        attach_tooltip(_today_btn, "Reset the cursor and load today's run-doc")

        _fwd_btn = ctkh.btn(self._fp_inner, "⏭",
                            command=self._load_tomorrow_run_doc,
                            kind="ghost", width=44)
        _fwd_btn.grid(row=0, column=6, padx=(4, 0))
        attach_tooltip(_fwd_btn, "Walk one day forward (skips empty days)")

        # Date label — its own narrow-mode row + movable inner.
        # _date_inner's parent is `self` so ResponsiveSnap can re-pack it
        # into the file picker row. See note in run_audit_gui.
        self._date_row = tk.Frame(self, bg=BG)
        self._date_inner = tk.Frame(self, bg=BG)
        self._date_inner.pack(in_=self._date_row, side="left", anchor="w",
                               padx=20)
        self.date_label = ctkh.ctk.CTkLabel(
            self._date_inner, text="", font=ctkh.font(10),
            text_color=TEXT_GRAY, fg_color=BG)
        self.date_label.pack(side="left")
        self._date_row.pack(fill="x")

        ResponsiveSnap(self,
                       inline_parent=self._fp,
                       narrow_parent=self._date_row,
                       movable=self._date_inner,
                       narrow_after=self._fp)

        # Bottom bar — packed BEFORE the scrollable jobs list and anchored
        # to the bottom so action buttons stay visible even when the window
        # is short. Buttons are added below.
        bar = ResponsiveActionBar(self, root_widget=self,
                                  bg=BG, padx=20, pady=10)
        bar.pack(side="bottom", fill="x")

        # Jobs list with scrollbar
        ctkh.h2(self, "Jobs — select which folders to create").pack(
            anchor="w", padx=20, pady=(8, 2))

        scroll = ScrollableFrame(self, bg=BG, canvas_bg=WHITE, padx=20)
        scroll.canvas.config(highlightthickness=1, highlightbackground=BORDER)
        scroll.pack(fill="both", expand=True)
        self.canvas     = scroll.canvas
        self.jobs_inner = scroll.inner
        self._scroll    = scroll
        # Inner frame uses the white canvas background — overrides the
        # ScrollableFrame default of inheriting outer bg.
        self.jobs_inner.config(bg=WHITE)

        self.empty_label = tk.Label(self.jobs_inner,
                                     text="Load a run document to see jobs.",
                                     font=("Segoe UI Variable", 9, "italic"),
                                     bg=WHITE, fg=TEXT_GRAY, pady=20)
        self.empty_label.pack()

        # Bottom bar buttons — bar itself was created/packed earlier so it
        # stays anchored to the bottom on short windows. Just two
        # controls: Select All toggle and Create Photo Folders.
        self.all_var = tk.BooleanVar(value=True)
        select_all = ctkh.ctk.CTkCheckBox(
            bar, text="Select All", variable=self.all_var,
            font=ctkh.font(10), text_color=TEXT_DARK,
            fg_color=GREEN, hover_color=GREEN_DARK,
            border_color=BORDER, corner_radius=4,
            checkbox_height=18, checkbox_width=18,
            command=self._toggle_all)
        bar.add(select_all, group="secondary", side="left", padx=(0, 6))

        # SP recent-photos audit — opens a Toplevel that walks SP
        # folders modified in the last N days (default 7) and surfaces
        # photos that didn't make it into OD. Lives here because Photo
        # Folders is already the "managing the SP-side photo flow"
        # tool; the audit is a manual check the user runs occasionally.
        recent_audit_btn = ctkh.btn(
            bar, "🔍 Audit recent SP",
            command=self._open_sp_recent_audit, kind="secondary",
            width=170, height=36)
        bar.add(recent_audit_btn, group="secondary", side="left", padx=(0, 6))

        # Cleanup empty folders — sweeps every job-level SP folder and
        # surfaces the ones with zero images, so the user can prune
        # leftovers from days the tech didn't end up needing the
        # folder. Recycle-bin delete only — never hard-delete from a
        # button click. Amber/orange fill on purpose — it's a
        # destructive-leaning action so it should stand out from the
        # green Create button without going full red (which we save
        # for "this can't be undone" actions).
        cleanup_btn = ctkh.btn(
            bar, "🗑 Cleanup empty",
            command=self._open_cleanup_empty_dialog, kind="ghost",
            fg_color="#F5A623", hover_color="#D8861A",
            text_color=WHITE, border_width=0,
            width=160, height=36)
        bar.add(cleanup_btn, group="secondary", side="left", padx=(0, 6))

        create_btn = ctkh.btn(bar, "Create Photo Folders",
                              command=self._create, kind="primary",
                              width=210, height=36)
        bar.add(create_btn, group="primary", side="right", padx=(0, 0))

    def _open_sp_recent_audit(self):
        """Open the SharePoint recent-photos audit dialog."""
        try:
            from sp_recent_audit import open_sp_recent_audit
        except Exception as ex:
            messagebox.showerror("Audit unavailable",
                                  f"Couldn't load module:\n{ex}",
                                  parent=self)
            return
        open_sp_recent_audit(self)

    def _open_cleanup_empty_dialog(self):
        """Open the empty-folders cleanup dialog. Walks every tech's
        job-level SP folder, surfaces the ones with no photos, and
        lets the user check off which to send to the recycle bin.

        Background-loaded so the network walk doesn't freeze the UI;
        results stream into the list as they arrive."""
        try:
            self._build_cleanup_empty_dialog()
        except Exception as ex:
            messagebox.showerror("Cleanup unavailable",
                                  f"Couldn't open the cleanup dialog:\n{ex}",
                                  parent=self)

    def _build_cleanup_empty_dialog(self):
        import threading
        import sharepoint as _sp

        dlg = tk.Toplevel(self)
        dlg.title("Cleanup empty photo folders")
        dlg.configure(bg=BG)
        try:
            dlg.geometry("760x620")
            dlg.minsize(620, 460)
        except tk.TclError:
            pass
        dlg.transient(self.winfo_toplevel())

        # ── Header ────────────────────────────────────────────────────
        head = tk.Frame(dlg, bg=BG, padx=14, pady=10)
        head.pack(fill="x")
        tk.Label(head, text="🗑 Cleanup empty photo folders",
                 font=("Segoe UI Variable", 12, "bold"),
                 bg=BG, fg=TEXT_DARK).pack(anchor="w")
        tk.Label(head,
                 text=("Walks every tech's SharePoint job folders and "
                       "lists the ones with zero photos. Filter by age, "
                       "uncheck anything you want to keep, then send "
                       "the rest to the recycle bin (recoverable)."),
                 font=("Segoe UI Variable", 8), bg=BG, fg=TEXT_GRAY,
                 wraplength=720, justify="left",
                 anchor="w").pack(fill="x", pady=(2, 0))

        # ── Filter row ────────────────────────────────────────────────
        ctl = tk.Frame(dlg, bg=BG, padx=14, pady=4)
        ctl.pack(fill="x")
        tk.Label(ctl, text="Older than:",
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=BG, fg=TEXT_DARK).pack(side="left")
        age_var = tk.IntVar(value=7)
        tk.Spinbox(ctl, from_=0, to=365, increment=1,
                    textvariable=age_var, width=4,
                    font=("Segoe UI Variable", 9)).pack(side="left", padx=(6, 2))
        tk.Label(ctl, text="days",
                 font=("Segoe UI Variable", 9), bg=BG, fg=TEXT_GRAY
                 ).pack(side="left")

        tk.Label(ctl, text="    Tech:",
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=BG, fg=TEXT_DARK).pack(side="left")
        tech_var = tk.StringVar(value="All")
        from tkinter import ttk as _ttk
        tech_cb = _ttk.Combobox(ctl, textvariable=tech_var,
                                 values=["All"], state="readonly",
                                 width=18, font=("Segoe UI Variable", 9))
        tech_cb.pack(side="left", padx=(6, 0))

        done_button(ctl, "🔄 Rescan", padx=10, pady=3,
                  command=lambda: _rescan()
                  ).pack(side="right")

        status_lbl = tk.Label(dlg, text="Scanning…",
                               font=("Segoe UI Variable", 8, "italic"),
                               bg=BG, fg=TEXT_GRAY,
                               padx=14, anchor="w")
        status_lbl.pack(fill="x", pady=(0, 4))

        # ── Folder list ──────────────────────────────────────────────
        scroll = ScrollableFrame(dlg, bg=BG, canvas_bg=WHITE)
        scroll.canvas.config(highlightthickness=1, highlightbackground=BORDER)
        scroll.pack(fill="both", expand=True, padx=14, pady=(0, 6))
        list_inner = scroll.inner

        # ── Bottom action bar ─────────────────────────────────────────
        bot = tk.Frame(dlg, bg=BG, padx=14, pady=10)
        bot.pack(fill="x", side="bottom")
        select_all_btn = secondary_button(
            bot, "Select all visible", padx=10, pady=4)
        select_all_btn.pack(side="left")
        select_none_btn = secondary_button(
            bot, "Select none", padx=10, pady=4)
        select_none_btn.pack(side="left", padx=(8, 0))

        sel_lbl = tk.Label(bot, text="0 selected",
                            font=("Segoe UI Variable", 9, "italic"),
                            bg=BG, fg=TEXT_GRAY)
        sel_lbl.pack(side="left", padx=(14, 0))

        delete_btn = danger_button(
            bot, "🗑 Move selected to Recycle Bin", padx=14, pady=4)
        delete_btn.pack(side="right")
        delete_btn.config(state="disabled")
        secondary_button(bot, "Close", padx=10, pady=4,
                          command=dlg.destroy
                  ).pack(side="right", padx=(0, 8))

        # ── State ────────────────────────────────────────────────────
        # `all_rows` holds every empty folder the scan found; the
        # filter/redraw cycle slices visible rows out of it. Each row
        # carries its own BooleanVar so checkbox state survives a
        # filter change (common workflow: apply 30-day filter, uncheck
        # 2-3 to keep, switch to 60-day filter, those 2-3 stay
        # unchecked when they re-appear).
        all_rows = []          # list of dicts (path, name, tech, age_days, var)
        var_by_path = {}       # path → BooleanVar (persists across redraws)
        od_cache = {}          # client → resolved OD folder path (None = miss)

        def _update_sel_count():
            visible = [r for r in all_rows if _passes_filter(r)]
            n_sel = sum(1 for r in visible if r["var"].get())
            sel_lbl.config(text=f"{n_sel} selected of {len(visible)} shown")
            delete_btn.config(state=("normal" if n_sel else "disabled"))

        def _passes_filter(r):
            if r["age_days"] < age_var.get():
                return False
            if tech_var.get() != "All" and (r["tech"] or "—") != tech_var.get():
                return False
            return True

        def _redraw():
            for w in list_inner.winfo_children():
                try: w.destroy()
                except tk.TclError: pass
            visible = [r for r in all_rows if _passes_filter(r)]
            if not visible:
                tk.Label(list_inner,
                         text="No empty folders match the current filter.",
                         font=("Segoe UI Variable", 9, "italic"),
                         bg=WHITE, fg=TEXT_GRAY,
                         padx=20, pady=20).pack(fill="x")
                _update_sel_count()
                return
            for r in visible:
                row = tk.Frame(list_inner, bg=WHITE,
                                highlightthickness=1,
                                highlightbackground=BORDER)
                row.pack(fill="x", padx=4, pady=1)
                cb = tk.Checkbutton(
                    row, variable=r["var"],
                    bg=WHITE, activebackground=WHITE,
                    command=_update_sel_count)
                cb.pack(side="left", padx=(4, 0))
                meta = tk.Frame(row, bg=WHITE, padx=2, pady=4)
                meta.pack(side="left", fill="x", expand=True)
                tk.Label(meta, text=r["name"],
                         font=("Segoe UI Variable", 9, "bold"),
                         bg=WHITE, fg=TEXT_DARK,
                         anchor="w").pack(fill="x")
                tk.Label(meta,
                         text=(f"{r['tech'] or '—'}  ·  "
                               f"{int(r['age_days'])}d old  ·  "
                               f"{r['path']}"),
                         font=("Segoe UI Variable", 7), bg=WHITE, fg=TEXT_GRAY,
                         anchor="w").pack(fill="x")
                icon_button(row, "📂", fg=TEXT_GRAY, padx=6, pady=4,
                             font=("Segoe UI Emoji", 10),
                             tooltip="Open SharePoint folder",
                          command=lambda p=r["path"]: _open_folder(p)
                          ).pack(side="right", padx=4)
                icon_button(row, "📁 OD", fg=LINK_FG, padx=6, pady=4,
                             font=("Segoe UI Emoji", 9, "bold"),
                             tooltip="Open matching OneDrive job folder",
                          command=lambda nm=r["name"]: _open_od(nm)
                          ).pack(side="right", padx=2)
            _update_sel_count()

        def _open_od(sp_folder_name):
            """Resolve the OD job folder for this SP row and open it. Cached
            per-client so repeat clicks skip the network walk."""
            client = _client_from_sp_name(sp_folder_name)
            if not client:
                status_lbl.config(text="Couldn't parse client from folder name.")
                return
            if client in od_cache:
                path = od_cache[client]
                if path:
                    _open_folder(path)
                else:
                    status_lbl.config(
                        text=f"No OD folder found for '{client}'.")
                return
            status_lbl.config(text=f"Finding OD folder for {client}…")
            def _bg():
                path = _find_od_folder_for_client(client)
                def _done():
                    od_cache[client] = path
                    if path:
                        status_lbl.config(text=f"Opened OD folder for {client}.")
                        _open_folder(path)
                    else:
                        status_lbl.config(
                            text=f"No OD folder found for '{client}'.")
                try:
                    dlg.after(0, _done)
                except tk.TclError:
                    pass
            threading.Thread(target=_bg, daemon=True).start()

        def _select_all_visible():
            for r in all_rows:
                if _passes_filter(r):
                    r["var"].set(True)
            _update_sel_count()

        def _select_none():
            for r in all_rows:
                if _passes_filter(r):
                    r["var"].set(False)
            _update_sel_count()

        select_all_btn.config(command=_select_all_visible)
        select_none_btn.config(command=_select_none)

        # ── Delete action ─────────────────────────────────────────────
        def _do_delete():
            visible = [r for r in all_rows if _passes_filter(r)]
            picked = [r for r in visible if r["var"].get()]
            if not picked:
                return
            # Hard confirm — recycle bin is recoverable but the user
            # should still see a count before pulling the trigger.
            if not messagebox.askyesno(
                    "Confirm delete",
                    f"Move {len(picked)} empty folder"
                    f"{'s' if len(picked) != 1 else ''} to the "
                    "Recycle Bin?\n\n"
                    "They can be restored from the Recycle Bin if "
                    "this was a mistake.",
                    parent=dlg):
                return

            try:
                from send2trash import send2trash
            except Exception as ex:
                messagebox.showerror(
                    "send2trash unavailable",
                    "The send2trash library isn't installed. Hard "
                    "delete is intentionally NOT available from this "
                    "dialog so a misclick can't be unrecoverable.\n\n"
                    f"Error: {ex}", parent=dlg)
                return

            delete_btn.config(state="disabled", text="Deleting…")
            status_lbl.config(text=f"Deleting {len(picked)}…")
            failed = []

            def _bg():
                deleted = 0
                for r in picked:
                    try:
                        send2trash(r["path"])
                        deleted += 1
                    except Exception as ex:
                        failed.append((r["path"], str(ex)))

                def _done():
                    # Remove the deleted entries from in-memory state.
                    survivors = [r for r in all_rows
                                  if not (r["var"].get()
                                          and (r["path"], None) not in
                                              [(p, None) for p, _ in failed])]
                    # Simpler: rebuild from-scratch by filtering out
                    # paths we know we deleted.
                    deleted_paths = {r["path"] for r in picked
                                     if r["path"] not in
                                        {p for p, _ in failed}}
                    all_rows[:] = [r for r in all_rows
                                   if r["path"] not in deleted_paths]
                    delete_btn.config(text="🗑 Move selected to Recycle Bin")
                    if failed:
                        status_lbl.config(
                            text=(f"Deleted {deleted} · "
                                  f"{len(failed)} failed (see error)"))
                        msg = "\n".join(
                            f"{p}\n  {e}" for p, e in failed[:5])
                        messagebox.showwarning(
                            "Some deletes failed",
                            f"{len(failed)} folder(s) couldn't be "
                            f"removed:\n\n{msg}", parent=dlg)
                    else:
                        status_lbl.config(
                            text=f"Done — {deleted} moved to Recycle Bin.")
                    _redraw()
                dlg.after(0, _done)
            threading.Thread(target=_bg, daemon=True).start()

        delete_btn.config(command=_do_delete)

        # ── Scan flow ─────────────────────────────────────────────────
        def _rescan():
            all_rows.clear()
            for w in list_inner.winfo_children():
                try: w.destroy()
                except tk.TclError: pass
            tk.Label(list_inner,
                     text="Scanning SharePoint folders…",
                     font=("Segoe UI Variable", 9, "italic"),
                     bg=WHITE, fg=TEXT_GRAY,
                     padx=20, pady=20).pack(fill="x")
            status_lbl.config(text="Scanning… this can take 10-30s on a slow share.")

            def _bg():
                try:
                    rows = _sp.find_empty_photo_folders()
                except Exception as ex:
                    rows = []
                    err = str(ex)
                else:
                    err = None

                def _done():
                    if err:
                        status_lbl.config(text=f"Scan failed: {err}")
                        return
                    # Build BooleanVars (or recycle existing ones for
                    # paths we've seen before so unchecked-state
                    # survives a rescan).
                    for r in rows:
                        v = var_by_path.get(r["path"])
                        if v is None:
                            v = tk.BooleanVar(
                                value=(r["age_days"] >= age_var.get()))
                            v.trace_add("write",
                                         lambda *_a: _update_sel_count())
                            var_by_path[r["path"]] = v
                        r["var"] = v
                        all_rows.append(r)
                    techs = sorted({(r["tech"] or "—") for r in rows})
                    tech_cb.config(values=["All"] + techs)
                    status_lbl.config(
                        text=(f"{len(rows)} empty folder"
                              f"{'s' if len(rows) != 1 else ''} found "
                              "across SharePoint."))
                    _redraw()
                dlg.after(0, _done)
            threading.Thread(target=_bg, daemon=True).start()

        # Filters live-update the list without re-walking SP.
        age_var.trace_add("write", lambda *_a: _redraw())
        tech_cb.bind("<<ComboboxSelected>>", lambda *_a: _redraw())

        _rescan()

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Select Daily Run",
            filetypes=[("Word Documents", "*.docx"), ("All Files", "*.*")],
            initialdir=_runs_dir()
        )
        if not path:
            return
        persistence.set_value("daily_photos_last_doc", path)
        # Delegate to the unified loader so the network folder pre-scan and
        # chunked render apply here too (otherwise the throbber freezes
        # mid-populate while the main thread does network folder lookups).
        self._load_doc(path)

    def _refresh(self):
        """Re-parse the currently loaded .docx and re-walk SharePoint
        folders. Prompts to Browse first if no doc is loaded yet.

        state_hub.parse_run_doc is mtime-keyed, so an unchanged .docx
        skips the parse cost — only the folder pre-scan re-runs, which
        is what catches techs adding their folder externally."""
        path = (self.doc_path.get() or "").strip()
        if not path or not os.path.isfile(path):
            self._browse()
            return
        self._load_doc(path)

    def _load_today_run_doc(self):
        """Reset the day cursor and load today's run-doc. ⏪/⏭ walks
        from this anchor afterward."""
        from datetime import datetime as _dt
        self._current_run_date = _dt.today()
        self._load_run_doc_for_offset(0, label="today")

    def _load_tomorrow_run_doc(self):
        """Walk one day forward from the date currently being viewed
        (not from today). Multiple clicks step further forward."""
        self._walk_to_run_doc(direction=+1, label="next")

    def _load_yesterday_run_doc(self):
        """Walk one day back from the date currently being viewed.

        Multiple clicks step further back day-by-day. Today resets
        the cursor. Empty days are skipped, capped at 14 per click."""
        self._walk_to_run_doc(direction=-1, label="prior")

    def _walk_to_run_doc(self, *, direction, label):
        """Step day-by-day from `_current_run_date` (defaults to today)
        in `direction` (±1). Loads the first run-doc found within 14
        days and updates `_current_run_date` so the next click steps
        from there."""
        from datetime import datetime as _dt, timedelta as _td
        from run_audit_gui import _find_run_doc_for_date
        start = getattr(self, "_current_run_date", None) or _dt.today()
        for step in range(1, 15):
            try:
                target = start + _td(days=direction * step)
                path = _find_run_doc_for_date(target)
            except Exception:
                path = None
            if path and os.path.isfile(path):
                self._current_run_date = target
                if path == self.doc_path.get():
                    self._load_doc(path)
                    return
                self.doc_path.set(path)
                try:
                    persistence.set_value("daily_photos_last_doc", path)
                except Exception:
                    pass
                self._load_doc(path)
                return
        messagebox.showinfo(
            f"No {label} run doc",
            f"Couldn't find a {label} run-doc within 14 days of "
            f"{start.strftime('%m/%d/%y')}.\n\n"
            "Click 📅 Today to reset the cursor, or Browse to pick a "
            "specific day. (If today's doc was just added and you've "
            "walked past it, the cursor needs resetting.)",
            parent=self)

    def _load_run_doc_for_offset(self, day_offset, *, label):
        """Shared helper for the Today / Tomorrow quick-load buttons.
        Mirrors run_audit_gui._load_run_doc_for_offset so behavior
        matches across the two panels."""
        from datetime import datetime as _dt, timedelta as _td
        from run_audit_gui import _find_run_doc_for_date
        try:
            target = _dt.today() + _td(days=day_offset)
            path = _find_run_doc_for_date(target)
        except Exception:
            path = None
        if not path or not os.path.isfile(path):
            messagebox.showinfo(
                f"No run doc for {label}",
                f"Couldn't find {label}'s run-doc in the Daily Run "
                "folder.\n\nTry Browse to pick a different day.",
                parent=self)
            return
        if path == self.doc_path.get():
            # Same file already loaded — re-parse so the user gets a
            # fresh folder scan without having to swap docs first.
            self._load_doc(path)
            return
        self.doc_path.set(path)
        try:
            persistence.set_value("daily_photos_last_doc", path)
        except Exception:
            pass
        self._load_doc(path)

    def _populate_jobs(self):
        for w in self.jobs_inner.winfo_children():
            w.destroy()
        self.job_data = []

        if not self.jobs:
            tk.Label(self.jobs_inner,
                     text="No jobs found in 'Work To Be Performed' section.",
                     font=("Segoe UI Variable", 9, "italic"),
                     bg=WHITE, fg=TEXT_GRAY, pady=20).pack()
            self.hide_loading()
            return

        photos_reachable = os.path.isdir(sharepoint.PHOTOS_ROOT)
        fmap = getattr(self, "_folder_map", None) or {}

        def _path_for(tech, client):
            if (tech, client) in fmap:
                return fmap[(tech, client)]
            return _photo_folder_path(tech, self.run_date, client)

        # Summary strip — how many jobs already have all folders done
        done_count = 0
        for job in self.jobs:
            if job["techs"] and photos_reachable:
                all_done = all(
                    _path_for(t, job["client"]) is not None
                    for t in job["techs"]
                )
                if all_done:
                    done_count += 1

        if photos_reachable and self.jobs:
            strip = tk.Frame(self.jobs_inner, bg=SUCCESS_BG, pady=5, padx=10)
            strip.pack(fill="x", padx=4, pady=(4, 6))
            remaining = len(self.jobs) - done_count
            summary   = f"Photo folder check for {self.run_date}:  "
            summary  += f"{done_count} done  ·  {remaining} still needed"
            tk.Label(strip, text=summary, font=("Segoe UI Variable", 9, "bold"),
                     bg=SUCCESS_BG, fg=SUCCESS_FG if remaining == 0 else TEXT_DARK,
                     anchor="w").pack(fill="x")
        elif not photos_reachable:
            strip = tk.Frame(self.jobs_inner, bg=DANGER_BG, pady=5, padx=10)
            strip.pack(fill="x", padx=4, pady=(4, 6))
            tk.Label(strip, text="⚠  Photos folder unreachable — folder check skipped",
                     font=("Segoe UI Variable", 8, "italic"),
                     bg=DANGER_BG, fg=DANGER_FG).pack(anchor="w")

        # Chunk the per-job render so the throbber spinner keeps animating.
        # Each card is ~5 widget creates; 30 cards back-to-back is ~150 tk
        # calls that block long enough to visibly freeze the spinner.
        # Render 4 cards per tick, yield, repeat.
        self._render_queue = list(self.jobs)
        self._render_ctx = {
            "photos_reachable": photos_reachable,
            "path_for": _path_for,
        }
        self._render_next_chunk()

    def _render_next_chunk(self, chunk_size=4):
        if not getattr(self, "_render_queue", None):
            self.hide_loading()
            return
        ctx = self._render_ctx
        for _ in range(min(chunk_size, len(self._render_queue))):
            job = self._render_queue.pop(0)
            self._render_one_job(job, ctx["photos_reachable"], ctx["path_for"])
        if self._render_queue:
            # `after_idle` lets tk process pending UI events (spinner tick,
            # repaint) before the next chunk runs. With chunk_size=4 this
            # keeps the spinner animating throughout.
            self.after_idle(self._render_next_chunk)
        else:
            self.hide_loading()
            # Final sweep — chunked render is done, pick up default
            # tooltips on every newly-spawned tech checkbox / button.
            try:
                self.after_idle(self.sweep_tooltips)
            except Exception:
                pass

    def _render_one_job(self, job, photos_reachable, _path_for):
        activity = detect_activity(job.get("raw", ""), job.get("section"),
                                   job.get("new_loss", False))
        needs_photos = activity["needs_photos"]
        tech_vars = {}
        for t in job["techs"]:
            exists = (_path_for(t, job["client"]) is not None
                      if photos_reachable else None)
            # Default-check only if photos are actually needed AND the
            # folder doesn't already exist. Monitor-only jobs default
            # unchecked so we don't create useless folders.
            tech_vars[t] = tk.BooleanVar(value=(needs_photos and not exists))
        self.job_data.append({"job": job, "tech_vars": tech_vars,
                              "activity": activity})

        card = tk.Frame(self.jobs_inner, bg=WHITE,
                        highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x", padx=4, pady=3)

        inner = tk.Frame(card, bg=WHITE, padx=10, pady=8)
        inner.pack(fill="x")

        # Client name row + activity badge
        name_row = tk.Frame(inner, bg=WHITE)
        name_row.pack(fill="x")
        tk.Label(name_row, text=job["client"],
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=WHITE, fg=TEXT_DARK,
                 anchor="w").pack(side="left")
        # Activity badge — color codes whether photos are needed
        label_text = " · ".join(activity["labels"])
        if needs_photos:
            badge_bg, badge_fg = "#DAF1E2", GREEN_DARK
            badge_icon = "📷"
        else:
            badge_bg, badge_fg = "#F0F0F0", TEXT_GRAY
            badge_icon = "⊝"
        tk.Label(name_row, text=f"  {badge_icon} {label_text}  ",
                 font=("Segoe UI Variable", 8, "bold"),
                 bg=badge_bg, fg=badge_fg,
                 padx=6, pady=1).pack(side="left", padx=(8, 0))

        # Workcenter heads-up — Fernando uploads photos straight to
        # Workcenter rather than the SharePoint photos folder, so when
        # he's on a job there's nothing for the daily-folders tool to
        # create on the share. Badge says "look in Workcenter for these
        # photos" so the user doesn't go hunting in OneDrive.
        if any("fernando" in str(t).lower() or str(t).upper() == "FB"
               for t in (job.get("techs") or [])):
            tk.Label(name_row, text="  📤 WC (Fernando)  ",
                     font=("Segoe UI Variable", 8, "bold"),
                     bg="#7B5BA8", fg=ON_ACCENT,
                     padx=6, pady=1).pack(side="left", padx=(6, 0))

        # Missing-tech warning — a job line with zero recognized techs
        # is almost always a roster gap (new hire not added yet). The
        # silent-skip was the root cause of "missing some things on
        # the run" — making it visible cues the user to update the
        # roster before creating folders.
        if not (job.get("techs") or []):
            tk.Label(name_row,
                     text="  ⚠ No techs recognized — check roster  ",
                     font=("Segoe UI Variable", 8, "bold"),
                     bg=WARN_BG, fg=WARN_FG,
                     padx=6, pady=1).pack(side="left", padx=(6, 0))

        # Expected-folders hint (only when photos are needed and we have
        # specific expectations beyond just "Initial")
        if needs_photos and activity["expected"]:
            hint = "expects: " + ", ".join(f + " pics" for f in activity["expected"])
            tk.Label(inner, text=hint,
                     font=("Segoe UI Variable", 8, "italic"),
                     bg=WHITE, fg=TEXT_GRAY, anchor="w"
                     ).pack(fill="x", pady=(2, 0))
        elif not needs_photos:
            tk.Label(inner, text="No photos required for this job type.",
                     font=("Segoe UI Variable", 8, "italic"),
                     bg=WHITE, fg=TEXT_GRAY, anchor="w"
                     ).pack(fill="x", pady=(2, 0))

        # Tech checkboxes row
        if job["techs"]:
            tech_row = tk.Frame(inner, bg=WHITE)
            tech_row.pack(fill="x", pady=(4, 0))
            tk.Label(tech_row, text="Folders for:", font=("Segoe UI Variable", 8),
                     bg=WHITE, fg=TEXT_GRAY).pack(side="left")
            for tech, var in tech_vars.items():
                folder_path = _path_for(tech, job["client"])
                exists = folder_path is not None
                health = (_photo_folder_health(folder_path)
                          if exists else {"status": "missing"})
                if not photos_reachable:
                    fg, suffix = TEXT_GRAY, ""
                elif not exists:
                    fg, suffix = GREEN, ""
                elif health["status"] == "ok":
                    fg = "#888888"
                    suffix = (f" ✓ {health['count']}·"
                              f"{_format_age(health['age_hours'])}")
                elif health["status"] == "empty":
                    fg, suffix = "#A6772A", " ⚠ empty"
                elif health["status"] == "stale":
                    fg = "#A6772A"
                    suffix = (f" ⚠ stale ({health['count']}·"
                              f"{_format_age(health['age_hours'])})")
                else:
                    fg, suffix = "#888888", " ✓"
                tk.Checkbutton(tech_row, text=tech + suffix, variable=var,
                               font=("Segoe UI Variable", 8, "bold"),
                               bg=WHITE, fg=fg, activebackground=WHITE,
                               selectcolor=WHITE).pack(side="left", padx=(6, 0))
                if exists and folder_path:
                    icon_button(tech_row, "📁", fg=TEXT_GRAY,
                                 hover=SUCCESS_HOVER, padx=2, pady=0,
                                 font=("Segoe UI Variable", 8),
                                 command=lambda p=folder_path: _open_folder(p)
                             ).pack(side="left")
        else:
            tk.Label(inner, text="No techs detected — check manually",
                     font=("Segoe UI Variable", 8, "italic"),
                     bg=WHITE, fg=FLAG_RED).pack(anchor="w")

        # Right-click anywhere on the card → shared client context menu
        # (Pin to Trello, Change folder, Edit aliases, Reset memory).
        # Same surface as Audit / IUQ / Snapshot / Hygiene / APA — when
        # a run-doc client name doesn't quite match the SharePoint
        # photo folder convention, the alias editor is the canonical
        # fix and it lives on every other tool's row menu already.
        try:
            from job_widgets import attach_card_context_menu
            import config as _cfg
            ab = (_cfg.load().get("audit_base") or "") or None
            client_name = (job.get("client") or "").strip()
            if client_name:
                attach_card_context_menu(
                    self, [card], client_name, audit_base=ab)
        except Exception:
            pass

    def _audit_run(self):
        if not self.jobs:
            messagebox.showerror("No Jobs", "Load a run document first.",
                                  parent=self)
            return

        has_work    = any(j["section"] == "work"    for j in self.jobs)
        has_monitor = any(j["section"] == "monitor" for j in self.jobs)

        var_work    = tk.BooleanVar(value=has_work)
        var_monitor = tk.BooleanVar(value=has_monitor)

        dlg = tk.Toplevel(self)
        dlg.title("Audit Sections")
        dlg.resizable(False, False)
        dlg.grab_set()
        f = tk.Frame(dlg, bg=BG, padx=20, pady=16)
        f.pack()
        tk.Label(f, text="Which sections to audit?",
                 font=("Segoe UI Variable", 10, "bold"), bg=BG).pack(anchor="w")
        if has_work:
            tk.Checkbutton(f, text="Work to Be Performed", variable=var_work,
                           font=("Segoe UI Variable", 9), bg=BG, activebackground=BG,
                           selectcolor=WHITE).pack(anchor="w", pady=2)
        if has_monitor:
            tk.Checkbutton(f, text="Monitor", variable=var_monitor,
                           font=("Segoe UI Variable", 9), bg=BG, activebackground=BG,
                           selectcolor=WHITE).pack(anchor="w", pady=2)

        def _go():
            selected = set()
            if var_work.get():    selected.add("work")
            if var_monitor.get(): selected.add("monitor")
            dlg.destroy()
            if not selected:
                return
            names = [j for j in self.jobs if j["section"] in selected]
            self._open_audit_window(names)

        done_button(f, "Run Audit", padx=16, pady=5,
                     command=_go).pack(pady=(12, 0), fill="x")

    def _open_audit_window(self, names):

        win = tk.Toplevel(self)
        win.title("Run Audit")
        win.geometry("620x560")
        win.configure(bg=BG)

        hdr = tk.Frame(win, bg=GREEN, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="SERVPRO  ·  Run Audit",
                 font=("Fraunces", 15, "bold"), bg=GREEN, fg=WHITE).pack()
        job_count = len(names)
        tk.Label(hdr, text=f"Run date: {self.run_date}  ·  {job_count} jobs",
                 font=("Segoe UI Variable", 9), bg=GREEN, fg="#B2DFC4").pack(pady=(2,0))

        nav = tk.Frame(win, bg=BG, padx=16, pady=6)
        nav.pack(fill="x")
        self._audit_status = tk.Label(nav, text="Running audit…",
                                      font=("Segoe UI Variable", 9, "italic"), bg=BG, fg=TEXT_GRAY)
        self._audit_status.pack(side="left")
        send_button(nav, "↺ Refresh", padx=8, pady=3,
                     font=("Segoe UI Variable", 9, "bold"),
                     command=lambda: self._audit_run_refresh(names, scroll_canvas, inner, win)
                     ).pack(side="right")
        def _export():
            if not self._last_audit_results:
                messagebox.showerror("No Results", "Run audit first.", parent=win)
                return
            audit_export.open_export_window(win, self._last_audit_results, self.run_date)
        done_button(nav, "Export PDF", padx=10, pady=3,
                     font=("Segoe UI Variable", 9, "bold"),
                     command=_export).pack(side="right", padx=(0, 6))

        outer = tk.Frame(win, bg=BG, padx=10)
        outer.pack(fill="both", expand=True, pady=(0, 10))
        scroll_canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        sb = tk.Scrollbar(outer, orient="vertical", command=scroll_canvas.yview)
        try:
            import theme as _theme
            _theme.style_tk_scrollbar(sb)
        except Exception:
            pass
        scroll_canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        scroll_canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(scroll_canvas, bg=BG)
        cw = scroll_canvas.create_window((0,0), window=inner, anchor="nw")
        inner.bind("<Configure>",
            lambda e: scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all")))
        scroll_canvas.bind("<Configure>",
            lambda e: scroll_canvas.itemconfig(cw, width=e.width))
        _sc = scroll_canvas
        def _scroll_audit(e): _sc.yview_scroll(-1*(e.delta//120), "units")
        _sc.bind("<Enter>", lambda e: _sc.bind_all("<MouseWheel>", _scroll_audit))
        _sc.bind("<Leave>", lambda e: _sc.unbind_all("<MouseWheel>"))

        self._audit_run_refresh(names, scroll_canvas, inner, win)

    def _audit_run_refresh(self, names, canvas, inner, win):
        for w in inner.winfo_children():
            w.destroy()
        self._audit_status.config(text="Running audit…")
        win.update()

        def _run():
            try:
                results, err = audit_jobs(names)
            except Exception as ex:
                results, err = None, str(ex)
            win.after(0, lambda: self._render_run_audit(results, err, inner, canvas))

        threading.Thread(target=_run, daemon=True).start()

    def _render_run_audit(self, results, err, inner, canvas):
        if err:
            self._audit_status.config(text=f"Error: {err}")
            tk.Label(inner, text=f"⚠  {err}", font=("Segoe UI Variable", 10),
                     bg=BG, fg=FLAG_RED).pack(pady=20)
            return

        self._last_audit_results = results
        audit_export.write_audit_md(results, run_date=self.run_date, source="Daily Photos")
        total    = len(results)
        flagged  = sum(1 for r in results if r["flagged"])
        resolved = [0]

        def _update_status():
            rem = flagged - resolved[0]
            self._audit_status.config(
                text=f"{total} jobs  ·  {rem} flagged  ·  {total - flagged + resolved[0]} OK")

        def _make_import_action(cp, var, lbl, all_v, bl, ca, cr,
                                   client_name=""):
            def _do():
                dlg = tk.Toplevel(self)
                dlg.title("Docusketch")
                dlg.resizable(False, False)
                dlg.grab_set()
                wf = tk.Frame(dlg, bg=BG, padx=20, pady=16)
                wf.pack()
                tk.Label(wf, text="Make sure the Docusketch zip was downloaded from:",
                         font=("Segoe UI Variable", 10), bg=BG).pack(anchor="w")
                _url = "https://app.docusketch.com/portal-cc/projects"
                lnk = tk.Label(wf, text=_url, font=("Segoe UI Variable", 9, "underline"),
                               bg=BG, fg=LINK_FG, cursor="hand2")
                lnk.pack(anchor="w", pady=(2, 10))
                lnk.bind("<Button-1>", lambda e: webbrowser.open(_url))
                tk.Label(wf, text="Confirm the zip is in your Downloads folder.",
                         font=("Segoe UI Variable", 10), bg=BG).pack(anchor="w", pady=(0, 8))

                def _request_via_trello():
                    try:
                        import docusketch_requests as dr
                        hit = dr.find_card_for_client(client_name)
                    except Exception as ex:
                        messagebox.showerror(
                            "Lookup failed",
                            f"Couldn't search Trello: {ex}",
                            parent=dlg)
                        return
                    if hit is None:
                        messagebox.showwarning(
                            "No card found",
                            f"Couldn't find a Trello card for "
                            f"'{client_name}'. Open the card manually "
                            f"and post '{dr.DEFAULT_NOTE}'.",
                            parent=dlg)
                        return
                    entry = dr.request(hit["card_id"],
                                         client_name=client_name)
                    if entry is None:
                        messagebox.showerror(
                            "Couldn't record",
                            "Trello request failed. Check ems.log.",
                            parent=dlg)
                        return
                    msg = (f"Posted to {entry['card_name']}.\n"
                           f"It'll show in the Hygiene panel's "
                           f"'📐 Docusketch pending' section daily "
                           f"until you import the zip.")
                    if not entry.get("comment_posted", True):
                        msg = ("Recorded locally, but the Trello "
                               "comment failed to post. Open the "
                               "card and post manually.")
                    messagebox.showinfo("Docusketch requested",
                                          msg, parent=dlg)
                    dlg.destroy()

                _proceed = [False]
                def _ok(): _proceed[0] = True; dlg.destroy()
                br = tk.Frame(wf, bg=BG); br.pack(fill="x", pady=(4, 0))
                secondary_button(br, "Cancel", padx=12, pady=4,
                                  command=dlg.destroy).pack(side="left")
                if client_name:
                    warn_button(br, "📐 Mark Requested", padx=10, pady=4,
                                 command=_request_via_trello
                              ).pack(side="left", padx=(8, 0))
                done_button(br, "Import", padx=12, pady=4,
                             command=_ok).pack(side="right")
                dlg.wait_window()
                if not _proceed[0]:
                    return
                try:
                    zips = sorted(
                        [f for f in os.listdir(DOWNLOADS)
                         if DOCUSKETCH_RE.match(f)
                         and os.path.isfile(os.path.join(DOWNLOADS, f))],
                        key=lambda f: os.path.getmtime(os.path.join(DOWNLOADS, f)),
                        reverse=True)
                except OSError:
                    messagebox.showerror("Error", "Could not read Downloads folder.",
                                          parent=self)
                    return
                if not zips:
                    messagebox.showerror("Not Found",
                        "No Docusketch zip found in Downloads.\n\n"
                        "Expected: Tour_*_Order_*_all_sketches*.zip",
                        parent=self)
                    return
                chosen = zips[0]
                if len(zips) > 1:
                    dlg = tk.Toplevel(self)
                    dlg.title("Select Docusketch Zip")
                    dlg.resizable(False, False)
                    dlg.grab_set()
                    f = tk.Frame(dlg, bg=BG, padx=16, pady=14)
                    f.pack()
                    tk.Label(f, text="Multiple zips found — pick one:",
                             font=("Segoe UI Variable", 10, "bold"), bg=BG).pack(anchor="w", pady=(0,8))
                    pick_var = tk.StringVar(value=zips[0])
                    for z in zips[:6]:
                        tk.Radiobutton(f, text=z, variable=pick_var, value=z,
                                       font=("Segoe UI Variable", 8), bg=BG,
                                       activebackground=BG).pack(anchor="w", pady=2)
                    result = [None]
                    def _pick():
                        result[0] = pick_var.get()
                        dlg.destroy()
                    done_button(f, "Import", padx=12, pady=4,
                                 command=_pick
                                 ).pack(pady=(12, 0), fill="x")
                    dlg.wait_window()
                    if not result[0]:
                        return
                    chosen = result[0]
                zip_path = os.path.join(DOWNLOADS, chosen)
                ems = os.path.join(cp, "EMS")
                base = ems if os.path.isdir(ems) else cp
                docs = find_docs_dir(base) or os.path.join(base, "DOCS")
                os.makedirs(docs, exist_ok=True)
                ds_folder = os.path.join(docs, "Docusketch")
                os.makedirs(ds_folder, exist_ok=True)
                try:
                    with zipfile.ZipFile(zip_path, 'r') as z:
                        z.extractall(ds_folder)
                except Exception as ex:
                    messagebox.showerror("Extract Error", str(ex), parent=self)
                    return
                var.set(True)
                lbl.config(fg=TEXT_MUTED, font=("Segoe UI Variable", 8, "overstrike"))
                if all(v.get() for v in all_v) and not cr[0]:
                    cr[0] = True
                    bl.config(text=" OK ", bg=GREEN)
                    ca.config(highlightbackground=GREEN)
                    resolved[0] += 1
                    _update_status()
                # Auto-clear any pending docusketch-request reminder for
                # this client — the zip just arrived. Best-effort lookup;
                # if no match nothing to clear. Also tick the Trello
                # PHYSICAL SKETCH checklist item now the sketch is in.
                ticked = []
                try:
                    import docusketch_requests as dr
                    if client_name:
                        hit = dr.find_card_for_client(client_name)
                        if hit is not None:
                            dr.resolve(hit["card_id"])
                except Exception:
                    pass
                try:
                    import persistence as _per
                    import trello_autotick as _at
                    _cid = (_per.get_trello_card_id(client_name)
                            or "") if client_name else ""
                    if _cid:
                        ticked = _at.autotick(
                            _cid, events=("docusketch_imported",),
                            client=client_name)
                except Exception:
                    ticked = []
                _msg = f"Extracted to:\n{ds_folder}"
                if ticked:
                    _msg += ("\n\n✓ Ticked Trello: "
                             + ", ".join(it for _cl, it in ticked))
                messagebox.showinfo("Docusketch Imported", _msg, parent=self)
            return _do

        _update_status()

        for r in results:
            card = tk.Frame(inner, bg=WHITE, highlightbackground=BORDER, highlightthickness=1)
            card.pack(fill="x", padx=6, pady=2)
            row = tk.Frame(card, bg=WHITE, padx=10, pady=6)
            row.pack(fill="x")

            badge_bg  = FLAG_RED if r["flagged"] else GREEN
            badge_txt = "FLAG" if r["flagged"] else " OK "
            badge_lbl = tk.Label(row, text=badge_txt, font=("Segoe UI Variable", 8, "bold"),
                                 bg=badge_bg, fg=WHITE, padx=4)
            badge_lbl.pack(side="left")

            detail = tk.Frame(row, bg=WHITE)
            detail.pack(side="left", fill="x", expand=True)

            name_row = tk.Frame(detail, bg=WHITE)
            name_row.pack(fill="x")

            client_lbl = r["client"]
            if r.get("folder") and r["folder"].lower() != r["client"].lower():
                client_lbl += f"  ({r['folder']})"
            if not r["found"]:
                client_lbl += "  — folder not found"
            tk.Label(name_row, text=f"  {client_lbl}",
                     font=("Segoe UI Variable", 9, "bold"), bg=WHITE,
                     fg=TEXT_MUTED if not r["found"] else TEXT_DARK,
                     anchor="w").pack(side="left", fill="x", expand=True)

            if r["path"]:
                icon_button(name_row, "📁", padx=2, pady=4,
                             command=lambda p=r["path"]: os.startfile(p),
                             tooltip="Open job folder"
                             ).pack(side="right")

            if not r["flagged"]:
                continue

            items = []
            for fi in (r.get("form_issues") or []):
                items.append((fi, FLAG_RED, False, _is_commercial_form(fi)))
            for pi in (r.get("photo_issues") or []):
                items.append((pi, FLAG_RED, "docusketch" in pi.lower(), False))
            if r["aging"] >= 3 and r["found"]:
                last_str = r["last"].strftime("%m/%d/%y") if r["last"] else "never"
                items.append((f"{r['aging']}d inactive (last: {last_str})", "#E67E22", False, False))

            if not items:
                continue

            card_resolved      = [False]
            all_vars           = []

            has_commercial = any(ic for _, _, _, ic in items)
            # Session-only here — Photo Folders is a one-shot file-creation
            # flow, no audit-state persistence to remember between runs.
            commercial = CommercialToggle(name_row, r["client"],
                                          persist=False,
                                          bg=WHITE, activebackground=WHITE,
                                          selectcolor=WHITE)
            if has_commercial:
                commercial.checkbutton.pack(side="right", padx=(0, 4))

            def _make_toggle(var, lbl, item_color, all_v, bl, ca, cr):
                def _toggle():
                    if var.get():
                        lbl.config(fg=TEXT_MUTED, font=("Segoe UI Variable", 8, "overstrike"))
                    else:
                        lbl.config(fg=item_color, font=("Segoe UI Variable", 8))
                    now_done = all(v.get() for v in all_v)
                    was_done = cr[0]
                    if now_done and not was_done:
                        cr[0] = True
                        bl.config(text=" OK ", bg=GREEN)
                        ca.config(highlightbackground=GREEN)
                        resolved[0] += 1
                        _update_status()
                    elif not now_done and was_done:
                        cr[0] = False
                        bl.config(text="FLAG", bg=FLAG_RED)
                        ca.config(highlightbackground=BORDER)
                        resolved[0] -= 1
                        _update_status()
                return _toggle

            for item_txt, item_color, is_ds, is_comm in items:
                var = tk.BooleanVar()
                all_vars.append(var)
                item_row = tk.Frame(detail, bg=WHITE)
                item_row.pack(fill="x", pady=1)
                lbl = tk.Label(item_row, text=item_txt,
                               font=("Segoe UI Variable", 8), bg=WHITE,
                               fg=item_color, anchor="w")
                lbl.pack(side="left", padx=(2, 0))
                toggle_fn = _make_toggle(var, lbl, item_color, all_vars,
                                         badge_lbl, card, card_resolved)
                if is_comm:
                    commercial.register(var, toggle_fn)
                if is_ds and r["path"]:
                    send_button(item_row, "📥 Import", padx=4, pady=1,
                                 font=("Segoe UI Variable", 7, "bold"),
                                 command=_make_import_action(r["path"], var, lbl,
                                                          all_vars, badge_lbl,
                                                          card, card_resolved,
                                                          client_name=r.get("client", ""))
                              ).pack(side="left", padx=(4, 0))
                tk.Checkbutton(item_row, variable=var, bg=WHITE,
                               activebackground=WHITE, selectcolor=WHITE,
                               command=toggle_fn
                               ).pack(side="right")

    def _toggle_all(self):
        v = self.all_var.get()
        for jd in self.job_data:
            for var in jd["tech_vars"].values():
                var.set(v)

    def _on_toggle(self):
        pass  # not used with per-tech model

    def _create(self):
        if not self.job_data:
            messagebox.showerror("No Jobs", "Load a run document first.",
                                  parent=self)
            return

        # Build list of jobs with only the selected techs
        to_create = []
        for jd in self.job_data:
            selected_techs = [t for t, v in jd["tech_vars"].items() if v.get()]
            if selected_techs:
                to_create.append({**jd["job"], "techs": selected_techs})

        if not to_create:
            messagebox.showerror("Nothing selected",
                                  "Select at least one tech for at least one job.",
                                  parent=self)
            return

        created, skipped = make_folders(to_create, self.run_date)

        msg = f"Created {len(created)} folder(s)."
        if created:
            msg += "\n\n" + "\n".join(created)
        if skipped:
            msg += f"\n\nSkipped ({len(skipped)}):\n" + "\n".join(skipped)
        messagebox.showinfo("Done", msg, parent=self)


def main(argv=None):
    run_standalone(App, geometry="560x520", resizable=(False, False))


if __name__ == "__main__":
    main()
