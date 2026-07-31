"""Standalone hygiene scan worker — runs in a subprocess so the
pywebview UI process stays completely responsive during the scan.

Reasoning: when the scan ran inside the panel's Python process,
`requests`-driven Trello fetches held the GIL during JSON parsing
between HTTP calls, and pywebview's bridge thread couldn't process
user clicks while that contention was high. Result: the UI froze
when the user clicked Run Scan and stayed frozen until the scan
finished. A subprocess has its own Python interpreter / GIL / heap
so nothing the scan does can affect the main UI process — the panel
just polls a status file for completion.

Status file layout (~/AppData/Local/Linguar Hub/hygiene_scan.json):
    {
      "phase":   "running" | "done" | "error",
      "started_at": ISO,
      "ended_at":   ISO,
      "done":    N, "total": M, "name": "current card name",
      "error":   "" | "message",
      "counts":  {section: count, ...}  # filled on phase=done
    }

The scan results themselves go straight into persistence via the
same `set_hygiene_scan_cache` call the in-process scan used. The
status file only carries progress.
"""
from __future__ import annotations
import os
import sys
import json
import datetime
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def status_path() -> str:
    """Status file location — under %LOCALAPPDATA% on Windows so the
    main app and the subprocess agree on the path."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, "Linguar Hub")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "hygiene_scan_status.json")


def _write_status(payload: dict) -> None:
    try:
        with open(status_path(), "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
    except Exception:
        pass


def _read_status() -> dict:
    p = status_path()
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh) or {}
    except Exception:
        return {}


def run(tab_key: str = "", mode: str = "full") -> int:
    """Subprocess entrypoint. Returns 0 on success, 1 on error.

    `mode`:
      • "minimal"  — hygiene rules ONLY, ~50 cards per board.
      • "full"     — every section, current limits.

    `mode` can ALSO be a comma-separated list of feature flags so
    the user can bisect which expensive section is causing problems:
      • "hygiene,handoff,closeout,xa_gaps,ipr"           ← Trello-only
      • "hygiene,handoff,closeout,xa_gaps,ipr,xa_apology" ← +AR board
      • etc.

    Recognized flags: hygiene, handoff, closeout, xa_gaps, ipr,
    xa_apology, weekly, estimates. Plus a `cap200` flag that bumps
    `max_per_list` to 200 (otherwise stays at 50 for safety).
    """
    started = datetime.datetime.now().isoformat(timespec="seconds")
    _write_status({
        "phase":      "running",
        "started_at": started,
        "mode":       mode,
        "pid":        os.getpid(),  # so the main process can kill us
        "done":       0,
        "total":      0,
        "name":       "Starting…",
    })
    try:
        import trello_hygiene as _th
        import persistence as _per

        # When running with an attached console (e.g. the standalone
        # run_hygiene_scan.bat), also echo progress to stdout so the
        # user can see what's happening. Detached subprocess runs from
        # the webview won't have a real stdout — try/except handles
        # both cases without branching.
        _has_console = sys.stdout is not None and sys.stdout.isatty()

        def _progress(done, total, name):
            try:
                _write_status({
                    "phase":      "running",
                    "started_at": started,
                    "mode":       mode,
                    "done":       int(done or 0),
                    "total":      int(total or 0),
                    "name":       str(name or "")[:120],
                })
            except Exception:
                pass
            if _has_console:
                try:
                    msg = (f"  [{int(done or 0)}/{int(total or 0)}] "
                           f"{str(name or '')[:80]}")
                    print(msg, flush=True)
                except Exception:
                    pass

        if _has_console:
            print(f"Hygiene scan started ({mode} mode) at {started}",
                  flush=True)

        # Translate tab_key to include_* flags (same as the in-process
        # version did).
        tab_flags = {}
        if tab_key:
            try:
                from hygiene_gui import _scan_flags_for_tab
                tab_flags = _scan_flags_for_tab(tab_key) or {}
            except Exception:
                tab_flags = {}

        # Parse the mode. "minimal" / "full" stay simple presets;
        # comma-list mode gives the user surgical control for
        # bisecting which include_* flag is the killer.
        flags = {"hygiene", "handoff", "closeout", "xa_gaps", "ipr",
                 "xa_apology", "weekly", "estimates"}
        if mode == "minimal":
            active = {"hygiene"}
            max_per_list = 50
        elif mode == "full":
            active = set(flags)
            max_per_list = 200
        else:
            tokens = [t.strip() for t in mode.split(",") if t.strip()]
            active = set(tokens) & flags
            max_per_list = 200 if "cap200" in tokens else 50

        results = _th.scan_workspace(
            max_per_list=max_per_list,
            include_hygiene=bool("hygiene" in active),
            include_handoff=bool("handoff" in active),
            include_closeout=bool("closeout" in active),
            include_xa_gaps=bool("xa_gaps" in active),
            include_ipr=bool("ipr" in active),
            progress_cb=_progress,
        ) or {}

        violations = list(results.get("hygiene") or [])
        closeouts  = list(results.get("closeout") or [])
        xa_gaps    = list(results.get("xa_gaps") or [])
        ipr_rows   = list(results.get("ipr") or [])

        # Side-fetches — gated by per-flag activation. Easy to bisect:
        # if the full scan kills the app, the user can flip them on
        # one at a time via the comma-list mode until the killer
        # shows up.
        xa_apology_rows = []
        weekly_rows = []
        estimate_rows = []
        if "xa_apology" in active:
            try:
                import ar_followup as _arf
                xa_apology_rows = _arf.find_stale_cards() or []
            except Exception:
                try:
                    import xa_apology as _xa
                    xa_apology_rows = _xa.list_recent_apologies() or []
                except Exception:
                    xa_apology_rows = []
        if "weekly" in active:
            try:
                import weekly_checkins as _wc
                weekly_rows = _wc.find_due_cards() or []
            except Exception:
                pass
        if "estimates" in active:
            try:
                import estimate_requests as _er
                # adjuster_monitor.scan_and_post deliberately omitted —
                # opt-in via Api.run_adjuster_scan(). detect_pending
                # accepts None as the documented fallback.
                try:
                    _er.detect_pending(xa_gaps, None)
                except Exception:
                    pass
                estimate_rows = _er.all_active() or []
            except Exception:
                pass

        # Same 1000-row cap the in-process version applied — defensive
        # against legacy lanes with thousands of stale cards.
        CAP = 1000
        try:
            _per.set_hygiene_scan_cache(
                violations[:CAP],
                closeouts[:CAP],
                xa_apology=xa_apology_rows[:CAP],
                xa_gaps=xa_gaps[:CAP],
                ipr=ipr_rows[:CAP],
                estimates=estimate_rows[:CAP],
                weekly=weekly_rows[:CAP],
            )
        except Exception as ex:
            _write_status({
                "phase":      "error",
                "started_at": started,
                "ended_at":   datetime.datetime.now().isoformat(timespec="seconds"),
                "error":      f"cache write failed: {ex}",
            })
            return 1

        _write_status({
            "phase":      "done",
            "started_at": started,
            "ended_at":   datetime.datetime.now().isoformat(timespec="seconds"),
            "counts": {
                "hygiene":    len(violations),
                "closeout":   len(closeouts),
                "xa_apology": len(xa_apology_rows),
                "xa_gaps":    len(xa_gaps),
                "ipr":        len(ipr_rows),
                "estimates":  len(estimate_rows),
                "weekly":     len(weekly_rows),
            },
        })
        if _has_console:
            print("\nDONE. Wrote cache:", flush=True)
            print(f"  hygiene:    {len(violations)}", flush=True)
            print(f"  closeout:   {len(closeouts)}", flush=True)
            print(f"  xa_apology: {len(xa_apology_rows)}", flush=True)
            print(f"  xa_gaps:    {len(xa_gaps)}", flush=True)
            print(f"  ipr:        {len(ipr_rows)}", flush=True)
            print(f"  estimates:  {len(estimate_rows)}", flush=True)
            print(f"  weekly:     {len(weekly_rows)}", flush=True)
        return 0
    except Exception as ex:
        _write_status({
            "phase":      "error",
            "started_at": started,
            "ended_at":   datetime.datetime.now().isoformat(timespec="seconds"),
            "error":      f"{type(ex).__name__}: {ex}",
            "traceback":  traceback.format_exc()[:4000],
        })
        return 1


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    tab_key = argv[0] if argv else ""
    mode = argv[1] if len(argv) > 1 else "full"
    sys.exit(run(tab_key, mode))


if __name__ == "__main__":
    main()
