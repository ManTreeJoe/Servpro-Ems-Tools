"""Detect stage + date groups inside a photo-import batch.

When a Workcenter/CompanyCam download spans multiple days or stages
(e.g. "7_14_26 demo garage", "7_16 monitor", "7_17 post mitigation"),
the import tool uses this to auto-split the photos: each STAGE routes to
its own PICS subfolder, and each distinct DAY+STAGE becomes a group the
user assigns a tech to. Filenames with no recognizable stage surface as
an 'Unassigned' group for the user to route in the review panel.

Pure string logic — no UI, no filesystem writes — so it's unit-testable
and shared by every import surface.
"""
from __future__ import annotations
import os
import re

# Stage keyword → canonical PICS subfolder. ORDER MATTERS: the most
# specific patterns come first so "post mold prep" doesn't match "post"
# and "mold prep" doesn't match "mold". Mirrors the audit's stage table
# + web_shared/stage_picker.js PICS_STAGES (minus the retired Post Mold
# entry). Contents came BACK 2026-08-14 — audit_logic never stopped
# routing to it.
_STAGE_PATTERNS = (
    ("Post Mold Prep", re.compile(r"post\s*mold\s*prep", re.I)),
    ("Mold Prep",      re.compile(r"mold\s*prep", re.I)),
    ("Reinspection",   re.compile(r"re-?inspect", re.I)),
    ("Abatement",      re.compile(r"abate", re.I)),
    # Same Contents routing as the CompanyCam tag path and the
    # audit's run-doc table, so a job filed by zip, by API or by
    # run-doc lands in the same folder.
    # The trailing \b matters: without it "pack..in" matches inside
    # "Packing Room", and a ROOM would be filed as a stage.
    ("Contents",       re.compile(
        r"\bcontents\b|\bpack\s*-?\s*(?:out|in)\b",
        re.I)),
    ("Post",           re.compile(r"post|tear\s*-?\s*down", re.I)),
    ("Mold",           re.compile(r"\bmold\b", re.I)),
    ("Monitor",        re.compile(r"monitor", re.I)),
    ("Demo",           re.compile(r"\bdemo(?:lition|lit|ed)?\b", re.I)),
    ("Equipment",      re.compile(r"equip", re.I)),
    ("Initial",        re.compile(r"initial|inspection", re.I)),
)

# Dates embedded in a filename, most-specific first:
#   ISO       — 2026-07-24        (CompanyCam export folder / some exports)
#   monthname — "Jul 23 2026", "July 23, 2026", "Jul 23 26"  (CompanyCam)
#   numeric   — 7_14_26, 7/14/26, 7-14, 07.14.2026
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
           "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
_MONTHNAME_DATE_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{2,4})\b", re.IGNORECASE)
_NUM_DATE_RE = re.compile(r"\b(\d{1,2})[_/.\-](\d{1,2})(?:[_/.\-](\d{2,4}))?\b")


def _mk_date(mo, day, yr):
    """(sort_key, label) for a month/day/(year), or None when out of range."""
    try:
        mi, di = int(mo), int(day)
    except (ValueError, TypeError):
        return None
    if not (1 <= mi <= 12 and 1 <= di <= 31):
        return None
    if yr:
        y = int(yr)
        if y < 100:
            y += 2000
        return (f"{y:04d}-{mi:02d}-{di:02d}", f"{mi}/{di}/{str(y)[2:]}")
    return (f"0000-{mi:02d}-{di:02d}", f"{mi}/{di}")


def detect_stage(name: str) -> str | None:
    """Canonical PICS stage for a filename, or None when nothing matches
    (the file needs a manual pick in the review panel)."""
    stem = os.path.splitext(os.path.basename(name or ""))[0]
    for stage, pat in _STAGE_PATTERNS:
        if pat.search(stem):
            return stage
    return None


def detect_date(name: str):
    """Return (sort_key, label) for the date in `name`, or (None, "") when
    there's none. Tries ISO, then month-name ('Jul 23 2026' — CompanyCam),
    then numeric. `sort_key` is 'YYYY-MM-DD' for ordering; `label` is the
    human 'M/D' (or 'M/D/YY' with a year)."""
    s = name or ""
    # ISO YYYY-MM-DD (year, month, day).
    m = _ISO_DATE_RE.search(s)
    if m:
        r = _mk_date(m.group(2), m.group(3), m.group(1))
        if r:
            return r
    # Month-name (CompanyCam), e.g. "Jul 23 2026".
    m = _MONTHNAME_DATE_RE.search(s)
    if m:
        r = _mk_date(_MONTHS.get(m.group(1).lower()[:3]), m.group(2), m.group(3))
        if r:
            return r
    # Numeric M/D(/Y) — iterate so a time like '11_43am' doesn't abort the
    # scan on an out-of-range 'day'; return the first VALID date.
    for m in _NUM_DATE_RE.finditer(s):
        r = _mk_date(m.group(1), m.group(2), m.group(3))
        if r:
            return r
    return (None, "")


def detect_groups(filenames) -> dict:
    """Group `filenames` by (date, stage). Returns:

        {
          "groups": [ {date_label, date_key, stage(or None), folder(or ""),
                       count, files:[names]} … ],   # sorted by date then stage
          "stages": [distinct non-None stages],
          "dates":  [distinct date labels],
          "multi":  bool  # >1 group OR >1 stage → worth the review panel
          "unassigned": int  # files with no detected stage
        }
    """
    buckets: dict = {}
    for fn in filenames or []:
        base = os.path.basename(fn)
        stage = detect_stage(base)
        dkey, dlabel = detect_date(base)
        key = (dkey or "", stage or "")
        b = buckets.get(key)
        if b is None:
            b = {"date_label": dlabel, "date_key": dkey or "",
                 "stage": stage, "folder": stage or "",
                 "count": 0, "files": []}
            buckets[key] = b
        b["count"] += 1
        b["files"].append(base)

    groups = sorted(
        buckets.values(),
        key=lambda g: (g["date_key"] or "9999", g["stage"] or "~"))
    stages = sorted({g["stage"] for g in groups if g["stage"]})
    dates = sorted({g["date_label"] for g in groups if g["date_label"]})
    unassigned = sum(g["count"] for g in groups if not g["stage"])
    multi = len(groups) > 1 or len(stages) > 1
    return {"groups": groups, "stages": stages, "dates": dates,
            "multi": multi, "unassigned": unassigned}
