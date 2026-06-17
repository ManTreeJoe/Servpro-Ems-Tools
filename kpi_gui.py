"""KPI dashboard panel.

Three rows:

  1. Right-now snapshot — current open hygiene/handoff/concerns/closeout
     counts pulled from the most recent hygiene scan cache. If the
     Hygiene panel hasn't run today, shows a "no recent scan" hint with
     a button to switch to it.
  2. This week — audits run, flagged, resolved, escalations, XA
     apologies, snapshots drafted, adjuster receipts. Each value is
     tagged with a small trend chip vs. last week (▲/▼/=).
  3. Repeat offenders — top 10 chronically-flagged jobs with audit_count
     and last-audit date. Click a row to open it in the Audit panel.

Pure read-only — no scans, no writes, no API calls. Loads in <50ms
even on a saturated state.json.
"""
from __future__ import annotations

import tkinter as tk
import webbrowser
from datetime import datetime, date as _date
from tkinter import messagebox

import kpi_metrics as km
from theme import (
    GREEN, GREEN_DARK, WHITE, BG, TEXT_DARK, TEXT_GRAY, BORDER, FLAG_RED,
)
from tool_panel import ToolPanel, ScrollableFrame, run_standalone
from ui_buttons import done_button


# Row labels + the metric key they pull from `weekly_metrics()`.
_WEEKLY_FIELDS = (
    ("Audits run",         "audits_run"),
    ("FLAG-status",        "flagged"),
    ("Issues resolved",    "resolved"),
    ("Escalations sent",   "escalations"),
    ("XA apologies posted", "xa_apologies"),
    ("Snapshots drafted",  "snapshots_drafted"),
    ("Adjuster receipts",  "adjuster_receipts"),
)


class KPIApp(ToolPanel):
    TOOL_TITLE = "KPI"
    TOOL_GEOMETRY_KEY = "kpi_geometry"

    def __init__(self, parent):
        super().__init__(parent)
        self.configure(bg=BG)
        self._closed = False
        self._after_ids: set[str] = set()
        self._build_ui()
        # Defer first render one tick so the panel paints before the
        # data load (typically <50ms but the placeholder feels snappy).
        self._track_after(50, self._refresh)

    # ── tracked after() ───────────────────────────────────────────────────
    def _track_after(self, ms, fn):
        if self._closed:
            return None
        try:
            aid = self.after(ms, fn)
            self._after_ids.add(aid)
            return aid
        except tk.TclError:
            return None

    # ── UI build ──────────────────────────────────────────────────────────
    def _build_ui(self):
        ctl = tk.Frame(self, bg=BG, padx=14, pady=10)
        ctl.pack(fill="x")
        tk.Label(ctl, text="KPI dashboard",
                 font=("Fraunces", 15, "bold"),
                 bg=BG, fg=TEXT_DARK).pack(side="left")
        self._status_lbl = tk.Label(ctl, text="",
                                     font=("Segoe UI Variable", 9, "italic"),
                                     bg=BG, fg=TEXT_GRAY)
        self._status_lbl.pack(side="left", padx=(14, 0))
        done_button(ctl, "↻ Refresh", padx=14, pady=4,
                     command=self._refresh).pack(side="right")

        scroll = ScrollableFrame(self, bg=BG, padx=14, pady=4)
        scroll.pack(fill="both", expand=True)
        self._body = scroll.inner

        # Section frames built once — _refresh repopulates contents.
        self._snap_section = self._mk_section(self._body,
            "🔍 Right now",
            "Current open flags from the most recent hygiene scan.")
        self._weekly_section = self._mk_section(self._body,
            "📈 This week",
            "Activity counts for the current Monday-to-Sunday week, "
            "with trend vs. last week.")
        self._repeat_section = self._mk_section(self._body,
            "♻ Repeat offenders",
            "Jobs flagged on 5+ audits — the chronic cases.")
        self._cycle_section = self._mk_section(self._body,
            "⏱ Cycle time",
            "Days a job stays open from earliest known activity to "
            "snapshot drafted. Median / p90 surface the long tail.")
        self._pipeline_section = self._mk_section(self._body,
            "🛤 Pipeline cycle time (per stage)",
            "Median + p90 days a job has been sitting in its current "
            "stage. Driven by job_lifecycle — kept fresh by every "
            "Hygiene scan. Stages where the median is high are where "
            "jobs pile up.")

    def _mk_section(self, parent, title, hint):
        wrap = tk.Frame(parent, bg=WHITE,
                        highlightthickness=1, highlightbackground=BORDER)
        wrap.pack(fill="x", pady=(0, 12))
        hdr = tk.Frame(wrap, bg=WHITE, padx=12, pady=8)
        hdr.pack(fill="x")
        tk.Label(hdr, text=title,
                 font=("Segoe UI Variable", 11, "bold"),
                 bg=WHITE, fg=TEXT_DARK).pack(side="left")
        tk.Label(hdr, text=hint,
                 font=("Segoe UI Variable", 8, "italic"),
                 bg=WHITE, fg=TEXT_GRAY).pack(side="left", padx=(14, 0))
        body = tk.Frame(wrap, bg=WHITE, padx=12)
        body.pack(fill="x", pady=(0, 10))
        return body

    # ── Refresh ───────────────────────────────────────────────────────────
    def _refresh(self):
        if self._closed:
            return
        self._populate_snapshot()
        self._populate_weekly()
        self._populate_repeat()
        self._populate_cycle()
        self._populate_pipeline()
        self._status_lbl.configure(
            text=f"Loaded {datetime.now().strftime('%I:%M %p')}.")

    def _clear(self, parent):
        for child in parent.winfo_children():
            try: child.destroy()
            except Exception: pass

    def _populate_snapshot(self):
        self._clear(self._snap_section)
        snap = km.current_open_flags()
        if not snap.get("scanned"):
            tk.Label(self._snap_section,
                     text=("No recent hygiene scan — open the ⚠ Hygiene "
                           "tab to populate these counts."),
                     font=("Segoe UI Variable", 9, "italic"),
                     bg=WHITE, fg=TEXT_GRAY).pack(anchor="w", pady=4)
            done_button(self._snap_section, "Open Hygiene →",
                         padx=10, pady=2,
                         command=self._open_hygiene
                         ).pack(anchor="w", pady=(4, 0))
            return
        tiles = (
            ("🚨 Concerns",  snap["concerns"],  FLAG_RED),
            ("🔔 XA needed", snap["xa_apology"], "#A6772A"),
            ("⚠ Hygiene",   snap["hygiene"],    "#A6772A"),
            ("🔄 Handoff",   snap["handoff"],   "#A6772A"),
            ("📸 Snapshot",  snap["closeout"],  GREEN_DARK),
        )
        row = tk.Frame(self._snap_section, bg=WHITE)
        row.pack(fill="x", pady=4)
        for label, n, color in tiles:
            tile = tk.Frame(row, bg=WHITE,
                             highlightthickness=1, highlightbackground=BORDER,
                             padx=12, pady=6)
            tile.pack(side="left", padx=(0, 8))
            tk.Label(tile, text=str(n),
                     font=("Segoe UI Variable", 16, "bold"),
                     bg=WHITE, fg=color if n else TEXT_GRAY).pack(anchor="w")
            tk.Label(tile, text=label,
                     font=("Segoe UI Variable", 8),
                     bg=WHITE, fg=TEXT_GRAY).pack(anchor="w")

    def _populate_weekly(self):
        self._clear(self._weekly_section)
        rows = km.weekly_metrics(weeks_back=4)
        if not rows:
            tk.Label(self._weekly_section, text="No data yet.",
                     font=("Segoe UI Variable", 9, "italic"),
                     bg=WHITE, fg=TEXT_GRAY).pack(anchor="w", pady=4)
            return
        this_week = rows[0]
        last_week = rows[1] if len(rows) > 1 else None

        # Header row
        hdr = tk.Frame(self._weekly_section, bg=WHITE)
        hdr.pack(fill="x")
        tk.Label(hdr, text=f"Week of {this_week['week_start']}",
                 font=("Segoe UI Variable", 9, "bold"),
                 bg=WHITE, fg=TEXT_DARK).pack(side="left")
        tk.Label(hdr,
                 text=("vs prior week" if last_week
                       else "(no prior-week data yet)"),
                 font=("Segoe UI Variable", 8, "italic"),
                 bg=WHITE, fg=TEXT_GRAY).pack(side="left", padx=(8, 0))

        # Per-metric rows
        for label, key in _WEEKLY_FIELDS:
            now = this_week.get(key, 0)
            prev = (last_week.get(key, 0) if last_week else 0)
            chip_text, chip_fg = self._trend_chip(now, prev)
            r = tk.Frame(self._weekly_section, bg=WHITE)
            r.pack(fill="x", pady=2)
            tk.Label(r, text=label, width=26, anchor="w",
                     font=("Segoe UI Variable", 9),
                     bg=WHITE, fg=TEXT_DARK).pack(side="left")
            tk.Label(r, text=str(now), width=6, anchor="e",
                     font=("Segoe UI Variable", 11, "bold"),
                     bg=WHITE, fg=TEXT_DARK).pack(side="left")
            tk.Label(r, text=chip_text, anchor="w",
                     font=("Segoe UI Variable", 9),
                     bg=WHITE, fg=chip_fg).pack(side="left", padx=(8, 0))
            tk.Label(r, text=f"  prev {prev}",
                     font=("Segoe UI Variable", 8, "italic"),
                     bg=WHITE, fg=TEXT_GRAY).pack(side="left")

    def _trend_chip(self, now: int, prev: int) -> tuple[str, str]:
        """Return (text, color) for a delta vs. previous week."""
        if prev == 0 and now == 0:
            return ("=", TEXT_GRAY)
        if prev == 0:
            return (f"▲ +{now}", GREEN_DARK)
        diff = now - prev
        if diff == 0:
            return ("=", TEXT_GRAY)
        pct = abs(diff) * 100 / prev if prev else 0
        if diff > 0:
            return (f"▲ +{diff}  ({int(pct)}%)", GREEN_DARK)
        return (f"▼ {diff}  ({int(pct)}%)", "#A64242")

    def _populate_repeat(self):
        self._clear(self._repeat_section)
        rows = km.repeat_offenders(threshold=5, limit=10)
        if not rows:
            tk.Label(self._repeat_section,
                     text="✓ No chronic flagged jobs (≥5 audits with FLAG).",
                     font=("Segoe UI Variable", 9, "italic"),
                     bg=WHITE, fg=TEXT_GRAY).pack(anchor="w", pady=4)
            return
        for j in rows:
            client = j.get("client") or j.get("folder") or "?"
            count = j.get("audit_count", 0)
            last = (j.get("last_audited") or "")[:10]
            r = tk.Frame(self._repeat_section, bg=WHITE)
            r.pack(fill="x", pady=2)
            tk.Label(r, text=f"×{count}", width=6, anchor="e",
                     font=("Segoe UI Variable", 10, "bold"),
                     bg=WHITE, fg=FLAG_RED).pack(side="left")
            tk.Label(r, text=client, anchor="w",
                     font=("Segoe UI Variable", 10),
                     bg=WHITE, fg=TEXT_DARK).pack(side="left",
                                                    fill="x", expand=True,
                                                    padx=(10, 0))
            tk.Label(r, text=f"last {last}",
                     font=("Segoe UI Variable", 8, "italic"),
                     bg=WHITE, fg=TEXT_GRAY).pack(side="right")

    def _populate_cycle(self):
        self._clear(self._cycle_section)
        try:
            s = km.cycle_time_stats(longest_n=5)
        except Exception:
            s = None
        if not s or (s.get("open_count", 0) + s.get("closed_count", 0)) == 0:
            tk.Label(self._cycle_section,
                     text="No cycle-time data yet — needs ems_db + at "
                          "least one job with first_seen_at populated.",
                     font=("Segoe UI Variable", 9, "italic"),
                     bg=WHITE, fg=TEXT_GRAY).pack(anchor="w", pady=4)
            return

        def _fmt(v):
            return "—" if v is None else f"{v:g} d"

        # Tile row — open count / closed count / median open / p90 open
        # / median close. Same visual language as the "Right now" tiles.
        tiles = (
            ("🔓 Open",        s["open_count"],
             FLAG_RED if s["open_count"] else TEXT_GRAY, ""),
            ("✅ Closed",      s["closed_count"],
             GREEN_DARK if s["closed_count"] else TEXT_GRAY, ""),
            ("Median open",   _fmt(s["median_days_open"]),  TEXT_DARK, ""),
            ("p90 open",      _fmt(s["p90_days_open"]),     "#A6772A", ""),
            ("Median close",  _fmt(s["median_days_to_close"]),
                                                       GREEN_DARK, ""),
        )
        row = tk.Frame(self._cycle_section, bg=WHITE)
        row.pack(fill="x", pady=4)
        for label, val, color, _hint in tiles:
            tile = tk.Frame(row, bg=WHITE,
                             highlightthickness=1, highlightbackground=BORDER,
                             padx=12, pady=6)
            tile.pack(side="left", padx=(0, 8))
            tk.Label(tile, text=str(val),
                     font=("Segoe UI Variable", 14, "bold"),
                     bg=WHITE, fg=color).pack(anchor="w")
            tk.Label(tile, text=label,
                     font=("Segoe UI Variable", 8),
                     bg=WHITE, fg=TEXT_GRAY).pack(anchor="w")

        # Longest-open list — the chronic open cases. Same right-aligned
        # number style the repeat-offenders section uses.
        longest = s.get("longest_open") or []
        if longest:
            tk.Label(self._cycle_section, text="Longest open",
                     font=("Segoe UI Variable", 9, "bold"),
                     bg=WHITE, fg=TEXT_DARK).pack(anchor="w", pady=(8, 0))
            for row_data in longest:
                client = row_data.get("client", "?")
                days = row_data.get("days", 0)
                r = tk.Frame(self._cycle_section, bg=WHITE)
                r.pack(fill="x", pady=1)
                tk.Label(r, text=f"{days:g} d", width=8, anchor="e",
                         font=("Segoe UI Variable", 10, "bold"),
                         bg=WHITE, fg=FLAG_RED if days >= 14 else "#A6772A"
                         ).pack(side="left")
                tk.Label(r, text=client, anchor="w",
                         font=("Segoe UI Variable", 10),
                         bg=WHITE, fg=TEXT_DARK
                         ).pack(side="left", padx=(10, 0))

    def _populate_pipeline(self):
        """Per-stage cycle-time table. Two metrics per stage:
          - CURRENT: median days-in-stage of jobs actively sitting in
            that stage right now.
          - HISTORICAL: median days the stage took for jobs that have
            ALREADY moved on (computed from the transition log over
            the last 180 days). Shows up only once enough transitions
            have accumulated; until then the column reads '—'."""
        self._clear(self._pipeline_section)
        try:
            import pipeline_stages as _ps
            stats = _ps.stage_cycle_stats()
            hist  = _ps.historical_stage_stats()
        except Exception:
            stats = {}
            hist  = {}
        if not stats or not any(v.get("count") for v in stats.values()):
            tk.Label(self._pipeline_section,
                      text=("No pipeline data yet — click ↻ Sync on "
                            "the 🛤 Pipeline panel (or just run a "
                            "⚠ Hygiene scan, which keeps it fresh)."),
                      font=("Segoe UI Variable", 9, "italic"),
                      bg=WHITE, fg=TEXT_GRAY
                      ).pack(anchor="w", pady=4)
            return

        # Header row
        hdr = tk.Frame(self._pipeline_section, bg=WHITE)
        hdr.pack(fill="x", pady=(2, 4))
        tk.Label(hdr, text="Stage", width=22, anchor="w",
                  font=("Segoe UI Variable", 8, "bold"),
                  bg=WHITE, fg=TEXT_GRAY).pack(side="left")
        for col in ("Jobs", "Median now", "p90 now",
                     "Hist. med.", "Hist. p90"):
            tk.Label(hdr, text=col, width=10, anchor="e",
                      font=("Segoe UI Variable", 8, "bold"),
                      bg=WHITE, fg=TEXT_GRAY).pack(side="left", padx=(4, 0))

        thresholds = _ps.get_thresholds()
        for stage in _ps.STAGES:
            s = stats.get(stage) or {"count": 0, "median": 0,
                                       "p90": 0, "max": 0}
            h = hist.get(stage) or {"sample_size": 0, "median": 0,
                                      "p90": 0}
            label = _ps.STAGE_LABELS.get(stage, stage)
            th = thresholds.get(stage, 9999)
            med = s.get("median", 0)
            med_color = (FLAG_RED if med > th * 2
                         else ("#A6772A" if med > th else TEXT_DARK))
            hist_med = h.get("median", 0)
            hist_p90 = h.get("p90", 0)
            hist_n   = h.get("sample_size", 0)
            hist_med_color = (FLAG_RED if hist_med > th * 2
                              else ("#A6772A" if hist_med > th
                                    else TEXT_DARK))

            row = tk.Frame(self._pipeline_section, bg=WHITE)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=label, width=22, anchor="w",
                      font=("Segoe UI Variable", 10),
                      bg=WHITE, fg=TEXT_DARK).pack(side="left")
            tk.Label(row, text=str(s.get("count", 0)), width=10,
                      anchor="e",
                      font=("Segoe UI Variable", 10, "bold"),
                      bg=WHITE, fg=TEXT_DARK).pack(side="left", padx=(4, 0))
            tk.Label(row, text=f"{med} d", width=10, anchor="e",
                      font=("Segoe UI Variable", 10, "bold"),
                      bg=WHITE, fg=med_color).pack(side="left", padx=(4, 0))
            tk.Label(row, text=f"{s.get('p90', 0)} d", width=10,
                      anchor="e",
                      font=("Segoe UI Variable", 10),
                      bg=WHITE, fg=TEXT_DARK).pack(side="left", padx=(4, 0))
            tk.Label(row,
                      text=(f"{hist_med} d" if hist_n else "—"),
                      width=10, anchor="e",
                      font=("Segoe UI Variable", 10),
                      bg=WHITE, fg=hist_med_color
                      ).pack(side="left", padx=(4, 0))
            tk.Label(row,
                      text=(f"{hist_p90} d" if hist_n else "—"),
                      width=10, anchor="e",
                      font=("Segoe UI Variable", 10),
                      bg=WHITE, fg=TEXT_DARK
                      ).pack(side="left", padx=(4, 0))

    # ── Actions ───────────────────────────────────────────────────────────
    def _open_hygiene(self):
        host = getattr(self, "host", None)
        if host is None:
            messagebox.showinfo("Open Hygiene manually",
                                 "Switch to the ⚠ Hygiene tab to run "
                                 "the workspace scan.", parent=self)
            return
        try:
            host.show_tool("hygiene")
        except Exception as ex:
            messagebox.showerror("Couldn't open Hygiene", str(ex),
                                  parent=self)

    # ── Lifecycle ─────────────────────────────────────────────────────────
    def on_show(self):
        if not self._closed:
            self._track_after(50, self._refresh)

    def on_hide(self):
        pass

    def on_close(self):
        self._closed = True
        for aid in list(self._after_ids):
            try: self.after_cancel(aid)
            except Exception: pass
        self._after_ids.clear()


def main():
    run_standalone(KPIApp, geometry="900x720", minsize=(560, 420))


if __name__ == "__main__":
    main()
