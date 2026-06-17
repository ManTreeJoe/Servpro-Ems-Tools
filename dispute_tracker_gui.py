"""Dispute Tracker panel — editable view of the shared
`Dispute Tracker.xlsx` workbook.

Routes every read/write through `dispute_tracker.py` so the
Audit Dispute auto-import (APA Monitor + inbox scan) and the panel
land on the same dedup key. Edits made in the GUI write straight to
the workbook; when Excel has the file open the writes queue to the
pending sidecar and replay on the next save attempt — same pattern
as `snapshots_excel`.

Per-row editor pops a modal with one input per column. Dropdown
columns read their options from the workbook's Options sheet, so
edits to that sheet pick up on the next refresh (no code change).
"""
from __future__ import annotations

import os
import sys
import tkinter as tk
from datetime import date, datetime
from tkinter import messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dispute_tracker as dt
import paths
from theme import (BG, BORDER, DANGER_HOVER, FLAG_RED, GREEN,
                    INFO_FG, SURFACE_2, TEXT_DARK, TEXT_GRAY, TEXT_MUTED,
                    WARN_FG, WARN_HOVER, WHITE)
from tool_panel import (ScrollableFrame, ToolPanel, attach_tooltip,
                         run_standalone, show_toast)
from ui_buttons import done_button, secondary_button, send_button

_ICON = paths.resource("wrench.ico")

# Column order shown in the table — matches the workbook left-to-right.
# Includes (column_key, display_label, treeview_width).
# Widths sum to ~1140 so the table fits inside the panel's default
# geometry (1200px usable after padding) on standard laptop screens
# without forcing horizontal scroll on the first paint.
_TABLE_COLUMNS: tuple[tuple[str, str, int], ...] = (
    (dt.COL_RECEIVED,      "Received",  72),
    (dt.COL_CLAIM,         "Claim #",   80),
    (dt.COL_INSURED,       "Insured",   170),
    (dt.COL_CARRIER,       "Carrier",   80),
    (dt.COL_TYPE,          "Type",      70),
    (dt.COL_PRIORITY,      "Priority",  60),
    (dt.COL_INTAKE,        "Intake",    60),
    (dt.COL_ACK,           "Ack?",      45),
    (dt.COL_ESTIMATOR,     "Estimator", 80),
    (dt.COL_ASSIGNED_DATE, "Assigned",  72),
    (dt.COL_TARGET_DATE,   "Target",    72),
    (dt.COL_STATUS,        "Status",    100),
    (dt.COL_NEXT_FOLLOWUP, "Next FU",   72),
    (dt.COL_RESOLUTION,    "Resolved",  72),
    (dt.COL_OUTCOME,       "Outcome",   75),
    (dt.COL_AMOUNT,        "Amount",    65),
)

# Filters across the top — quick "Status" + "Estimator" buttons.
_STATUS_FILTERS = ("All", "Open only", "New", "Under Review",
                    "Response Sent", "Closed")


def _short(s, n=60):
    s = (str(s or "")).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _coerce_display(val) -> str:
    """Treeview values must be strings — coerce dates / amounts cleanly."""
    if val is None:
        return ""
    if isinstance(val, (datetime, date)):
        return (val.date() if isinstance(val, datetime) else val).isoformat()
    if isinstance(val, float):
        # Money columns: show two decimals when the value is non-zero.
        if val == int(val):
            return f"{int(val)}"
        return f"{val:.2f}"
    return str(val)


def _today_iso() -> str:
    return date.today().isoformat()


class DisputeTrackerApp(ToolPanel):
    TOOL_TITLE        = "Dispute Tracker"
    TOOL_AUMID        = "Servpro.EMS.DisputeTracker"
    TOOL_GEOMETRY_KEY = "dispute_tracker"
    # Default sized to fit a 1366×768 laptop screen with room for the
    # taskbar and launcher chrome. Column widths above sum to ~1140
    # so the treeview fills inside this without horizontal scroll.
    DEFAULT_GEOMETRY  = "1240x680"

    def __init__(self, parent):
        super().__init__(parent)
        self.title(self.TOOL_TITLE)
        self.restore_geometry()
        # Minsize set low enough that even an awkward window snap leaves
        # the most important columns (Status, Insured, Claim) visible.
        self.minsize(760, 420)
        self.configure(bg=BG)
        if os.path.isfile(_ICON):
            try:
                self.iconbitmap(default=_ICON)
                self.iconbitmap(_ICON)
            except Exception:
                pass

        # Filter state
        self._status_filter = tk.StringVar(value="Open only")
        self._estimator_filter = tk.StringVar(value="All")
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._refresh_table())

        # In-memory cache of the last read so per-row edits don't have
        # to re-walk the workbook for every cell-update operation.
        self._rows: list[dict] = []
        self._dropdown_options: dict[str, list[str]] = {}

        self._build_ui()
        # Defer the workbook read until the panel is actually shown.
        # When the launcher preloads every panel up front, an
        # `after(50, _reload_workbook)` would run on the main thread
        # during the preload sweep — blocking later panels behind a
        # synchronous xlsx open. on_show() loads on demand instead.
        self._loaded_once = False

    def on_close(self):
        # Symmetric unbind for the global Ctrl+F handler — without
        # this, a launcher cycle leaks the handler and Ctrl+F keeps
        # firing into a destroyed widget.
        try:
            self.unbind_all("<Control-f>")
        except tk.TclError:
            pass
        super().on_close()

    # ── UI build ───────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header strip
        hdr = tk.Frame(self, bg=BG, padx=14, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="⚖  Dispute Tracker",
                 font=("Fraunces", 16, "bold"),
                 bg=BG, fg=TEXT_DARK).pack(side="left")
        self._path_lbl = tk.Label(
            hdr, text="", font=("Segoe UI Variable", 9),
            bg=BG, fg=TEXT_GRAY, cursor="hand2")
        self._path_lbl.pack(side="left", padx=(14, 0))
        self._path_lbl.bind(
            "<Button-1>", lambda _e: self._open_workbook_externally())
        attach_tooltip(self._path_lbl,
                        "Click to open the xlsx in Excel.")
        self._pending_lbl = tk.Label(
            hdr, text="", font=("Segoe UI Variable", 9, "italic"),
            bg=BG, fg=WARN_FG)
        self._pending_lbl.pack(side="left", padx=(14, 0))

        # Right-side header buttons
        send_button(
            hdr, "➕ New dispute",
            command=self._open_new_dispute_dialog,
            tooltip="Add a new dispute row to the workbook."
        ).pack(side="right")
        secondary_button(
            hdr, "↻ Refresh",
            command=self._reload_workbook,
            tooltip="Re-read the workbook (and drain any pending "
                    "writes Excel held up)."
        ).pack(side="right", padx=(0, 6))
        secondary_button(
            hdr, "🔄 Sync from Trello board",
            command=self._sync_from_trello_board,
            tooltip=("Pull every card from the EMS BILLING DISPUTES "
                     "Trello board and insert any that aren't already "
                     "tracked. Existing rows are NEVER overwritten — "
                     "your manual edits stay put.")
        ).pack(side="right", padx=(0, 6))

        # Filter row
        # NOTE: tuple pady on widget construction is a Tk error
        # ("bad screen distance"). Use a single int here and put the
        # asymmetric (0, 6) on the .pack() below.
        filt = tk.Frame(self, bg=BG, padx=14, pady=0)
        filt.pack(fill="x", pady=(0, 6))
        tk.Label(filt, text="Status:",
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=BG, fg=TEXT_DARK).pack(side="left")
        for label in _STATUS_FILTERS:
            self._make_filter_chip(filt, self._status_filter, label
                                     ).pack(side="left", padx=(4, 0))
        tk.Label(filt, text="    Estimator:",
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=BG, fg=TEXT_DARK).pack(side="left")
        self._estimator_chip_holder = tk.Frame(filt, bg=BG)
        self._estimator_chip_holder.pack(side="left")
        # Search
        tk.Label(filt, text="    🔍",
                 bg=BG, fg=TEXT_GRAY).pack(side="left")
        search_entry = ttk.Entry(filt, textvariable=self._search_var,
                                  font=("Segoe UI Variable", 9), width=24)
        search_entry.pack(side="left", padx=(4, 0))
        self._search_entry = search_entry
        # Esc clears, Ctrl+F focuses — mirrors the Hygiene + Spreadsheets
        # search affordance so keyboard behavior is consistent across
        # every panel with a text-filter box.
        def _clear_search(_e=None):
            try: self._search_var.set("")
            except tk.TclError: pass
            return "break"
        search_entry.bind("<Escape>", _clear_search)
        def _focus_search(_e=None):
            try:
                if not self.winfo_ismapped():
                    return None
                self._search_entry.focus_set()
                self._search_entry.select_range(0, "end")
            except tk.TclError:
                return None
            return "break"
        self.bind_all("<Control-f>", _focus_search, add="+")

        # Treeview body
        # Same tuple-on-construction trap — pad on the .pack() below.
        body = tk.Frame(self, bg=BG, padx=14, pady=0)
        body.pack(fill="both", expand=True, pady=(0, 10))

        cols = [k for k, _, _ in _TABLE_COLUMNS]
        # Inner frame holds the tree + horizontal scrollbar so the user
        # can pan to columns that overflow on narrower windows.
        tree_inner = tk.Frame(body, bg=BG)
        tree_inner.pack(side="left", fill="both", expand=True)
        self._tree = ttk.Treeview(
            tree_inner, columns=cols, show="headings", height=18,
            selectmode="browse")
        for key, label, width in _TABLE_COLUMNS:
            self._tree.heading(key, text=label)
            anchor = "e" if key in (dt.COL_AMOUNT,) else "w"
            # Only Insured stretches — gives the user-typed name the
            # extra room when the window is wider than the column sum.
            # Status used to stretch too; it widened past its needs
            # whenever Insured was short and shoved Next FU off-screen.
            self._tree.column(key, width=width, anchor=anchor,
                              stretch=(key == dt.COL_INSURED))
        # Aging tints
        self._tree.tag_configure("overdue",   background=DANGER_HOVER,
                                  foreground=FLAG_RED)
        self._tree.tag_configure("needs_ack", background=WARN_HOVER,
                                  foreground=WARN_FG)
        self._tree.tag_configure("closed",    background=SURFACE_2,
                                  foreground=TEXT_MUTED)
        self._tree.tag_configure("zebra",     background=SURFACE_2)

        vsb = ttk.Scrollbar(body, orient="vertical",
                              command=self._tree.yview)
        hsb = ttk.Scrollbar(tree_inner, orient="horizontal",
                              command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set,
                              xscrollcommand=hsb.set)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self._tree.pack(side="top", fill="both", expand=True)

        # Double-click → edit dialog. Right-click → context menu.
        self._tree.bind("<Double-1>", self._on_row_double_click)
        self._tree.bind("<Button-3>", self._on_row_right_click)

        # Footer status line
        foot = tk.Frame(self, bg=BG, padx=14, pady=8)
        foot.pack(fill="x", side="bottom")
        self._status_lbl = tk.Label(
            foot, text="", font=("Segoe UI Variable", 9),
            bg=BG, fg=TEXT_GRAY, anchor="w")
        self._status_lbl.pack(side="left", fill="x", expand=True)

    def _make_filter_chip(self, parent, var, label) -> tk.Label:
        """Pill button bound to a StringVar — visually tracks which
        chip is active. Cheaper than ttk.Radiobutton and themes
        cleanly without extra style juggling."""
        def _render():
            active = var.get() == label
            chip.configure(
                bg=GREEN if active else SURFACE_2,
                fg=WHITE if active else TEXT_DARK,
                font=("Segoe UI Variable", 9,
                       "bold" if active else "normal"))
        chip = tk.Label(parent, text=label,
                         padx=8, pady=2, cursor="hand2",
                         bg=SURFACE_2, fg=TEXT_DARK,
                         font=("Segoe UI Variable", 9))
        def _click(_e=None):
            var.set(label)
            _render()
            for sib in parent.winfo_children():
                if (isinstance(sib, tk.Label)
                        and getattr(sib, "_chip_refresh", None)):
                    sib._chip_refresh()
            self._refresh_table()
        chip.bind("<Button-1>", _click)
        chip._chip_refresh = _render
        _render()
        return chip

    # ── Data loading ───────────────────────────────────────────────────────

    def on_show(self):
        """Trigger the workbook read the first time the user opens the
        panel. Subsequent shows skip — the user can hit ↻ Refresh to
        re-read explicitly. Keeps launcher preload fast: each panel
        adds widget construction only (sub-100ms typical); the slow
        xlsx open waits until the user actually navigates here."""
        if not self._loaded_once:
            self._loaded_once = True
            # Tk-scheduled callback gives the show animation a tick to
            # paint before we kick the synchronous workbook read.
            self.after(20, self._reload_workbook)

    def _open_workbook_externally(self):
        p = dt.path()
        if not os.path.isfile(p):
            messagebox.showinfo(
                "Workbook not found",
                f"No file at:\n{p}\n\nFirst write will create it.",
                parent=self)
            return
        try:
            os.startfile(p)
        except Exception as ex:
            messagebox.showerror(
                "Couldn't open", str(ex), parent=self)

    def _sync_from_trello_board(self):
        """Pull every card from the EMS BILLING DISPUTES board (shortLink
        ``bnV8zbpJ``) and upsert each into the workbook. Insert-only:
        existing rows keyed by (claim, insured) are untouched, so the
        operator's manual edits stay put. Runs on a background thread
        so the rate-limited Trello calls don't freeze the panel."""
        import threading
        try:
            self._pending_lbl.config(text="Syncing from Trello board…",
                                       fg=INFO_FG)
        except (tk.TclError, AttributeError):
            pass

        def _bg():
            err = None
            result = {"added": 0, "skipped_existing": 0, "errors": 0}
            try:
                def _progress(i, n, name):
                    short = (name[:40] + "…") if len(name) > 41 else name
                    try:
                        self.after(0, lambda: self._pending_lbl.config(
                            text=f"Trello sync {i}/{n}: {short}",
                            fg=INFO_FG))
                    except (tk.TclError, AttributeError):
                        pass
                result = dt.sync_from_trello_board(progress_cb=_progress)
            except Exception as ex:
                err = ex

            def _done():
                if err is not None:
                    messagebox.showerror(
                        "Trello sync failed",
                        f"{type(err).__name__}: {err}", parent=self)
                    try:
                        self._pending_lbl.config(text="", fg=WARN_FG)
                    except (tk.TclError, AttributeError):
                        pass
                    return
                msg = (f"Synced from Trello — "
                       f"{result['added']} new, "
                       f"{result['skipped_existing']} already tracked")
                if result.get("errors"):
                    msg += f", {result['errors']} errors"
                try:
                    self._pending_lbl.config(text="", fg=WARN_FG)
                except (tk.TclError, AttributeError):
                    pass
                try:
                    show_toast(self, msg, kind="success", duration=3000)
                except Exception:
                    pass
                # Refresh the table so the new rows appear.
                self._reload_workbook()

            try:
                self.after(0, _done)
            except (tk.TclError, AttributeError):
                pass

        threading.Thread(target=_bg, daemon=True).start()

    def _reload_workbook(self):
        # Drain pending writes first — Excel may have released the
        # file between the last queued write and now.
        try:
            drained = dt.process_pending()
        except Exception:
            drained = 0
        try:
            self._dropdown_options = dt.read_options()
        except Exception:
            self._dropdown_options = {}
        try:
            self._rows = dt.read_rows()
        except Exception as ex:
            self._rows = []
            self._status_lbl.configure(
                text=f"⚠ Couldn't read workbook: {ex}",
                fg=FLAG_RED)
            self._refresh_table()
            return
        self._rebuild_estimator_chips()
        self._refresh_table()
        # Publish open-dispute count to persistence so the launcher's
        # Dispute Tracker tile can render a notification badge. Open =
        # any row whose Sent column isn't "yes". Best-effort.
        try:
            import persistence as _per
            open_n = 0
            for r in (self._rows or []):
                sent = (r.get("sent") or "").strip().lower()
                if sent != "yes":
                    open_n += 1
            _per.set_value("dispute_tracker_open_count", int(open_n))
        except Exception:
            pass
        # Path label + pending badge
        self._path_lbl.configure(text=_short(dt.path(), 92))
        pcount = dt.pending_count()
        if pcount:
            self._pending_lbl.configure(
                text=f"⏳ {pcount} queued (Excel has file open)")
        elif drained:
            self._pending_lbl.configure(
                text=f"✓ {drained} queued write(s) applied")
            # Clear that hint after a few seconds.
            self.after(4000, lambda: self._pending_lbl.configure(text=""))
        else:
            self._pending_lbl.configure(text="")

    def _rebuild_estimator_chips(self):
        """Estimator chips depend on whatever Options says — rebuild
        them after every reload so a user adding 'Pablo' to Options
        sees the chip without a restart."""
        for child in self._estimator_chip_holder.winfo_children():
            child.destroy()
        estimators = ["All", *(self._dropdown_options.get(dt.COL_ESTIMATOR) or [])]
        for label in estimators:
            self._make_filter_chip(
                self._estimator_chip_holder,
                self._estimator_filter, label
            ).pack(side="left", padx=(4, 0))

    # ── Table render ──────────────────────────────────────────────────────

    def _matches_filters(self, row: dict) -> bool:
        """Apply the three filter controls (status / estimator /
        search) against one row. Status filter is the most-restrictive
        — its "Open only" mode collapses to !Closed."""
        status_filter = self._status_filter.get()
        status = (row.get(dt.COL_STATUS) or "").strip()
        if status_filter == "Open only":
            if status.lower() == "closed":
                return False
        elif status_filter != "All":
            if status != status_filter:
                return False
        est_filter = self._estimator_filter.get()
        if est_filter and est_filter != "All":
            est = (row.get(dt.COL_ESTIMATOR) or "").strip()
            if est != est_filter:
                return False
        q = (self._search_var.get() or "").strip().lower()
        if q:
            haystack = " ".join(
                str(row.get(k) or "") for k, _, _ in _TABLE_COLUMNS)
            if q not in haystack.lower():
                return False
        return True

    def _row_tag(self, row: dict) -> str:
        """Pick a color tag for visual priority — overdue beats
        needs-ack beats default. Closed rows render muted regardless."""
        status = (row.get(dt.COL_STATUS) or "").strip().lower()
        if status == "closed":
            return "closed"
        # Overdue: target date in the past and open
        tgt = row.get(dt.COL_TARGET_DATE)
        if tgt:
            try:
                if isinstance(tgt, (datetime, date)):
                    d = (tgt.date()
                          if isinstance(tgt, datetime) else tgt)
                else:
                    d = datetime.fromisoformat(str(tgt)[:10]).date()
                if d < date.today():
                    return "overdue"
            except (ValueError, TypeError):
                pass
        ack = (row.get(dt.COL_ACK) or "").strip().lower()
        if ack != "yes":
            return "needs_ack"
        return ""

    def _refresh_table(self):
        # Clear current view
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        visible = [r for r in self._rows if self._matches_filters(r)]
        # Aging-first: open + overdue rises to the top.
        def _sort_key(r):
            tag = self._row_tag(r)
            # overdue=0, needs_ack=1, open=2, closed=3
            tag_rank = {"overdue": 0, "needs_ack": 1, "closed": 3}.get(tag, 2)
            received = str(r.get(dt.COL_RECEIVED) or "")
            return (tag_rank, received)
        visible.sort(key=_sort_key)
        for idx, row in enumerate(visible):
            values = tuple(_coerce_display(row.get(k))
                            for k, _, _ in _TABLE_COLUMNS)
            tag = self._row_tag(row)
            tags = (tag,) if tag else (("zebra",) if idx % 2 else ())
            self._tree.insert(
                "", "end", iid=f"r{row.get('row_number')}",
                values=values, tags=tags)
        # Footer status
        total = len(self._rows)
        open_n = sum(1 for r in self._rows
                      if (r.get(dt.COL_STATUS) or "").strip().lower()
                      != "closed")
        overdue_n = sum(1 for r in self._rows
                         if self._row_tag(r) == "overdue")
        ack_n = sum(1 for r in self._rows
                     if self._row_tag(r) == "needs_ack")
        bits = [
            f"Showing {len(visible)} of {total}",
            f"{open_n} open",
        ]
        if overdue_n:
            bits.append(f"{overdue_n} overdue")
        if ack_n:
            bits.append(f"{ack_n} need ack")
        self._status_lbl.configure(
            text="  ·  ".join(bits),
            fg=FLAG_RED if overdue_n else TEXT_GRAY)

    # ── Edit / new dialogs ────────────────────────────────────────────────

    def _row_from_iid(self, iid: str) -> dict | None:
        try:
            target_row = int(iid.lstrip("r"))
        except (ValueError, AttributeError):
            return None
        for r in self._rows:
            if r.get("row_number") == target_row:
                return r
        return None

    def _on_row_double_click(self, _e):
        iid = self._tree.focus()
        if not iid:
            return
        row = self._row_from_iid(iid)
        if not row:
            return
        self._open_edit_dialog(row)

    def _on_row_right_click(self, e):
        iid = self._tree.identify_row(e.y)
        if not iid:
            return
        self._tree.selection_set(iid)
        self._tree.focus(iid)
        row = self._row_from_iid(iid)
        if not row:
            return
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="✎ Edit row…",
                          command=lambda: self._open_edit_dialog(row))
        # One-click status transitions — the most common edits.
        menu.add_separator()
        cur_status = (row.get(dt.COL_STATUS) or "").strip()
        for opt in (self._dropdown_options.get(dt.COL_STATUS)
                     or ["New", "Under Review", "Response Sent",
                          "Closed"]):
            if opt == cur_status:
                continue
            menu.add_command(
                label=f"  Status → {opt}",
                command=lambda o=opt: self._quick_set_status(row, o))
        menu.add_separator()
        cur_ack = (row.get(dt.COL_ACK) or "").strip().lower()
        if cur_ack != "yes":
            menu.add_command(
                label="✓ Mark Ack Email Sent",
                command=lambda: self._quick_set_ack(row, "Yes"))
        else:
            menu.add_command(
                label="↶ Un-mark Ack",
                command=lambda: self._quick_set_ack(row, "No"))
        menu.add_separator()
        menu.add_command(label="🗑 Delete row",
                          command=lambda: self._confirm_delete(row))
        try:
            menu.tk_popup(e.x_root, e.y_root)
        finally:
            menu.grab_release()

    def _quick_set_status(self, row, new_status):
        updates = {dt.COL_STATUS: new_status}
        if new_status.lower() == "closed":
            updates.setdefault(dt.COL_RESOLUTION, _today_iso())
        if not dt.update_row(row["row_number"], updates):
            show_toast(self, "Couldn't update — Excel may have the "
                              "file open. Queued.", kind="warn",
                       duration=4000)
        self._reload_workbook()

    def _quick_set_ack(self, row, val):
        if not dt.update_row(row["row_number"], {dt.COL_ACK: val}):
            show_toast(self, "Update queued (Excel has the file open)",
                       kind="warn", duration=3000)
        self._reload_workbook()

    def _confirm_delete(self, row):
        name = row.get(dt.COL_INSURED) or row.get(dt.COL_CLAIM) or "(blank)"
        if not messagebox.askyesno(
                "Delete this dispute row?",
                f"Permanently blank the row for:\n\n{name}\n\n"
                "This clears the row in the workbook — undo isn't "
                "automatic.", parent=self):
            return
        if not dt.delete_row(row["row_number"]):
            show_toast(self, "Delete queued (Excel has the file open)",
                       kind="warn", duration=3000)
        self._reload_workbook()

    def _open_new_dispute_dialog(self):
        self._open_edit_dialog(None)

    def _open_edit_dialog(self, row: dict | None):
        """Pop the row editor. `row=None` → blank new-dispute form.
        On save, either inserts (via upsert) or updates by row_number.

        Dialog is intentionally tall + scroll-free; the row schema has
        18 columns and they all fit on a standard 720px window."""
        is_new = row is None
        dlg = tk.Toplevel(self)
        dlg.title("New dispute" if is_new else "Edit dispute row")
        dlg.configure(bg=BG)
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()
        # Cap dialog height to the visible screen so it never exceeds
        # the taskbar on a 768px laptop. ScrollableFrame handles the
        # overflow when the column count is taller than the cap.
        try:
            screen_h = dlg.winfo_screenheight()
            dh = max(420, min(640, screen_h - 120))
            dlg.geometry(f"560x{dh}")
        except tk.TclError:
            pass

        # Title
        title = tk.Frame(dlg, bg=BG, padx=18, pady=12)
        title.pack(fill="x")
        tk.Label(title,
                 text=("Add a new dispute" if is_new
                        else "Edit dispute row"),
                 font=("Fraunces", 14, "bold"),
                 bg=BG, fg=TEXT_DARK).pack(side="left")
        if not is_new:
            label = (row.get(dt.COL_INSURED) or
                     row.get(dt.COL_CLAIM) or "")
            tk.Label(title, text=f"  ·  {label}",
                     font=("Segoe UI Variable", 11),
                     bg=BG, fg=TEXT_GRAY).pack(side="left")

        # Scrollable body
        body_outer = tk.Frame(dlg, bg=WHITE,
                               highlightthickness=1,
                               highlightbackground=BORDER)
        body_outer.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        scroll = ScrollableFrame(body_outer, bg=WHITE)
        scroll.pack(fill="both", expand=True)
        body = scroll.inner

        # Field definitions: (col_key, label, kind, hint)
        # kind: "text" / "long" / "date" / "amount" / "dropdown" / "readonly"
        fields: list[tuple[str, str, str, str]] = [
            (dt.COL_RECEIVED,      "Received Date",        "date",     ""),
            (dt.COL_CLAIM,         "Claim #",              "text",     "Carrier claim# — dedup key"),
            (dt.COL_INSURED,       "Insured / Customer",   "text",     "Lastname, Firstname"),
            (dt.COL_CARRIER,       "Carrier",              "text",     ""),
            (dt.COL_TYPE,          "Dispute Type",         "dropdown", ""),
            (dt.COL_PRIORITY,      "Priority",             "dropdown", ""),
            (dt.COL_INTAKE,        "Intake Source",        "dropdown", ""),
            (dt.COL_SUMMARY,       "Dispute Summary",      "long",     "What's being contested?"),
            (dt.COL_ACK,           "Ack Email Sent?",      "dropdown", ""),
            (dt.COL_ESTIMATOR,     "Assigned Estimator",   "dropdown", ""),
            (dt.COL_ASSIGNED_DATE, "Assigned Date",        "date",     "Target = +3 business days"),
            (dt.COL_TARGET_DATE,   "Target Response Date", "readonly", "Auto = WORKDAY(Assigned,3)"),
            (dt.COL_STATUS,        "Status",               "dropdown", ""),
            (dt.COL_NEXT_FOLLOWUP, "Next Follow-Up Date",  "date",     ""),
            (dt.COL_RESOLUTION,    "Resolution Date",      "date",     ""),
            (dt.COL_OUTCOME,       "Outcome",              "dropdown", ""),
            (dt.COL_AMOUNT,        "Amount in Dispute",    "amount",   ""),
            (dt.COL_NOTES,         "Notes",                "long",     ""),
        ]

        widgets: dict[str, object] = {}
        for col_key, label, kind, hint in fields:
            row_frame = tk.Frame(body, bg=WHITE, padx=12, pady=4)
            row_frame.pack(fill="x")
            tk.Label(row_frame, text=label,
                     font=("Segoe UI Variable", 9, "bold"),
                     bg=WHITE, fg=TEXT_DARK, width=22, anchor="w"
                     ).pack(side="left")
            current = "" if is_new else _coerce_display(row.get(col_key))
            if kind == "dropdown":
                opts = self._dropdown_options.get(col_key) or []
                # Empty option lets the user blank a column.
                opts = ["", *opts] if opts and opts[0] != "" else opts
                var = tk.StringVar(value=current)
                w = ttk.Combobox(row_frame, textvariable=var,
                                  values=opts, state="readonly",
                                  font=("Segoe UI Variable", 9),
                                  width=24)
                w.pack(side="left", fill="x", expand=True)
                widgets[col_key] = var
            elif kind == "long":
                w = tk.Text(row_frame, height=3, wrap="word",
                             font=("Segoe UI Variable", 9),
                             bg=SURFACE_2, fg=TEXT_DARK,
                             insertbackground=TEXT_DARK,
                             relief="flat", padx=6, pady=4,
                             highlightthickness=1,
                             highlightbackground=BORDER)
                if current:
                    w.insert("1.0", current)
                w.pack(side="left", fill="both", expand=True)
                widgets[col_key] = w
            elif kind == "readonly":
                tk.Label(row_frame,
                         text=(current or "(auto-calculated)"),
                         font=("Segoe UI Variable", 9, "italic"),
                         bg=WHITE, fg=TEXT_GRAY
                         ).pack(side="left", fill="x", expand=True)
            else:
                var = tk.StringVar(value=current)
                w = ttk.Entry(row_frame, textvariable=var,
                               font=("Segoe UI Variable", 9))
                w.pack(side="left", fill="x", expand=True)
                widgets[col_key] = var
            if hint:
                tk.Label(row_frame, text=f"  {hint}",
                         font=("Segoe UI Variable", 8, "italic"),
                         bg=WHITE, fg=TEXT_MUTED
                         ).pack(side="left")

        # Footer buttons
        bot = tk.Frame(dlg, bg=BG, padx=14, pady=10)
        bot.pack(fill="x", side="bottom")

        def _collect_payload() -> dict:
            out: dict[str, object] = {}
            for col_key, _label, kind, _hint in fields:
                if kind == "readonly":
                    continue
                widget = widgets.get(col_key)
                if widget is None:
                    continue
                if kind == "long":
                    val = widget.get("1.0", "end").strip()
                else:
                    val = widget.get().strip()
                out[col_key] = val
            return out

        def _save():
            payload = _collect_payload()
            if is_new:
                # Need at least a claim# OR an insured to dedup.
                if (not payload.get(dt.COL_CLAIM)
                        and not payload.get(dt.COL_INSURED)):
                    messagebox.showwarning(
                        "Need a key",
                        "Add at least a Claim # or Insured so the row "
                        "can be looked up later.",
                        parent=dlg)
                    return
                payload.setdefault(dt.COL_RECEIVED, _today_iso())
                was_new, _r = dt.upsert(payload, source=payload.get(
                    dt.COL_INTAKE) or "")
                if was_new:
                    show_toast(self, "✓ Dispute added",
                               kind="success", duration=2500)
                else:
                    show_toast(self,
                                "Updated existing row (claim/insured "
                                "match found)", kind="info", duration=3500)
            else:
                ok = dt.update_row(row["row_number"], payload)
                if ok:
                    show_toast(self, "✓ Saved",
                               kind="success", duration=2000)
                else:
                    show_toast(self,
                                "Update queued (Excel has file open)",
                                kind="warn", duration=3500)
            dlg.destroy()
            self._reload_workbook()

        secondary_button(
            bot, "Cancel",
            command=dlg.destroy).pack(side="right", padx=(6, 0))
        done_button(
            bot, "💾 Save",
            command=_save).pack(side="right")

        # Center on parent — clamped to the screen so the dialog never
        # lands partly off-screen on a small or off-monitor window.
        try:
            dlg.update_idletasks()
            screen_w = dlg.winfo_screenwidth()
            screen_h = dlg.winfo_screenheight()
            px = self.winfo_rootx() + (self.winfo_width() // 2)
            py = self.winfo_rooty() + (self.winfo_height() // 2)
            dw = dlg.winfo_width()
            dh = dlg.winfo_height()
            x = max(0, min(px - dw // 2, screen_w - dw))
            y = max(0, min(py - dh // 2, screen_h - dh - 40))
            dlg.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass


def main(argv=None):
    run_standalone(DisputeTrackerApp,
                   geometry="1320x720", minsize=(900, 480))


if __name__ == "__main__":
    main()
