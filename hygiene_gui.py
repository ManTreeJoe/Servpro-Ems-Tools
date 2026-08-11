"""Hygiene panel — Trello card hygiene + handoff + closeout candidates.

Three sections, all populated by the same background scan:
  ⚠ Hygiene violations          (trello_hygiene.scan_all_in_scope)
  🔄 Lane moves missing handoff (subset of the same scan)
  📸 Ready for snapshot         (closeout_watcher.find_snapshot_candidates)

Per-row actions: open card in browser, snooze 1d, dismiss permanently,
"Open in Snapshot" for closeout-ready rows. Dismissed rows are filtered
out of the next scan via persistence.is_card_warning_dismissed.

Background scan runs in a daemon thread; results are marshalled back
to the Tk main loop via `after`. Cancel-on-hide so a stale scan can't
stomp on a panel that's been swapped out.
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time
import tkinter as tk
import webbrowser
from datetime import datetime, timezone
from tkinter import messagebox, ttk

# Pull "GUADALUPE PLOUSSARD" out of email subjects like
#   "RE: An Assignment Note Has Been Added in XactAnalysis Insured: GUADALUPE PLOUSSARD"
# Used as a last-resort client-name source for estimate request rows
# where adjuster_monitor couldn't match a Trello card and therefore
# left insured/claim blank in the record.
_INSURED_FROM_SUBJECT_RE = re.compile(
    r"Insured:\s*([^\r\n]+)", re.IGNORECASE)

import config as _config
import hygiene_tabs as _htabs

from theme import (
    GREEN, GREEN_DARK, WHITE, BG, TEXT_DARK, TEXT_GRAY, TEXT_MUTED,
    BORDER, FLAG_RED, SURFACE_2, NEUTRAL_HOVER,
    SUCCESS_BG, SUCCESS_FG, SUCCESS_HOVER,
    INFO_BG, INFO_FG, INFO_HOVER,
    LINK_BG, LINK_FG, LINK_HOVER,
    WARN_BG, WARN_FG, WARN_HOVER,
    DANGER_BG, DANGER_FG, DANGER_HOVER,
    ON_ACCENT,
)
from tool_panel import (ToolPanel, ScrollableFrame, VirtualizedCardList,
                        run_standalone, show_toast)
from trello_icon import trello_icon
from ui_buttons import (
    done_button, send_button, link_button, secondary_button,
    warn_button, danger_button, icon_button, trello_link_button,
)
import persistence as per


# Browser preference — set in config.json["preferred_browser"]. Values:
#   "arc" | "chrome" | "firefox" | "edge" | "default"
# Default = "arc" since that's what the user picked. Falls through to
# webbrowser.open (system default = Edge on Windows) if the preferred
# browser exe can't be found.
_BROWSER_EXE_PATHS = {
    "arc": [
        r"%LOCALAPPDATA%\Microsoft\WindowsApps\Arc.exe",
        r"%LOCALAPPDATA%\Programs\Arc\Arc.exe",
        r"%LOCALAPPDATA%\Arc\Application\Arc.exe",
    ],
    "chrome": [
        r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe",
        r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe",
        r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
    ],
    "firefox": [
        r"%PROGRAMFILES%\Mozilla Firefox\firefox.exe",
        r"%PROGRAMFILES(X86)%\Mozilla Firefox\firefox.exe",
    ],
    "edge": [
        r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe",
        r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe",
    ],
}


def _resolve_browser_exe(name: str) -> str | None:
    """Expand env vars + return the first path that exists, or None
    when none of the candidates resolve. Lets us launch the browser
    via subprocess.Popen even when it isn't on PATH (Arc isn't, by
    default on Windows)."""
    for raw in _BROWSER_EXE_PATHS.get(name.lower(), []):
        candidate = os.path.expandvars(raw)
        if os.path.isfile(candidate):
            return candidate
    return None


# ProgId fragments registered for each browser at
# HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.html\UserChoice.
# Match is case-insensitive substring against the registered ProgId
# string so we don't have to know the exact AppX hash on every machine.
_DEFAULT_PROGID_MARKERS = {
    "arc":     ("thebrowsercompany.arc",
                "appx8sgb24wtejr2qv47ksrvht0p80wg1n4h"),
    "chrome":  ("chromehtml",),
    "firefox": ("firefoxurl",),
    "edge":    ("msedgehtm",),
}


def _is_default_browser(name: str) -> bool:
    """True when the registered default URL handler matches `name`.
    Used to pick the fast ShellExecute path (`os.startfile`) when the
    user's preferred browser is also their system default — that
    avoids the slow App Execution Alias stub at
    `%LOCALAPPDATA%\\Microsoft\\WindowsApps\\Arc.exe`, which can take
    1-3 seconds per launch even when Arc is already running."""
    nm = (name or "").strip().lower()
    if nm == "default":
        return True
    markers = _DEFAULT_PROGID_MARKERS.get(nm, ())
    if not markers:
        return False
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer"
                r"\FileExts\.html\UserChoice") as k:
            progid, _ = winreg.QueryValueEx(k, "ProgId")
    except OSError:
        return False
    pl = (progid or "").lower()
    return any(m in pl for m in markers)


def open_url_in_preferred_browser(url: str) -> None:
    """Open `url` in the user's preferred browser. Reads the
    `preferred_browser` config key (default 'arc'). Falls through to
    the system default when the preferred browser isn't installed —
    it's a UX preference, not a hard requirement.

    Hot path: when the preferred browser is the system default we use
    `os.startfile` (Windows ShellExecute), which routes through the
    OS's URL protocol handler. That's ~50ms tab-open vs the 1-3 sec
    you'd get launching Arc.exe directly through subprocess.Popen
    (the stub at \\Microsoft\\WindowsApps\\Arc.exe goes through the
    App Execution Alias machinery on every call). We only fall back
    to Popen for explicit browser overrides that differ from the
    system default."""
    if not url:
        return
    cfg = _config.load()
    pref = (cfg.get("preferred_browser") or "default").strip().lower()

    # Fast path — preferred browser IS the system default, so let the
    # OS handle the protocol activation. webbrowser.open also routes
    # through ShellExecute on Windows but adds Python overhead;
    # os.startfile is the most direct call.
    if _is_default_browser(pref):
        try:
            os.startfile(url)
            return
        except OSError:
            pass

    # Slow path — explicit browser override. Resolve the exe and
    # Popen it directly. Detach so the launch doesn't tie up the
    # Tk process.
    exe = _resolve_browser_exe(pref)
    if exe:
        try:
            subprocess.Popen([exe, url],
                             creationflags=getattr(subprocess,
                                                    "DETACHED_PROCESS", 0))
            return
        except OSError:
            pass
    # webbrowser.get(name) covers chrome/firefox/edge when they're on
    # PATH or registered with Python — Arc isn't, which is why the
    # exe-path lookup runs first.
    if pref in ("chrome", "firefox", "edge"):
        try:
            webbrowser.get(pref).open(url)
            return
        except (webbrowser.Error, Exception):
            pass
    # Last resort: system default. Better than failing silently.
    try: os.startfile(url)
    except OSError:
        try: webbrowser.open(url)
        except Exception: pass


# Section icons + titles. Order = stack order. Customer concerns top
# the stack because legal/complaint matches need to be seen before any
# hygiene noise — these rules emit only on real keyword hits, so a
# non-empty count is high-signal.
_SECTIONS = (
    ("wc_audit_due", "🗂", "Monthly WC Audit due",
     "Reminder to run the monthly WorkCenter audit. Surfaces from the "
     "first Monday of the month through that Sunday. Auto-clears once "
     "you save this month's audit file in the shared share."),
    ("weekly",   "📆", "Weekly check-ins due",
     "Cards on the Estimating board whose last weekly status note was "
     "7+ days ago (or never). One-click sends the canonical text to "
     "clipboard + Trello @mention + Teams DM. Stamps the card's last-"
     "note timestamp so it drops off the list for another 7 days."),
    ("estimates", "💰", "Estimate Requests (48h SLA)",
     "Inbound inquiries from adjusters (email) or carriers (XA notes). "
     "One-click 'Send 48h ack' copies the canonical reply to clipboard "
     "and notifies the estimator on Trello + Teams. Tracks the 48h "
     "deadline; rows flip to red when overdue."),
    ("adjuster_pending", "📨", "Adjuster inquiries (approve to post)",
     "Inbox messages the matcher tied to a Trello card. Nothing gets "
     "posted automatically — click ✓ Post to drop the receipt comment "
     "on the card, or ✕ Dismiss for false positives (realtors, "
     "vendors, shared mailboxes). Dismissals are remembered so the "
     "same message doesn't re-queue on the next scan."),
    ("disputes", "⚖", "Audit disputes (open + overdue)",
     "Open disputes from the shared Dispute Tracker workbook. "
     "Auto-populated when a job first appears under APA Monitor's "
     "Audit Dispute section OR when a matching email lands in the "
     "inbox. Rows flip red when past the 3-business-day target "
     "response date. ✎ Edit opens the row's editor in the Disputes "
     "panel; ✓ Mark Ack flips Ack Email Sent → Yes."),
    ("concerns", "🚨", "Customer concerns",
     "Trello comments + inbox emails mentioning complaints, legal, "
     "refunds, or escalations."),
    ("ipr", "📷", "Initial Photo Report requests",
     "Trello cards where someone @mentioned you with a request for "
     "an Initial Photo Report. Auto-clears once you reply with "
     "'uploaded' / 'done' on the same card."),
    ("xa_apology", "🔔", "Apology reminders (XA)",
     "AR Board cards needing the apology note added in XactAnalysis "
     "(manual step — click Done after posting)."),
    ("docusketch_needed", "📐", "Docusketch needed (WIP)",
     "Cards currently in a WORK IN PROGRESS lane that haven't had a "
     "Docusketch requested yet. Workflow rule: enter WIP → request "
     "Docusketch. One-click 📐 Request posts the comment + logs the "
     "request; the row then graduates to the 'Docusketch pending' "
     "section below. ✕ Dismiss when the Docusketch was already done "
     "outside this tracker."),
    ("docusketch", "📐", "Docusketch pending",
     "Jobs you've already requested a Docusketch on (logged from the "
     "import dialog) but the zip hasn't been imported yet. "
     "Auto-clears when you import the zip."),
    ("docusign",   "📝", "Docusign pending",
     "Paperwork sent for e-signature, or waiting on the office to call "
     "the insured for an email. ✓ Received closes the entry; rows "
     "without an email show ✉ Got email to flip them to "
     "pending-signature."),
    ("xa_gaps", "📝", "XA gaps (stale + open commitments)",
     "Jobs whose XactAnalysis notes are stale or have open verbal "
     "commitments (billing to follow, scheduled, underway) without "
     "a closing note. Pulled from the EMS@ inbox."),
    ("hygiene",  "⚠", "Hygiene violations",
     "Cards missing owner, follow-up date, or recent activity."),
    ("handoff",  "🔄", "Lane moves missing handoff",
     "Cards moved to a new lane in the last 24h without a handoff note."),
    ("closeout", "📸", "Ready for Snapshot",
     "Cards in the SNAPSHOT lane or with 'ready for snapshot' comments."),
    ("missing_items", "📋", "Missing",
     "Items flagged as missing at any stage — intake, daily audit, or "
     "snapshot. Forms (ATP/CIF/etc), scope, photos. Age in days since "
     "the flag was raised; ✓ Resolved when the item arrives, 👁 Ignore "
     "for opt-out cases."),
    ("docusign_resends", "✍", "Docusign physical-signature SLA",
     "Docusign resends past 5 days without signature. Escalation cue "
     "to send someone out for a physical signature visit."),
    ("open_jobs", "📋", "All open Trello jobs",
     "Every card on the in-scope Trello boards that isn't closed. "
     "Sourced from the shared ems_db cache — click 🔄 Sync from Trello "
     "in Settings to refresh. Aging-first so the longest-stale jobs "
     "rise to the top."),
    ("stalled", "🐌", "Stalled in stage",
     "Jobs that have been in their current pipeline stage past the "
     "per-stage threshold (e.g. >14 days in Mitigation, >30 in AR). "
     "Auto-populated by the Pipeline lifecycle table, kept fresh by "
     "every Hygiene scan. Click to open the Pipeline panel filtered "
     "to that stage."),
    ("anomalies", "🚨", "Anomalous jobs",
     "Jobs whose days-in-stage is 3+× the historical median for "
     "their stage. Different from Stalled (which uses static "
     "thresholds): anomalies are jobs much slower than the norm for "
     "their specific stage, so a systemically-slow stage doesn't "
     "trigger an anomaly on every row. Needs ≥3 historical "
     "transitions per stage to call any row anomalous."),
)


# Tab groupings live in hygiene_tabs — the web panel had its own copy
# and they drifted (see that module). These aliases keep the local
# names so the rest of this file reads unchanged.
_TABS = _htabs.TABS
_DEFAULT_TAB = _htabs.DEFAULT_TAB
_TAB_KEYS = _htabs.TAB_KEYS
_SECTION_TO_TAB = _htabs.SECTION_TO_TAB
_TAB_BUTTON_LABELS = _htabs.TAB_BUTTON_LABELS
_tab_section_keys = _htabs.tab_section_keys
_scan_flags_for_tab = _htabs.scan_flags_for_tab


# Per-rule severity → row accent color
_SEVERITY_COLORS = {
    "warn":  "#A6772A",
    "error": FLAG_RED,
    "info":  TEXT_GRAY,
}


class HygieneApp(ToolPanel):
    TOOL_TITLE = "Hygiene"
    TOOL_GEOMETRY_KEY = "hygiene_geometry"

    # Cache freshness window — beyond this age the on_show flow forces a
    # fresh scan automatically. The user can always click Re-scan to
    # bypass the cache entirely.
    CACHE_TTL_MINUTES = 10

    # Cap how many rows we render per section. Without this the panel
    # tries to build a Tk widget tree for every result, and a 3000-row
    # scan freezes the launcher for 30+ seconds during render. Cap is
    # generous enough to cover any normal day; the rest are still in
    # `self._sections` and visible via filtering, just not rendered.
    MAX_ROWS_PER_SECTION = 75

    # Soft cap below which all rows show by default. Past this, the
    # section renders the first N then a "▼ Show K more" toggle so the
    # user isn't bombarded with 60-row hygiene dumps the moment they
    # open the panel. Per-section state persisted across sessions.
    COLLAPSE_THRESHOLD = 50

    # Hourly XA inbox mini-scan cadence. Picks up new donotreply@xactware
    # notification emails between full scans so the user doesn't have to
    # click Re-scan to see fresh adjuster requests. Lightweight — only
    # walks the inbox; skips the Trello hygiene + closeout passes. Set
    # high enough (1 hour) that even an open-all-day session only does
    # ~8 background scans, each ≤30s.
    _XA_MINI_SCAN_INTERVAL_MS = 3600 * 1000
    # Smaller inbox window than the full scan (60 days) — hourly cadence
    # means the last 14 days is plenty to catch fresh requests.
    _XA_MINI_SCAN_WINDOW_DAYS = 14

    def __init__(self, parent):
        super().__init__(parent)
        self.configure(bg=BG)
        # Cancellation guard: each scan thread carries an int that must
        # match self._scan_id when it returns; otherwise its results are
        # ignored. Stops a slow scan from overwriting a fresher one.
        self._scan_id = 0
        self._scanning = False
        # Hard-stop flag the bg thread checks between cards so close
        # doesn't have to wait for the entire scan to drain. Also
        # prevents any after() callbacks from running past close.
        self._closed = False
        # Soft-pause flag set on tab switch (on_hide) — the bg scan
        # keeps running so results are ready when the user returns,
        # but UI-touching after() callbacks become no-ops while
        # hidden. Without this, the launcher's update_idletasks() in
        # _show_panel can re-enter Tk's event loop while a queued
        # progress callback is mid-flight, causing the whole launcher
        # to lock up on tab switch.
        self._hidden = False
        # Track all scheduled after() ids so on_close can cancel them.
        # Without this, pending callbacks fire against destroyed
        # widgets and raise TclError on close — which is what was
        # leaving zombie pythonw processes behind.
        self._after_ids: set[str] = set()
        self._show_dismissed = tk.BooleanVar(value=False)
        # Board filter: "" = all boards, otherwise a specific board id.
        # Persisted across sessions so refresh-and-relaunch keeps focus
        # on whichever board the user was working in.
        self._board_filter = tk.StringVar(
            value=per.get("hygiene_board_filter") or "")
        self._board_filter.trace_add(
            "write", lambda *_: self._on_board_filter_changed())
        # Free-text filter across every section. Session-only — search
        # box is for "is X on the panel right now," not a persisted view.
        self._text_filter = tk.StringVar(value="")
        self._text_filter_after_id = None
        # board_id → display name map, populated lazily once we have
        # rows so the dropdown can show real names.
        self._board_names: dict[str, str] = {}
        # Section data caches: {section_key: [row_dict, ...]}
        self._sections: dict[str, list[dict]] = {k: [] for k, *_ in _SECTIONS}
        self._section_frames: dict[str, tk.Frame] = {}
        self._section_count_lbls: dict[str, tk.Label] = {}
        self._section_body_wraps: dict[str, tk.Frame] = {}
        # Per-section expanded state. Persisted as the list of keys that
        # are currently expanded so a user who clicked Show All on Hygiene
        # last session sees Hygiene already expanded next time.
        try:
            saved = per.get("hygiene_section_expanded") or []
        except Exception:
            saved = []
        if not isinstance(saved, list):
            saved = []
        # Default all sections to expanded so items are always visible
        # without needing to click "Show K more". User can still collapse
        # individual sections; that preference is then persisted.
        self._section_expanded: dict[str, bool] = {
            k: True for k, *_ in _SECTIONS}
        # Active tab — persisted across sessions. Default = Action Needed
        # (most-urgent rows). Falls back to default if the saved key is
        # stale (a tab was renamed in a build).
        try:
            saved_tab = per.get("hygiene_active_tab") or _DEFAULT_TAB
        except Exception:
            saved_tab = _DEFAULT_TAB
        if saved_tab not in _TAB_KEYS:
            saved_tab = _DEFAULT_TAB
        self._active_tab = saved_tab
        self._tab_btns: dict[str, tk.Button] = {}
        self._build_ui()
        # Kick off the cache-or-scan flow shortly after construct so the
        # background scan runs even when the user is working in other
        # tabs. By the time they switch to Hygiene, results are usually
        # already populated. The launcher's _preload_panels constructs
        # every embedded panel after startup, so this will fire once
        # per launcher session — and the persistence cache (30-min TTL)
        # prevents re-scanning when the launcher is reopened quickly.
        self._track_after(150, self._load_cached_or_scan)
        # Schedule the XA inbox mini-scan. Lightweight email walk that
        # picks up new donotreply@xactware notifications, adjuster
        # inquiry queue entries, and (via dispute_email_scan) new
        # dispute mentions — without re-scanning Trello.
        #
        # First tick fires shortly after first paint (the user just
        # opened the panel; they likely WANT a fresh sweep, and
        # waiting a full hour means the launcher's only-session-of-the-day
        # case never sees new inbound mail until the next session
        # rolls over). Subsequent ticks re-arm at the full
        # _XA_MINI_SCAN_INTERVAL_MS cadence inside _run_xa_mini_scan.
        self._xa_mini_scan_after_id = None
        self._track_after(60_000, self._run_xa_mini_scan)

    # ── UI build ──────────────────────────────────────────────────────────
    def _build_ui(self):
        # Top control band
        ctl = tk.Frame(self, bg=BG, padx=14, pady=10)
        ctl.pack(fill="x")
        tk.Label(ctl, text="Trello hygiene & closeout watcher",
                 font=("Fraunces", 15, "bold"),
                 bg=BG, fg=TEXT_DARK).pack(side="left")
        self._status_lbl = tk.Label(ctl, text="",
                                     font=("Segoe UI Variable", 9, "italic"),
                                     bg=BG, fg=TEXT_GRAY)
        self._status_lbl.pack(side="left", padx=(14, 0))

        # Re-scan button rescans ONLY the active tab — its label
        # updates on every _switch_tab so the user can see which slice
        # they're refreshing. A full-workspace rescan still happens on
        # first-run when no cached data exists.
        self._refresh_btn = done_button(
            ctl, "↻ Re-scan", padx=14, pady=4,
            command=lambda: self._start_scan(self._active_tab))
        self._refresh_btn.pack(side="right")
        # 📋 Copy summary — end-of-day affordance. Compiles a Teams-paste-
        # ready status note across every populated section so the user
        # doesn't have to hand-write the daily roll-up. Toast on success.
        copy_btn = secondary_button(
            ctl, "📋 Copy summary", padx=12, pady=4,
            font=("Segoe UI Variable", 9, "bold"),
            command=self._copy_hygiene_summary)
        copy_btn.pack(side="right", padx=(0, 8))
        try:
            from tool_panel import attach_tooltip
            attach_tooltip(
                copy_btn,
                "Copy a one-paragraph end-of-day Hygiene roll-up to the "
                "clipboard — paste straight into Teams / Slack for the "
                "EOD status note.")
        except Exception:
            pass
        tk.Checkbutton(
            ctl, text="Show dismissed",
            variable=self._show_dismissed, bg=BG, fg=TEXT_DARK,
            activebackground=BG, selectcolor=WHITE,
            font=("Segoe UI Variable", 9), cursor="hand2",
            command=self._redraw_all
        ).pack(side="right", padx=(0, 12))

        # Board filter dropdown — populated lazily once we have rows.
        # Empty value = "All boards"; specific value = board id.
        tk.Label(ctl, text="Board:",
                 font=("Segoe UI Variable", 9), bg=BG, fg=TEXT_DARK
                 ).pack(side="right", padx=(0, 4))
        self._board_combo = ttk.Combobox(
            ctl, textvariable=self._board_filter,
            state="readonly", width=22, font=("Segoe UI Variable", 9),
            values=("All boards",))
        self._board_combo.pack(side="right", padx=(0, 12))

        # Free-text search — hides rows across every section that don't
        # contain the substring (case-insensitive). Debounced 150ms so
        # each keystroke doesn't trigger a full _redraw_all.
        tk.Label(ctl, text="🔍",
                 font=("Segoe UI Emoji", 10), bg=BG, fg=TEXT_DARK
                 ).pack(side="right", padx=(0, 2))
        search_entry = tk.Entry(
            ctl, textvariable=self._text_filter,
            font=("Segoe UI Variable", 9), width=22,
            relief="solid", bd=1)
        search_entry.pack(side="right", padx=(0, 6))
        self._text_filter.trace_add(
            "write", lambda *_: self._on_text_filter_changed())
        self._search_entry = search_entry
        # Esc clears the box while it has focus — standard "cancel
        # find" gesture. Returning "break" stops the event from
        # propagating to any parent that might also bind Esc.
        def _clear_search(_e=None):
            try:
                self._text_filter.set("")
            except tk.TclError:
                pass
            return "break"
        search_entry.bind("<Escape>", _clear_search)
        # Ctrl+F focuses the search box. Bound on the toplevel via
        # bind_all (the only way to catch the shortcut regardless of
        # which child widget has focus), but the handler checks
        # `winfo_ismapped()` first so the shortcut only fires while
        # the Hygiene panel is the active tab — other panels keep
        # their own Ctrl+F semantics (or none).
        def _focus_search(_e=None):
            try:
                if not self.winfo_ismapped() or self._closed:
                    return None
                self._search_entry.focus_set()
                self._search_entry.select_range(0, "end")
            except tk.TclError:
                return None
            return "break"
        self.bind_all("<Control-f>", _focus_search, add="+")
        # Funnel name kept so on_close can `unbind_all` symmetrically.
        self._ctrl_f_focus_handler = _focus_search
        try:
            from tool_panel import attach_tooltip
            attach_tooltip(
                search_entry,
                "Filter visible Hygiene rows by client / claim # / sender / "
                "subject text. Ctrl+F to focus · Esc to clear · empty = "
                "show all.")
        except Exception:
            pass

        # Progress strip — only visible during a scan. Determinate bar
        # plus a counter line ("47/499 · Smith, John · ETA 4m") so the
        # user sees that the scan is alive even on Trello's slow stretches.
        self._progress_wrap = tk.Frame(self, bg=BG, padx=14)
        # Don't pack yet — _start_scan / _finish_scan toggle visibility.
        # Bar packed without fill/expand so its width stays fixed at
        # `length=400` regardless of label content. The label fills
        # the remaining horizontal space, so longer card names eat
        # label space — the bar never shifts.
        self._progress_bar = ttk.Progressbar(
            self._progress_wrap, mode="determinate",
            length=400, maximum=100, value=0)
        self._progress_bar.pack(side="left", pady=(0, 4))
        self._progress_lbl = tk.Label(
            self._progress_wrap, text="",
            font=("Segoe UI Variable", 9), bg=BG, fg=TEXT_GRAY,
            anchor="w")
        self._progress_lbl.pack(side="left", padx=(10, 0), pady=(0, 4),
                                  fill="x", expand=True)

        # Tab strip — groups the 8 sections into 3 nav tabs by intent.
        # Lives ABOVE the scrollable body so it stays visible while the
        # user scrolls a long section. Tab counts roll up the per-section
        # counts (filtered the same way the section bodies are).
        # pady-tuple must go on .pack(), NOT on tk.Frame() — the
        # widget constructor only accepts scalar screen-distance values
        # and throws "bad screen distance" on a 2-tuple.
        # Tab strip — same styling pattern as the audit panel's
        # Daily Run / Initial Upload / Backlog / SP Recent buttons.
        # Inactive tabs sit one elevation above the panel bg (SURFACE_2)
        # with muted gray text; active gets the sage GREEN_DARK fill
        # with cream label for clear "selected" affordance.
        self._tab_strip = tk.Frame(self, bg=BG, padx=14, pady=6)
        self._tab_strip.pack(fill="x", pady=(0, 6))
        for tab_key, tab_label, _section_keys in _TABS:
            btn = tk.Button(
                self._tab_strip, text=tab_label,
                font=("Segoe UI Variable", 10),
                bg=SURFACE_2, fg=TEXT_GRAY,
                activebackground=NEUTRAL_HOVER,
                activeforeground=TEXT_DARK,
                relief="flat", bd=0, padx=14, pady=6, cursor="hand2",
                command=lambda k=tab_key: self._switch_tab(k))
            btn.pack(side="left", padx=(0 if tab_key == _TABS[0][0] else 4, 0))
            self._tab_btns[tab_key] = btn

        # Body — scrollable column of section panels
        scroll = ScrollableFrame(self, bg=BG, padx=14, pady=4)
        scroll.pack(fill="both", expand=True)
        self._scroll = scroll
        self._body = scroll.inner
        self._virt = VirtualizedCardList(scroll, overscan_px=600)
        # Loading overlay — covers the scroll area while _redraw_all is
        # walking its staggered render so the user sees a single "Loading…"
        # state instead of sections popping in one at a time. Lazy-created
        # on first show. _loading_show_after_id tracks a 100ms delay so a
        # no-op redraw (cache hit, single section) never flashes the
        # overlay; it only appears when the render is slow enough to be
        # visible as a stutter.
        self._loading_overlay = None
        self._loading_show_after_id = None
        for key, icon, title, hint in _SECTIONS:
            self._build_section(self._body, key, icon, title, hint)
        # Apply the persisted/default tab — hides sections not in this
        # tab and updates tab-button styling. Done AFTER all sections
        # are built so the pack order is well-defined.
        self._apply_active_tab()

    def _build_section(self, parent, key, icon, title, hint):
        wrap = tk.Frame(parent, bg=WHITE,
                        highlightthickness=1, highlightbackground=BORDER)
        wrap.pack(fill="x", pady=(0, 12))
        # Header bar
        hdr = tk.Frame(wrap, bg=WHITE, padx=12, pady=8)
        hdr.pack(fill="x")
        tk.Label(hdr, text=f"{icon}  {title}",
                 font=("Segoe UI Variable", 11, "bold"),
                 bg=WHITE, fg=TEXT_DARK).pack(side="left")
        cnt = tk.Label(hdr, text="(–)",
                       font=("Segoe UI Variable", 10),
                       bg=WHITE, fg=TEXT_GRAY)
        cnt.pack(side="left", padx=(8, 0))
        tk.Label(hdr, text=hint,
                 font=("Segoe UI Variable", 8, "italic"),
                 bg=WHITE, fg=TEXT_GRAY).pack(side="left", padx=(14, 0))
        # Per-section header actions. xa_apology gets a "Copy apology
        # note" button so the user can paste the standard text into XA
        # without re-typing it every job. Other sections can grow their
        # own header buttons here without touching the core layout.
        if key == "xa_apology":
            try:
                from ui_buttons import secondary_button
                secondary_button(
                    hdr, "🔔 Copy apology note",
                    padx=10, pady=2,
                    font=("Segoe UI Variable", 9),
                    command=self._copy_xa_apology_note,
                    tooltip=("Copy the standard XA apology text to your "
                             "clipboard so you can paste it into XactAnalysis "
                             "for each job that needs it."),
                ).pack(side="right")
            except Exception:
                pass

        body = tk.Frame(wrap, bg=WHITE, padx=12)
        body.pack(fill="x", pady=(0, 8))
        self._section_frames[key] = wrap
        self._section_count_lbls[key] = cnt
        self._section_body_wraps[key] = body
        self._virt.register(body, lambda _f, k=key: self._render_section_inner(k))

    # ── Tab navigation ────────────────────────────────────────────────────
    def _switch_tab(self, tab_key):
        """User clicked a tab button. Hide non-matching sections,
        re-show matching ones in their canonical _SECTIONS order, and
        persist the choice so the panel reopens on the same tab."""
        if tab_key not in _TAB_KEYS:
            return
        self._active_tab = tab_key
        self._apply_active_tab()
        try:
            per.set_value("hygiene_active_tab", tab_key)
        except Exception:
            pass

    def _apply_active_tab(self):
        """Hide section frames not in the active tab; re-pack the
        matching ones in _SECTIONS order. Pack-forget is safe to call
        on already-hidden frames; the order is reset by repacking
        in canonical sequence so a previously-hidden section slots
        back in the right spot."""
        active_keys = set()
        for tk_key, _label, sec_keys in _TABS:
            if tk_key == self._active_tab:
                active_keys = set(sec_keys)
                break
        for sec_key in self._section_frames:
            try:
                self._section_frames[sec_key].pack_forget()
            except tk.TclError:
                pass
        for sec_key, _icon, _title, _hint in _SECTIONS:
            if sec_key in active_keys:
                try:
                    self._section_frames[sec_key].pack(
                        fill="x", pady=(0, 12))
                except tk.TclError:
                    pass
        self._refresh_tab_chrome()

    def _refresh_tab_chrome(self):
        """Recompute each tab's rolled-up count and update button
        styling so the active tab pops. Called after every section
        render and after board / dismissed filter changes — keeps the
        tab badges in lockstep with what's actually rendered below.

        Side effect: publishes the 🔴 Action-Needed count to
        persistence (`hygiene_action_needed_count`) so other surfaces
        — the launcher's Hygiene button badge in particular — can
        read a live count without spinning up the whole panel."""
        action_count = 0
        for tk_key, tk_label, sec_keys in _TABS:
            n = 0
            for sk in sec_keys:
                rows = self._sections.get(sk) or []
                try:
                    if not self._show_dismissed.get():
                        rows = self._filter_dismissed(rows)
                    rows = self._apply_board_filter(rows)
                    rows = self._apply_text_filter(rows)
                except Exception:
                    pass
                n += len(rows)
                # Always keep the section header count in sync here —
                # this runs for every section on every tab, so collapsed
                # and off-screen sections never show a stale "(–)".
                try:
                    cnt_lbl = self._section_count_lbls.get(sk)
                    if cnt_lbl is not None:
                        cnt_lbl.configure(
                            text=f"({len(rows)})",
                            fg=TEXT_GRAY if not rows else GREEN_DARK)
                except Exception:
                    pass
            if tk_key == "action":
                action_count = n
            btn = self._tab_btns.get(tk_key)
            if btn is None:
                continue
            is_active = (tk_key == self._active_tab)
            try:
                btn.config(
                    text=f"{tk_label}  ({n})",
                    bg=GREEN_DARK if is_active else SURFACE_2,
                    fg=WHITE if is_active else TEXT_GRAY,
                    activebackground=(GREEN_DARK if is_active
                                       else NEUTRAL_HOVER),
                    activeforeground=(WHITE if is_active else TEXT_DARK),
                    font=("Segoe UI Variable", 10,
                          "bold" if is_active else "normal"),
                    relief="flat", bd=0,
                )
            except tk.TclError:
                pass
        # Update the Re-scan button to reflect the active tab so the
        # user can see which slice will be rescanned. Skip while a scan
        # is in progress — _start_scan owns the label until it finishes.
        if not self._scanning:
            try:
                lbl = _TAB_BUTTON_LABELS.get(self._active_tab, "")
                self._refresh_btn.configure(
                    text=f"↻ Re-scan {lbl}" if lbl else "↻ Re-scan")
            except (tk.TclError, AttributeError):
                pass

        # Publish Action-Needed count for the launcher badge. Best-effort —
        # if persistence write fails, just skip; badge will sync next tick.
        try:
            per.set_value("hygiene_action_needed_count", int(action_count))
        except Exception:
            pass

    # ── Hourly XA mini-scan ───────────────────────────────────────────────
    def _run_xa_mini_scan(self):
        """Background-thread XA inbox walk that runs every hour while
        the Hygiene panel is alive. Refreshes `xa_gaps`, `estimates`,
        and `disputes` sections (the latter via dispute_email_scan)
        without touching the Trello hygiene scan (which is heavier
        and runs on its own cadence — manual rescan or cache miss).

        Skipped silently when a full scan is currently in progress
        (avoids two threads writing the same section). Re-schedules
        itself for the next interval regardless of outcome so a
        transient inbox failure doesn't disable the auto-refresh."""
        if self._closed:
            return
        # Defer when a full scan is already underway — the full scan
        # writes the same sections, so racing it would be a write-write
        # collision with stale loser. Reschedule for next hour and
        # let the full scan publish its results normally.
        if self._scanning:
            self._xa_mini_scan_after_id = self._track_after(
                self._XA_MINI_SCAN_INTERVAL_MS, self._run_xa_mini_scan)
            return

        def _bg():
            try:
                import xa_email_ingest as xei
                xa_result = xei.scan_inbox(
                    days=self._XA_MINI_SCAN_WINDOW_DAYS,
                    progress_cb=None)
                xa_groups = xei.filter_unresolved(
                    xa_result.get("groups") or [])
            except Exception:
                xa_groups = None

            est_rows = None
            if xa_groups is not None:
                try:
                    import estimate_requests as er
                    import adjuster_monitor as am
                    try:
                        # dry_run=False writes to adjuster_pending_approval
                        # (the user-approval queue) without ever calling
                        # tc.post_comment — safe from the GUI thread.
                        # _redraw_all picks the new entries up afterwards.
                        adj_result = am.scan_and_post(days=14, dry_run=False)
                    except Exception:
                        adj_result = None
                    er.detect_pending(xa_groups, adj_result)
                    est_rows = er.all_active()
                except Exception:
                    est_rows = None

            # Dispute email scan — feeds the Dispute Tracker workbook
            # independently of the cron (Task Scheduler may not be
            # running on every workstation). Idempotent via
            # `dispute_email_seen` persistence, so re-scans are cheap.
            try:
                import dispute_email_scan as _des
                _des.scan_inbox(days=14)
            except Exception:
                pass
            # Re-read the open disputes after the email scan so any
            # newly-imported rows appear in the ⚖ section without
            # waiting for a manual rescan.
            dispute_rows = None
            try:
                import dispute_tracker as _dt
                dispute_rows = _dt.open_disputes()
            except Exception:
                dispute_rows = None

            def _apply():
                if self._closed:
                    return
                # If a full scan kicked off while we were in the
                # worker thread, drop these results — its writes will
                # be authoritative.
                if self._scanning:
                    return
                if xa_groups is not None:
                    self._sections["xa_gaps"] = list(xa_groups)
                    try:
                        self._render_section("xa_gaps")
                    except Exception:
                        pass
                if est_rows is not None:
                    self._sections["estimates"] = list(est_rows)
                    try:
                        self._render_section("estimates")
                    except Exception:
                        pass
                if dispute_rows is not None:
                    self._sections["disputes"] = list(dispute_rows)
                    try:
                        self._render_section("disputes")
                    except Exception:
                        pass
                # Roll the new counts onto the tab badges so the user
                # sees the section badge tick without re-opening the
                # panel.
                try:
                    self._refresh_tab_chrome()
                except Exception:
                    pass
            try:
                self.after(0, _apply)
            except tk.TclError:
                pass

        try:
            import threading as _th
            _th.Thread(target=_bg, daemon=True).start()
        except Exception:
            pass

        # Always re-arm — even on a worker-thread failure we want next
        # hour's tick to try again.
        self._xa_mini_scan_after_id = self._track_after(
            self._XA_MINI_SCAN_INTERVAL_MS, self._run_xa_mini_scan)

    # ── Cache-aware first paint ───────────────────────────────────────────
    def _load_cached_or_scan(self):
        """Render last scan from persistence if fresh; otherwise auto-scan."""
        # Guard against the deferred __init__ schedule firing AFTER the
        # panel was closed (e.g. user opens launcher, closes it within
        # 150ms; the scheduled callback would still fire and try to
        # touch destroyed widgets).
        if self._closed:
            return
        cache = per.get_hygiene_scan_cache(
            max_age_minutes=self.CACHE_TTL_MINUTES)
        if cache is None:
            self._start_scan()
            return
        payload, age_s = cache
        hygiene_rows = payload.get("hygiene") or []
        closeout_rows = payload.get("closeout") or []
        xa_rows = payload.get("xa_apology") or []
        self._sections["concerns"] = [v for v in hygiene_rows
                                       if v.get("rule") == "customer_complaint"]
        self._sections["handoff"]  = [v for v in hygiene_rows
                                       if v.get("rule") == "lane_move_no_handoff"]
        self._sections["hygiene"]  = [
            v for v in hygiene_rows
            if v.get("rule") not in ("customer_complaint",
                                     "lane_move_no_handoff")]
        self._sections["xa_apology"] = list(xa_rows)
        self._sections["xa_gaps"] = list(payload.get("xa_gaps") or [])
        # Cron supplement: if xa_email_ingest_cron has run more recently
        # than the in-app cache, prefer its xa_gaps so the user sees
        # everything that arrived while the launcher was closed.
        try:
            cron_iso = per.get("xa_cron_last_run") or ""
            if cron_iso:
                import datetime as _dt
                cron_dt = _dt.datetime.fromisoformat(cron_iso)
                # `age_s` from above is age of the in-app cache in
                # seconds; cron-newer means it ran fewer seconds ago.
                cron_age_s = (
                    _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None) - cron_dt).total_seconds()
                if cron_age_s < age_s:
                    cron_groups = per.get("xa_cron_groups") or []
                    if cron_groups:
                        self._sections["xa_gaps"] = list(cron_groups)
        except Exception:
            pass
        self._sections["ipr"] = list(payload.get("ipr") or [])
        self._sections["closeout"] = list(closeout_rows)
        # Adjuster pending-approval queue lives in persistence, not the
        # scan cache — the email scan that queues it runs from the cron
        # path (xa_email_ingest_cron). Read directly so an approval done
        # in another launcher session shows up immediately here.
        try:
            import adjuster_monitor as am
            self._sections["adjuster_pending"] = am.list_pending()
        except Exception:
            self._sections["adjuster_pending"] = []
        # Disputes — open + overdue rows pulled live from the Dispute
        # Tracker workbook. The tracker auto-imports from APA Monitor
        # AND dispute_email_scan; this section is the read-out of
        # what's open right now. Run on a background thread so the
        # synchronous xlsx open doesn't block the cache-or-scan path
        # the Hygiene panel uses at first paint (50-200ms per read
        # times all panels = perceptible startup lag during the
        # launcher's preload sweep).
        self._sections["disputes"] = []
        try:
            import threading as _th
            def _bg_disputes():
                try:
                    import dispute_tracker as _dt
                    rows = _dt.open_disputes()
                except Exception:
                    rows = []
                def _apply():
                    if self._closed:
                        return
                    self._sections["disputes"] = rows
                    try:
                        self._render_section("disputes")
                    except Exception:
                        pass
                try:
                    self.after(0, _apply)
                except Exception:
                    pass
            _th.Thread(target=_bg_disputes, daemon=True).start()
        except Exception:
            pass
        # Estimates pull from persistence directly rather than the
        # cached payload — single persistence read, always live, and
        # picks up any acks/completions the user did between sessions.
        try:
            import estimate_requests as er
            self._sections["estimates"] = er.all_active()
        except Exception:
            self._sections["estimates"] = list(payload.get("estimates") or [])
        # Weekly check-ins — cached payload is fine, the actual
        # cadence math runs at find_due_cards time. Next scan will
        # refresh.
        self._sections["weekly"] = list(payload.get("weekly") or [])
        # Cache hit: still want the board dropdown populated so the
        # user can filter the cached data without re-scanning.
        try:
            self._populate_board_filter()
        except Exception:
            pass
        age_label = (f"{int(age_s // 60)}m ago"
                     if age_s >= 60 else f"{int(age_s)}s ago")
        self._status_lbl.configure(
            text=f"Cached scan ({age_label}) — click ↻ Re-scan for fresh data.")
        self._redraw_all()

    # ── Scan kickoff (background) ─────────────────────────────────────────
    def _start_scan(self, tab=None):
        """Run the Trello scan. `tab` selects which sections to refresh:

        - "action"  → concerns, ipr, xa_apology (docusketch refreshes
                       lazily on redraw, no Trello cost)
        - "quality" → hygiene, handoff, closeout
        - "stale"   → xa_gaps (email-only walk, no Trello)
        - None      → full workspace pass (every section)

        Sections outside the chosen tab keep their existing rows. The
        Re-scan button rescans the active tab by default; the cache-or-
        scan first-paint passes None to force a full scan.
        """
        if self._scanning:
            return
        if tab is not None and tab not in _TAB_KEYS:
            tab = None
        self._scan_tab = tab  # None = full
        # Re-scan invalidates the persisted cache up front so a crash /
        # cancel during the scan doesn't leave stale data masquerading
        # as fresh on the next reopen.
        try:
            per.clear_hygiene_scan_cache()
        except Exception:
            pass
        self._scanning = True
        self._scan_id += 1
        my_id = self._scan_id
        self._scan_started_at = time.time()
        scan_label = (_TAB_BUTTON_LABELS.get(tab, "")
                      if tab else "everything")
        self._refresh_btn.configure(text="…scanning", state="disabled")
        self._status_lbl.configure(
            text=f"Scanning {scan_label}…" if scan_label else "Scanning…")
        # Show the progress strip + reset the bar
        try:
            self._progress_wrap.pack(fill="x", before=self._body.master.master,
                                      pady=(0, 4))
        except (tk.TclError, AttributeError):
            # before= can fail on first paint; fall back to plain pack.
            self._progress_wrap.pack(fill="x", pady=(0, 4))
        self._progress_bar.configure(value=0, maximum=100)
        self._progress_lbl.configure(text="Enumerating boards…")
        # Clear only the section rows owned by this tab so the user
        # sees the panel react immediately, while sections outside
        # the tab keep their current rows (and the user keeps working).
        if tab is None:
            sections_to_clear = list(self._sections.keys())
        else:
            sections_to_clear = list(_tab_section_keys(tab))
        for key in sections_to_clear:
            self._sections[key] = []
            self._render_section(key)

        def _bg():
            # Throttle UI updates: pushing every callback through after()
            # adds Tk events at ~2 Hz, which is plenty smooth for a 4-min
            # scan and doesn't flood the event loop. Keep the latest
            # progress in a small dict the main thread polls.
            last_emit = [0.0]

            def _on_progress(done, total, name):
                if my_id != self._scan_id:
                    return
                # Enumeration phase events arrive with total=0 — always
                # forward those (they're rare; one per board) so the
                # user sees activity during the slow boards/lists walk
                # before the per-card phase starts.
                if total == 0:
                    self.after(0, lambda d=done, t=total, n=name:
                               self._on_scan_progress(my_id, d, t, n))
                    return
                now = time.time()
                # Always emit on first + last; throttle the middle to ~2/s
                if not (done == 1 or done == total
                        or now - last_emit[0] >= 0.5):
                    return
                last_emit[0] = now
                if self._closed:
                    return
                try:
                    self.after(0, lambda d=done, t=total, n=name:
                               self._on_scan_progress(my_id, d, t, n))
                except tk.TclError:
                    return

            # Per-tab include flags. None = full pass (default).
            flags = _scan_flags_for_tab(tab)
            try:
                import trello_hygiene as th
                if flags["any_workspace"]:
                    results = th.scan_workspace(
                        include_hygiene=flags["hygiene"],
                        include_handoff=flags["handoff"],
                        include_closeout=flags["closeout"],
                        include_xa_gaps=flags["xa_gaps"],
                        include_ipr=flags["ipr"],
                        progress_cb=_on_progress)
                else:
                    results = {"hygiene": [], "closeout": [],
                               "xa_gaps": [], "ipr": []}
                # AR Board → XA apology worklist runs only when the
                # action tab is being refreshed (or on a full pass).
                xa_rows = None  # None = "don't overwrite the existing section"
                if flags["ar_followup"]:
                    xa_rows = []
                    try:
                        import ar_followup as arf
                        xa_rows = arf.find_stale_cards()
                    except Exception:
                        pass
                # Stale-tab-only path: skip the Trello walk entirely
                # and pull XA gaps directly from the inbox. Faster
                # rescan when the user is only chasing stale notes.
                if flags["xa_gaps_only"]:
                    try:
                        import xa_email_ingest as xei
                        xa_result = xei.scan_inbox(days=60, progress_cb=None)
                        results = {
                            "hygiene": [],
                            "closeout": [],
                            "ipr": [],
                            "xa_gaps": xei.filter_unresolved(
                                xa_result.get("groups") or []),
                        }
                    except Exception:
                        results = {"hygiene": [], "closeout": [],
                                    "ipr": [], "xa_gaps": []}
                # Weekly check-ins — every card on the Estimating
                # board needs a status note ≥ once a week. The scanner
                # walks every list on that board and returns cards
                # whose last weekly note is 7+ days old (or never).
                # Best-effort — returns [] when Trello / the board
                # isn't reachable.
                weekly_rows = None
                if flags["weekly"]:
                    try:
                        import weekly_checkins as _wc
                        weekly_rows = _wc.find_due_cards()
                    except Exception:
                        weekly_rows = []
                # Estimate-request detection — pulls fresh inbox data
                # (XA notes + adjuster emails) and folds them into the
                # persistence-backed estimate_requests store. Returns
                # the active set (pending / acked / overdue). Best-
                # effort: returns None when Outlook is unavailable.
                est_rows = None
                if flags["estimates"]:
                    try:
                        import estimate_requests as er
                        # Reuse the xa_gaps groups when we already have
                        # them — avoids a second inbox walk. Otherwise
                        # pull them now (a 14-day window is enough for
                        # active inquiries).
                        xa_groups = results.get("xa_gaps") or []
                        if not xa_groups:
                            try:
                                import xa_email_ingest as xei
                                xa_groups = (xei.scan_inbox(days=14).get(
                                    "groups") or [])
                            except Exception:
                                xa_groups = []
                        adj_result = None
                        try:
                            import adjuster_monitor as am
                            # dry_run=False writes to the approval queue
                            # (adjuster_pending_approval) without posting
                            # — safe from the scan thread; _redraw_all
                            # picks the new entries up after the scan.
                            adj_result = am.scan_and_post(
                                days=14, dry_run=False)
                        except Exception:
                            adj_result = None
                        er.detect_pending(xa_groups, adj_result)
                        est_rows = er.all_active()
                    except Exception:
                        est_rows = None
            except Exception as ex:
                err = str(ex)
                if not self._closed:
                    try:
                        self.after(0, lambda: self._scan_failed(my_id, err))
                    except tk.TclError:
                        pass
                return
            if self._closed:
                return
            try:
                self.after(0, lambda: self._scan_finished(
                    my_id,
                    results.get("hygiene", []),
                    results.get("closeout", []),
                    xa_rows,
                    results.get("xa_gaps", []),
                    results.get("ipr", []),
                    est_rows,
                    weekly_rows))
            except tk.TclError:
                return

        threading.Thread(target=_bg, daemon=True).start()

    def _on_scan_progress(self, my_id, done, total, name):
        if self._closed or self._hidden or my_id != self._scan_id:
            return
        try:
            # Enumeration-phase event: total == 0, name = "Listing
            # board ..." — we just update the label.
            if total <= 0:
                self._progress_lbl.configure(text=name or "Enumerating…")
                return
            pct = max(0.0, min(100.0, 100.0 * done / total))
            self._progress_bar.configure(value=pct, maximum=100)
            elapsed = max(0.001, time.time() - self._scan_started_at)
            rate = done / elapsed
            eta_s = (total - done) / rate if rate > 0 else 0
            eta = (f"{int(eta_s // 60)}m {int(eta_s % 60)}s"
                   if eta_s >= 60 else f"{int(eta_s)}s")
            short_name = (name or "")[:46]
            self._progress_lbl.configure(
                text=f"{done}/{total} · {short_name}  ·  ETA {eta}")
        except tk.TclError:
            # Widget gone / hidden / mid-teardown — drop the update
            # silently. The next valid progress callback will catch up.
            return

    def _hide_progress(self):
        try:
            self._progress_wrap.pack_forget()
        except tk.TclError:
            pass

    def _scan_failed(self, my_id, err):
        if self._closed or my_id != self._scan_id:
            return
        self._scanning = False
        lbl = _TAB_BUTTON_LABELS.get(self._active_tab, "")
        self._refresh_btn.configure(
            text=f"↻ Re-scan {lbl}" if lbl else "↻ Re-scan",
            state="normal")
        self._status_lbl.configure(text=f"Scan failed: {err[:80]}")
        self._hide_progress()

    def _scan_finished(self, my_id, violations, closeouts, xa_rows=None,
                       xa_gaps=None, iprs=None, estimates=None,
                       weekly=None):
        if self._closed or my_id != self._scan_id:
            return
        # If we're hidden mid-scan, still record the results into
        # self._sections so they're ready when the user comes back —
        # but defer any widget configuration until on_show triggers a
        # redraw. This is the difference between losing 4 minutes of
        # scan work and not.
        try:
            self._scan_finished_impl(
                my_id, violations, closeouts, xa_rows, xa_gaps, iprs,
                estimates, weekly)
        except tk.TclError:
            return
        except Exception as ex:
            try:
                import ems_log
                ems_log.error("hygiene", f"_scan_finished failed: {ex}")
            except Exception:
                pass

    def _scan_finished_impl(self, my_id, violations, closeouts, xa_rows=None,
                             xa_gaps=None, iprs=None, estimates=None,
                             weekly=None):
        self._scanning = False
        scanned_tab = getattr(self, "_scan_tab", None)
        if not self._hidden:
            lbl = _TAB_BUTTON_LABELS.get(self._active_tab, "")
            self._refresh_btn.configure(
                text=f"↻ Re-scan {lbl}" if lbl else "↻ Re-scan",
                state="normal")
        # Split violations into 3 buckets by rule:
        #   customer_complaint → concerns
        #   lane_move_no_handoff → handoff
        #   everything else → hygiene
        concerns_rows = [v for v in violations
                          if v.get("rule") == "customer_complaint"]
        handoff_rows = [v for v in violations
                        if v.get("rule") == "lane_move_no_handoff"]
        hygiene_rows = [v for v in violations
                        if v.get("rule") not in
                        ("customer_complaint", "lane_move_no_handoff")]
        # Map each section key to its freshly-scanned rows. We only
        # overwrite a section when the just-finished scan actually
        # refreshed it (scanned_tab governs that). Sections outside the
        # scanned tab keep their existing rows so a per-tab rescan
        # doesn't wipe rows the user was working on in another tab.
        fresh_rows = {
            "concerns":   concerns_rows,
            "handoff":    handoff_rows,
            "hygiene":    hygiene_rows,
            "closeout":   list(closeouts),
            "ipr":        list(iprs or []),
            "xa_gaps":    list(xa_gaps or []),
        }
        if xa_rows is not None:
            fresh_rows["xa_apology"] = list(xa_rows)
        if estimates is not None:
            fresh_rows["estimates"] = list(estimates)
        if weekly is not None:
            fresh_rows["weekly"] = list(weekly)
        if scanned_tab is None:
            target_sections = set(fresh_rows.keys())
        else:
            target_sections = set(_tab_section_keys(scanned_tab))
        for sec_key, rows in fresh_rows.items():
            if sec_key in target_sections:
                self._sections[sec_key] = rows
        # Refresh the board-filter dropdown so it reflects which
        # boards actually have rows in this scan.
        try:
            self._populate_board_filter()
        except Exception:
            pass
        elapsed = time.time() - getattr(self, "_scan_started_at", time.time())
        elapsed_s = (f"{int(elapsed // 60)}m {int(elapsed % 60)}s"
                     if elapsed >= 60 else f"{int(elapsed)}s")
        if not self._hidden:
            self._status_lbl.configure(
                text=(f"Last scan {datetime.now().strftime('%I:%M %p')} · "
                      f"took {elapsed_s}"))
            self._hide_progress()
        # Rebuild cache payload from self._sections rather than the
        # function args. On a per-tab rescan, `violations` / `closeouts`
        # only cover what THIS scan touched — but the cache needs the
        # complete state (other tabs' sections that weren't refreshed
        # this pass should still be persisted with their existing rows).
        merged_violations = (
            list(self._sections.get("concerns") or [])
            + list(self._sections.get("handoff") or [])
            + list(self._sections.get("hygiene") or []))
        merged_closeouts = list(self._sections.get("closeout") or [])
        # If hidden, skip the redraw — sections are populated, the
        # next on_show will repaint. Cache write still happens so a
        # later launcher run sees fresh data.
        if self._hidden:
            try:
                per.set_hygiene_scan_cache(
                    merged_violations, merged_closeouts,
                    xa_apology=self._sections.get("xa_apology") or [],
                    xa_gaps=self._sections.get("xa_gaps") or [],
                    ipr=self._sections.get("ipr") or [],
                    estimates=self._sections.get("estimates") or [],
                    weekly=self._sections.get("weekly") or [])
            except TypeError:
                # Older persistence build without xa_gaps / ipr / estimates kwarg.
                try:
                    per.set_hygiene_scan_cache(
                        merged_violations, merged_closeouts,
                        xa_apology=self._sections.get("xa_apology") or [])
                except Exception:
                    pass
            except Exception:
                pass
            return
        # Persist the fresh result so the next panel-open is instant.
        # Lists store violation/candidate dicts which json.dump handles
        # natively (every field is str/int/list). XA worklist piggybacks
        # on the cache via an extra kwarg — see set_hygiene_scan_cache.
        try:
            per.set_hygiene_scan_cache(
                merged_violations, merged_closeouts,
                xa_apology=self._sections.get("xa_apology") or [],
                xa_gaps=self._sections.get("xa_gaps") or [],
                ipr=self._sections.get("ipr") or [],
                estimates=self._sections.get("estimates") or [])
        except TypeError:
            # Older persistence builds without the xa_gaps / xa_apology
            # / ipr / estimates kwargs — fall back so the panel still
            # works on mixed deployments.
            try:
                per.set_hygiene_scan_cache(
                    merged_violations, merged_closeouts,
                    xa_apology=self._sections.get("xa_apology") or [])
            except TypeError:
                try:
                    per.set_hygiene_scan_cache(
                        merged_violations, merged_closeouts)
                except Exception as ex:
                    try:
                        import ems_log
                        ems_log.warn("hygiene", f"cache write failed: {ex}")
                    except Exception:
                        pass
            except Exception as ex:
                try:
                    import ems_log
                    ems_log.warn("hygiene", f"cache write failed: {ex}")
                except Exception:
                    pass
        except Exception as ex:
            try:
                import ems_log
                ems_log.warn("hygiene", f"cache write failed: {ex}")
            except Exception:
                pass
        self._redraw_all()
        # Phase 4 — passive enrichment: after every Hygiene scan, walk
        # any newly-tracked lifecycle rows and upgrade their
        # stage_entered_at to the exact Trello lane-entry timestamp.
        # Spawned as a separate background thread so it doesn't block
        # the UI; the lifecycle table was just populated by the scan
        # piggyback in trello_hygiene._iter_all_cards, so this is the
        # natural follow-up step. Idempotent — only un-enriched rows
        # get touched, so the cost amortizes to ~0 after the first run.
        try:
            import threading as _th

            def _bg_enrich():
                try:
                    import pipeline_stages as _ps
                    _ps.enrich_stage_entered_from_actions()
                except Exception:
                    pass
            _th.Thread(target=_bg_enrich, daemon=True).start()
        except Exception:
            pass

    # ── Rendering ─────────────────────────────────────────────────────────
    def _redraw_all(self):
        # Re-filter the closeout section against persistence's drafted
        # dict on every redraw. mark_drafted (called from this panel
        # AND auto-fired by snapshot generation) writes the card_id
        # straight to persistence; without this filter, cards drafted
        # outside the in-memory drop path in _mark_closeout_drafted
        # (e.g. via snapshot_gui's auto-mark on generate) would stay
        # visible until the next full Trello scan.
        try:
            import persistence as _per
            drafted = _per.get("closeout_drafted") or {}
            if isinstance(drafted, dict) and drafted:
                self._sections["closeout"] = [
                    c for c in (self._sections.get("closeout") or [])
                    if c.get("card_id") not in drafted
                ]
        except Exception:
            pass
        # Refresh the docusketch-pending list before rendering — it's
        # backed by persistence (not the Trello scan), so it can change
        # whenever the user clicks "Request via Trello" or imports a
        # zip from another panel. Cheap (one persistence read).
        try:
            import docusketch_requests as dr
            self._sections["docusketch"] = dr.pending_requests()
        except Exception:
            self._sections["docusketch"] = []
        try:
            import docusign_requests as dsr
            self._sections["docusign"] = dsr.pending_requests()
        except Exception:
            self._sections["docusign"] = []
        # Missing-items tracker + docusign-resend SLA. Both backed by
        # persistence — cheap to refresh on every render. needs_physical
        # _signature() posts an escalation comment when the 5-day
        # threshold is first crossed; idempotent thereafter.
        try:
            import missing_items_tracker as mit
            self._sections["missing_items"] = mit.list_open_items()
            self._sections["docusign_resends"] = (
                mit.needs_physical_signature(threshold_days=5))
        except Exception:
            self._sections["missing_items"] = []
            self._sections["docusign_resends"] = []
        # Adjuster pending-approval queue — persistence-backed; the cron
        # path (xa_email_ingest_cron) keeps it fed in the background. A
        # redraw here picks up new entries without waiting for the user
        # to Re-scan, and reflects ✓ Post / ✕ Dismiss decisions made
        # on this panel without a section-only re-render.
        try:
            import adjuster_monitor as am
            self._sections["adjuster_pending"] = am.list_pending()
        except Exception:
            self._sections["adjuster_pending"] = []
        # Open disputes — same pattern. The dispute_tracker workbook
        # is the source of truth; both APA Monitor + dispute_email_scan
        # populate it independently. Threaded so the synchronous xlsx
        # open doesn't block every redraw on the main thread — the
        # section renders empty initially and gets repainted as soon
        # as the bg thread finishes (typically 50-100ms later).
        try:
            import threading as _th
            def _bg_disputes_redraw():
                try:
                    import dispute_tracker as _dt
                    rows = _dt.open_disputes()
                except Exception:
                    rows = []
                def _apply():
                    if self._closed:
                        return
                    self._sections["disputes"] = rows
                    try:
                        self._render_section("disputes")
                    except Exception:
                        pass
                try:
                    self.after(0, _apply)
                except Exception:
                    pass
            _th.Thread(target=_bg_disputes_redraw, daemon=True).start()
        except Exception:
            pass
        # All open Trello jobs — sourced from ems_db. Cheap (single
        # SQLite query); the user runs 🔄 Sync from Trello to refresh
        # the underlying cache.
        try:
            import ems_db
            self._sections["open_jobs"] = ems_db.find_jobs_by_status("active")
        except Exception:
            self._sections["open_jobs"] = []
        # Stalled-in-stage section — pulls from the pipeline lifecycle
        # table that Hygiene's scan keeps fresh on every walk. Threshold
        # check uses pipeline_stages.DEFAULT_STAGE_THRESHOLDS. Cheap
        # (single DB query); the surfacing here is the user's at-a-glance
        # "where are the stallers" cue without having to open Pipeline.
        try:
            import pipeline_stages as _ps
            self._sections["stalled"] = _ps.list_stalled()
        except Exception:
            self._sections["stalled"] = []
        # Anomalous-jobs section — needs historical transition data to
        # be useful. Returns empty until enough transitions accumulate
        # (min_sample=5 per stage), which is honest: "no signal yet".
        # getattr guard so an older pipeline_stages (PyInstaller bundle
        # built pre-Phase-4) doesn't AttributeError.
        try:
            _list_anomalies = getattr(_ps, "list_anomalies", None)
            self._sections["anomalies"] = (
                _list_anomalies() if _list_anomalies is not None else [])
        except Exception:
            self._sections["anomalies"] = []
        # Docusketch-needed (WIP) — cards that just hit Work In Progress
        # and haven't had a Docusketch requested yet. Reads from the
        # same lifecycle table the Anomalies / Stalled sections use, so
        # the data is current whenever Hygiene's scan piggyback runs.
        try:
            import docusketch_requests as _dr
            _find_wip = getattr(_dr, "find_wip_cards_needing_docusketch",
                                  None)
            self._sections["docusketch_needed"] = (
                _find_wip() if _find_wip is not None else [])
        except Exception:
            self._sections["docusketch_needed"] = []
        # Monthly WC audit reminder — surfaces from the first Monday of
        # the month through that Sunday, unless a file already exists
        # for this month in OUTPUT_DIR. Single-row section.
        try:
            import wc_audit as _wca
            import datetime as _dtm
            if _wca.is_audit_due():
                today = _dtm.date.today()
                month_label = today.strftime("%B %Y")
                first_mon = _wca._first_monday_of_month(
                    today.year, today.month)
                days_since = (today - first_mon).days
                self._sections["wc_audit_due"] = [{
                    "month":    month_label,
                    "subtitle": (
                        f"Due since {first_mon.strftime('%b %d')} "
                        f"({days_since}d ago). Click to open the "
                        f"WC Audit panel."),
                }]
            else:
                self._sections["wc_audit_due"] = []
        except Exception:
            self._sections["wc_audit_due"] = []
        # Stagger renders one section per event-loop tick so the UI
        # stays responsive during the initial load burst. _post_redraw
        # runs after the last section and handles tab chrome + tooltips.
        self._schedule_loading_overlay()
        self._render_sections_staggered(list(self._sections.keys()))

    def _render_sections_staggered(self, keys, idx=0):
        if idx >= len(keys):
            self._post_redraw()
            return
        try:
            self._render_section(keys[idx])
        except Exception:
            pass
        try:
            self.after(0, self._render_sections_staggered, keys, idx + 1)
        except Exception:
            self._post_redraw()

    def _post_redraw(self):
        self._hide_loading_overlay()
        try:
            self._refresh_tab_chrome()
        except Exception:
            pass
        try:
            self.after_idle(self.sweep_tooltips)
        except Exception:
            pass

    def _schedule_loading_overlay(self):
        """Show the loading overlay after 100ms — if _post_redraw fires
        before then (no-op redraw / cache hit), the show never lands."""
        try:
            if self._loading_show_after_id is not None:
                self.after_cancel(self._loading_show_after_id)
        except tk.TclError:
            pass
        try:
            self._loading_show_after_id = self.after(
                100, self._show_loading_overlay)
        except tk.TclError:
            self._loading_show_after_id = None

    def _show_loading_overlay(self):
        self._loading_show_after_id = None
        scroll = getattr(self, "_scroll", None)
        if scroll is None:
            return
        try:
            if not scroll.winfo_exists():
                return
        except tk.TclError:
            return
        if self._loading_overlay is None:
            self._loading_overlay = tk.Frame(self, bg=WHITE)
            tk.Label(self._loading_overlay,
                     text="⏳  Loading…",
                     font=("Segoe UI Variable", 12, "italic"),
                     bg=WHITE, fg=TEXT_GRAY,
                     pady=40).pack(expand=True)
        try:
            self._loading_overlay.place(
                in_=scroll, x=0, y=0, relwidth=1, relheight=1)
            self._loading_overlay.lift()
        except tk.TclError:
            pass

    def _hide_loading_overlay(self):
        try:
            if self._loading_show_after_id is not None:
                self.after_cancel(self._loading_show_after_id)
        except tk.TclError:
            pass
        self._loading_show_after_id = None
        if self._loading_overlay is not None:
            try:
                self._loading_overlay.place_forget()
            except tk.TclError:
                pass

    def _render_section(self, key):
        try:
            self._render_section_inner(key)
        except Exception as ex:
            # End-to-end safety net. If any step (filter, board filter,
            # units construction, count label update) throws, the
            # section body would be left empty after the children-destroy
            # pass at the top of `_render_section_inner` — which is what
            # caused the "I collapsed XA and everything vanished" report.
            # Surface the error inline so the section header still shows
            # and the user knows something went wrong (instead of just
            # mysteriously empty rows).
            try:
                body = self._section_body_wraps.get(key)
                if body is not None:
                    for child in body.winfo_children():
                        try:
                            child.destroy()
                        except Exception:
                            pass
                    tk.Label(body,
                             text=(f"⚠ Section render failed: {ex}\n"
                                   "Click 🔄 Refresh to retry."),
                             font=("Segoe UI Variable", 9, "italic"),
                             bg=WHITE, fg=FLAG_RED,
                             justify="left",
                             wraplength=640
                             ).pack(anchor="w", pady=8, padx=10)
            except Exception:
                pass

    def _render_section_inner(self, key):
        body = self._section_body_wraps.get(key)
        if body is None:
            return
        # Always update the count label, even for off-screen sections,
        # so the header shows the real number before the user scrolls to it.
        _raw_rows = self._sections.get(key) or []
        try:
            cnt_lbl = self._section_count_lbls.get(key)
            if cnt_lbl is not None:
                _disp = _raw_rows
                try:
                    if not self._show_dismissed.get():
                        _disp = self._filter_dismissed(_raw_rows)
                    _disp = self._apply_board_filter(_disp)
                    _disp = self._apply_text_filter(_disp)
                except Exception:
                    pass
                cnt_lbl.configure(
                    text=f"({len(_disp)})",
                    fg=TEXT_GRAY if not _disp else GREEN_DARK)
        except Exception:
            pass
        # If this section is currently derealized (off-screen or on an
        # inactive tab), skip the widget rebuild — the virtualizer will
        # call _render_section_inner again when the section scrolls back
        # into view, at which point self._sections[key] has fresh data.
        if not self._virt.is_frame_realized(body):
            return
        for child in body.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass
        rows = self._sections.get(key) or []
        try:
            if not self._show_dismissed.get():
                rows = self._filter_dismissed(rows)
            rows = self._apply_board_filter(rows)
            rows = self._apply_text_filter(rows)
        except Exception:
            # Filter failure shouldn't blank the section — show the
            # unfiltered rows so the user still sees content.
            rows = self._sections.get(key) or []
        try:
            cnt_lbl = self._section_count_lbls.get(key)
            if cnt_lbl is not None:
                cnt_lbl.configure(
                    text=f"({len(rows)})",
                    fg=TEXT_GRAY if not rows else GREEN_DARK)
        except Exception:
            pass
        # Section-specific top affordances. The Docusign section gets a
        # "+ Add manually" link so the user can track paperwork they
        # sent outside the right-click flow (no pinned card needed).
        # Rendered BEFORE the empty-state check so the link still shows
        # when there are no rows yet.
        if key == "docusign":
            self._render_docusign_add_link(body)
        if not rows:
            tk.Label(body, text="✓ Nothing to flag here.",
                     font=("Segoe UI Variable", 9, "italic"),
                     bg=WHITE, fg=TEXT_GRAY).pack(anchor="w", pady=4)
            return
        # Two caps in play:
        #   hard_cap (MAX_ROWS_PER_SECTION) — Tk widget-storm protection.
        #     Beyond this we silently truncate; the rest live in
        #     self._sections but never render.
        #   soft_cap (COLLAPSE_THRESHOLD) — UX cap. When collapsed (the
        #     default past 5 rows), the section shows only the first
        #     soft_cap rows and a "▼ Show K more" toggle. User can flip
        #     to expanded; state persists across sessions.
        hard_cap = self.MAX_ROWS_PER_SECTION
        soft_cap = self.COLLAPSE_THRESHOLD
        expanded = self._section_expanded.get(key, False)

        # Build a homogeneous list of "render units" so the cap logic
        # doesn't have to be duplicated per-section. For card-grouped
        # sections one unit = one card (one or more violations); for
        # flat sections one unit = one row.
        if key in ("hygiene", "handoff", "concerns"):
            grouped: dict[str, list[dict]] = {}
            for r in rows:
                # Email-source complaints with no card match still get
                # one row per email — keyed by email_id so they don't
                # collide with each other.
                gk = r["card_id"] or r.get("email_id") or id(r)
                grouped.setdefault(gk, []).append(r)
            units: list[tuple] = [
                ("card", vs[0]["card_id"], vs)
                for _gk, vs in grouped.items()]
        elif key == "xa_apology":
            units = [("xa", r) for r in rows]
        elif key == "xa_gaps":
            units = [("gap", r) for r in rows]
        elif key == "docusketch":
            units = [("docusketch", r) for r in rows]
        elif key == "docusign":
            units = [("docusign", r) for r in rows]
        elif key == "ipr":
            units = [("ipr", r) for r in rows]
        elif key == "estimates":
            # Sort priority:
            #   1. Explicit estimate requests (🔴) — adjuster asked for
            #      it explicitly; jumps to the top regardless of status.
            #   2. Status: overdue > pending_ack > acked.
            #   3. Deadline ASC within each bucket.
            _order = {"overdue": 0, "pending_ack": 1, "acked": 2}
            sorted_rows = sorted(
                rows,
                key=lambda r: (
                    0 if r.get("is_explicit_request") else 1,
                    _order.get(r.get("status"), 9),
                    r.get("deadline") or ""))
            units = [("estimate", r) for r in sorted_rows]
        elif key == "wc_audit_due":
            units = [("wc_audit_due", r) for r in rows]
        elif key == "stalled":
            # Already sorted longest-stall-first by pipeline_stages.list_stalled.
            units = [("stalled", r) for r in rows]
        elif key == "anomalies":
            # Already sorted by anomaly ratio (most-extreme first).
            units = [("anomaly", r) for r in rows]
        elif key == "docusketch_needed":
            # Already sorted longest-in-WIP first by the source query.
            units = [("docusketch_needed", r) for r in rows]
        elif key == "weekly":
            # Sort: never-acked first (days_since=None goes to the top
            # of the existing find_due_cards ordering — preserve it).
            units = [("weekly", r) for r in rows]
        elif key == "missing_items":
            # Aging-first: oldest snapshot dates rise to the top so the
            # rows the user has been ignoring longest stay visible.
            sorted_rows = sorted(
                rows, key=lambda r: r.get("snapshot_at") or "")
            units = [("missing_item", r) for r in sorted_rows]
        elif key == "docusign_resends":
            sorted_rows = sorted(
                rows, key=lambda r: r.get("resent_at") or "")
            units = [("docusign_resend", r) for r in sorted_rows]
        elif key == "open_jobs":
            # Stale-first: jobs we haven't seen Trello updates on in
            # the longest rise to the top (highest oversight value).
            sorted_rows = sorted(
                rows, key=lambda r: r.get("last_seen_at") or "")
            units = [("open_job", r) for r in sorted_rows]
        elif key == "adjuster_pending":
            # Newest received first — fresh inquiries are the ones
            # most likely to need a same-day acknowledgement.
            sorted_rows = sorted(
                rows, key=lambda r: r.get("received") or "",
                reverse=True)
            units = [("adjuster_pending", r) for r in sorted_rows]
        elif key == "disputes":
            # Overdue first, then needs-ack, then by oldest Received.
            def _dispute_sort(r):
                tgt = r.get("target_response_date") or ""
                from datetime import date as _date, datetime as _dtm
                overdue = 0
                try:
                    if tgt:
                        d = (tgt.date() if isinstance(tgt, _dtm)
                              else (tgt if isinstance(tgt, _date)
                                    else _dtm.fromisoformat(
                                        str(tgt)[:10]).date()))
                        if d < _date.today():
                            overdue = -1   # sort first
                except (ValueError, TypeError):
                    pass
                ack = (r.get("ack_email_sent") or "").strip().lower()
                ack_rank = 0 if ack != "yes" else 1
                return (overdue, ack_rank,
                         str(r.get("received_date") or ""))
            units = [("dispute", r) for r in sorted(rows,
                                                       key=_dispute_sort)]
        else:
            units = [("closeout", r) for r in rows]

        total_units = len(units)
        truncated_hard = total_units > hard_cap
        if truncated_hard:
            units = units[:hard_cap]

        if not expanded and len(units) > soft_cap:
            visible = units[:soft_cap]
            hidden = len(units) - soft_cap
        else:
            visible = units
            hidden = 0

        render_errors = 0
        for u in visible:
            kind = u[0]
            # Each row is wrapped in its own try/except. If one row hits
            # an exception (e.g. malformed cache entry, unexpected None
            # field), every later row in the same section USED to never
            # render because the loop unwound to the section handler
            # — that's the "I collapsed XA and everything vanished" bug.
            # Now a bad row produces a tiny error line and the rest of
            # the section keeps rendering.
            try:
                if kind == "card":
                    self._render_card_row(body, u[1], u[2], key)
                elif kind == "xa":
                    self._render_xa_row(body, u[1])
                elif kind == "gap":
                    self._render_xa_gap_row(body, u[1])
                elif kind == "docusketch":
                    self._render_docusketch_row(body, u[1])
                elif kind == "docusign":
                    self._render_docusign_row(body, u[1])
                elif kind == "ipr":
                    self._render_ipr_row(body, u[1])
                elif kind == "estimate":
                    self._render_estimate_row(body, u[1])
                elif kind == "weekly":
                    self._render_weekly_row(body, u[1])
                elif kind == "closeout":
                    self._render_closeout_row(body, u[1])
                elif kind == "missing_item":
                    self._render_missing_item_row(body, u[1])
                elif kind == "docusign_resend":
                    self._render_docusign_resend_row(body, u[1])
                elif kind == "open_job":
                    self._render_open_job_row(body, u[1])
                elif kind == "adjuster_pending":
                    self._render_adjuster_pending_row(body, u[1])
                elif kind == "dispute":
                    self._render_dispute_row(body, u[1])
                elif kind == "wc_audit_due":
                    self._render_wc_audit_due_row(body, u[1])
                elif kind == "stalled":
                    self._render_stalled_row(body, u[1])
                elif kind == "anomaly":
                    self._render_anomaly_row(body, u[1])
                elif kind == "docusketch_needed":
                    self._render_docusketch_needed_row(body, u[1])
            except Exception as ex:
                render_errors += 1
                try:
                    tk.Label(body,
                             text=f"  ⚠ render error on this row: {ex}",
                             font=("Segoe UI Variable", 8, "italic"),
                             bg=WHITE, fg=FLAG_RED, anchor="w"
                             ).pack(fill="x", pady=1)
                except Exception:
                    pass

        # Trailing controls: show/collapse toggle when relevant, hard-cap
        # warning when we silently dropped widgets.
        if hidden > 0:
            self._render_expand_toggle(body, key, hidden, expanded=False)
        elif expanded and total_units > soft_cap:
            self._render_expand_toggle(body, key, 0, expanded=True)
        if truncated_hard:
            tk.Label(body,
                     text=(f"... rendering capped at {hard_cap} of "
                           f"{total_units}. Use board filter to narrow."),
                     font=("Segoe UI Variable", 9, "italic"),
                     bg=WHITE, fg=TEXT_GRAY).pack(anchor="w",
                                                   pady=(8, 4))
        # Roll the section's count back up onto the tab badge so
        # mark-resolved / dismissals on a single row reflect on the
        # tab without needing a full _redraw_all.
        try:
            self._refresh_tab_chrome()
        except Exception:
            pass

    def _render_expand_toggle(self, body, key, hidden_count, *, expanded):
        """Render the inline 'Show K more / Collapse' link at the
        bottom of a section. Click flips section state and re-renders."""
        if expanded:
            text = "▲  Collapse"
        else:
            text = f"▼  Show {hidden_count} more"
        link = tk.Label(body, text=text,
                        font=("Segoe UI Variable", 9, "bold"),
                        bg=WHITE, fg=LINK_FG, cursor="hand2",
                        padx=4, pady=8)
        link.pack(anchor="w")
        link.bind("<Button-1>",
                  lambda _e, k=key: self._toggle_section_expand(k))

    def _toggle_section_expand(self, key):
        """Flip a section's expand state, persist, and re-render. Other
        sections are untouched so flipping Hygiene doesn't reset XA
        gaps' expand state."""
        cur = self._section_expanded.get(key, False)
        self._section_expanded[key] = not cur
        try:
            keys_open = sorted([k for k, v in self._section_expanded.items()
                                 if v])
            per.set_value("hygiene_section_expanded", keys_open)
        except Exception:
            pass
        self._render_section(key)

    def _on_board_filter_changed(self):
        """Persist the filter selection + redraw every section.
        Stored value uses the display string ('All boards' or a board
        name) so the dropdown round-trips cleanly across sessions."""
        val = self._board_filter.get()
        try:
            per.set_value("hygiene_board_filter", val)
        except Exception:
            pass
        # Avoid recursive triggers if _redraw_all touches the var
        # (it doesn't currently, but defensive).
        self._redraw_all()

    def _populate_board_filter(self):
        """Refresh the board dropdown based on which boards appear in
        the current rows. Called after each scan and on first render
        from cache. Only boards that actually have rows show up — no
        point in offering a filter for boards with no flags."""
        board_ids: set[str] = set()
        for rows in self._sections.values():
            for r in rows:
                bid = r.get("board_id", "")
                if bid:
                    board_ids.add(bid)
        # Lazy-cache the id→name map. tc.list_boards() is a single
        # API call we already paid for during the scan.
        if board_ids and not self._board_names:
            try:
                import trello_client as tc
                for b in tc.list_boards() or []:
                    self._board_names[b["id"]] = b["name"]
            except Exception:
                pass
        names = sorted({self._board_names.get(bid, f"(unknown {bid[:6]})")
                        for bid in board_ids})
        values = ["All boards"] + names
        try:
            self._board_combo.configure(values=values)
        except tk.TclError:
            return
        # Reset to "All boards" if the saved filter isn't in the list
        # (e.g. the only board with rows changed since last session).
        cur = self._board_filter.get()
        if cur not in values:
            # Set without triggering the persist callback recursion —
            # the trace fires anyway, but persisting "All boards" as
            # the new default is the right thing.
            self._board_filter.set("All boards")

    def _apply_board_filter(self, rows):
        val = self._board_filter.get()
        if not val or val in ("All boards", ""):
            return rows
        return [r for r in rows
                if self._board_names.get(r.get("board_id", "")) == val]

    def _filter_dismissed(self, rows):
        out = []
        for r in rows:
            cid = r.get("card_id") or ""
            rule = r.get("rule") or r.get("source") or ""
            if per.is_card_warning_dismissed(cid, rule):
                continue
            out.append(r)
        return out

    # ── Text search filter ───────────────────────────────────────────────
    _TEXT_FILTER_FIELDS = (
        # Common identifiers across every section row type. Covers
        # cards (client, name), email-driven rows (subject, sender_*),
        # disputes (insured, claim, carrier, dispute_summary),
        # adjuster pending (sender_name, sender_email, subject), and
        # hygiene/handoff rule rows (rule_name, message).
        "client", "name", "card_name", "insured", "claim", "carrier",
        "subject", "sender_name", "sender_email", "from",
        "dispute_summary", "summary", "rule_name", "message",
        "estimator", "assigned_estimator", "card_url", "shortUrl",
    )

    def _apply_text_filter(self, rows):
        q = (self._text_filter.get() or "").strip().lower()
        if not q:
            return rows
        out = []
        for r in rows:
            hit = False
            for f in self._TEXT_FILTER_FIELDS:
                v = r.get(f, "")
                if not v:
                    continue
                try:
                    if q in str(v).lower():
                        hit = True
                        break
                except Exception:
                    continue
            if hit:
                out.append(r)
        return out

    def _on_text_filter_changed(self):
        """Debounce text-input changes so a fast typist doesn't kick a
        _redraw_all on every keystroke. 150ms is short enough to feel
        live but coalesces a burst into one render."""
        if self._closed:
            return
        if self._text_filter_after_id is not None:
            try:
                self.after_cancel(self._text_filter_after_id)
            except tk.TclError:
                pass
            self._text_filter_after_id = None
        try:
            self._text_filter_after_id = self.after(150, self._redraw_all)
        except tk.TclError:
            self._text_filter_after_id = None

    # ── EOD clipboard summary ────────────────────────────────────────────
    def _copy_hygiene_summary(self):
        """Build a paste-ready end-of-day Hygiene roll-up and put it
        on the clipboard. One short paragraph per populated section so
        the user can drop it straight into the Teams EOD thread."""
        from datetime import date as _date
        # Pretty label per section key. Sections not in this map are
        # included by their internal key — anything we ship in
        # `_SECTIONS` should already be present here.
        pretty = {
            "weekly":           "📆 Weekly check-ins due",
            "estimates":        "💰 Estimate requests (48h SLA)",
            "adjuster_pending": "📨 Adjuster inquiries pending approval",
            "disputes":         "⚖ Audit disputes",
            "concerns":         "🚨 Customer concerns",
            "ipr":              "📷 IPR requests",
            "xa_apology":       "🔔 XA apology reminders",
            "docusketch":       "📐 Docusketch pending",
            "docusign":         "📝 Docusign pending",
            "docusign_resends": "✍ Docusign resends",
            "missing_items":    "📋 Missing items (post-flag)",
            "hygiene":          "⚠ Trello hygiene violations",
            "handoff":          "🔄 Lane moves missing handoff",
            "closeout":         "📸 Ready for Snapshot",
            "open_jobs":        "📋 All open Trello jobs",
            "xa_gaps":          "📝 XA gaps",
        }
        lines = [f"EOD Hygiene roll-up — {_date.today().strftime('%a %b %-d, %Y')}"]
        # %-d is POSIX; on Windows strftime needs %#d. Try both.
        try:
            head = _date.today().strftime("%a %b %#d, %Y")
            lines[0] = f"EOD Hygiene roll-up — {head}"
        except Exception:
            pass
        any_rows = False
        for tk_key, tab_label, sec_keys in _TABS:
            tab_total = 0
            section_bits = []
            for sk in sec_keys:
                rows = self._sections.get(sk) or []
                if not self._show_dismissed.get():
                    rows = self._filter_dismissed(rows)
                rows = self._apply_board_filter(rows)
                # Note: deliberately DON'T apply text_filter — the
                # roll-up should report actual workspace state, not
                # what's currently filtered in the UI.
                n = len(rows)
                if n > 0:
                    tab_total += n
                    section_bits.append(f"{pretty.get(sk, sk)}: {n}")
            if tab_total > 0:
                any_rows = True
                lines.append("")
                lines.append(f"{tab_label} ({tab_total} open)")
                for b in section_bits:
                    lines.append(f"  • {b}")
        if not any_rows:
            lines.append("")
            lines.append("✓ Everything's clear — no open Hygiene items.")
        text = "\n".join(lines)
        # Copy + toast feedback.
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            # update() forces Tk to actually own the selection so the
            # text persists after the window loses focus. Without it,
            # external pastes pick up stale clipboard content.
            self.update()
        except tk.TclError:
            return
        try:
            from tool_panel import show_toast
            show_toast(self,
                       f"Copied EOD summary ({len(lines)} lines) to clipboard.",
                       kind="success", duration=2200)
        except Exception:
            pass

    def _render_card_row(self, parent, card_id, violations, section_key):
        """Card with one or more hygiene/handoff/concern violations.
        First row of violations.list is treated as the headline; the
        rest are stacked beneath as bullet lines.

        For email-source concerns the headline shows the sender + an
        Open in Outlook button instead of an Open in Trello button
        (when the email didn't match a card)."""
        head = violations[0]
        row = tk.Frame(parent, bg=WHITE, padx=4, pady=6,
                       highlightthickness=0)
        row.pack(fill="x")
        # Top row: lane chip + card name
        top = tk.Frame(row, bg=WHITE)
        top.pack(fill="x")
        is_email = head.get("source") == "email"
        if is_email:
            lane_label = "📧 inbox"
            chip_bg, chip_fg = WARN_HOVER, WARN_FG
        else:
            lane_label = f"[{head.get('lane') or '?'}]"
            chip_bg, chip_fg = SUCCESS_HOVER, GREEN_DARK
        tk.Label(top, text=lane_label,
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=chip_bg, fg=chip_fg,
                 padx=6, pady=1).pack(side="left")
        # Clickable title — jumps to the email (for email-source rows)
        # or the matched Trello card. Same affordance as the estimates
        # section so muscle memory carries between sections.
        _concern_link = (head.get("email_link") if is_email
                         else head.get("card_url")) or ""
        self._make_title_label(
            top, head.get("card_name", "?"),
            primary_link=_concern_link
        ).pack(side="left", padx=(8, 0))
        self._add_property_chip_if_multiunit(top, head.get("card_name") or "")
        # Action buttons on the right.
        # Email-source rows: prefer the Outlook link, fall back to
        # card_url when an email also matched a card. Trello-card
        # rows use the Trello-branded "T" so the button reads as
        # "open in Trello" instead of a generic arrow.
        primary_url = (head.get("email_link") if is_email
                       else head.get("card_url"))
        if is_email and head.get("email_link"):
            btn_open = link_button(
                top, "📨 Open email",
                command=lambda u=primary_url: self._open_url(u))
        else:
            btn_open = trello_link_button(
                top,
                command=lambda u=primary_url: self._open_url(u))
        btn_open.pack(side="right")
        # If the email also matched a Trello card, give a second button
        # so the user can jump to that card in one click.
        if is_email and head.get("card_url"):
            trello_link_button(
                top, pady=1,
                command=lambda u=head.get("card_url"): self._open_url(u),
            ).pack(side="right", padx=(0, 6))
        secondary_button(
            top, "Snooze 1d",
            command=lambda c=card_id, vs=violations:
                self._snooze_card(c, vs, hours=24)
        ).pack(side="right", padx=(0, 6))
        secondary_button(
            top, "Dismiss",
            command=lambda c=card_id, vs=violations:
                self._snooze_card(c, vs, hours=None)
        ).pack(side="right", padx=(0, 6))

        # Violation lines
        for v in violations:
            color = _SEVERITY_COLORS.get(v.get("severity", "warn"), TEXT_GRAY)
            line = f"  · {v.get('rule', '?'):24s} {v.get('detail', '')}"
            tk.Label(row, text=line,
                     font=("Consolas", 9), bg=WHITE, fg=color,
                     anchor="w", justify="left"
                     ).pack(fill="x", padx=(2, 0), pady=(2, 0))
        self._attach_card_menu_to(row, head.get("card_name") or "")
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(2, 0))

    def _render_xa_row(self, parent, row):
        """AR Board card needing the apology in XactAnalysis. The user
        opens the Trello card to grab carrier/claim/adjuster details,
        posts the apology in XA manually, then clicks Done so the row
        clears for ~a week (cooldown)."""
        wrap = tk.Frame(parent, bg=WHITE, padx=4, pady=6)
        wrap.pack(fill="x")
        top = tk.Frame(wrap, bg=WHITE)
        top.pack(fill="x")
        tk.Label(top, text=f"[{row.get('lane') or '?'}]",
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=WARN_BG, fg=WARN_FG,
                 padx=6, pady=1).pack(side="left")
        self._make_title_label(
            top, row.get("card_name", "?"),
            primary_link=row.get("card_url") or ""
        ).pack(side="left", padx=(8, 0))
        days = row.get("days_silent")
        if days is not None:
            tk.Label(top, text=f"  · {days}d silent",
                     font=("Segoe UI Variable", 9, "italic"),
                     bg=WHITE, fg=TEXT_GRAY).pack(side="left")

        _xa_card_url = row.get("card_url") or ""
        if not _xa_card_url and row.get("card_id"):
            try:
                import trello_client as _tc
                _xa_card_url = _tc.card_url_from_id(row["card_id"])
            except Exception:
                _xa_card_url = ""
        if _xa_card_url:
            trello_link_button(
                top,
                command=lambda u=_xa_card_url: self._open_url(u),
            ).pack(side="right")
        # Direct jump to the job's XA assignment URL (parsed from the
        # Trello card desc's LINKS / XACTANALYSIS LINK row). Only
        # renders when the URL is present — protects against cards
        # whose template field was left blank.
        xa_url = (row.get("xa_link") or "").strip()
        if xa_url:
            link_button(
                top, "🔗 XA",
                command=lambda u=xa_url: self._open_url(u),
                tooltip="Open this job's XactAnalysis assignment in browser",
            ).pack(side="right", padx=(0, 6))
        quick_btn = secondary_button(
            top, "📋 Quick note ▾",
            command=lambda: None,  # replaced below; tk needs an initial cmd
            tooltip=("Copy one of the canned XA notes (apology, scan-in-"
                     "progress, estimate underway, etc.) to clipboard "
                     "for pasting into XactAnalysis."),
        )
        quick_btn.pack(side="right", padx=(0, 6))
        quick_btn.config(command=lambda b=quick_btn:
                          self._show_xa_quick_menu(b))
        done_button(
            top, "✓ Done in XA",
            command=lambda r=row: self._mark_xa_handled(r),
        ).pack(side="right", padx=(0, 6))
        self._attach_card_menu_to(wrap, row.get("card_name") or "")
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(2, 0))

    def _copy_xa_note(self):
        """Legacy single-template copy — kept for any caller that still
        targets it. New code paths use `_show_xa_quick_menu` to pick
        from the full template library."""
        try:
            import ar_followup as arf
            self.clipboard_append(arf.DEFAULT_NOTE)
            self.update()
            self._status_lbl.configure(
                text="Apology note copied to clipboard.")
        except Exception as ex:
            messagebox.showerror("Copy failed", str(ex), parent=self)

    def _card_url_for_row(self, row):
        """Best-effort Trello card URL for a Hygiene row dict.

        Tries the cached `card_url` / `shortUrl` first, falls back to
        building a /c/<id> URL when only the card id is on hand
        (adjuster_monitor / xa_email_ingest sometimes drop the cached
        URL but preserve the id). Returns '' when no card linkage
        exists at all."""
        if not isinstance(row, dict):
            return ""
        url = (row.get("card_url") or row.get("shortUrl")
               or row.get("url") or "")
        if url:
            return url
        cid = row.get("card_id") or row.get("id") or ""
        if not cid:
            return ""
        try:
            import trello_client as _tc
            return _tc.card_url_from_id(cid) or ""
        except Exception:
            return ""

    def _show_xa_quick_menu(self, anchor_btn):
        """Pop a menu of canned XA notes anchored just below `anchor_btn`.
        Clicking a template copies its text to the clipboard and updates
        the status line so the user gets immediate confirmation."""
        try:
            import xa_messages as xm
        except Exception as ex:
            messagebox.showerror("Templates unavailable", str(ex),
                                  parent=self)
            return

        def _copy(text, label):
            ok = xm.copy_to_clipboard(self, text)
            if not ok:
                self._status_lbl.configure(
                    text="Copy failed — clipboard may be locked.")
                return
            self._status_lbl.configure(
                text=f"Copied: {label}")

        menu = tk.Menu(self, tearoff=0)
        for _key, label, text in xm.TEMPLATES:
            menu.add_command(
                label=label,
                command=lambda t=text, l=label: _copy(t, l))
        try:
            anchor_btn.update_idletasks()
            x = anchor_btn.winfo_rootx()
            y = anchor_btn.winfo_rooty() + anchor_btn.winfo_height()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _mark_xa_handled(self, row):
        try:
            import ar_followup as arf
            arf.mark_handled(row.get("card_id", ""))
        except Exception as ex:
            messagebox.showerror("Couldn't mark handled", str(ex),
                                  parent=self)
            return
        # Drop the row from the in-memory section + cache without
        # forcing a full re-scan.
        cid = row.get("card_id")
        self._sections["xa_apology"] = [
            r for r in self._sections["xa_apology"]
            if r.get("card_id") != cid]
        try:
            per.set_hygiene_scan_cache(
                self._sections["concerns"]
                + self._sections["hygiene"]
                + self._sections["handoff"],
                self._sections["closeout"],
                xa_apology=self._sections["xa_apology"])
        except Exception:
            pass
        self._render_section("xa_apology")

    def _render_xa_gap_row(self, parent, group):
        """One row per job whose XA notes are stale or have an open
        commitment. `group` shape from xa_email_ingest.scan_inbox():
            {"claim", "insured_hint", "notes", "analysis", "card",
             "board_id"}
        """
        analysis = group.get("analysis") or {}
        days_silent = analysis.get("days_since_human")
        commits = analysis.get("open_commitments") or []
        labels = sorted({c.get("label", "") for c in commits if c.get("label")})

        wrap = tk.Frame(parent, bg=WHITE, padx=4, pady=6)
        wrap.pack(fill="x")
        top = tk.Frame(wrap, bg=WHITE)
        top.pack(fill="x")

        # Severity chip: red for very stale (10+ days), warn for 5-9d,
        # info for everything else (which means there's an open
        # commitment but the job is still active).
        if days_silent is not None and days_silent >= 10:
            chip_bg, chip_fg = DANGER_HOVER, FLAG_RED
        elif days_silent is not None and days_silent >= 5:
            chip_bg, chip_fg = WARN_HOVER, WARN_FG
        else:
            chip_bg, chip_fg = SUCCESS_HOVER, GREEN_DARK
        chip_text = (f"📝 {days_silent}d"
                     if days_silent is not None else "📝 XA")
        tk.Label(top, text=chip_text,
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=chip_bg, fg=chip_fg,
                 padx=6, pady=1).pack(side="left")

        # Title: claim# + insured hint + matched card name.
        claim = group.get("claim", "")
        insured = group.get("insured_hint", "")
        card = group.get("card") or {}
        title_parts = []
        if claim:
            title_parts.append(claim)
        if insured and insured.lower() not in (claim or "").lower():
            title_parts.append(insured)
        if card.get("name"):
            title_parts.append(f"→ {card['name']}")
        title = "  ".join(title_parts) or "(unknown job)"
        # Click → latest XA-note email if available, else the Trello card.
        notes = group.get("notes") or []
        _latest = notes[0] if notes else {}
        _gap_link = (_latest.get("_email_link")
                     or card.get("shortUrl") or "")
        self._make_title_label(
            top, title, primary_link=_gap_link
        ).pack(side="left", padx=(8, 0))

        # Right-side action buttons. Fall back to /c/<id> URL when the
        # matched card has an id but no cached shortUrl.
        primary_url = card.get("shortUrl") or card.get("url") or ""
        if not primary_url and card.get("id"):
            try:
                import trello_client as _tc
                primary_url = _tc.card_url_from_id(card["id"])
            except Exception:
                primary_url = ""
        if primary_url:
            trello_link_button(
                top,
                command=lambda u=primary_url: self._open_url(u),
            ).pack(side="right")

        # Direct jump to the job's XA assignment URL. Pulled from the
        # Trello card desc by xa_email_ingest when the group was
        # matched to a card; we just render the button when it's
        # available.
        xa_url = (group.get("xa_link") or "").strip()
        if xa_url:
            link_button(
                top, "🔗 XA",
                command=lambda u=xa_url: self._open_url(u),
                tooltip="Open this job's XactAnalysis assignment in browser",
            ).pack(side="right", padx=(0, 6))

        # Latest XA note's email link, when present.
        notes = group.get("notes") or []
        latest = notes[0] if notes else {}
        email_link = latest.get("_email_link", "")
        if email_link:
            secondary_button(
                top, "📨 Email",
                command=lambda u=email_link: self._open_url(u),
            ).pack(side="right", padx=(0, 6))

        # 📋 Quick-note dropdown — same canned-template menu as the
        # apology row, so wherever the user is dealing with an XA note
        # they can grab a templated message without re-typing it.
        gap_quick_btn = secondary_button(
            top, "📋 Quick note ▾",
            command=lambda: None,
            tooltip=("Copy one of the canned XA notes (apology, scan-in-"
                     "progress, estimate underway, etc.) to clipboard."),
        )
        gap_quick_btn.pack(side="right", padx=(0, 6))
        gap_quick_btn.config(command=lambda b=gap_quick_btn:
                              self._show_xa_quick_menu(b))

        done_button(
            top, "✓ Resolved",
            command=lambda g=group: self._mark_xa_gap_resolved(g),
        ).pack(side="right", padx=(0, 6))

        # Detail line: open commitment labels + summary.
        detail_bits: list[str] = []
        if labels:
            detail_bits.append("open: " + ", ".join(labels))
        if commits:
            # Show the snippet from the most recent open commitment so
            # the user sees the actual XA wording without clicking.
            most_recent = max(
                commits,
                key=lambda c: ((c.get("from_note") or {}).get("timestamp")
                               or datetime.min))
            snip = (most_recent.get("snippet") or "").strip()
            if snip:
                detail_bits.append(f'"{snip[:140]}"')
        if detail_bits:
            tk.Label(wrap, text="  ↳ " + " · ".join(detail_bits),
                     font=("Segoe UI Variable", 9, "italic"),
                     bg=WHITE, fg=TEXT_GRAY,
                     anchor="w", justify="left", wraplength=720
                     ).pack(fill="x", padx=(2, 0), pady=(2, 0))
        self._attach_card_menu_to(
            wrap, group.get("insured_hint") or group.get("claim") or "")
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(2, 0))

    def _mark_xa_gap_resolved(self, group):
        """User confirmed the XA gap has been closed (note posted in
        XactAnalysis). Persist the resolution + drop the row from this
        section without forcing a re-scan."""
        try:
            import xa_email_ingest as xei
            key = (group.get("claim") or
                   f"name:{(group.get('insured_hint') or '').lower()}")
            xei.mark_resolved(key)
        except Exception as ex:
            messagebox.showerror("Couldn't mark resolved", str(ex),
                                  parent=self)
            return
        # Drop the group from the in-memory section + cache.
        gid = id(group)
        self._sections["xa_gaps"] = [
            g for g in self._sections["xa_gaps"] if id(g) != gid]
        try:
            per.set_hygiene_scan_cache(
                self._sections["concerns"]
                + self._sections["hygiene"]
                + self._sections["handoff"],
                self._sections["closeout"],
                xa_apology=self._sections["xa_apology"],
                xa_gaps=self._sections["xa_gaps"])
        except Exception:
            pass
        self._render_section("xa_gaps")

    # ── Estimate-request rows ─────────────────────────────────────────────

    def _render_estimate_row(self, parent, req):
        """One row of the 💰 Estimate Requests section.

        Three visual states based on req['status']:
          pending_ack — fresh inquiry awaiting the user's ack click
          acked       — clock running, hours remaining shown in chip
          overdue     — past deadline, urgent red chip + Extend prominent
        """
        status = req.get("status", "")
        wrap = tk.Frame(parent, bg=WHITE, padx=4, pady=6)
        wrap.pack(fill="x")
        top = tk.Frame(wrap, bg=WHITE)
        top.pack(fill="x")

        # Severity chip — color + text reflect status urgency.
        if status == "overdue":
            chip_bg, chip_fg, chip_text = DANGER_HOVER, FLAG_RED, "⏰ OVERDUE"
        elif status == "acked":
            chip_text = "⏱ acked"
            try:
                dl_iso = (req.get("deadline") or "").split(".")[0].rstrip("Z")
                deadline = datetime.fromisoformat(dl_iso)
                remaining_h = (deadline - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds() / 3600
                if remaining_h >= 0:
                    chip_text = f"⏱ {remaining_h:.0f}h left"
            except (ValueError, AttributeError):
                pass
            chip_bg, chip_fg = WARN_HOVER, WARN_FG
        else:
            chip_bg, chip_fg, chip_text = "#E8F0FB", "#1A56A8", "💰 NEW"
        tk.Label(top, text=chip_text, font=("Segoe UI Variable", 9, "bold"),
                 bg=chip_bg, fg=chip_fg, padx=6, pady=1
                 ).pack(side="left")

        # Explicit-request chip — fires when the source email body
        # contains a phrase like "please send the estimate" / "where's
        # the estimate" / etc. Renders right next to the status chip
        # so the user sees BOTH the SLA state and the priority signal.
        if req.get("is_explicit_request"):
            tk.Label(top, text="🔴 ESTIMATE REQUEST",
                     font=("Segoe UI Variable", 8, "bold"),
                     bg=DANGER_BG, fg=DANGER_FG, padx=6, pady=1
                     ).pack(side="left", padx=(4, 0))

        # Source chip — XA vs Email, with a callout for non-XA adjusters
        # (those need a direct Outlook reply, not an XA paste).
        src = req.get("source", "")
        if src == "xa":
            src_text = "XA"
        elif not req.get("uses_xa", True):
            src_text = "📧 No-XA"
        else:
            src_text = "Email"
        tk.Label(top, text=src_text, font=("Segoe UI Variable", 8),
                 bg=SURFACE_2, fg=TEXT_GRAY,
                 padx=5, pady=1).pack(side="left", padx=(4, 0))

        # Title: insured + claim + carrier (best-effort; fall back to
        # the email subject for unmatched email-source rows).
        title_parts: list[str] = []
        insured = (req.get("insured") or "").strip()
        if insured:
            title_parts.append(insured)
        claim = (req.get("claim") or "").strip()
        if claim:
            title_parts.append(f"#{claim}")
        carrier = (req.get("carrier") or "").strip()
        if carrier:
            title_parts.append(carrier)
        title = "  ".join(title_parts)
        if not title:
            title = (req.get("email_subject") or
                     req.get("adjuster") or
                     "(unmatched email)")
        # Resolve a usable client name for downstream lookups. Order:
        #   1. insured (set when email matched a Trello card)
        #   2. claim   (rarer fallback)
        #   3. extract "Insured: <NAME>" from email_subject (XA
        #      notification format) — this is the path that lights up
        #      the right-click menu for unmatched email rows.
        derived_client = (req.get("insured") or "").strip()
        if not derived_client:
            derived_client = (req.get("claim") or "").strip()
        if not derived_client:
            subj = req.get("email_subject") or ""
            m = _INSURED_FROM_SUBJECT_RE.search(subj)
            if m:
                derived_client = m.group(1).strip()

        # Title label — clickable when there's a source email link OR a
        # Trello card to jump to. Email takes precedence (the user's
        # primary need on these rows is "show me what they actually
        # asked for"); falls back to the Trello card when the row
        # came from an XA note rather than a direct adjuster email.
        primary_link = req.get("source_link") or req.get("card_url") or ""
        self._make_title_label(
            top, title, primary_link=primary_link
        ).pack(side="left", padx=(8, 0))

        # 🏢 chip for multi-unit properties — surfaces affiliation
        # next to the title without taking right-side button space.
        self._add_property_chip_if_multiunit(top, derived_client)

        # Right-side buttons (packed right-to-left so visual L→R order
        # matches code top-to-bottom).
        # Fall back to building a /c/<id> URL when the row carries a
        # card_id but no cached card_url — adjuster_monitor's output
        # sometimes preserves the id without the shortUrl, and we want
        # the Trello button to render either way.
        _est_card_url = req.get("card_url") or ""
        _est_card_id = req.get("card_id") or ""
        # No card on the record → consult the persisted pin store under
        # the derived client name. After the user right-clicks → "Pin
        # to Trello..." this lookup lights the Trello button up on the
        # next render without any other plumbing.
        if not _est_card_id and derived_client:
            try:
                _est_card_id = per.get_trello_card_id(derived_client) or ""
            except Exception:
                _est_card_id = ""
        if not _est_card_url and _est_card_id:
            try:
                import trello_client as _tc
                _est_card_url = _tc.card_url_from_id(_est_card_id)
            except Exception:
                _est_card_url = ""
        if _est_card_url:
            trello_link_button(
                top,
                command=lambda u=_est_card_url: self._open_url(u),
            ).pack(side="right")

        if req.get("source_link"):
            secondary_button(
                top, "📨 Email",
                command=lambda u=req["source_link"]: self._open_url(u),
            ).pack(side="right", padx=(0, 6))

        # Status-dependent primary action.
        if status == "pending_ack":
            send_button(
                top, "📋 Send 48h ack",
                command=lambda r=req: self._send_estimate_ack(r),
            ).pack(side="right", padx=(0, 6))
            icon_button(
                top, "🗑",
                command=lambda r=req: self._dismiss_estimate(r),
            ).pack(side="right", padx=(0, 4))
        else:
            done_button(
                top, "✓ Completed",
                command=lambda r=req: self._complete_estimate(r),
            ).pack(side="right", padx=(0, 6))
            # Overdue rows promote Extend to danger styling so the
            # urgency is unmistakable; non-overdue keeps the warn tint.
            _ext_kind = (danger_button if status == "overdue"
                         else warn_button)
            _ext_kind(
                top, "⏱ Extend",
                command=lambda r=req: self._extend_estimate(r),
            ).pack(side="right", padx=(0, 6))

        # Detail line: adjuster, received, deadline, assigned estimator,
        # extension totals so the user can scan the row's whole state
        # at a glance.
        bits: list[str] = []
        adj = (req.get("adjuster") or "").strip()
        if adj:
            bits.append(f"from {adj}")
        rcv = req.get("received_at") or ""
        if rcv:
            try:
                rcv_clean = rcv.split(".")[0].rstrip("Z")
                bits.append(
                    f"received {datetime.fromisoformat(rcv_clean):%a %b %d %I:%M %p}")
            except (ValueError, AttributeError):
                pass
        dl = req.get("deadline") or ""
        if dl:
            try:
                dl_clean = dl.split(".")[0].rstrip("Z")
                bits.append(
                    f"due {datetime.fromisoformat(dl_clean):%a %b %d %I:%M %p}")
            except (ValueError, AttributeError):
                pass
        est = (req.get("estimator") or "").strip()
        if est:
            bits.append(f"→ {est}")
        exts = req.get("extensions") or []
        if exts:
            total_h = sum(int(e.get("hours") or 0) for e in exts
                          if isinstance(e, dict))
            if total_h:
                bits.append(f"+{total_h}h extended")
        if bits:
            tk.Label(wrap, text="  ↳ " + " · ".join(bits),
                     font=("Segoe UI Variable", 9, "italic"),
                     bg=WHITE, fg=TEXT_GRAY,
                     anchor="w", justify="left", wraplength=720
                     ).pack(fill="x", padx=(2, 0), pady=(2, 0))

        # ▶ Show email — collapsible to view the full message body.
        # Body is fetched lazily on first expand (Outlook COM round-trip
        # for adjuster_email rows; XA rows have no EntryID so we just
        # show a placeholder there). Cached on the req dict so toggling
        # off/on doesn't refetch.
        self._build_email_collapsible(wrap, req)

        self._attach_card_menu_to(wrap, derived_client)
        tk.Frame(parent, bg=BORDER, height=1
                 ).pack(fill="x", pady=(2, 0))

    def _build_email_collapsible(self, parent, req):
        """Render a ▶/▼ toggle that expands to show the email body.

        Lazy: the body is fetched on first expand via
        `outlook_local.get_message_body(source_id)` for adjuster_email
        rows (the source_id IS the Outlook EntryID). XA rows have no
        EntryID, so they show a placeholder noting the body lives in
        XactAnalysis. Subsequent toggles use a cache pinned on `req`
        so we don't hit Outlook COM repeatedly.
        """
        toggle_frame = tk.Frame(parent, bg=WHITE)
        toggle_frame.pack(fill="x", padx=(2, 0), pady=(2, 0))

        toggle_lbl = tk.Label(
            toggle_frame, text="▶ Show email",
            font=("Segoe UI Variable", 8, "underline"),
            bg=WHITE, fg=LINK_FG, cursor="hand2", padx=4)
        toggle_lbl.pack(side="left")

        body_frame = tk.Frame(parent, bg=WHITE)
        # NOT packed yet — pack() is what reveals it on toggle.

        state = {"open": False, "loaded": False}

        def _load_body():
            # Honor cache on the row dict first (a previous render in
            # this session may have already fetched the body).
            cached = req.get("_email_body_cache")
            if cached is not None:
                return cached
            src = (req.get("source") or "").lower()
            if src == "adjuster_email":
                msg_id = (req.get("source_id") or "").strip()
                if not msg_id:
                    return "(no Outlook message id on this record)"
                try:
                    import outlook_local as ol
                    body = ol.get_message_body(msg_id) or ""
                except Exception as ex:
                    return f"(couldn't fetch from Outlook: {ex})"
                return body or "(message body was empty)"
            if src == "xa":
                return ("(this row came from an XA notification — open "
                        "the card's XactAnalysis link to read the full "
                        "note)")
            return "(no email body available for this row)"

        def _toggle(_e=None):
            if state["open"]:
                body_frame.pack_forget()
                toggle_lbl.config(text="▶ Show email")
                state["open"] = False
                return
            if not state["loaded"]:
                for w in body_frame.winfo_children():
                    try: w.destroy()
                    except tk.TclError: pass
                body = _load_body()
                req["_email_body_cache"] = body
                txt = tk.Text(body_frame, wrap="word", height=10,
                              font=("Segoe UI Variable", 9),
                              bg=SURFACE_2, fg=TEXT_DARK,
                              relief="flat", padx=8, pady=6,
                              highlightthickness=1,
                              highlightbackground=BORDER)
                txt.insert("1.0", body)
                txt.config(state="disabled")
                txt.pack(fill="x", padx=4, pady=(2, 4))
                state["loaded"] = True
            body_frame.pack(fill="x")
            toggle_lbl.config(text="▼ Hide email")
            state["open"] = True

        toggle_lbl.bind("<Button-1>", _toggle)

    def _send_estimate_ack(self, req):
        """One-click 48h acknowledgment. Chains:
          1. Copy XA template to clipboard ("our estimating team will
             address within 48 hours" — generic, no estimator name)
          2. Open source email link
          3. Post a generic Trello comment ("📩 48h estimate inquiry
             received from <adjuster>. Deadline: <when>.") — no
             @mention, no estimator name
          4. mark_acked → starts the 48h clock + syncs Excel

        Per user feedback (2026-05-13): no estimator picker, no
        @mention, no Teams DM. The user wanted Teams initially but
        retracted — Trello + clipboard is enough; they'll handle
        Teams manually when needed.
        """
        import estimate_requests as er

        card_id = (req.get("card_id") or "").strip()
        # Live lane classification still drives template choice (TBA
        # gets the "we are assigning" wording; assigned/unknown gets
        # the generic "estimating team will address" wording). Neither
        # template names any specific person.
        status, _lane_estimator = er.classify_assignment(card_id)
        template = er.ack_template_for(status)

        steps: list[str] = []
        status_tag = ("TBA ack" if status == "tba"
                      else "estimating team ack")

        # 1. Clipboard — first because it's most likely to fail when a
        # clipboard manager is interfering, and we'd rather know
        # immediately.
        try:
            self.clipboard_append(template)
            self.update()
            steps.append("clipboard")
        except tk.TclError:
            pass

        # 2. Source email
        src_link = (req.get("source_link") or "").strip()
        if src_link:
            try:
                self._open_url(src_link)
                steps.append("email")
            except Exception:
                pass

        # 3. Trello comment — generic wording, no @mention, no name.
        if card_id:
            try:
                import trello_client as tc
                from datetime import timedelta as _td
                actual_deadline = (datetime.now(timezone.utc).replace(tzinfo=None) + _td(hours=48)
                                    ).strftime("%a %b %d %I:%M %p")
                adj = (req.get("adjuster") or "").strip()
                from_clause = f" from {adj}" if adj else ""
                body = (f"📩 48h estimate inquiry received{from_clause}. "
                        f"Our estimating team will address within "
                        f"48 hours. Deadline: {actual_deadline}.")
                tc.post_comment(card_id, body)
                steps.append("Trello")
            except Exception:
                pass

        # 4. Mark acked — this also kicks the Excel sync via
        # estimate_requests._excel_sync_safe. Pass estimator="" so
        # nothing stored on the record names a specific person either.
        try:
            er.mark_acked(req["request_id"], estimator="")
        except Exception as ex:
            messagebox.showerror(
                "Ack save failed", str(ex), parent=self)
            return

        self._refresh_estimates_section()
        self._status_lbl.configure(
            text=(f"{status_tag} sent — paste from clipboard into XA. "
                  f"Routed: "
                  f"{', '.join(steps) or '(no channels reachable)'}."))

    def _prompt_estimator_for_estimate(self, req):
        """Modal estimator picker. Used when the request has no
        pre-resolved estimator (i.e., the card had no lane/desc match
        we recognized). Returns the chosen name or '' on cancel."""
        options = sorted(per.get_estimator_emails().keys())
        if not options:
            messagebox.showinfo(
                "No estimators configured",
                "Open APA Monitor → Contacts and add estimator emails first.",
                parent=self)
            return ""
        dlg = tk.Toplevel(self)
        dlg.title("Pick estimator")
        dlg.geometry("320x150")
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()
        dlg.configure(bg=BG)
        label_text = (req.get("insured") or req.get("claim")
                      or req.get("adjuster") or "this inquiry")
        tk.Label(dlg, text=f"For {label_text}",
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=BG, fg=TEXT_DARK).pack(padx=12, pady=(10, 6))
        var = tk.StringVar(value=options[0])
        ttk.Combobox(dlg, textvariable=var, values=options,
                     state="readonly").pack(padx=12, pady=4, fill="x")
        chosen: list[str] = [""]

        def _ok():
            chosen[0] = var.get()
            dlg.destroy()

        btn_row = tk.Frame(dlg, bg=BG)
        btn_row.pack(pady=12)
        done_button(btn_row, "OK", padx=12,
                     command=_ok).pack(side="left", padx=6)
        secondary_button(btn_row, "Cancel", padx=8,
                          command=dlg.destroy).pack(side="left", padx=6)
        self.wait_window(dlg)
        return chosen[0]

    def _complete_estimate(self, req):
        """Mark an estimate request completed — flips status to
        completed, removes from active set, moves Excel row to
        Completed sheet."""
        import estimate_requests as er
        try:
            er.mark_completed(req["request_id"])
        except Exception as ex:
            messagebox.showerror(
                "Couldn't mark completed", str(ex), parent=self)
            return
        self._refresh_estimates_section()

    def _extend_estimate(self, req):
        """Modal: ask for a reason + extra hours, then push the
        deadline forward by that amount. Reason is required so we have
        an audit trail of why something missed the 48h SLA."""
        import estimate_requests as er
        dlg = tk.Toplevel(self)
        dlg.title("Extend deadline")
        dlg.geometry("380x210")
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()
        dlg.configure(bg=BG)
        label_text = (req.get("insured") or req.get("claim")
                      or req.get("adjuster") or "this inquiry")
        tk.Label(dlg, text=f"Why is {label_text} taking longer?",
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=BG, fg=TEXT_DARK
                 ).pack(padx=12, pady=(10, 4), anchor="w")
        reason_var = tk.StringVar()
        tk.Entry(dlg, textvariable=reason_var, font=("Segoe UI Variable", 10)
                 ).pack(padx=12, pady=4, fill="x")
        tk.Label(dlg, text="Extra hours:", font=("Segoe UI Variable", 9),
                 bg=BG, fg=TEXT_DARK
                 ).pack(padx=12, pady=(8, 2), anchor="w")
        hours_var = tk.IntVar(value=24)
        tk.Spinbox(dlg, from_=1, to=168, textvariable=hours_var,
                   width=8).pack(padx=12, anchor="w")

        def _ok():
            reason = reason_var.get().strip()
            try:
                hours = int(hours_var.get())
            except (tk.TclError, ValueError):
                hours = 0
            if not reason:
                messagebox.showwarning(
                    "Reason required",
                    "Type a short reason — this gets logged on the "
                    "request and the spreadsheet.",
                    parent=dlg)
                return
            if hours <= 0:
                messagebox.showwarning(
                    "Hours required",
                    "Pick at least 1 extra hour.",
                    parent=dlg)
                return
            try:
                er.mark_extended(req["request_id"], reason=reason,
                                  extra_hours=hours)
            except Exception as ex:
                messagebox.showerror(
                    "Extend failed", str(ex), parent=dlg)
                return
            dlg.destroy()
            self._refresh_estimates_section()

        btn_row = tk.Frame(dlg, bg=BG)
        btn_row.pack(pady=12)
        done_button(btn_row, "Extend", padx=14,
                     command=_ok).pack(side="left", padx=6)
        secondary_button(btn_row, "Cancel", padx=8,
                          command=dlg.destroy).pack(side="left", padx=6)
        self.wait_window(dlg)

    def _dismiss_estimate(self, req):
        """User says this isn't a real inquiry (junk, dupe, false-pos
        from the broad XA trigger). Drops the row from the tracker so
        it won't surface again on re-scan."""
        label_text = (req.get("insured") or req.get("claim")
                      or req.get("adjuster") or "this inquiry")
        if not messagebox.askyesno(
                "Dismiss inquiry",
                f"Drop '{label_text}' from the SLA tracker?\n\n"
                "The email/XA note itself isn't touched — this just "
                "stops surfacing it in Hygiene.",
                parent=self):
            return
        import estimate_requests as er
        try:
            er.dismiss(req["request_id"])
        except Exception as ex:
            messagebox.showerror(
                "Dismiss failed", str(ex), parent=self)
            return
        self._refresh_estimates_section()

    def _refresh_estimates_section(self):
        """Re-hydrate the estimates section from persistence and re-
        render. Called after every state-change button (ack/complete/
        extend/dismiss) so the UI reflects the new state without
        forcing a full Trello + inbox rescan."""
        try:
            import estimate_requests as er
            self._sections["estimates"] = er.all_active()
        except Exception:
            self._sections["estimates"] = []
        # Persist the cache too — next launcher-open should see fresh
        # rows without re-running the inbox scan.
        try:
            per.set_hygiene_scan_cache(
                (self._sections.get("concerns") or [])
                + (self._sections.get("hygiene") or [])
                + (self._sections.get("handoff") or []),
                self._sections.get("closeout") or [],
                xa_apology=self._sections.get("xa_apology") or [],
                xa_gaps=self._sections.get("xa_gaps") or [],
                ipr=self._sections.get("ipr") or [],
                estimates=self._sections.get("estimates") or [])
        except Exception:
            pass
        self._render_section("estimates")

    # ── Weekly check-in rows ─────────────────────────────────────────────
    def _render_weekly_row(self, parent, row):
        """One row of the 📆 Weekly check-ins section. Mirrors the
        estimates row layout so muscle memory carries over: lane chip,
        card name + days-since, ↗ Card / 📋 Send / ⏭ Skip buttons.
        """
        wrap = tk.Frame(parent, bg=WHITE, padx=4, pady=6)
        wrap.pack(fill="x")
        top = tk.Frame(wrap, bg=WHITE)
        top.pack(fill="x")

        days = row.get("days_since")
        if days is None:
            chip_text = "📆 never"
            chip_bg, chip_fg = DANGER_HOVER, FLAG_RED
        elif days >= 14:
            chip_text = f"📆 {int(days)}d silent"
            chip_bg, chip_fg = DANGER_HOVER, FLAG_RED
        else:
            chip_text = f"📆 {int(days)}d silent"
            chip_bg, chip_fg = WARN_HOVER, WARN_FG
        tk.Label(top, text=chip_text,
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=chip_bg, fg=chip_fg, padx=6, pady=1
                 ).pack(side="left")

        # Lane chip — which estimator owns the card right now.
        lane = (row.get("list_name") or "").strip()
        if lane:
            tk.Label(top, text=lane[:18], font=("Segoe UI Variable", 8),
                     bg=SURFACE_2, fg=TEXT_GRAY,
                     padx=5, pady=1
                     ).pack(side="left", padx=(4, 0))

        # Card name — clickable, opens the Trello card.
        self._make_title_label(
            top, row.get("card_name") or "(unnamed)",
            primary_link=row.get("card_url") or ""
        ).pack(side="left", padx=(8, 0))

        # Right-side buttons.
        if row.get("card_url"):
            trello_link_button(
                top,
                command=lambda u=row["card_url"]: self._open_url(u),
            ).pack(side="right")

        secondary_button(
            top, "⏭ Skip",
            command=lambda r=row: self._skip_weekly(r),
        ).pack(side="right", padx=(0, 6))

        send_button(
            top, "📋 Send weekly note",
            command=lambda r=row: self._send_weekly_note(r),
        ).pack(side="right", padx=(0, 6))

        self._attach_card_menu_to(wrap, row.get("card_name") or "")
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x",
                                                       pady=(2, 0))

    def _send_weekly_note(self, row):
        """One-click weekly status note. Same chain as the 48h ack:
          1. Copy canonical text to clipboard (paste into XA)
          2. Open Trello card in browser
          3. Post Trello comment with @estimator + 'weekly status'
          4. Open Teams DM to estimator
          5. mark_weekly_note_sent — drops row from this section for
             another 7 days.
        Best-effort: a missing channel doesn't block the rest."""
        import weekly_checkins as wc

        card_id = (row.get("card_id") or "").strip()
        if not card_id:
            return

        # Estimator resolution mirrors _send_estimate_ack — lane name
        # → APA estimator (when the lane matches). Falls back to a
        # blank estimator (no @mention / no Teams) when the lane is
        # something generic like "TBA".
        estimator = ""
        try:
            import estimate_requests as er
            lane_name = (row.get("list_name") or "")
            if lane_name:
                needle = lane_name.strip().lower()
                for marker, name in er._LANE_TO_ESTIMATOR:
                    if marker in needle:
                        estimator = name
                        break
        except Exception:
            pass

        steps: list[str] = []

        # 1. Clipboard
        try:
            self.clipboard_append(wc.template())
            steps.append("clipboard")
        except tk.TclError:
            pass

        # 2. Open Trello card in browser (source link for the user to
        # paste the XA note onto).
        if row.get("card_url"):
            try:
                self._open_url(row["card_url"])
                steps.append("card")
            except Exception:
                pass

        # 3. Trello comment.
        try:
            import trello_client as tc
            if estimator:
                handle = per.get_estimator_trello_handle(estimator)
                mention = f"@{handle} " if handle else ""
                body = (f"{mention}📆 Weekly status check — sending "
                        f"the standard note to XA today.")
            else:
                body = ("📆 Weekly status check — sending the standard "
                        "note to XA today. (TBA / unassigned lane.)")
            tc.post_comment(card_id, body)
            steps.append("Trello")
        except Exception:
            pass

        # 4. Teams DM (only when an estimator is resolved).
        if estimator:
            try:
                from apa_monitor_gui import open_teams_chat
                email = per.get_estimator_email(estimator)
                if email:
                    summary_target = row.get("card_name") or "this file"
                    if open_teams_chat(
                            email,
                            f"📆 Weekly note for {summary_target} "
                            f"sent to XA. FYI — clock resets for "
                            "another 7 days."):
                        steps.append("Teams")
            except Exception:
                pass

        # 5. Stamp timestamp + drop the row from the in-memory list.
        try:
            wc.mark_weekly_note_sent(card_id)
        except Exception as ex:
            messagebox.showerror(
                "Couldn't save weekly stamp", str(ex), parent=self)
            return

        self._sections["weekly"] = [
            r for r in self._sections.get("weekly") or []
            if r.get("card_id") != card_id]
        self._render_section("weekly")
        self._status_lbl.configure(
            text=(f"Weekly note sent — paste from clipboard into XA. "
                  f"Routed: "
                  f"{', '.join(steps) or '(no channels reachable)'}."))

    def _skip_weekly(self, row):
        """Mark this card as 'note sent now' without actually sending —
        snoozes it for another 7 days. Useful for cards the user knows
        don't need a note this week (e.g., just sent yesterday outside
        the tool, or already closed but the Trello lane hasn't moved
        yet)."""
        card_id = (row.get("card_id") or "").strip()
        if not card_id:
            return
        try:
            import weekly_checkins as wc
            wc.mark_weekly_note_sent(card_id)
        except Exception as ex:
            messagebox.showerror(
                "Couldn't skip", str(ex), parent=self)
            return
        self._sections["weekly"] = [
            r for r in self._sections.get("weekly") or []
            if r.get("card_id") != card_id]
        self._render_section("weekly")

    def _render_docusketch_row(self, parent, entry):
        """Pending Docusketch request reminder. User clicks ✓ Resolved
        when the docusketch is no longer needed (auto-resolves on import
        elsewhere)."""
        wrap = tk.Frame(parent, bg=WHITE, padx=4, pady=6)
        wrap.pack(fill="x")
        top = tk.Frame(wrap, bg=WHITE)
        top.pack(fill="x")

        days = entry.get("days_pending", 0)
        if days >= 7:
            chip_bg, chip_fg = DANGER_HOVER, FLAG_RED
        elif days >= 3:
            chip_bg, chip_fg = WARN_HOVER, WARN_FG
        else:
            chip_bg, chip_fg = SUCCESS_HOVER, GREEN_DARK
        chip_text = (f"📐 {days}d" if days > 0 else "📐 today")
        tk.Label(top, text=chip_text,
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=chip_bg, fg=chip_fg,
                 padx=6, pady=1).pack(side="left")

        title = entry.get("client") or entry.get("card_name") or "(unknown)"
        self._make_title_label(
            top, title,
            primary_link=entry.get("card_url") or ""
        ).pack(side="left", padx=(8, 0))
        self._add_property_chip_if_multiunit(top, title)

        if entry.get("lane"):
            tk.Label(top, text=f"  · {entry['lane']}",
                     font=("Segoe UI Variable", 9, "italic"),
                     bg=WHITE, fg=TEXT_GRAY).pack(side="left")

        card_url = self._card_url_for_row(entry)
        if card_url:
            trello_link_button(
                top,
                command=lambda u=card_url: self._open_url(u),
            ).pack(side="right")

        done_button(
            top, "✓ Resolved",
            command=lambda e=entry: self._resolve_docusketch_request(e),
        ).pack(side="right", padx=(0, 6))
        self._attach_card_menu_to(
            wrap, entry.get("client") or entry.get("card_name") or "")
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(2, 0))

    def _render_docusign_add_link(self, parent):
        """Render the '+ Add Docusign manually' link at the top of the
        Docusign pending section. Renders regardless of whether the
        section has rows so the user can always reach the add flow."""
        link = tk.Label(parent, text="➕ Add Docusign manually…",
                         font=("Segoe UI Variable", 9, "bold underline"),
                         bg=WHITE, fg=LINK_FG, cursor="hand2",
                         anchor="w", padx=4, pady=4)
        link.pack(anchor="w")
        link.bind("<Button-1>",
                   lambda _e: self._open_docusign_add_dialog())

    def _open_docusign_add_dialog(self):
        """Modal: client name + (optional) email → adds a synthetic
        Docusign pending entry via docusign_requests.add_manual.

        If email is provided the entry lands in pending_signature state
        (Hygiene shows it under 'Awaiting signature'). If email is
        blank it lands in pending_email state — same ✉ Got email
        transition as the right-click flow."""
        dlg = tk.Toplevel(self)
        dlg.title("Add Docusign manually")
        dlg.configure(bg=BG)
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()
        try:
            dlg.geometry("440x220")
            dlg.resizable(False, False)
        except tk.TclError:
            pass

        head = tk.Frame(dlg, bg=BG, padx=14, pady=10)
        head.pack(fill="x")
        tk.Label(head, text="📝 Add Docusign pending",
                 font=("Segoe UI Variable", 11, "bold"),
                 bg=BG, fg=TEXT_DARK, anchor="w").pack(fill="x")
        tk.Label(head,
                 text=("Track a Docusign without a pinned Trello card. "
                       "Leave email blank to mark it as waiting for "
                       "the insured's email (you can fill in later "
                       "via ✉ Got email)."),
                 font=("Segoe UI Variable", 8), bg=BG, fg=TEXT_GRAY,
                 wraplength=400, justify="left",
                 anchor="w").pack(fill="x", pady=(4, 0))

        body_f = tk.Frame(dlg, bg=BG, padx=14)
        body_f.pack(fill="x")
        tk.Label(body_f, text="Client:",
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=BG, fg=TEXT_DARK).pack(anchor="w")
        client_var = tk.StringVar()
        cb = tk.Entry(body_f, textvariable=client_var,
                       font=("Segoe UI Variable", 10),
                       bg=WHITE, relief="solid", bd=1)
        cb.pack(fill="x", pady=(2, 8))
        cb.focus_set()

        tk.Label(body_f, text="Email (optional):",
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=BG, fg=TEXT_DARK).pack(anchor="w")
        email_var = tk.StringVar()
        email_entry = tk.Entry(body_f, textvariable=email_var,
                                font=("Segoe UI Variable", 10),
                                bg=WHITE, relief="solid", bd=1)
        email_entry.pack(fill="x", pady=(2, 0))

        bot = tk.Frame(dlg, bg=BG, padx=14, pady=12)
        bot.pack(fill="x", side="bottom")

        def _do_add():
            client = (client_var.get() or "").strip()
            if not client:
                messagebox.showerror("No client",
                                      "Type or pick a client name.",
                                      parent=dlg)
                return
            email = (email_var.get() or "").strip()
            try:
                import docusign_requests as dsr
                entry = dsr.add_manual(client, email=email)
            except Exception as ex:
                messagebox.showerror("Add failed", str(ex), parent=dlg)
                return
            if not entry:
                messagebox.showerror(
                    "Add failed",
                    "Couldn't record this entry.", parent=dlg)
                return
            dlg.destroy()
            state_label = ("Awaiting signature" if email
                           else "Awaiting email")
            show_toast(self,
                       f"Docusign added for {client} — {state_label}",
                       kind="info")
            # Refresh the section so the new entry shows immediately.
            try:
                import docusign_requests as dsr
                self._sections["docusign"] = dsr.pending_requests()
            except Exception:
                pass
            self._render_section("docusign")

        secondary_button(bot, "Cancel", padx=12, pady=4,
                          command=dlg.destroy
                          ).pack(side="right", padx=(8, 0))
        done_button(bot, "➕ Add", padx=18, pady=4,
                     command=_do_add
                  ).pack(side="right")

    def _render_docusign_row(self, parent, entry):
        """Pending-Docusign row. Renders one of two layouts:
          • pending_signature — paperwork was sent; offer ✓ Received.
          • pending_email     — no email known; offer ✉ Got email.
        Both layouts share the age chip + name + 🔗 Open card.
        """
        wrap = tk.Frame(parent, bg=WHITE, padx=4, pady=6)
        wrap.pack(fill="x")
        top = tk.Frame(wrap, bg=WHITE)
        top.pack(fill="x")

        days = entry.get("days_pending", 0)
        if days >= 7:
            chip_bg, chip_fg = DANGER_HOVER, FLAG_RED
        elif days >= 3:
            chip_bg, chip_fg = WARN_HOVER, WARN_FG
        else:
            chip_bg, chip_fg = SUCCESS_HOVER, GREEN_DARK
        chip_text = (f"📝 {days}d" if days > 0 else "📝 today")
        tk.Label(top, text=chip_text,
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=chip_bg, fg=chip_fg,
                 padx=6, pady=1).pack(side="left")

        # State pill — at-a-glance signal for which of the two waits.
        state = (entry.get("state") or "pending_signature")
        if state == "pending_email":
            state_bg, state_fg, state_lbl = ("#FFF6D6", "#7A5C12",
                                              "Awaiting email")
        else:
            state_bg, state_fg, state_lbl = ("#E6EFFA", "#1F4E8A",
                                              "Awaiting signature")
        tk.Label(top, text=f" {state_lbl} ",
                 font=("Segoe UI Variable", 7, "bold"),
                 bg=state_bg, fg=state_fg,
                 padx=4, pady=0).pack(side="left", padx=(6, 0))

        title = entry.get("client") or entry.get("card_name") or "(unknown)"
        self._make_title_label(
            top, title,
            primary_link=entry.get("card_url") or ""
        ).pack(side="left", padx=(8, 0))
        self._add_property_chip_if_multiunit(top, title)

        if entry.get("lane"):
            tk.Label(top, text=f"  · {entry['lane']}",
                     font=("Segoe UI Variable", 9, "italic"),
                     bg=WHITE, fg=TEXT_GRAY).pack(side="left")

        # Show the email when we have one — confirms paperwork went to
        # the right address without the user having to open the card.
        if state == "pending_signature" and entry.get("email"):
            tk.Label(wrap, text=f"  → {entry['email']}",
                     font=("Segoe UI Variable", 8),
                     bg=WHITE, fg=TEXT_GRAY,
                     anchor="w").pack(fill="x", pady=(2, 0))

        card_url = self._card_url_for_row(entry)
        if card_url:
            trello_link_button(
                top,
                command=lambda u=card_url: self._open_url(u),
            ).pack(side="right")

        # Right-most action: ✓ Received (always available) — closes the
        # pending state entirely. For email-pending rows we also offer
        # ✉ Got email to transition state without resolving.
        done_button(
            top, "✓ Received",
            command=lambda e=entry: self._resolve_docusign_request(e),
        ).pack(side="right", padx=(0, 6))
        if state == "pending_email":
            link_button(
                top, "✉ Got email",
                padx=8, pady=2,
                command=lambda e=entry: self._docusign_capture_email(e),
                tooltip=("Enter the insured's email — posts the Docusign "
                         "sent comment to Trello and flips this row to "
                         "Awaiting signature.")
            ).pack(side="right", padx=(0, 6))
        # 🔄 Resend — start the 5-day physical-signature SLA. Distinct
        # from ✓ Received because the user may resend multiple times
        # before the paperwork actually comes back signed; each resend
        # restarts the clock and posts a Trello note.
        if state == "pending_signature":
            secondary_button(
                top, "🔄 Resend",
                command=lambda e=entry: self._docusign_record_resend(e),
                tooltip=("Resent the paperwork — starts the 5-day SLA. "
                         "Past 5 days unsigned, the row lands in the "
                         "Physical-signature SLA section.")
            ).pack(side="right", padx=(0, 6))

        self._attach_card_menu_to(
            wrap, entry.get("client") or entry.get("card_name") or "")
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(2, 0))

    def _resolve_docusign_request(self, entry):
        try:
            import docusign_requests as dsr
            dsr.resolve(entry.get("card_id", ""))
        except Exception as ex:
            messagebox.showerror("Couldn't resolve", str(ex), parent=self)
            return
        self._sections["docusign"] = [
            e for e in self._sections.get("docusign", [])
            if e.get("card_id") != entry.get("card_id")]
        self._render_section("docusign")
        # Also clear any matching resend tracker since the paperwork is
        # now received — keeps the two sections consistent without the
        # user having to click ✓ Signed separately.
        try:
            import missing_items_tracker as mit
            for r in mit.list_docusign_resends():
                if r.get("card_id") == entry.get("card_id"):
                    mit.mark_docusign_signed(r.get("id") or "")
        except Exception:
            pass

    def _docusign_record_resend(self, entry):
        """Start the 5-day physical-signature SLA timer for this card.
        Posts a Trello comment + creates / restarts the tracker row.
        Re-renders both the source section and the SLA section so the
        user sees the timer started."""
        client = (entry.get("client")
                  or entry.get("card_name") or "(unknown)")
        try:
            import missing_items_tracker as mit
            mit.record_docusign_resend(
                client,
                card_id=entry.get("card_id") or "",
                card_url=entry.get("card_url") or "")
        except Exception as ex:
            messagebox.showerror("Couldn't record resend",
                                  str(ex), parent=self)
            return
        try:
            show_toast(
                self,
                f"Docusign resend tracked — 5-day SLA started for {client}",
                kind="info", duration=2800)
        except Exception:
            pass
        # Refresh sections so the new tracker row shows up in
        # docusign_resends and the source row stays put.
        try:
            import missing_items_tracker as mit
            self._sections["docusign_resends"] = (
                mit.needs_physical_signature(threshold_days=5))
            self._render_section("docusign_resends")
        except Exception:
            pass

    def _docusign_capture_email(self, entry):
        """Prompt for the insured's email, then call
        docusign_requests.update_email — which posts the Docusign-sent
        comment to Trello and flips the entry's state. Re-renders the
        section so the row reflects the new state immediately."""
        from tkinter import simpledialog
        email = simpledialog.askstring(
            "Got email",
            f"Insured's email for {entry.get('client') or entry.get('card_name')}:",
            parent=self)
        if not email or not email.strip():
            return
        email = email.strip()
        try:
            import docusign_requests as dsr
            updated = dsr.update_email(entry.get("card_id", ""), email)
        except Exception as ex:
            messagebox.showerror("Couldn't update", str(ex), parent=self)
            return
        if updated is None:
            messagebox.showinfo(
                "Not found",
                "This Docusign entry wasn't in the pending list anymore — "
                "maybe it was resolved from another tab. Refreshing.",
                parent=self)
            self._redraw_all()
            return
        # Refresh the section so the new state pill + email show.
        try:
            import docusign_requests as dsr
            self._sections["docusign"] = dsr.pending_requests()
        except Exception:
            pass
        self._render_section("docusign")

    def _resolve_docusketch_request(self, entry):
        try:
            import docusketch_requests as dr
            dr.resolve(entry.get("card_id", ""))
        except Exception as ex:
            messagebox.showerror("Couldn't resolve", str(ex), parent=self)
            return
        # Drop in-memory + redraw the section. Persistence handles the
        # store; next scan re-reads from there.
        self._sections["docusketch"] = [
            e for e in self._sections.get("docusketch", [])
            if e.get("card_id") != entry.get("card_id")]
        self._render_section("docusketch")

    def _render_ipr_row(self, parent, entry):
        """Initial Photo Report request — someone @mentioned the user
        on a Trello card asking for the IPR. Auto-clears once the user
        replies with 'uploaded'/'done' on the same card; the ✓ Done
        button is the manual override."""
        wrap = tk.Frame(parent, bg=WHITE, padx=4, pady=6)
        wrap.pack(fill="x")
        top = tk.Frame(wrap, bg=WHITE)
        top.pack(fill="x")

        # Age chip — request comments older than 3d are warmer to draw
        # the eye to ones the user has been ignoring.
        age_days = 0
        ts = entry.get("requested_at") or ""
        try:
            from datetime import datetime as _dt
            from datetime import timezone as _tz
            t = _dt.fromisoformat(ts.split(".")[0].rstrip("Z"))
            now = _dt.now(_tz.utc).replace(tzinfo=None)
            age_days = max(0, (now - t).days)
        except Exception:
            pass
        if age_days >= 5:
            chip_bg, chip_fg = DANGER_HOVER, FLAG_RED
        elif age_days >= 2:
            chip_bg, chip_fg = WARN_HOVER, WARN_FG
        else:
            chip_bg, chip_fg = SUCCESS_HOVER, GREEN_DARK
        chip_text = f"📷 {age_days}d" if age_days > 0 else "📷 today"
        tk.Label(top, text=chip_text,
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=chip_bg, fg=chip_fg,
                 padx=6, pady=1).pack(side="left")

        # 🚨 Escalate chip — duties-doc requires escalation to Sam for
        # items pending > 3 business days. 5 calendar days is the safe
        # trigger across any weekend boundary.
        if age_days >= 5:
            esc_label = "🚨 → Sam" if age_days < 10 else "🚨 → Sam (overdue)"
            tk.Label(top, text=esc_label,
                     font=("Segoe UI Variable", 8, "bold"),
                     bg=DANGER_HOVER, fg=FLAG_RED,
                     padx=5, pady=1).pack(side="left", padx=(4, 0))

        title = entry.get("card_name") or "(unknown)"
        self._make_title_label(
            top, title,
            primary_link=entry.get("card_url") or ""
        ).pack(side="left", padx=(8, 0))
        self._add_property_chip_if_multiunit(top, entry.get("card_name") or "")

        meta_bits = []
        if entry.get("lane_name"):
            meta_bits.append(entry["lane_name"])
        if entry.get("requested_by"):
            meta_bits.append(f"asked by {entry['requested_by']}")
        if meta_bits:
            tk.Label(top, text="  · " + "  ·  ".join(meta_bits),
                     font=("Segoe UI Variable", 9, "italic"),
                     bg=WHITE, fg=TEXT_GRAY).pack(side="left")

        card_url = self._card_url_for_row(entry)
        if card_url:
            trello_link_button(
                top,
                command=lambda u=card_url: self._open_url(u),
            ).pack(side="right")

        done_button(
            top, "✓ Done",
            command=lambda e=entry: self._resolve_ipr_request(e),
        ).pack(side="right", padx=(0, 6))

        snippet = entry.get("snippet") or ""
        if snippet:
            tk.Label(wrap, text=f"“{snippet}”",
                     font=("Segoe UI Variable", 9, "italic"),
                     bg=WHITE, fg=TEXT_GRAY,
                     wraplength=720, justify="left", anchor="w"
                     ).pack(fill="x", anchor="w", padx=(20, 0), pady=(2, 0))
        self._attach_card_menu_to(
            wrap, entry.get("client") or entry.get("card_name") or "")
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(2, 0))

    def _resolve_ipr_request(self, entry):
        cid = entry.get("card_id") or ""
        cmt = entry.get("comment_id") or ""
        if not cid or not cmt:
            return
        try:
            per.set_ipr_resolved(cid, cmt, by="manual")
        except Exception as ex:
            messagebox.showerror("Couldn't resolve", str(ex), parent=self)
            return
        # Drop in-memory + redraw the section. Persistence handles the
        # store; next scan filters via ipr_resolved automatically.
        self._sections["ipr"] = [
            e for e in self._sections.get("ipr", [])
            if not (e.get("card_id") == cid
                    and e.get("comment_id") == cmt)]
        self._render_section("ipr")

    def _render_adjuster_pending_row(self, parent, entry):
        """Inbox match awaiting user approval. Shows the matched Trello
        card, the sender, the subject, and a preview of the match
        reason so the user can decide ✓ Post (drop the receipt comment
        on the card) or ✕ Dismiss (false positive — vendor, realtor,
        shared-mailbox sender that slipped through the static filter).
        Dismissals are persisted so the message doesn't re-queue on
        the next scan."""
        wrap = tk.Frame(parent, bg=WHITE, padx=4, pady=6)
        wrap.pack(fill="x")
        top = tk.Frame(wrap, bg=WHITE)
        top.pack(fill="x")

        # Age chip — warmer the older the inquiry, so the user sees
        # which approvals are at risk of being stale by the time they
        # post.
        received_iso = (entry.get("received") or "")[:19]
        age_days = 0
        try:
            from datetime import datetime as _dt
            from datetime import timezone as _tz
            t = _dt.fromisoformat(received_iso.rstrip("Z"))
            now = _dt.now(_tz.utc).replace(tzinfo=None)
            age_days = max(0, (now - t).days)
        except Exception:
            pass
        if age_days >= 3:
            chip_bg, chip_fg = DANGER_HOVER, FLAG_RED
        elif age_days >= 1:
            chip_bg, chip_fg = WARN_HOVER, WARN_FG
        else:
            chip_bg, chip_fg = SUCCESS_HOVER, GREEN_DARK
        chip_text = f"📨 {age_days}d" if age_days > 0 else "📨 today"
        tk.Label(top, text=chip_text,
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=chip_bg, fg=chip_fg,
                 padx=6, pady=1).pack(side="left")

        title = entry.get("card_name") or "(unknown card)"
        self._make_title_label(
            top, title,
            primary_link=entry.get("card_url") or ""
        ).pack(side="left", padx=(8, 0))
        self._add_property_chip_if_multiunit(top, title)

        meta_bits = []
        if entry.get("match"):
            meta_bits.append(f"match: {entry['match']}")
        if entry.get("received"):
            meta_bits.append(
                entry["received"][:16].replace("T", " ") + " UTC")
        if meta_bits:
            tk.Label(top, text="  · " + "  ·  ".join(meta_bits),
                     font=("Segoe UI Variable", 9, "italic"),
                     bg=WHITE, fg=TEXT_GRAY).pack(side="left")

        # Right-side actions, packed right-to-left so visual L→R order
        # mirrors the order I want the user to read them: card link,
        # then dismiss, then approve. Approve is the primary action so
        # it gets done_button (green); dismiss is destructive-ish so
        # it gets warn_button (amber, not red — false positives aren't
        # errors, just a filter the matcher hasn't learned yet).
        card_url = entry.get("card_url") or ""
        if card_url:
            trello_link_button(
                top,
                command=lambda u=card_url: self._open_url(u),
            ).pack(side="right")
        warn_button(
            top, "✕ Dismiss",
            command=lambda e=entry: self._dismiss_adjuster_pending(e),
        ).pack(side="right", padx=(0, 6))
        done_button(
            top, "✓ Post",
            command=lambda e=entry: self._approve_adjuster_pending(e),
        ).pack(side="right", padx=(0, 6))

        # Detail block: sender + subject + body preview. Helps the user
        # judge whether the match is real without opening Outlook for
        # every row.
        detail = tk.Frame(wrap, bg=WHITE)
        detail.pack(fill="x", padx=(20, 0), pady=(2, 0))

        sender_line = ""
        if entry.get("sender_name") and entry.get("sender_email"):
            sender_line = (f"From: {entry['sender_name']} "
                            f"<{entry['sender_email']}>")
        elif entry.get("sender_email"):
            sender_line = f"From: {entry['sender_email']}"
        if sender_line:
            tk.Label(detail, text=sender_line,
                     font=("Segoe UI Variable", 9),
                     bg=WHITE, fg=TEXT_GRAY,
                     anchor="w", justify="left"
                     ).pack(fill="x", anchor="w")

        subject = entry.get("subject") or ""
        if subject:
            tk.Label(detail, text=f"Subject: {subject}",
                     font=("Segoe UI Variable", 9, "italic"),
                     bg=WHITE, fg=TEXT_GRAY,
                     wraplength=720, justify="left", anchor="w"
                     ).pack(fill="x", anchor="w")

        preview = (entry.get("preview") or "").strip()
        if preview:
            tk.Label(detail, text=f"“{preview}”",
                     font=("Segoe UI Variable", 9, "italic"),
                     bg=WHITE, fg=TEXT_GRAY,
                     wraplength=720, justify="left", anchor="w"
                     ).pack(fill="x", anchor="w", pady=(2, 0))

        # Show the exact comment that ✓ Post would drop on the card,
        # in a muted block — the user is approving a literal post, so
        # there should be no ambiguity about what lands on Trello.
        #
        # The queue stores a 240-char body preview only; the actual
        # ✓ Post fetches the full email via outlook_local before
        # dropping the comment. Surface that explicitly so the user
        # isn't surprised when a long body lands on Trello.
        comment_text = (entry.get("comment_text") or "").strip()
        preview_len = len((entry.get("preview") or ""))
        body_truncated = preview_len >= 235
        if comment_text:
            title_text = ("Will post (preview — full body fetched on ✓):"
                          if body_truncated else "Will post:")
            tk.Label(detail,
                     text=f"{title_text}\n{comment_text}",
                     font=("Consolas", 8),
                     bg=SURFACE_2, fg=TEXT_GRAY,
                     wraplength=720, justify="left", anchor="w",
                     padx=6, pady=4
                     ).pack(fill="x", anchor="w", pady=(4, 0))

        self._attach_card_menu_to(wrap, title)
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(2, 0))

    def _approve_adjuster_pending(self, entry):
        """User clicked ✓ Post: actually post the receipt comment to
        Trello, then drop the in-memory row + re-render."""
        mid = entry.get("message_id") or ""
        if not mid:
            return
        try:
            import adjuster_monitor as am
            ok = am.approve_pending(mid)
        except Exception as ex:
            messagebox.showerror("Couldn't post", str(ex), parent=self)
            return
        if not ok:
            messagebox.showerror(
                "Couldn't post",
                "Trello rejected the comment. The entry is still in the "
                "approval queue — try again or dismiss it.",
                parent=self)
            return
        self._sections["adjuster_pending"] = [
            e for e in self._sections.get("adjuster_pending", [])
            if (e or {}).get("message_id") != mid]
        self._render_section("adjuster_pending")

    def _dismiss_adjuster_pending(self, entry):
        """User clicked ✕ Dismiss: drop the entry + remember the
        message_id so the next inbox scan doesn't re-queue the same
        false positive."""
        mid = entry.get("message_id") or ""
        if not mid:
            return
        try:
            import adjuster_monitor as am
            am.dismiss_pending(mid)
        except Exception as ex:
            messagebox.showerror("Couldn't dismiss", str(ex), parent=self)
            return
        self._sections["adjuster_pending"] = [
            e for e in self._sections.get("adjuster_pending", [])
            if (e or {}).get("message_id") != mid]
        self._render_section("adjuster_pending")

    def _render_wc_audit_due_row(self, parent, entry):
        """🗂 Monthly WC Audit reminder. One-row banner with a click
        action that navigates to the WC Audit panel. Auto-clears once
        the operator saves a file in OUTPUT_DIR for the current month."""
        row = tk.Frame(parent, bg=WHITE, padx=4, pady=8,
                        highlightthickness=1,
                        highlightbackground=WARN_FG)
        row.pack(fill="x", pady=(2, 4))
        left = tk.Frame(row, bg=WHITE)
        left.pack(side="left", fill="x", expand=True, padx=8)
        month_label = entry.get("month") or ""
        tk.Label(left,
                  text=f"🗂  {month_label} WC audit due",
                  font=("Segoe UI Variable", 10, "bold"),
                  bg=WHITE, fg=WARN_FG, cursor="hand2",
                  anchor="w").pack(anchor="w")
        sub = entry.get("subtitle") or ""
        if sub:
            tk.Label(left, text=sub,
                      font=("Segoe UI Variable", 8),
                      bg=WHITE, fg=TEXT_GRAY,
                      anchor="w").pack(anchor="w", pady=(2, 0))
        try:
            from ui_buttons import done_button as _done
            _done(row, "🗂  Open WC Audit",
                   command=self._open_wc_audit_panel,
                   padx=12, pady=4
                   ).pack(side="right", padx=(0, 8))
        except Exception:
            pass

    def _open_wc_audit_panel(self):
        """Cross-tool jump. Prefer launcher-embedded navigation per the
        feedback-navigate_to-embedded rule; fall back to spawning the
        standalone if we're not embedded in a launcher."""
        try:
            self.navigate_to("wc_audit")
            return
        except Exception:
            pass
        try:
            import paths as _paths
            _paths.spawn_tool("wc_audit")
        except Exception:
            pass

    def _render_stalled_row(self, parent, entry):
        """🐌 Stalled jobs row. Surfaces a job that's been in its
        current pipeline stage past the threshold. Color escalates
        amber → red at 2× threshold. Click jumps to the Pipeline panel."""
        import pipeline_stages as _ps
        days = int(entry.get("_days_in_stage") or 0)
        th = int(entry.get("_stage_threshold") or 9999)
        stage_key = entry.get("current_stage") or ""
        stage_label = _ps.STAGE_LABELS.get(stage_key, stage_key)
        # 2× threshold = red, otherwise amber.
        if days > th * 2:
            chip_bg, chip_fg = DANGER_HOVER, FLAG_RED
        else:
            chip_bg, chip_fg = WARN_HOVER, WARN_FG

        row = tk.Frame(parent, bg=WHITE, padx=4, pady=4)
        row.pack(fill="x", pady=(0, 2))
        top = tk.Frame(row, bg=WHITE)
        top.pack(fill="x")

        tk.Label(top,
                  text=f"🐌 {days}d / {th}d",
                  font=("Segoe UI Variable", 9, "bold"),
                  bg=chip_bg, fg=chip_fg, padx=6, pady=1
                  ).pack(side="left")
        tk.Label(top,
                  text=stage_label,
                  font=("Segoe UI Variable", 9, "bold"),
                  bg=WHITE, fg=TEXT_DARK).pack(side="left", padx=(8, 0))
        client = entry.get("client_display") or ""
        title_lbl = tk.Label(top, text=client,
                              font=("Segoe UI Variable", 10),
                              bg=WHITE, fg=LINK_FG, cursor="hand2")
        title_lbl.pack(side="left", padx=(10, 0))
        title_lbl.bind("<Button-1>",
                        lambda _e, s=stage_key:
                        self._open_pipeline_panel(stage_filter=s))

        # Sub-line: board / lane + last activity preview.
        board_lane = ((entry.get("board_name") or "") + "  /  "
                      + (entry.get("list_name") or ""))
        last = (entry.get("last_activity_at") or "")[:10]
        sub_bits = []
        if board_lane.strip(" /"):
            sub_bits.append(board_lane)
        if last:
            sub_bits.append(f"last activity {last}")
        if sub_bits:
            tk.Label(row, text="  ·  ".join(sub_bits),
                      font=("Segoe UI Variable", 8),
                      bg=WHITE, fg=TEXT_GRAY).pack(anchor="w", padx=(80, 0))

        # Action buttons — Open Trello + Open Pipeline panel.
        url = entry.get("card_url") or ""
        if url:
            try:
                from ui_buttons import link_button as _link_btn
                _link_btn(row, "🔗 Trello",
                            command=lambda u=url: self._open_url(u),
                            padx=8, pady=2
                            ).pack(side="right", padx=(0, 6))
            except Exception:
                pass

    def _render_anomaly_row(self, parent, entry):
        """🚨 Anomalous jobs row. Surfaces a job that's far past its
        stage's historical median (3×+). Always uses red coloring —
        the existence of an anomaly is itself the alarm signal."""
        import pipeline_stages as _ps
        days = int(entry.get("_days_in_stage") or 0)
        med = int(entry.get("_hist_median") or 0)
        ratio = float(entry.get("_anomaly_ratio") or 0.0)
        stage_key = entry.get("current_stage") or ""
        stage_label = _ps.STAGE_LABELS.get(stage_key, stage_key)

        row = tk.Frame(parent, bg=WHITE, padx=4, pady=4)
        row.pack(fill="x", pady=(0, 2))
        top = tk.Frame(row, bg=WHITE)
        top.pack(fill="x")

        tk.Label(top,
                  text=f"🚨 {ratio:.1f}× ({days}d vs {med}d)",
                  font=("Segoe UI Variable", 9, "bold"),
                  bg=DANGER_HOVER, fg=FLAG_RED, padx=6, pady=1
                  ).pack(side="left")
        tk.Label(top, text=stage_label,
                  font=("Segoe UI Variable", 9, "bold"),
                  bg=WHITE, fg=TEXT_DARK).pack(side="left", padx=(8, 0))
        client = entry.get("client_display") or ""
        title_lbl = tk.Label(top, text=client,
                              font=("Segoe UI Variable", 10),
                              bg=WHITE, fg=LINK_FG, cursor="hand2")
        title_lbl.pack(side="left", padx=(10, 0))
        title_lbl.bind("<Button-1>",
                        lambda _e, s=stage_key:
                        self._open_pipeline_panel(stage_filter=s))

        board_lane = ((entry.get("board_name") or "") + "  /  "
                      + (entry.get("list_name") or ""))
        last = (entry.get("last_activity_at") or "")[:10]
        sub_bits = []
        if board_lane.strip(" /"):
            sub_bits.append(board_lane)
        if last:
            sub_bits.append(f"last activity {last}")
        if sub_bits:
            tk.Label(row, text="  ·  ".join(sub_bits),
                      font=("Segoe UI Variable", 8),
                      bg=WHITE, fg=TEXT_GRAY).pack(anchor="w", padx=(80, 0))

        url = entry.get("card_url") or ""
        if url:
            try:
                from ui_buttons import link_button as _link_btn
                _link_btn(row, "🔗 Trello",
                            command=lambda u=url: self._open_url(u),
                            padx=8, pady=2
                            ).pack(side="right", padx=(0, 6))
            except Exception:
                pass

    def _render_docusketch_needed_row(self, parent, entry):
        """📐 Docusketch needed (WIP) row. One-click 📐 Request posts
        the Trello comment + logs the pending entry — the row then
        graduates to the existing 'Docusketch pending' section above.
        ✕ Dismiss for cards whose Docusketch was already done outside
        the tracker."""
        days = int(entry.get("days_in_wip") or 0)
        # Age chip — amber under 3d, red past that. WIP without a sketch
        # request beyond ~3 days is operator-actionable.
        if days >= 3:
            chip_bg, chip_fg = DANGER_HOVER, FLAG_RED
        else:
            chip_bg, chip_fg = WARN_HOVER, WARN_FG

        row = tk.Frame(parent, bg=WHITE, padx=4, pady=4)
        row.pack(fill="x", pady=(0, 2))
        top = tk.Frame(row, bg=WHITE)
        top.pack(fill="x")

        chip_text = (f"📐 {days}d in WIP"
                      if days > 0 else "📐 just hit WIP")
        tk.Label(top, text=chip_text,
                  font=("Segoe UI Variable", 9, "bold"),
                  bg=chip_bg, fg=chip_fg, padx=6, pady=1
                  ).pack(side="left")

        client = entry.get("client") or ""
        title_lbl = tk.Label(top, text=client,
                              font=("Segoe UI Variable", 10),
                              bg=WHITE, fg=LINK_FG, cursor="hand2")
        title_lbl.pack(side="left", padx=(10, 0))
        url = entry.get("card_url") or ""
        if url:
            title_lbl.bind("<Button-1>",
                            lambda _e, u=url: self._open_url(u))

        # Sub-line: board / lane so the user can verify it's the right WIP
        board_lane = ((entry.get("board_name") or "") + "  /  "
                      + (entry.get("list_name") or ""))
        if board_lane.strip(" /"):
            tk.Label(row, text=board_lane,
                      font=("Segoe UI Variable", 8),
                      bg=WHITE, fg=TEXT_GRAY).pack(anchor="w",
                                                    padx=(90, 0))

        # 📐 Request button — the primary action.
        try:
            from ui_buttons import warn_button as _warn_btn
            _warn_btn(row, "📐 Request via Trello",
                       command=lambda e=entry:
                           self._request_docusketch_for_card(e),
                       padx=10, pady=2
                       ).pack(side="right", padx=(0, 6))
        except Exception:
            pass
        # ✕ Dismiss — operator-says "already done elsewhere, don't ask
        # again". Persists so the row doesn't reappear on next scan.
        try:
            from ui_buttons import icon_button as _icon_btn
            _icon_btn(row, "✕", fg=TEXT_GRAY, padx=6, pady=2,
                       tooltip=("Dismiss — Docusketch already handled "
                                "outside the tracker"),
                       command=lambda e=entry:
                           self._dismiss_docusketch_needed(e)
                       ).pack(side="right", padx=(0, 4))
        except Exception:
            pass

    def _request_docusketch_for_card(self, entry):
        """One-click Request — posts the Trello comment + logs the
        pending entry. Mirrors the docusketch import dialog's
        'Mark Requested' flow but skips the dialog (we're already
        on the Hygiene panel, no further confirmation needed)."""
        cid = entry.get("card_id")
        client = entry.get("client") or ""
        if not cid:
            return
        try:
            import docusketch_requests as dr
        except Exception as ex:
            messagebox.showerror("Docusketch unavailable",
                                  str(ex), parent=self)
            return
        try:
            posted = dr.request(cid, client_name=client)
        except Exception as ex:
            messagebox.showerror("Trello post failed",
                                  f"{type(ex).__name__}: {ex}",
                                  parent=self)
            return
        if posted is None:
            messagebox.showerror(
                "Couldn't record",
                "Trello request failed — check ems.log.",
                parent=self)
            return
        msg = f"📐 Docusketch requested on {posted.get('card_name', client)}"
        if not posted.get("comment_posted", True):
            msg += " (locally — Trello comment failed to post)"
        try:
            show_toast(self, msg, kind="success", duration=2500)
        except Exception:
            pass
        # Drop the local in-memory row immediately so the section
        # updates without waiting for the next scan. The card will
        # appear in 'Docusketch pending' on the next _redraw_all.
        self._sections["docusketch_needed"] = [
            r for r in self._sections.get("docusketch_needed", [])
            if r.get("card_id") != cid]
        self._render_section("docusketch_needed")

    def _dismiss_docusketch_needed(self, entry):
        """Persist the dismissal + drop the row from the section."""
        cid = entry.get("card_id")
        if not cid:
            return
        try:
            import docusketch_requests as dr
            dr.dismiss_wip_card(cid)
        except Exception:
            pass
        self._sections["docusketch_needed"] = [
            r for r in self._sections.get("docusketch_needed", [])
            if r.get("card_id") != cid]
        self._render_section("docusketch_needed")

    def _open_pipeline_panel(self, *, stage_filter=None):
        """Jump to the Pipeline panel. When `stage_filter` is given,
        the panel opens with that stage's filter chip active."""
        try:
            self.navigate_to("pipeline")
        except Exception:
            try:
                import paths as _paths
                _paths.spawn_tool("pipeline")
            except Exception:
                return
        # Best-effort: if the launcher embeds and we can reach the
        # panel instance, set its filter so the user lands on the
        # right slice. Catches the "no host available" case silently.
        if not stage_filter:
            return
        try:
            host = getattr(self, "host", None)
            if host is not None and hasattr(host, "_panels"):
                panel = host._panels.get("pipeline")
                if panel is not None and hasattr(panel, "_set_filter"):
                    panel.after(50, lambda:
                                 panel._set_filter(stage_filter))
        except Exception:
            pass

    def _open_url(self, url):
        if not url:
            return
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass

    def _copy_xa_apology_note(self):
        """Copy the standard XA apology text to the clipboard. Same
        wording as `ar_followup.DEFAULT_NOTE` — single source of truth
        so a wording change in one place propagates everywhere.
        """
        try:
            from ar_followup import DEFAULT_NOTE as _note
        except Exception:
            _note = ("Our apologies for the delay. Please note our "
                     "estimating team is diligently working on the file.")
        try:
            self.clipboard_clear()
            self.clipboard_append(_note)
            # update() forces the clipboard buffer to flush before the
            # method returns — without it, paste-targets that grab the
            # clipboard sub-1s after the click can miss the new content.
            self.update()
        except tk.TclError:
            return
        try:
            show_toast(self, "📋 Copied XA apology note", kind="success")
        except Exception:
            pass

    def _render_dispute_row(self, parent, entry):
        """One row in the ⚖ Audit disputes section. Shows aging chip
        (overdue→red, needs-ack→amber, default→green), insured name +
        carrier, claim #, intake source pill, summary preview, and
        actions: ✓ Mark Ack, ✎ Open editor, ↗ Open in Excel."""
        from datetime import date as _date, datetime as _dtm
        import dispute_tracker as _dt

        wrap = tk.Frame(parent, bg=WHITE, padx=4, pady=6)
        wrap.pack(fill="x")
        top = tk.Frame(wrap, bg=WHITE)
        top.pack(fill="x")

        # Aging chip — compute overdue/needs-ack/default to color.
        tgt_raw = entry.get("target_response_date") or ""
        is_overdue = False
        days_to_target = None
        try:
            if tgt_raw:
                if isinstance(tgt_raw, (_dtm, _date)):
                    d = (tgt_raw.date()
                          if isinstance(tgt_raw, _dtm) else tgt_raw)
                else:
                    d = _dtm.fromisoformat(str(tgt_raw)[:10]).date()
                days_to_target = (d - _date.today()).days
                if days_to_target < 0:
                    is_overdue = True
        except (ValueError, TypeError):
            pass
        ack = (entry.get("ack_email_sent") or "").strip().lower()
        needs_ack = (ack != "yes")

        # Tiered escalation by days vs. next-day midnight cutoff:
        #   • ≥2d before cutoff → calm green
        #   • 1d before cutoff  → amber "due tomorrow"
        #   • 0d (cutoff today) → strong amber "due today"
        #   • 1d overdue        → red "OVERDUE 1d"
        #   • ≥2d overdue       → 🚨 red "OVERDUE Nd" (loud)
        # The previous logic was binary (red/amber/green) regardless of
        # days, so a dispute 7d overdue and one 0d overdue looked the
        # same. This makes the escalation continuous.
        chip_font = ("Segoe UI Variable", 9, "bold")
        if is_overdue and days_to_target is not None:
            n = abs(days_to_target)
            chip_bg, chip_fg = DANGER_HOVER, FLAG_RED
            if n >= 2:
                chip_text = f"🚨 OVERDUE {n}d"
                chip_font = ("Segoe UI Variable", 9, "bold")
            else:
                chip_text = f"⚖ OVERDUE {n}d"
        elif is_overdue:
            chip_bg, chip_fg = DANGER_HOVER, FLAG_RED
            chip_text = "⚖ OVERDUE"
        elif days_to_target == 0:
            chip_bg, chip_fg = WARN_HOVER, WARN_FG
            chip_text = "⚖ DUE TODAY"
        elif days_to_target == 1:
            chip_bg, chip_fg = WARN_HOVER, WARN_FG
            chip_text = "⚖ due tomorrow"
        elif needs_ack:
            chip_bg, chip_fg = WARN_HOVER, WARN_FG
            chip_text = "⚖ ack needed"
        else:
            chip_bg, chip_fg = SUCCESS_HOVER, GREEN_DARK
            if days_to_target is not None:
                chip_text = f"⚖ {days_to_target}d left"
            else:
                chip_text = "⚖ open"
        tk.Label(top, text=chip_text,
                 font=chip_font,
                 bg=chip_bg, fg=chip_fg, padx=6, pady=1
                 ).pack(side="left")

        # Intake-source pill (XA / Email / Other)
        intake = (entry.get("intake_source") or "").strip()
        if intake:
            tk.Label(top, text=intake.upper(),
                     font=("Segoe UI Variable", 7, "bold"),
                     bg=LINK_BG, fg=LINK_FG, padx=5, pady=1
                     ).pack(side="left", padx=(6, 0))

        # Status pill — drives the rest of the workflow.
        status = (entry.get("status") or "New").strip()
        tk.Label(top, text=status,
                 font=("Segoe UI Variable", 7, "bold"),
                 bg=SURFACE_2, fg=TEXT_DARK, padx=5, pady=1
                 ).pack(side="left", padx=(4, 0))

        # Title: insured + carrier
        insured = (entry.get("insured") or "(unknown)").strip()
        title_parts = [insured]
        carrier = (entry.get("carrier") or "").strip()
        if carrier:
            title_parts.append(f"({carrier})")
        title = " ".join(title_parts)
        self._make_title_label(
            top, title, primary_link=""
        ).pack(side="left", padx=(8, 0))
        self._add_property_chip_if_multiunit(top, insured)

        # Meta line: claim # + estimator + assigned date
        meta_bits = []
        claim = (entry.get("claim") or "").strip()
        if claim:
            meta_bits.append(f"claim {claim}")
        est = (entry.get("assigned_estimator") or "").strip()
        if est:
            meta_bits.append(f"est: {est}")
        assigned_d = entry.get("assigned_date") or ""
        if assigned_d:
            meta_bits.append(f"assigned {str(assigned_d)[:10]}")
        if meta_bits:
            tk.Label(top, text="  · " + "  ·  ".join(meta_bits),
                     font=("Segoe UI Variable", 9, "italic"),
                     bg=WHITE, fg=TEXT_GRAY).pack(side="left")

        # Right-side actions
        secondary_button(
            top, "↗ Open in Excel",
            command=lambda: self._open_dispute_in_excel(),
        ).pack(side="right")
        secondary_button(
            top, "✎ Edit row…",
            command=lambda e=entry: self._open_dispute_editor(e),
        ).pack(side="right", padx=(0, 6))
        if needs_ack:
            done_button(
                top, "✓ Mark Ack",
                command=lambda e=entry: self._dispute_mark_ack(e),
            ).pack(side="right", padx=(0, 6))

        # Summary preview line
        summary = (entry.get("dispute_summary") or "").strip()
        if summary:
            tk.Label(wrap, text=f"“{summary}”",
                     font=("Segoe UI Variable", 9, "italic"),
                     bg=WHITE, fg=TEXT_GRAY, wraplength=720,
                     justify="left", anchor="w"
                     ).pack(fill="x", anchor="w",
                             padx=(20, 0), pady=(2, 0))

        self._attach_card_menu_to(wrap, insured)
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(2, 0))

    def _dispute_mark_ack(self, entry):
        """User clicked ✓ Mark Ack on a dispute row. Flip Ack Email
        Sent → Yes via dispute_tracker.update_row. Drop the row in
        memory + re-render so the chip flips to green immediately."""
        import dispute_tracker as _dt
        row_no = entry.get("row_number") or 0
        if not row_no:
            return
        ok = _dt.update_row(row_no, {_dt.COL_ACK: "Yes"})
        if not ok:
            show_toast(self,
                        "Queued (Excel has the file open)",
                        kind="warn", duration=3000)
        # Update in-memory + re-render. _do_write returns False when
        # queued, but the next _redraw_all will pick up the workbook
        # change once it lands. Local cache update keeps the UI snappy.
        entry["ack_email_sent"] = "Yes"
        self._render_section("disputes")

    def _open_dispute_editor(self, entry):
        """Open the dedicated Dispute Tracker panel — the rich editor
        lives there. Closest equivalent in the Hygiene panel is just
        an Ack-or-not toggle; everything else (status transitions,
        notes, dates) needs the per-column dropdowns the dedicated
        panel provides.

        Uses `navigate_to` so launcher-hosted Hygiene swaps panels
        inside the same window; only standalone Hygiene (rare) falls
        through to a spawn. The previous direct `spawn_tool` call
        produced a second Dispute Tracker window even when the
        launcher already had the panel embedded — user-reported as
        the tracker "popping open in its own window unprompted."
        """
        try:
            self.navigate_to("dispute_tracker")
        except Exception as ex:
            messagebox.showerror(
                "Couldn't open",
                f"Dispute Tracker panel didn't launch:\n{ex}",
                parent=self)

    def _open_dispute_in_excel(self):
        """Open the workbook file in whatever's registered for .xlsx
        (Excel for most users)."""
        try:
            import dispute_tracker as _dt
            p = _dt.path()
            if os.path.isfile(p):
                os.startfile(p)
            else:
                messagebox.showinfo(
                    "Not found",
                    f"No workbook at:\n{p}\n\nFirst write will create "
                    "it.", parent=self)
        except Exception as ex:
            messagebox.showerror(
                "Couldn't open", str(ex), parent=self)

    def _render_missing_item_row(self, parent, entry):
        """One row in the 📋 Missing section. Shows the item label,
        client, age in days since the flag was raised, the stage chip
        (INTAKE / AUDIT / SNAPSHOT / OFFICE), and three actions:
        ✓ Resolved, 👁 Ignore, 🔗 Open card."""
        row = tk.Frame(parent, bg=WHITE, padx=4, pady=6)
        row.pack(fill="x")
        top = tk.Frame(row, bg=WHITE)
        top.pack(fill="x")

        # Age chip — warmer the older it gets.
        age = int(entry.get("age_days") or 0)
        if age >= 14:
            chip_bg, chip_fg = DANGER_HOVER, FLAG_RED
        elif age >= 7:
            chip_bg, chip_fg = WARN_HOVER, WARN_FG
        else:
            chip_bg, chip_fg = SUCCESS_HOVER, GREEN_DARK
        chip_text = f"📋 {age}d" if age > 0 else "📋 today"
        tk.Label(top, text=chip_text,
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=chip_bg, fg=chip_fg,
                 padx=6, pady=1).pack(side="left")

        # 🚨 Escalate chip — per the EMS Admin duties doc, jobs pending
        # missing items for more than 3 business days must escalate to
        # Sam. 5 calendar days is the safe trigger (covers any 3-BD
        # window even with a full weekend); past 7 calendar days the
        # rule is unambiguously triggered.
        if age >= 5:
            esc_label = "🚨 → Sam" if age < 10 else "🚨 → Sam (overdue)"
            tk.Label(top, text=esc_label,
                     font=("Segoe UI Variable", 8, "bold"),
                     bg=DANGER_HOVER, fg=FLAG_RED,
                     padx=5, pady=1).pack(side="left", padx=(4, 0))

        # Item-type pill — "ATP form" / "Initial photos" / etc.
        tk.Label(top, text=entry.get("item_label", "?"),
                 font=("Segoe UI Variable", 8, "bold"),
                 bg=LINK_BG, fg=LINK_FG,
                 padx=4, pady=1).pack(side="left", padx=(6, 0))

        # Stage pill — INITIAL / SNAPSHOT / AUDIT — so the user knows
        # where in the workflow the gap was flagged. Helps prioritize:
        # an INITIAL-stage gap that's been open 5 days is a "tech never
        # turned it in" thread; a SNAPSHOT-stage gap is "we caught it
        # at closeout, paper chase from here." Older records without a
        # stage value default to SNAPSHOT (the only source pre-stage).
        stage = (entry.get("stage") or "snapshot").lower()
        stage_palette = {
            "initial":  (INFO_HOVER,    INFO_FG),
            "snapshot": (WARN_HOVER,    WARN_FG),
            "audit":    (SUCCESS_HOVER, SUCCESS_FG),
            "manual":   (SURFACE_2,     TEXT_GRAY),
        }
        sbg, sfg = stage_palette.get(stage, stage_palette["snapshot"])
        stage_text = {
            "initial":  "INTAKE",
            "snapshot": "SNAPSHOT",
            "audit":    "AUDIT",
            "manual":   "OFFICE",
        }.get(stage, "SNAPSHOT")
        tk.Label(top, text=stage_text,
                 font=("Segoe UI Variable", 7, "bold"),
                 bg=sbg, fg=sfg,
                 padx=5, pady=1).pack(side="left", padx=(4, 0))

        # Client title — clickable when the card_url is known.
        client = entry.get("client") or "(unknown)"
        card_url = entry.get("card_url") or ""
        if not card_url and entry.get("card_id"):
            try:
                import trello_client as _tc
                card_url = _tc.card_url_from_id(entry["card_id"])
            except Exception:
                card_url = ""
        self._make_title_label(
            top, client, primary_link=card_url
        ).pack(side="left", padx=(8, 0))
        self._add_property_chip_if_multiunit(top, client)

        # Status flair — ignored rows render with a muted strikethrough
        # color so the section still groups them visually.
        if entry.get("status") == "ignored":
            tk.Label(top, text=f"  · ignored: {entry.get('ignore_reason') or ''}",
                     font=("Segoe UI Variable", 8, "italic"),
                     bg=WHITE, fg=TEXT_GRAY).pack(side="left")

        # Right-side actions, packed right-to-left so visual L→R order
        # mirrors code order.
        if card_url:
            trello_link_button(
                top,
                command=lambda u=card_url: self._open_url(u),
            ).pack(side="right")
        done_button(
            top, "✓ Resolved",
            command=lambda r=entry: self._missing_item_mark_resolved(r),
        ).pack(side="right", padx=(0, 6))
        secondary_button(
            top, "👁 Ignore",
            command=lambda r=entry: self._missing_item_open_ignore_dialog(r),
        ).pack(side="right", padx=(0, 6))

        self._attach_card_menu_to(row, client)
        tk.Frame(parent, bg=BORDER, height=1
                 ).pack(fill="x", pady=(2, 0))

    def _render_docusign_resend_row(self, parent, entry):
        """One row in the ✍ Docusign physical-signature SLA section.
        Triggered when a resend is ≥ 5 days old without signature.
        Actions: ✓ Signed (closes), 🚶 Physical-signature done (closes
        with note), 🔗 Open card."""
        row = tk.Frame(parent, bg=WHITE, padx=4, pady=6)
        row.pack(fill="x")
        top = tk.Frame(row, bg=WHITE)
        top.pack(fill="x")

        age = int(entry.get("age_days") or 0)
        chip_bg, chip_fg = DANGER_HOVER, FLAG_RED
        tk.Label(top, text=f"⏰ {age}d since resend",
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=chip_bg, fg=chip_fg,
                 padx=6, pady=1).pack(side="left")

        client = entry.get("client") or "(unknown)"
        card_url = entry.get("card_url") or ""
        if not card_url and entry.get("card_id"):
            try:
                import trello_client as _tc
                card_url = _tc.card_url_from_id(entry["card_id"])
            except Exception:
                card_url = ""
        self._make_title_label(
            top, client, primary_link=card_url
        ).pack(side="left", padx=(8, 0))
        self._add_property_chip_if_multiunit(top, client)

        if card_url:
            trello_link_button(
                top,
                command=lambda u=card_url: self._open_url(u),
            ).pack(side="right")
        done_button(
            top, "🚶 Physical sig'd",
            command=lambda r=entry: self._docusign_resend_mark_physical(r),
        ).pack(side="right", padx=(0, 6))
        secondary_button(
            top, "✓ Signed",
            command=lambda r=entry: self._docusign_resend_mark_signed(r),
        ).pack(side="right", padx=(0, 6))

        # Escalation footnote so the user can see whether the
        # 5-day comment has been posted.
        if entry.get("escalation_posted_at"):
            try:
                from datetime import datetime as _dt
                t = _dt.fromisoformat(
                    entry["escalation_posted_at"].split(".")[0].rstrip("Z"))
                stamp = t.strftime("%a %b %d %I:%M %p")
            except Exception:
                stamp = entry["escalation_posted_at"]
            tk.Label(row,
                     text=f"  ↳ Escalation comment posted {stamp}",
                     font=("Segoe UI Variable", 9, "italic"),
                     bg=WHITE, fg=TEXT_GRAY, anchor="w"
                     ).pack(fill="x", padx=(2, 0), pady=(2, 0))

        self._attach_card_menu_to(row, client)
        tk.Frame(parent, bg=BORDER, height=1
                 ).pack(fill="x", pady=(2, 0))

    def _missing_item_mark_resolved(self, entry):
        try:
            import missing_items_tracker as mit
            mit.mark_resolved(entry.get("id") or "")
        except Exception as ex:
            messagebox.showerror("Couldn't resolve", str(ex), parent=self)
            return
        self._sections["missing_items"] = [
            r for r in self._sections.get("missing_items", [])
            if r.get("id") != entry.get("id")]
        self._render_section("missing_items")

    def _missing_item_open_ignore_dialog(self, entry):
        """Prompt the user for an ignore reason — required so the row
        is auditable later ('why was this case opted out?')."""
        from tkinter import simpledialog
        reason = simpledialog.askstring(
            "Ignore reason",
            f"Why are we ignoring this missing item for "
            f"{entry.get('client') or '(unknown)'}?\n\n"
            "(Examples: 'client out of country', 'closing 2027', "
            "'on-purpose self-pay — no forms')",
            parent=self)
        if reason is None:
            return     # cancelled
        try:
            import missing_items_tracker as mit
            mit.mark_ignored(entry.get("id") or "", reason=reason or "")
        except Exception as ex:
            messagebox.showerror("Couldn't ignore", str(ex), parent=self)
            return
        self._sections["missing_items"] = [
            r for r in self._sections.get("missing_items", [])
            if r.get("id") != entry.get("id")]
        self._render_section("missing_items")

    def _docusign_resend_mark_signed(self, entry):
        try:
            import missing_items_tracker as mit
            mit.mark_docusign_signed(entry.get("id") or "")
        except Exception as ex:
            messagebox.showerror("Couldn't mark signed", str(ex), parent=self)
            return
        self._sections["docusign_resends"] = [
            r for r in self._sections.get("docusign_resends", [])
            if r.get("id") != entry.get("id")]
        self._render_section("docusign_resends")

    def _docusign_resend_mark_physical(self, entry):
        from tkinter import simpledialog
        note = simpledialog.askstring(
            "Physical signature note",
            f"Who picked up the physical signature for "
            f"{entry.get('client') or '(unknown)'}?\n\n"
            "(Optional — leave blank to just close.)",
            parent=self) or ""
        try:
            import missing_items_tracker as mit
            mit.mark_physical_signature_done(
                entry.get("id") or "", note=note)
        except Exception as ex:
            messagebox.showerror("Couldn't mark physical signed",
                                  str(ex), parent=self)
            return
        self._sections["docusign_resends"] = [
            r for r in self._sections.get("docusign_resends", [])
            if r.get("id") != entry.get("id")]
        self._render_section("docusign_resends")

    def _render_open_job_row(self, parent, entry):
        """One row in the 📋 All open Trello jobs section. Cheap
        oversight view — one line per card with lane, age since last
        seen by the DB, and a Trello jump button."""
        row = tk.Frame(parent, bg=WHITE, padx=4, pady=4)
        row.pack(fill="x")
        top = tk.Frame(row, bg=WHITE)
        top.pack(fill="x")

        # Age chip based on last_seen_at — stale jobs warmer.
        from datetime import datetime as _dt
        from datetime import timezone as _tz
        days_stale = 0
        ts = entry.get("last_seen_at") or ""
        try:
            t = _dt.fromisoformat(ts.split(".")[0].rstrip("Z"))
            now = _dt.now(_tz.utc).replace(tzinfo=None)
            days_stale = max(0, (now - t).days)
        except Exception:
            pass
        if days_stale >= 30:
            chip_bg, chip_fg = DANGER_HOVER, FLAG_RED
        elif days_stale >= 14:
            chip_bg, chip_fg = WARN_HOVER, WARN_FG
        else:
            chip_bg, chip_fg = SUCCESS_HOVER, GREEN_DARK
        chip_text = (f"📋 {days_stale}d"
                     if days_stale > 0 else "📋 today")
        tk.Label(top, text=chip_text,
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=chip_bg, fg=chip_fg,
                 padx=6, pady=1).pack(side="left")

        # Lane chip — from metadata captured at sync time.
        md = entry.get("metadata") or {}
        lane = (md.get("lane") if isinstance(md, dict) else "") or "?"
        tk.Label(top, text=f"[{lane}]",
                 font=("Segoe UI Variable", 8, "bold"),
                 bg=SUCCESS_BG, fg=SUCCESS_FG,
                 padx=4, pady=1).pack(side="left", padx=(6, 0))

        # Title — clickable to the card.
        card_id = ""
        try:
            import ems_db
            card_id = ems_db.get_link(entry.get("canon_key", ""),
                                        "trello_card") or ""
        except Exception:
            card_id = ""
        card_url = ""
        if card_id:
            try:
                import trello_client as _tc
                card_url = _tc.card_url_from_id(card_id)
            except Exception:
                card_url = ""
        title = entry.get("display_name") or entry.get("canon_key", "?")
        self._make_title_label(
            top, title, primary_link=card_url
        ).pack(side="left", padx=(8, 0))
        self._add_property_chip_if_multiunit(top, title)

        if card_url:
            trello_link_button(
                top,
                command=lambda u=card_url: self._open_url(u),
            ).pack(side="right")

        self._attach_card_menu_to(row, title)
        tk.Frame(parent, bg=BORDER, height=1
                 ).pack(fill="x", pady=(2, 0))

    def _render_closeout_row(self, parent, candidate):
        row = tk.Frame(parent, bg=WHITE, padx=4, pady=6)
        row.pack(fill="x")
        top = tk.Frame(row, bg=WHITE)
        top.pack(fill="x")
        src = candidate.get("source", "?").upper()
        src_color = "#5C2C9D" if src == "LANE" else "#2C6FA8"
        tk.Label(top, text=f"[{src}]",
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=WHITE, fg=src_color).pack(side="left")
        tk.Label(top, text=f"[{candidate.get('lane') or '?'}]",
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=SUCCESS_BG, fg=SUCCESS_FG,
                 padx=6, pady=1).pack(side="left", padx=(8, 0))
        self._make_title_label(
            top, candidate.get("card_name", "?"),
            primary_link=candidate.get("card_url") or ""
        ).pack(side="left", padx=(8, 0))
        self._add_property_chip_if_multiunit(top, candidate.get("card_name") or "")
        # 🛑 Pre-snapshot blocker chip — count any open missing-items
        # the team needs to chase BEFORE this card gets snapshotted.
        # Catches the "sometimes they forget to move things over"
        # case: the card is in the SNAPSHOT lane but the photo/form
        # chase isn't done. Surface aggressively (red) so the user
        # sees it before they click 📸 Snapshot.
        try:
            import missing_items_tracker as _mit
            _mit_card_id = (candidate.get("card_id") or "")
            _open_misses = []
            if _mit_card_id:
                _open_misses = [
                    r for r in _mit.list_open_items()
                    if r.get("card_id") == _mit_card_id
                ]
            if _open_misses:
                _summary = ", ".join(
                    r.get("item_label", "?") for r in _open_misses[:3])
                if len(_open_misses) > 3:
                    _summary += f", +{len(_open_misses) - 3} more"
                _blk = tk.Label(
                    top,
                    text=f"🛑 {len(_open_misses)} missing — {_summary}",
                    font=("Segoe UI Variable", 8, "bold"),
                    bg=DANGER_BG, fg=DANGER_FG,
                    padx=4, pady=1)
                _blk.pack(side="left", padx=(6, 0))
                try:
                    from tool_panel import attach_tooltip
                    attach_tooltip(_blk,
                                    "Open missing-items tracked for this "
                                    "card. Resolve before snapshotting.")
                except Exception:
                    pass
        except Exception:
            pass
        # Buttons
        trello_link_button(
            top,
            command=lambda u=candidate.get("card_url"): self._open_url(u),
        ).pack(side="right")
        secondary_button(
            top, "Mark drafted",
            command=lambda c=candidate: self._mark_closeout_drafted(c)
        ).pack(side="right", padx=(0, 6))
        send_button(
            top, "📸 Snapshot", padx=10, pady=2,
            font=("Segoe UI Variable", 8, "bold"),
            command=lambda c=candidate: self._open_in_snapshot(c)
        ).pack(side="right", padx=(0, 6))
        # Trigger text
        if candidate.get("trigger_text"):
            tk.Label(row,
                     text=f"  ↳ {candidate['trigger_text'][:140]}",
                     font=("Segoe UI Variable", 9, "italic"),
                     bg=WHITE, fg=TEXT_GRAY,
                     anchor="w", justify="left", wraplength=720
                     ).pack(fill="x", padx=(2, 0), pady=(2, 0))
        self._attach_card_menu_to(row, candidate.get("card_name") or "")
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(2, 0))

    # ── Row actions ───────────────────────────────────────────────────────
    def _open_url(self, url):
        if not url:
            return
        try:
            open_url_in_preferred_browser(url)
        except Exception as ex:
            messagebox.showerror("Couldn't open URL", str(ex), parent=self)

    def _make_title_label(self, parent, text, *, primary_link="",
                            font_size=10, default_fg=None):
        """Build a section-row title Label, clickable when `primary_link`
        is set. Shared across every Hygiene row renderer — link-blue +
        underline + hand cursor signal the jump affordance without
        adding another button to the right side of the row.

        The caller still .pack()s the returned widget, so each section
        keeps full control of its layout (side/padx/expand)."""
        if primary_link:
            font_spec = ("Segoe UI Variable", font_size, "bold underline")
            fg = "#1A56A8"
            cur = "hand2"
        else:
            font_spec = ("Segoe UI Variable", font_size, "bold")
            fg = default_fg if default_fg is not None else TEXT_DARK
            cur = ""
        lbl = tk.Label(parent, text=text, font=font_spec,
                        bg=WHITE, fg=fg, cursor=cur)
        if primary_link:
            lbl.bind(
                "<Button-1>",
                lambda _e, u=primary_link: self._open_url(u))
        return lbl

    def _add_property_chip_if_multiunit(self, parent, client,
                                          *, side="left",
                                          padx=(6, 0)):
        """Render a `🏢 <Property>` chip when `client` looks like a
        unit of a multi-unit property (Avila Apartments 1416, etc.).
        Returns the widget when one was created so the caller can
        adjust packing/tooltip, else None.

        Shared so every Hygiene section that surfaces a row tied to a
        specific client can flag the property affiliation at a
        glance — same chip styling as audit + IUQ panels."""
        if not client:
            return None
        try:
            import ems_db
            prop_name, _unit = ems_db.detect_property_and_unit(client)
        except Exception:
            return None
        if not prop_name:
            return None
        chip = tk.Label(
            parent, text=f" 🏢 {prop_name} ",
            font=("Segoe UI Variable", 8, "bold"),
            bg=LINK_BG, fg=LINK_FG,
            padx=4, pady=1)
        chip.pack(side=side, padx=padx)
        try:
            from tool_panel import attach_tooltip
            attach_tooltip(chip,
                            f"Part of {prop_name} (multi-unit property)")
        except Exception:
            pass
        return chip

    def _attach_card_menu_to(self, row_widget, client):
        """Bind the shared client-card right-click menu to a Hygiene
        section row. Same menu the Audit / IUQ / Snapshot panels show
        (Pin to Trello, Change folder, Edit aliases, Reset memory), so
        a pin / alias edit applied from Hygiene immediately propagates
        to every other surface that consults the same persistence keys.

        Silently no-ops when `client` is blank (some rows don't carry
        a usable client name — e.g. an email-source concern with no
        matched card) or the helper isn't importable."""
        if not client or not row_widget:
            return
        try:
            from job_widgets import attach_card_context_menu
        except Exception:
            return
        try:
            import config as _cfg
            audit_base = (_cfg.load().get("audit_base") or "") or None
        except Exception:
            audit_base = None
        try:
            attach_card_context_menu(
                self, [row_widget], client,
                audit_base=audit_base,
                on_change_folder=lambda _p, c=client: show_toast(
                    self,
                    f"OD folder pinned for {c} — applies on next audit",
                    kind="info"))
        except Exception:
            pass

    def _snooze_card(self, card_id, violations, *, hours):
        """Snooze every violation rule on this card. `hours=None` means
        permanent (clear via 'Show dismissed' → re-rendered → click again
        to reactivate, or via persistence.clear_card_warning)."""
        for v in violations:
            rule = v.get("rule") or ""
            per.dismiss_card_warning(card_id, rule, hours=hours)
        self._redraw_all()

    def _mark_closeout_drafted(self, candidate):
        cid = candidate.get("card_id", "")
        try:
            import closeout_watcher as cw
            cw.mark_drafted(cid)
        except Exception as ex:
            messagebox.showerror("Couldn't mark drafted", str(ex), parent=self)
            return
        # Drop the card from the in-memory closeout list right now so
        # the row disappears without waiting on the next full Trello
        # scan. Without this, _redraw_all renders the cached section
        # which still contains the card and the user sees no effect
        # from their click — the "Mark drafted does nothing" symptom.
        if cid:
            self._sections["closeout"] = [
                c for c in (self._sections.get("closeout") or [])
                if c.get("card_id") != cid
            ]
        self._redraw_all()

    def _open_in_snapshot(self, candidate):
        """Switch the launcher to the Snapshot panel and pre-fill it
        from this card. Marks the card as drafted so it stops surfacing
        here on the next refresh."""
        cid = candidate.get("card_id", "")
        host = getattr(self, "host", None)
        if host is None:
            messagebox.showinfo(
                "Open Snapshot manually",
                "Couldn't switch tabs from a standalone window — open "
                "Snapshot from the launcher and click 'Pull from Trello…'.",
                parent=self)
            return
        try:
            host.show_tool("snapshot")
            panel = host._panels.get("snapshot")
            if panel is not None and cid and hasattr(
                    panel, "_fill_from_trello_card"):
                # Defer one tick so the panel's on_show finishes first
                # (it may reset state) before we feed it the card id.
                self._track_after(60, lambda: panel._fill_from_trello_card(cid))
            if cid:
                import closeout_watcher as cw
                cw.mark_drafted(cid)
        except Exception as ex:
            messagebox.showerror("Couldn't open Snapshot", str(ex),
                                  parent=self)

    # ── Lifecycle ─────────────────────────────────────────────────────────
    def _track_after(self, ms, fn):
        """Wrapper around self.after that tracks the returned id so
        on_close can cancel everything pending. Without this, the bg
        scan's `self.after(0, ...)` calls queue Tk events that fire
        AFTER the launcher tried to destroy the panel — Tk raises
        TclError and the process stays alive holding the mainloop."""
        if self._closed:
            return None
        try:
            aid = self.after(ms, fn)
            self._after_ids.add(aid)
            return aid
        except tk.TclError:
            return None

    def on_show(self):
        if self._closed:
            return
        self._hidden = False
        # Always run the cache-or-scan flow on every show so stale data
        # never requires a manual Re-scan click.  If the cache is fresh
        # (< CACHE_TTL_MINUTES) it loads from persistence instantly; if
        # stale it kicks off a background scan automatically.
        self._track_after(50, self._load_cached_or_scan)

    def on_hide(self):
        # Soft-pause: scan thread keeps running, but UI-touching
        # callbacks become no-ops until on_show flips the flag back.
        # Don't bump scan_id here — that would discard a scan that's
        # about to finish; instead let it land into self._sections.
        self._hidden = True

    def on_close(self):
        # Mark closed so the bg thread short-circuits and pending
        # after-callbacks become no-ops.
        self._closed = True
        self._scan_id += 1
        # Cancel every pending after() so the Tk loop has nothing
        # left to drain. Iterate over a snapshot — after_cancel may
        # mutate the set indirectly through callback teardown.
        for aid in list(self._after_ids):
            try: self.after_cancel(aid)
            except Exception: pass
        self._after_ids.clear()
        # Symmetric unbind for the global Ctrl+F handler installed in
        # _build_ui — without this, a launcher cycle leaks the handler
        # and Ctrl+F keeps firing into a destroyed widget.
        try:
            self.unbind_all("<Control-f>")
        except tk.TclError:
            pass


def main():
    run_standalone(HygieneApp, geometry="1000x720", minsize=(640, 420))


if __name__ == "__main__":
    main()
