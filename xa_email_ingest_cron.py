"""Headless email-scan runner for Windows Task Scheduler.

This is the out-of-app counterpart to `hygiene_gui._run_xa_mini_scan`:
- The in-app polling only fires while the EMS launcher is open. If the
  user closes the launcher for the weekend, no new XA notes / adjuster
  emails / estimate requests get picked up until they reopen it.
- This script runs headlessly on a schedule (Task Scheduler), reads the
  same Outlook inbox via outlook_local + xa_email_ingest, writes the
  fresh results into the shared persistence file, and posts any
  adjuster-monitor inbound-receipt comments to Trello.

When the user next opens Hygiene, `_load_cached_or_scan` will read the
cron's last persisted result and skip an immediate rescan — so they get
fresh data with zero wait.

CLI:
    python xa_email_ingest_cron.py [--days=14] [--quiet]
        One-shot run. Logs to `<scripts>/logs/xa_cron.log`.
        Use --quiet to suppress stdout (Task Scheduler default).

    python xa_email_ingest_cron.py --install [--every=15]
        Print a `schtasks` command to install this script in Windows
        Task Scheduler firing every N minutes (default 15).

    python xa_email_ingest_cron.py --uninstall
        Print the `schtasks` command to remove the entry.

Safety:
- A lockfile (`logs/xa_cron.lock`) prevents two concurrent runs from
  writing persistence simultaneously. Stale locks older than 30 minutes
  are reclaimed (in case a prior run crashed without releasing it).
- All exceptions are logged but never re-raised — the script always
  exits 0 so Task Scheduler doesn't mark the entry as failed and
  back off.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import logging
import logging.handlers
import os
import sys
import time

# Make sure relative imports work when launched via `python <path>` from
# Task Scheduler (the scheduler doesn't cd to the script dir by default).
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


# Task Scheduler firing name. Used by --install / --uninstall.
TASK_NAME = "EMS XA Email Ingest"

# Where logs and the lockfile live. Logs/ already exists in most installs
# but we create it on first run if not.
LOGS_DIR = os.path.join(_HERE, "logs")
LOG_PATH = os.path.join(LOGS_DIR, "xa_cron.log")
LOCK_PATH = os.path.join(LOGS_DIR, "xa_cron.lock")

# How long before a lock is considered stale (crashed run).
STALE_LOCK_MIN = 30


def _setup_logging(quiet: bool) -> logging.Logger:
    """Console + rotating-file logger. Rotating cap keeps the log file
    bounded so a year of every-15-min runs doesn't fill the disk."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    log = logging.getLogger("xa_cron")
    log.setLevel(logging.INFO)
    # Avoid duplicate handlers when imported by tests.
    log.handlers.clear()
    fh = logging.handlers.RotatingFileHandler(
        LOG_PATH, maxBytes=512 * 1024, backupCount=4, encoding="utf-8")
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"))
    log.addHandler(fh)
    if not quiet:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(sh)
    return log


def _acquire_lock(log: logging.Logger) -> bool:
    """Best-effort exclusive lock via a sentinel file. Returns True
    when the caller has the lock; False when another run is active.

    Stale locks (older than STALE_LOCK_MIN) get reclaimed so a crashed
    run can't block forever."""
    try:
        if os.path.exists(LOCK_PATH):
            age = time.time() - os.path.getmtime(LOCK_PATH)
            if age < STALE_LOCK_MIN * 60:
                log.info("Another run holds the lock (age %.0fs) — exiting.",
                          age)
                return False
            log.warning("Reclaiming stale lock (age %.0fs)", age)
        with open(LOCK_PATH, "w", encoding="utf-8") as f:
            f.write(f"pid={os.getpid()} at={_dt.datetime.now().isoformat()}")
        return True
    except OSError as ex:
        log.warning("Lock acquire failed: %s — proceeding anyway", ex)
        return True


def _release_lock(log: logging.Logger) -> None:
    try:
        if os.path.exists(LOCK_PATH):
            os.remove(LOCK_PATH)
    except OSError as ex:
        log.warning("Lock release failed: %s", ex)


def run_once(days: int, log: logging.Logger) -> int:
    """Run a single XA-ingest + adjuster + estimate-request scan and
    persist results so the Hygiene panel sees them on next open.

    Returns the number of flagged XA groups (for log readability).
    Never raises — all failures are caught and logged."""
    started = time.monotonic()

    # ── XA notes ingest ────────────────────────────────────────────────
    try:
        import xa_email_ingest as xei
    except Exception as ex:
        log.error("Failed to import xa_email_ingest: %s", ex)
        return 0
    try:
        xa_result = xei.scan_inbox(days=days, progress_cb=None)
    except Exception as ex:
        log.exception("scan_inbox failed: %s", ex)
        xa_result = {"groups": [], "scanned": 0, "matched": 0,
                      "unrouted": []}
    groups = xa_result.get("groups") or []
    try:
        unresolved = xei.filter_unresolved(groups)
    except Exception:
        unresolved = list(groups)
    log.info("XA scan: scanned=%d matched=%d unresolved=%d",
             xa_result.get("scanned", 0),
             xa_result.get("matched", 0),
             len(unresolved))

    # ── Adjuster inbound-receipt queueing ──────────────────────────────
    # Queue matches for user approval — adjuster_monitor.scan_and_post
    # writes to adjuster_pending_approval, the Hygiene panel renders
    # ✓ Post / ✕ Dismiss buttons per row. We don't auto-post anymore
    # (vendor / realtor / shared-mailbox false positives were leaking
    # through the static filters), so the cron's job is just to keep
    # the queue populated even while the launcher is closed.
    adj_result: dict | None = None
    try:
        import adjuster_monitor as am
        adj_result = am.scan_and_post(days=2, dry_run=False)
        log.info("Adjuster scan: queued=%d skipped=%d",
                 len(adj_result.get("posted") or []),
                 len(adj_result.get("skipped") or []))
    except Exception as ex:
        log.exception("adjuster_monitor.scan_and_post failed: %s", ex)

    # ── Estimate-request detection ─────────────────────────────────────
    # Updates the shared estimate_requests state so the Hygiene panel
    # picks up new estimating asks even when the launcher was closed.
    try:
        import estimate_requests as er
        er.detect_pending(unresolved, adj_result)
        log.info("Estimate-request state updated.")
    except Exception as ex:
        log.exception("estimate_requests.detect_pending failed: %s", ex)

    # ── Dispute detection (email source) ───────────────────────────────
    # Scans the inbox for dispute-language emails and seeds the shared
    # Dispute Tracker workbook with new rows. Insert-if-missing — user
    # edits to existing rows won't get overwritten by a re-scan.
    try:
        import dispute_email_scan as des
        d_result = des.scan_inbox(days=14)
        log.info("Dispute email scan: matched=%d new=%d skipped_seen=%d",
                 len(d_result.get("matched") or []),
                 d_result.get("new_in_tracker", 0),
                 d_result.get("skipped_seen", 0))
        if d_result.get("error"):
            log.warning("dispute_email_scan reported: %s",
                         d_result["error"])
    except Exception as ex:
        log.exception("dispute_email_scan failed: %s", ex)

    # ── Persist for next Hygiene open ──────────────────────────────────
    # The Hygiene panel's _load_cached_or_scan reads these keys and
    # skips an immediate rescan when they're fresh.
    try:
        import persistence as per
        per.set_value("xa_cron_last_run",
                       _dt.datetime.now(_dt.timezone.utc)
                          .replace(tzinfo=None).isoformat())
        # Sections cache the panel re-uses on first paint.
        per.set_value("xa_cron_groups",
                       [_groups_to_jsonable(g) for g in unresolved])
        log.info("Persistence written. xa_cron_groups=%d", len(unresolved))
    except Exception as ex:
        log.exception("persistence write failed: %s", ex)

    elapsed = time.monotonic() - started
    log.info("Run complete in %.1fs", elapsed)
    return len(unresolved)


def _sanitize_for_json(obj):
    """Recursively convert datetime / set / non-JSON values into JSON-
    safe forms. xa_notes' open_commitments embed `from_note` dicts that
    carry datetime `timestamp` fields, which would otherwise blow up
    persistence's `json.dump`."""
    if isinstance(obj, _dt.datetime):
        return obj.isoformat()
    if isinstance(obj, _dt.date):
        return obj.isoformat()
    if isinstance(obj, (set, tuple)):
        return [_sanitize_for_json(x) for x in obj]
    if isinstance(obj, list):
        return [_sanitize_for_json(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    # Anything else (custom objects, Outlook COM wrappers, etc.)
    return str(obj)


def _groups_to_jsonable(g: dict) -> dict:
    """Strip non-JSON-serializable fields from a group dict so
    persistence can round-trip it. We keep only the surface fields the
    Hygiene UI actually reads, and sanitize them recursively to catch
    any nested datetime / object leaks from xa_notes."""
    out = {
        "claim": g.get("claim") or "",
        "insured_hint": g.get("insured_hint") or "",
    }
    a = g.get("analysis") or {}
    out["analysis"] = _sanitize_for_json({
        "is_stale": bool(a.get("is_stale")),
        "open_commitments": a.get("open_commitments") or [],
        "days_since": a.get("days_since"),
    })
    card = g.get("card") or None
    if isinstance(card, dict):
        out["card"] = {
            "id": str(card.get("id") or ""),
            "name": str(card.get("name") or ""),
            "shortUrl": str(card.get("shortUrl") or ""),
        }
    return out


def _install_command(every_minutes: int) -> str:
    """Build the `schtasks` command line that registers this script.
    Returns a string the caller can either print or pass to subprocess.

    The TR (trigger) is MINUTE/N, which fires every N minutes
    indefinitely. We use `-NoProfile -ExecutionPolicy Bypass` on the
    pythonw invocation so Task Scheduler doesn't pop a console window."""
    pyw = sys.executable
    # Use pythonw.exe (windowless) if the user ran us with python.exe so
    # the scheduled run doesn't pop a console.
    if pyw.lower().endswith("python.exe"):
        pyw_candidate = pyw[:-len("python.exe")] + "pythonw.exe"
        if os.path.exists(pyw_candidate):
            pyw = pyw_candidate
    script = os.path.abspath(__file__)
    cmd = (
        f'schtasks /Create /SC MINUTE /MO {every_minutes} '
        f'/TN "{TASK_NAME}" '
        f'/TR "\\"{pyw}\\" \\"{script}\\" --quiet" '
        f'/RL LIMITED /F'
    )
    return cmd


def _uninstall_command() -> str:
    return f'schtasks /Delete /TN "{TASK_NAME}" /F'


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--days", type=int, default=14,
                     help="Inbox lookback window in days (default 14).")
    ap.add_argument("--quiet", action="store_true",
                     help="Suppress stdout; log file still written.")
    ap.add_argument("--install", action="store_true",
                     help="Print the schtasks command to register this "
                          "as a Windows scheduled task.")
    ap.add_argument("--uninstall", action="store_true",
                     help="Print the schtasks command to remove the "
                          "scheduled task.")
    ap.add_argument("--every", type=int, default=15,
                     help="With --install: minutes between runs "
                          "(default 15).")
    args = ap.parse_args(argv)

    if args.install:
        print(_install_command(args.every))
        return 0
    if args.uninstall:
        print(_uninstall_command())
        return 0

    log = _setup_logging(args.quiet)
    # ASCII separator — Task Scheduler runs under cp1252 on some hosts
    # and unicode box-drawing chars raise UnicodeEncodeError on the
    # stream handler even though the file handler is UTF-8.
    log.info("---- xa_cron start (days=%d) ----", args.days)
    if not _acquire_lock(log):
        return 0
    try:
        run_once(args.days, log)
    except Exception as ex:
        # Should be unreachable — run_once catches everything itself —
        # but keep this catch so Task Scheduler never sees a non-zero
        # exit and backs off the schedule.
        log.exception("Unhandled error: %s", ex)
    finally:
        _release_lock(log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
