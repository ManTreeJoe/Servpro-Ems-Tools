"""KPI dashboard — Pywebview spike.

Phase-2 of the Tk → web migration (after pipeline_web). Renders the
four KPI sections (Weekly trends / Right now / Cycle time / Repeat
offenders) in an Edge WebView2 window. Backend modules
(`kpi_metrics`, `ems_db`, etc.) are unchanged — only the GUI layer
swaps.

Launch:
    python kpi_web.py
    # or via launcher:
    python launcher.py --tool kpi_web

Python ↔ JS bridge follows the same pattern as pipeline_web — every
method on the `Api` class is callable from JS via
`await pywebview.api.method_name(args)`. All returns are JSON-
serializable; numbers stay as numbers, None stays as null.
"""
from __future__ import annotations

import os
import sys
import threading
import webbrowser

import webview

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import kpi_metrics


ASSETS_DIR = os.path.join(_HERE, "kpi_web_assets")
INDEX_HTML = os.path.join(ASSETS_DIR, "index.html")


class Api:
    """Methods exposed to JS via `pywebview.api`.

    Long-running operations (refresh) are not heavy enough to need
    threading — `kpi_metrics` reads are fast (mostly local
    persistence reads + ems_db queries on already-cached state).
    """

    def __init__(self):
        self._window = None

    def attach(self, window):
        self._window = window

    # ── Section payloads ─────────────────────────────────────────────
    def weekly_metrics(self, weeks_back: int = 4) -> list[dict]:
        """4 most-recent weeks × the standard 7 KPIs. The frontend
        renders each metric as a row across the week columns so the
        trend reads left-to-right."""
        try:
            return kpi_metrics.weekly_metrics(weeks_back=weeks_back)
        except Exception:
            return []

    def current_open_flags(self) -> dict:
        """Right-now hygiene-scan counts. Returns scanned=False when
        the panel hasn't run yet (so the JS can show a "scan first"
        nudge instead of "0 concerns" misleadingly)."""
        try:
            return kpi_metrics.current_open_flags()
        except Exception:
            return {"concerns": 0, "xa_apology": 0, "hygiene": 0,
                    "handoff": 0, "closeout": 0, "scanned": False}

    def cycle_time_stats(self, longest_n: int = 5) -> dict:
        """Avg/median/p90 days-open + days-to-close, plus the top-N
        longest-open jobs. None values come through as null in JS
        and the renderer shows "—" so divides-by-zero don't leak."""
        try:
            return kpi_metrics.cycle_time_stats(longest_n=longest_n)
        except Exception:
            return {"open_count": 0, "closed_count": 0,
                    "avg_days_open": None, "median_days_open": None,
                    "p90_days_open": None, "avg_days_to_close": None,
                    "median_days_to_close": None, "longest_open": []}

    def repeat_offenders(self, threshold: int = 5,
                          limit: int = 10) -> list[dict]:
        """Jobs flagged on >=threshold audits, newest-audit first."""
        try:
            return kpi_metrics.repeat_offenders(
                threshold=threshold, limit=limit)
        except Exception:
            return []

    def job_performance_stats(self) -> dict:
        try:
            return kpi_metrics.job_performance_stats()
        except Exception:
            return {"stage_bottlenecks": [], "stalled_jobs": [],
                    "completed_this_month": 0, "monthly_quota": 0,
                    "quota_remaining": 0, "quota_percent": None}

    def all_sections(self) -> dict:
        """One-shot bundle for the initial render — saves four
        bridge round-trips."""
        return {
            "weekly":  self.weekly_metrics(),
            "right_now": self.current_open_flags(),
            "cycle_time": self.cycle_time_stats(),
            "repeat_offenders": self.repeat_offenders(),
            "job_performance": self.job_performance_stats(),
        }

    # ── Actions ──────────────────────────────────────────────────────
    def open_url(self, url: str) -> bool:
        if not url:
            return False
        try:
            webbrowser.open(url)
            return True
        except Exception:
            return False

    def copy_to_clipboard(self, text: str) -> bool:
        if not text:
            return False
        # Win32 clipboard, NOT a throwaway tk.Tk() — Tk's delayed-rendering
        # clipboard left a dead owner that froze the next paste everywhere.
        from web_helpers import set_clipboard_text
        return set_clipboard_text(text)


def main(argv=None):
    api = Api()
    window = webview.create_window(
        title="KPI — Linguar Hub (web spike)",
        url=INDEX_HTML,
        js_api=api,
        width=1180, height=820,
        min_size=(720, 500),
    )
    api.attach(window)
    webview.start(debug=False)


if __name__ == "__main__":
    main()
