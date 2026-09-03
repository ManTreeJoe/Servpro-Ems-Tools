"""Dated copies of the files the business cannot lose.

There were no backups. `state.json` holds every pin, resolved issue,
closeout ledger and tracker record; `ems_jobs.db` holds the job index;
`config.json` holds the paths and tokens that make the app work at all.
A corrupt write, a half-finished migration or a mistaken bulk action
took any of them with no way back.

That is not hypothetical here. `state.json` failed to write three times
in July with "Access is denied" while two builds fought over the file,
and twelve Trello pins were later found stranded in an abandoned data
folder. Both were recoverable only because someone went looking.

Runs at launch and checks again hourly on daemon threads. The per-file
intervals below prevent redundant copies. It never raises: a backup that
can break startup is worse than no backup.
"""
import os
import shutil
import threading

import paths

# What gets copied. Regenerable caches (the cache_*.json sidecars) are
# deliberately absent — they cost a re-fetch, not data.
FILES = ("state.json", "ems_jobs.db", "config.json")

KEEP = 7                      # dated copies per file
_DIRNAME = "backups"
_MIN_INTERVAL_H = 12          # don't re-copy on a quick restart

# The shared database has been the source of truth since the cloud
# cutover, which quietly demoted `ems_jobs.db` above to the offline
# mirror — so the three files here back up two local files and a cache,
# and the data every machine now READS from had no backup at all.
#
# Taken less often than the local copies: this one is a network pull on
# someone's office connection, not a file copy.
CLOUD_NAME = "cloud.json"
_CLOUD_INTERVAL_H = 24

# A long-running desktop session still needs to reach the 12/24 hour
# backup intervals. A one-hour check is cheap because run_once() exits
# immediately for every copy that is still recent.
_BACKGROUND_CHECK_S = 60 * 60
_TIMER_LOCK = threading.Lock()
_NEXT_TIMER = None
_RUN_LOCK = threading.Lock()
_IN_PROGRESS = False
_LAST_REPORT = None


def backup_dir():
    return paths.data(_DIRNAME)


def _stamp():
    import datetime as _dt
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _stamp_time(value):
    """Epoch for our filename timestamp, or zero for an unknown name."""
    import datetime as _dt
    try:
        return _dt.datetime.strptime(str(value), "%Y%m%d-%H%M%S").timestamp()
    except (TypeError, ValueError):
        return 0.0


def _prune(dest, base):
    """Keep the newest KEEP copies of one file."""
    try:
        mine = sorted(
            (f for f in os.listdir(dest) if f.startswith(base + ".")),
            reverse=True)
        for old in mine[KEEP:]:
            try:
                os.remove(os.path.join(dest, old))
            except OSError:
                pass
    except OSError:
        pass


def _recent_copy_exists(dest, base, hours=None):
    """True when one was taken within `hours` (default _MIN_INTERVAL_H).

    The app gets restarted several times in a row while working; without
    this the seven slots fill with copies of the same minute and the
    week of history they exist for is gone.
    """
    import time
    try:
        newest = max((_stamp_time(f.rpartition(".")[2])
                      for f in os.listdir(dest)
                      if f.startswith(base + ".")), default=0)
    except OSError:
        return False
    window = _MIN_INTERVAL_H if hours is None else hours
    return (time.time() - newest) < window * 3600


def _quiet_remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _note_failure(name, detail):
    try:
        import ems_log
        ems_log.warn("backup", f"{name}: {detail}")
    except Exception:
        pass


def _cloud_once(dest, stamp, force=False):
    """Snapshot the shared database into the same dated rotation.

    Returns a status string for the report, and never raises — this one
    reaches the network, and a backup that can break startup is worse
    than no backup.
    """
    try:
        import ems_db
        if ems_db.backend_name() != "supabase":
            # Local backend: ems_jobs.db in FILES already IS the database.
            return "skipped: local backend"
    except Exception as ex:
        return f"failed: {type(ex).__name__}"

    if not force and _recent_copy_exists(dest, CLOUD_NAME,
                                         hours=_CLOUD_INTERVAL_H):
        return "recent"

    try:
        import supabase_client
        supabase_client.access_token()
    except (supabase_client.NotSignedIn, supabase_client.NotConfigured):
        return "skipped: sign-in required"
    except supabase_client.SupabaseError as ex:
        if getattr(ex, "status", None) == 0:
            return "deferred: shared database unavailable"
        _note_failure(CLOUD_NAME, ex)
        return f"failed: HTTP {getattr(ex, 'status', '?')}"

    final = os.path.join(dest, f"{CLOUD_NAME}.{stamp}")
    # Leading dot, like the local copies above. Both _prune and
    # _recent_copy_exists glob on "cloud.json.", so a temp named
    # cloud.json.<stamp>.part would match them — a half-written snapshot
    # would read as a recent one and suppress the next day's backup.
    tmp = os.path.join(dest, f".{CLOUD_NAME}.{stamp}.snap")
    try:
        import ems_db_supabase
        res = ems_db_supabase.snapshot(tmp)
    except Exception as ex:
        _quiet_remove(tmp)
        _note_failure(CLOUD_NAME, ex)
        return f"failed: {type(ex).__name__}"

    if not res.get("ok"):
        # A snapshot that lost a table must never become the file someone
        # restores from — it would look complete at the worst moment.
        _quiet_remove(tmp)
        _note_failure(CLOUD_NAME, f"incomplete: {res.get('errors')}")
        return "failed: incomplete"

    try:
        os.replace(tmp, final)
    except OSError as ex:
        _quiet_remove(tmp)
        _note_failure(CLOUD_NAME, ex)
        return f"failed: {type(ex).__name__}"
    _prune(dest, CLOUD_NAME)
    return "copied"


def run_once(force=False):
    """Copy each file if it's due. Returns a {name: status} report."""
    report = {}
    try:
        dest = backup_dir()
        os.makedirs(dest, exist_ok=True)
    except OSError as ex:
        return {"_error": str(ex)}

    stamp = _stamp()
    for name in FILES:
        src = paths.data(name)
        try:
            if not os.path.isfile(src):
                report[name] = "missing"
                continue
            if not force and _recent_copy_exists(dest, name):
                report[name] = "recent"
                continue
            tmp = os.path.join(dest, f".{name}.{stamp}.part")
            final = os.path.join(dest, f"{name}.{stamp}")
            # Copy to .part then rename: a backup half-written when the
            # machine goes down must not look like a usable one.
            shutil.copy2(src, tmp)
            os.replace(tmp, final)
            _prune(dest, name)
            report[name] = "copied"
        except Exception as ex:
            report[name] = f"failed: {type(ex).__name__}"
            _note_failure(name, ex)
    report[CLOUD_NAME] = _cloud_once(dest, stamp, force=force)
    return report


def start_background(force=False):
    """Run asynchronously and keep scheduling due checks after launch.

    ``force=True`` is intentionally one-shot for manual runs and tests.
    Normal launch calls schedule another check after the worker finishes.
    """
    def _go():
        global _IN_PROGRESS, _LAST_REPORT
        with _RUN_LOCK:
            if _IN_PROGRESS:
                return
            _IN_PROGRESS = True
        try:
            _LAST_REPORT = run_once(force=force)
        except Exception:
            _LAST_REPORT = {"_error": "backup worker failed"}
        finally:
            with _RUN_LOCK:
                _IN_PROGRESS = False
            if not force:
                _schedule_next()
    t = threading.Thread(target=_go, daemon=True, name="data-backup")
    t.start()
    return t


def _scheduled_run():
    global _NEXT_TIMER
    with _TIMER_LOCK:
        _NEXT_TIMER = None
    start_background()


def _schedule_next():
    """Keep at most one pending backup timer in this process."""
    global _NEXT_TIMER
    with _TIMER_LOCK:
        if _NEXT_TIMER is not None and _NEXT_TIMER.is_alive():
            return _NEXT_TIMER
        timer = threading.Timer(_BACKGROUND_CHECK_S, _scheduled_run)
        timer.daemon = True
        timer.name = "data-backup-timer"
        _NEXT_TIMER = timer
        timer.start()
        return timer


def list_backups():
    """[{name, stamp, path, size}] newest first — for Settings."""
    out = []
    dest = backup_dir()
    try:
        names = os.listdir(dest)
    except OSError:
        return out
    for f in names:
        if f.startswith("."):
            continue
        base, _, stamp = f.rpartition(".")
        if base not in FILES + (CLOUD_NAME,):
            continue
        p = os.path.join(dest, f)
        try:
            size = os.path.getsize(p)
        except OSError:
            size = 0
        out.append({"name": base, "stamp": stamp, "path": p, "size": size})
    out.sort(key=lambda r: (r["stamp"], r["name"]), reverse=True)
    return out


def health() -> dict:
    """Read-only backup freshness summary for Data & Sync Health."""
    import time
    rows = list_backups()
    latest = {}
    for row in rows:
        latest.setdefault(row["name"], row)

    try:
        import config
        cloud_required = ((config.load().get("ems_db_backend") or "sqlite")
                          .strip().lower() == "supabase")
        if cloud_required:
            import supabase_client
            cloud_required = (supabase_client.is_configured()
                              and supabase_client.is_signed_in())
    except Exception:
        cloud_required = False

    checks = []
    now = time.time()
    for name in FILES + ((CLOUD_NAME,) if cloud_required else ()):
        row = latest.get(name)
        max_age_h = 36 if name != CLOUD_NAME else 60
        if not row:
            checks.append({"name": name, "ok": False, "state": "missing",
                           "last_success": "", "age_hours": None})
            continue
        try:
            # copy2 intentionally preserves the source file mtime, so the
            # backup file's mtime says when config/state last changed—not
            # when the backup succeeded. The dated filename is authoritative.
            backed_up_at = _stamp_time(row.get("stamp"))
            if not backed_up_at:
                backed_up_at = os.path.getmtime(row["path"])
            age_h = max(0.0, (now - backed_up_at) / 3600)
        except OSError:
            age_h = max_age_h + 1
        checks.append({
            "name": name,
            "ok": age_h <= max_age_h,
            "state": "ok" if age_h <= max_age_h else "stale",
            "last_success": row["stamp"],
            "age_hours": round(age_h, 1),
        })
    healthy = all(c["ok"] for c in checks)
    with _RUN_LOCK:
        pending = bool(_IN_PROGRESS)
        attempted = _LAST_REPORT is not None
        last_report = dict(_LAST_REPORT or {})
    # Startup already schedules a backup before health is rendered. Suppress
    # the stale banner while that real recovery attempt is still running;
    # after it finishes, any remaining failure becomes actionable.
    return {"ok": bool(healthy or pending), "checks": checks,
            "pending": pending, "attempted": attempted,
            "last_report": last_report, "dir": backup_dir()}


if __name__ == "__main__":
    import json
    print(json.dumps(run_once(force=True), indent=2))
    for b in list_backups():
        print(f"  {b['stamp']}  {b['name']:14} {b['size'] / 1024:8.0f} KB")
