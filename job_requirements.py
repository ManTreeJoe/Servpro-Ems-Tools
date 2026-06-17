"""Day-by-day photo-requirements tracker.

As a job's daily run-doc repeats a photographable activity across days,
this module accumulates a per-day photo requirement:

    Demo on 6/3        -> "Demo photos"
    Demo again on 6/4  -> "Demo day 2 photos"
    Demo again on 6/5  -> "Demo day 3 photos"

Each requirement auto-satisfies when a photo *dated to that day* exists in
the job's PICS tree — detected either by the file's modified-date OR by a
date token in the file's path (SP / WC import folders are named with the
visit date, e.g. "Marco 06-03-2026 John Camp").

The ledger itself lives in persistence (`record_job_activity` /
`get_job_activity_log`); this module is the policy layer on top:
  - record_from_labels(client, date_iso, labels) — log the day's work
  - compute(client, pics_path) — the cumulative requirement list with
    each entry's `satisfied` flag resolved against photos on disk.
"""
from __future__ import annotations

import os
import re
from datetime import datetime

# Activities that warrant photos. Mirrors the photos_needed=True rows in
# audit_logic._ACTIVITY_PATTERNS. Monitor / Mold Clearance don't take
# progress photos, so they never generate a requirement.
PHOTOGRAPHABLE = {
    "Demo",
    "Mold Prep",
    "Contents",
    "Pack-out",
    "Pack-in",
    "Reinspection",
    "Initial Inspection",
    "Teardown",
}

_IMG_EXTS = {
    ".jpg", ".jpeg", ".png", ".heic", ".heif",
    ".webp", ".bmp", ".gif", ".tif", ".tiff",
}


def has_ledger(client: str) -> bool:
    """True when the client has any recorded activities — a cheap dict
    lookup callers use to skip the (expensive) PICS walk in `compute`
    for jobs that have never had a photographable activity logged."""
    try:
        import persistence as per
        return bool(per.get_job_activity_log(client))
    except Exception:
        return False


def record_from_labels(client: str, date_iso: str, labels) -> None:
    """Log each photographable label from a day's run-doc into the
    persistent ledger. Non-photographable labels (Monitor, etc.) are
    ignored. Idempotent — re-recording the same date+activity is a
    no-op (the persistence helper dedups)."""
    if not client or not date_iso:
        return
    try:
        import persistence as per
    except Exception:
        return
    for lbl in (labels or []):
        if lbl in PHOTOGRAPHABLE:
            per.record_job_activity(client, date_iso, lbl)


def _day_label(activity: str, day_num: int) -> str:
    """'Demo' + day 1 -> 'Demo photos'; day 2 -> 'Demo day 2 photos'."""
    if day_num <= 1:
        return f"{activity} photos"
    return f"{activity} day {day_num} photos"


def _date_tokens(date_iso: str) -> set:
    """String date tokens that might appear in a folder / file name for
    this date — covers the slash, dash, dot, and underscore conventions
    techs use ('6-3-26', '06-03-2026', '6/3', '6.3.26', …)."""
    try:
        d = datetime.strptime(date_iso, "%Y-%m-%d")
    except ValueError:
        return set()
    m, day, yy, yyyy = d.month, d.day, d.year % 100, d.year
    return {
        f"{m}-{day}-{yy}", f"{m:02d}-{day:02d}-{yyyy}",
        f"{m}-{day}-{yyyy}", f"{m:02d}-{day:02d}-{yy}",
        f"{m}_{day}_{yy}",  f"{m}.{day}.{yy}",
        f"{m}/{day}/{yy}",  f"{m:02d}/{day:02d}/{yyyy}",
        f"{m}/{day}",       f"{m}-{day}",
    }


def _scan_photos(pics_path: str):
    """Walk pics_path once, returning [(lower_path, mtime_date), …].
    Empty list when the folder is missing/unreadable."""
    out = []
    if not pics_path or not os.path.isdir(pics_path):
        return out
    try:
        for root, _dirs, files in os.walk(pics_path):
            for f in files:
                if os.path.splitext(f)[1].lower() not in _IMG_EXTS:
                    continue
                fp = os.path.join(root, f)
                try:
                    mt_date = datetime.fromtimestamp(
                        os.path.getmtime(fp)).date()
                except (OSError, ValueError):
                    mt_date = None
                out.append((fp.lower(), mt_date))
    except OSError:
        pass
    return out


def _photo_dated_to(photos, date_iso: str) -> bool:
    """True when any photo in the pre-scanned `photos` list is dated to
    `date_iso` — by a date token in its path OR its modified-date."""
    try:
        target = datetime.strptime(date_iso, "%Y-%m-%d").date()
    except ValueError:
        return False
    tokens = _date_tokens(date_iso)
    for low_path, mt_date in photos:
        if tokens and any(tok in low_path for tok in tokens):
            return True
        if mt_date == target:
            return True
    return False


def compute(client: str, pics_path: str) -> list:
    """Return the cumulative day-by-day photo requirements for a job.

    Each entry: {activity, date, day_num, label, satisfied}. Sorted by
    activity, then by date ascending (so day 1 precedes day 2). The
    `satisfied` flag is resolved against the photos currently on disk —
    so a requirement auto-clears once that day's photos are imported."""
    try:
        import persistence as per
    except Exception:
        return []
    log = per.get_job_activity_log(client)
    if not log:
        return []
    photos = _scan_photos(pics_path)
    out = []
    for activity in sorted(log):
        dates = sorted(d for d in (log.get(activity) or []) if d)
        for i, date_iso in enumerate(dates, 1):
            out.append({
                "activity":  activity,
                "date":      date_iso,
                "day_num":   i,
                "label":     _day_label(activity, i),
                "satisfied": _photo_dated_to(photos, date_iso),
            })
    return out


def unsatisfied_count(requirements) -> int:
    """Convenience — how many requirements are still missing photos."""
    return sum(1 for r in (requirements or []) if not r.get("satisfied"))
