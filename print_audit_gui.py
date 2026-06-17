"""Audit Backlog Viewer — all audited jobs organized by week."""
import sys
import os
import tkinter as tk
from tkinter import messagebox, ttk
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_export
import ctk_helpers as ctkh
import paths
from theme import (GREEN, GREEN_DARK, WHITE, BG, TEXT_DARK, TEXT_GRAY,
                    TEXT_MUTED, BORDER, FLAG_RED,
                    SUCCESS_BG, SUCCESS_FG, SUCCESS_HOVER,
                    WARN_BG, WARN_FG)
from tool_panel import (ToolPanel, run_standalone,
                         ResponsiveActionBar, ScrollableFrame)
from ui_buttons import done_button

WEEK_BG  = "#E8F5EE"
ISSUE_BG = "#FEF9F9"


def _week_label(ws):
    try:
        d = date.fromisoformat(ws)
        return f"Week of {d.strftime('%B %d, %Y')}"
    except Exception:
        return ws or "Unknown Week"


class BacklogView(tk.Frame):
    """Audit Backlog UI as a reusable Frame.

    Hosted by `BacklogApp` for standalone runs and embedded in the
    Audit panel's `Backlog` tab. All state (filter, scroll, last
    loaded data) lives on the view."""

    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._build_ui()
        self._load()


class BacklogApp(ToolPanel):
    """Standalone wrapper — hosts a BacklogView. Kept so users can
    still launch the backlog as its own window (or test it standalone)
    even though the launcher now surfaces it as an Audit tab."""

    TOOL_TITLE = "EMS Audit Backlog"
    TOOL_AUMID = "Servpro.EMS.AuditBacklog"

    def __init__(self, parent):
        super().__init__(parent)
        self.title("EMS Audit Backlog")
        self.geometry("640x700")
        self.minsize(500, 400)
        self.configure(bg=BG)
        try:
            ico = paths.resource("wrench.ico")
            if os.path.isfile(ico):
                self.iconbitmap(ico)
        except Exception:
            pass
        # Standalone-only green title band — auto no-ops when embedded
        # in the launcher. Renders here (not inside the View) because
        # BacklogView is a plain Frame and can't call ToolPanel methods.
        self.build_header("Audit Backlog",
                          subtitle="All jobs  ·  organized by week  ·  most recent first")
        self._view = BacklogView(self)
        self._view.pack(fill="both", expand=True)

    def _build_ui(self):
        # Layout convention shared with Initial Upload + SP Recent so
        # the four audit tabs feel cohesive: NO redundant title (the
        # tab strip is already the title), a single thin control band
        # with view-specific primary controls on the left and 🔄 Refresh
        # on the right, an optional subtitle helper line, an italic
        # status line, then the scrollable body. Same fonts, same
        # paddings, same button styles. Export stays on a dedicated
        # bottom action bar — it's a heavier action than Refresh and
        # warrants its own anchored slot.
        ctl = tk.Frame(self, bg=BG, padx=14, pady=8)
        ctl.pack(fill="x")
        tk.Label(ctl, text="🔍",
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=BG, fg=TEXT_DARK).pack(side="left", padx=(0, 6))
        self._filter_var = tk.StringVar()
        self._filter_deb = ctkh.Debouncer(self, 250)
        self._filter_var.trace_add(
            "write", lambda *_: self._filter_deb.fire(self._load))
        ctkh.entry(ctl, textvariable=self._filter_var
                   ).pack(side="left", fill="x", expand=True)
        ctkh.btn(ctl, "Clear", command=lambda: self._filter_var.set(""),
                 kind="ghost", width=60).pack(side="left", padx=(8, 8))
        done_button(ctl, "🔄 Refresh", padx=12, pady=3,
                     command=self._load).pack(side="right")

        tk.Label(self,
                 text=("All audited jobs  ·  organized by week  ·  "
                       "most recent first"),
                 font=("Segoe UI Variable", 8), bg=BG, fg=TEXT_GRAY,
                 padx=14, anchor="w").pack(fill="x")
        self._status_lbl = tk.Label(self, text="",
                                     font=("Segoe UI Variable", 8, "italic"),
                                     bg=BG, fg=TEXT_GRAY,
                                     padx=14, anchor="w")
        self._status_lbl.pack(fill="x", pady=(0, 4))

        # Bottom bar — packed BEFORE the scrollable body and anchored to
        # the bottom so the Export button stays visible even when the
        # window is short.
        bar = ResponsiveActionBar(self, root_widget=self,
                                  bg=BG, padx=12, pady=10)
        bar.pack(side="bottom", fill="x")

        scroll = ScrollableFrame(self, bg=BG, padx=10, pady=8)
        scroll.pack(fill="both", expand=True)
        self._canvas = scroll.canvas
        self._inner  = scroll.inner
        self._scroll = scroll

        export_btn = ctkh.btn(bar, "Export Flagged PDF",
                              command=self._export, kind="primary",
                              width=170, height=34)
        bar.add(export_btn, group="primary", side="right", padx=(0, 0))

    def _load(self):
        for w in self._inner.winfo_children():
            w.destroy()

        data      = audit_export.load_audit_backlog()
        jobs      = data.get("jobs", [])
        last_upd  = data.get("last_updated", "")

        # Apply filter (matches client name OR folder name, case-insensitive)
        filt = ""
        if hasattr(self, "_filter_var"):
            filt = self._filter_var.get().strip().lower()
        if filt:
            jobs = [j for j in jobs
                    if filt in j.get("client", "").lower()
                    or filt in j.get("folder", "").lower()]

        if last_upd:
            try:
                dt = datetime.fromisoformat(last_upd)
                self._status_lbl.configure(
                    text=f"Updated {dt.strftime('%m/%d/%Y %I:%M %p')}")
            except Exception:
                self._status_lbl.configure(text=f"Updated {last_upd}")

        if not jobs:
            tk.Label(self._inner,
                     text="No audits recorded yet.\n\nRun an audit from EMS Snapshot or Daily Run Audit.",
                     font=("Segoe UI Variable", 11), bg=BG, fg=TEXT_GRAY, justify="center",
                     pady=60).pack()
            return

        # Summary strip
        total     = len(jobs)
        n_flagged = sum(1 for j in jobs if j["status"] == "FLAG")
        n_ok      = total - n_flagged
        strip = tk.Frame(self._inner, bg=WHITE,
                         highlightthickness=1, highlightbackground=BORDER)
        strip.pack(fill="x", padx=4, pady=(4, 8))
        _lbl(strip, f"  {total} total jobs", ("Segoe UI Variable", 9, "bold"), WHITE, TEXT_DARK).pack(side="left", padx=(6,0))
        _lbl(strip, f"  {n_flagged} flagged", ("Segoe UI Variable", 9), WHITE, FLAG_RED).pack(side="left")
        _lbl(strip, f"  {n_ok} OK  ", ("Segoe UI Variable", 9), WHITE, GREEN).pack(side="left")

        # Group by week_start
        week_groups = {}
        for j in jobs:
            ws = j.get("week_start", "")
            week_groups.setdefault(ws, []).append(j)

        for ws in sorted(week_groups.keys(), reverse=True):
            group    = week_groups[ws]
            flagged  = [j for j in group if j["status"] == "FLAG"]
            ok_jobs  = [j for j in group if j["status"] == "OK"]

            # Week header bar
            wk = tk.Frame(self._inner, bg=WEEK_BG, pady=5, padx=10)
            wk.pack(fill="x", padx=4, pady=(6, 0))
            _lbl(wk, _week_label(ws), ("Segoe UI Variable", 10, "bold"), WEEK_BG, GREEN_DARK).pack(side="left")
            _lbl(wk, f"{len(flagged)} flagged · {len(ok_jobs)} OK",
                 ("Segoe UI Variable", 8), WEEK_BG, TEXT_GRAY).pack(side="right")

            # Card for this week's jobs
            card = tk.Frame(self._inner, bg=WHITE,
                            highlightthickness=1, highlightbackground=BORDER)
            card.pack(fill="x", padx=4, pady=(0, 4))

            rows = flagged + ok_jobs
            for i, j in enumerate(rows):
                self._job_row(card, j, last=(i == len(rows) - 1))

    def _job_row(self, parent, j, last=False):
        is_flag  = j["status"] == "FLAG"
        badge_bg = FLAG_RED if is_flag else GREEN
        badge    = "FLAG" if is_flag else " OK "

        issues = (j.get("form_issues") or []) + (j.get("photo_issues") or [])
        missing = j.get("missing") or []
        aging   = j.get("aging", 0)
        if aging >= 3 and j.get("found", True) and is_flag:
            last_str = ""
            if j.get("last_active"):
                try:
                    last_str = datetime.fromisoformat(j["last_active"]).strftime("%m/%d/%y")
                except Exception:
                    pass
            issues = list(issues) + [f"{aging}d inactive (last: {last_str or 'unknown'})"]

        has_issues = bool(issues or missing)

        # Wrap the row + detail in a single per-job frame. Without this
        # wrapper the detail frame was a sibling of `parent` (the card)
        # and pack-order put it AFTER every later job's row — so click-
        # to-expand looked like nothing happened, the detail was just
        # appearing at the bottom of the entire week's list.
        wrap = tk.Frame(parent, bg=WHITE)
        wrap.pack(fill="x")

        row = tk.Frame(wrap, bg=WHITE, pady=5, padx=8)
        row.pack(fill="x")

        tk.Label(row, text=badge,
                 font=("Segoe UI Variable", 7, "bold"),
                 bg=badge_bg, fg=WHITE, padx=4, pady=1).pack(side="left")

        # Chevron indicator — only when there are issues to show.
        # Without it, click-to-expand was undiscoverable: the row looked
        # like an end-state, not something you could drill into.
        chevron_lbl = None
        if has_issues:
            chevron_lbl = tk.Label(row, text="▶",
                                   font=("Segoe UI Variable", 7),
                                   bg=WHITE, fg=TEXT_GRAY,
                                   cursor="hand2")
            chevron_lbl.pack(side="left", padx=(4, 0))

        name = j["client"]
        if j.get("folder") and j["folder"].lower() != j["client"].lower():
            name += f"  ({j['folder']})"
        if not j.get("found", True):
            name += "  — folder not found"

        cursor = "hand2" if has_issues else "arrow"
        name_lbl = tk.Label(row, text=name,
                            font=("Segoe UI Variable", 9, "bold"), bg=WHITE,
                            fg=TEXT_DARK, anchor="w", cursor=cursor)
        name_lbl.pack(side="left", padx=(6, 0), fill="x", expand=True)

        cnt = j.get("audit_count", 1)
        if cnt > 1:
            tk.Label(row, text=f"×{cnt}",
                     font=("Segoe UI Variable", 8), bg=WHITE, fg=TEXT_MUTED).pack(side="right", padx=4)

        if has_issues:
            # Item-count badge — shows how many things remain to do
            # at a glance so the user can prioritize without expanding.
            n_items = len(issues) + len(missing)
            tk.Label(row, text=f"{n_items} item{'s' if n_items != 1 else ''}",
                     font=("Segoe UI Variable", 7), bg=WARN_BG, fg=WARN_FG,
                     padx=5, pady=1
                     ).pack(side="right", padx=(4, 4))

            # Detail goes inside this job's wrapper, not the card —
            # so pack/forget toggles only its own slot, not the whole
            # card's append order.
            det = tk.Frame(wrap, bg=ISSUE_BG, padx=20, pady=3)
            for txt in issues:
                tk.Label(det, text=f"  ☐  {txt}",
                         font=("Segoe UI Variable", 8), bg=ISSUE_BG,
                         fg=FLAG_RED, anchor="w").pack(fill="x")
            for m in missing:
                tk.Label(det, text=f"  ☐  Empty folder: {m}",
                         font=("Segoe UI Variable", 8), bg=ISSUE_BG,
                         fg=FLAG_RED, anchor="w").pack(fill="x")

            def _toggle(detail=det, chev=chevron_lbl):
                if detail.winfo_ismapped():
                    detail.pack_forget()
                    if chev is not None:
                        try: chev.config(text="▶")
                        except tk.TclError: pass
                else:
                    detail.pack(fill="x")
                    if chev is not None:
                        try: chev.config(text="▼")
                        except tk.TclError: pass

            name_lbl.bind("<Button-1>", lambda e: _toggle())
            if chevron_lbl is not None:
                chevron_lbl.bind("<Button-1>", lambda e: _toggle())

        if not last:
            # Divider goes inside the wrapper too so it stays at the
            # bottom of THIS job's slot whether the detail is expanded
            # or collapsed.
            tk.Frame(wrap, bg=BORDER, height=1).pack(fill="x")

    def _export(self):
        data = audit_export.load_audit_backlog()
        jobs = [j for j in data.get("jobs", []) if j["status"] == "FLAG"]

        if not jobs:
            messagebox.showinfo("Nothing to Print",
                                "No flagged jobs in the backlog.", parent=self)
            return

        results = []
        for j in jobs:
            last_dt = None
            if j.get("last_active"):
                try:
                    last_dt = datetime.fromisoformat(j["last_active"])
                except Exception:
                    pass
            results.append({
                "client":      j["client"],
                "folder":      j.get("folder", j["client"]),
                "flagged":     True,
                "form_issues": j.get("form_issues", []),
                "photo_issues":j.get("photo_issues", []),
                "missing":     j.get("missing", []),
                "aging":       j.get("aging", 0),
                "last":        last_dt,
                "found":       j.get("found", True),
                "new_loss":    j.get("new_loss", False),
                "is_current":  False,
            })

        audit_export.open_export_window(self, results, "", on_close=None)


def _lbl(parent, text, font, bg, fg):
    return tk.Label(parent, text=text, font=font, bg=bg, fg=fg)


# Bind the body methods onto BacklogView. They're written against
# BacklogApp historically but only depend on Frame-compatible behavior,
# so the same `self` semantics work on either class. Avoids a 250-line
# textual move during the audit-tab refactor.
for _m in ("_build_ui", "_load", "_job_row", "_export"):
    setattr(BacklogView, _m, getattr(BacklogApp, _m))
del _m


def main(argv=None):
    run_standalone(BacklogApp, geometry="640x700", minsize=(500, 400))


if __name__ == "__main__":
    main()
