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

Runs once per launch, on a thread, and never raises: a backup that can
break startup is worse than no backup.
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


def backup_dir():
    return paths.data(_DIRNAME)


def _stamp():
    import datetime as _dt
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


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


def _recent_copy_exists(dest, base):
    """True when one was taken within _MIN_INTERVAL_H.

    The app gets restarted several times in a row while working; without
    this the seven slots fill with copies of the same minute and the
    week of history they exist for is gone.
    """
    import time
    try:
        newest = max(
            (os.path.getmtime(os.path.join(dest, f))
             for f in os.listdir(dest) if f.startswith(base + ".")),
            default=0)
    except OSError:
        return False
    return (time.time() - newest) < _MIN_INTERVAL_H * 3600


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
            try:
                import ems_log
                ems_log.warn("backup", f"{name}: {ex}")
            except Exception:
                pass
    return report


def start_background(force=False):
    """Fire and forget at launch. Never blocks, never raises."""
    def _go():
        try:
            run_once(force=force)
        except Exception:
            pass
    t = threading.Thread(target=_go, daemon=True, name="data-backup")
    t.start()
    return t


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
        if base not in FILES:
            continue
        p = os.path.join(dest, f)
        try:
            size = os.path.getsize(p)
        except OSError:
            size = 0
        out.append({"name": base, "stamp": stamp, "path": p, "size": size})
    out.sort(key=lambda r: (r["stamp"], r["name"]), reverse=True)
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(run_once(force=True), indent=2))
    for b in list_backups():
        print(f"  {b['stamp']}  {b['name']:14} {b['size'] / 1024:8.0f} KB")
