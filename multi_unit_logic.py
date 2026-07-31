"""Multi-unit / sub-job folder logic — the pure half of multi_unit_gui.

Four panels (audit, snapshot, quick import, multi-unit) needed these and
each imported the TK module to get them, dragging tkinter, customtkinter
and the theme into web panels that only wanted to list some folders.

Nothing here touches a widget: all four functions were already free of Tk
and `self`. `multi_unit_gui` imports them back, so the Tk window keeps
working and there is ONE definition rather than a copy per caller.
"""
from __future__ import annotations

import os
import re

import audit_logic
import config
import persistence as per

_UNIT_WORD_TOKEN_RE = re.compile(
    r"(?:unit|apt|apartment|suite|ste)\b[\s#:_-]*(?P<num>\d+)",
    re.IGNORECASE)

_HASH_TOKEN_RE = re.compile(r"#\s*(?P<num>\d{1,4})\b")

_HASH_NONUNIT_CTX_RE = re.compile(
    r"(?:claim|job|ticket|inv(?:oice)?|po|w/?o|wo|order|ref(?:erence)?|"
    r"policy|file|acct|account|no|number)\s*[#:.\-]?\s*$",
    re.IGNORECASE)

_UNIT_WALK_SKIP_DIRS = {
    "ems", "contents", "recon", "pics", "photos",
    "docs", "doc", "documents", "forms", "sketch", "sketches",
    "snapshot", "snapshots", "estimating", "estimates",
    "drying", "equipment", "eq", "ar", "from sharepoint",
}


def parse_unit_token(text: str) -> int | None:
    """Pull a unit number out of arbitrary text. Returns None when no
    Unit/Apt/Apartment/# token with a numeric tail is found.

    Used to route SP imports / WC zips to the right unit subfolder
    when the source name carries the unit (e.g.
    'Avila Apt 207 Demo 5-10-26' → 207). A bare '#<n>' only counts as a
    unit when it isn't a claim/job/ticket/etc. number (see guards above)."""
    if not text:
        return None
    # Prefer an explicit unit/apt/suite word — unambiguous.
    m = _UNIT_WORD_TOKEN_RE.search(text)
    if m:
        try:
            return int(m.group("num"))
        except ValueError:
            return None
    # Fall back to a bare "#207", but skip any hash that's preceded by a
    # claim/job/ticket-style keyword (those aren't unit numbers).
    for hm in _HASH_TOKEN_RE.finditer(text):
        if _HASH_NONUNIT_CTX_RE.search(text[:hm.start()]):
            continue
        try:
            return int(hm.group("num"))
        except ValueError:
            continue
    return None


def list_unit_subfolders(job_path: str, *, max_depth: int = 3):
    """Return [{name, path, num, rel}, ...] for every Unit/Apt folder
    found under `job_path`, walked up to `max_depth` levels deep.

    Empty list when there are none (i.e. a normal single-unit job).
    Skips the job's internal EMS / CONTENTS / PICS / DOCS subtrees so
    a randomly-named photo subfolder can't look like a unit.

    The `rel` field is the relative path from `job_path` (e.g.
    'Villaigo/Unit 101 - 95286 Burnett, Gina') so callers that need
    to show which sub-property the unit belongs to have it without
    re-computing.

    Used by Run Audit to decide whether a job is a multi-unit property
    and, if so, which destination subfolder each import should target.
    Some jobs are 2 levels deep (Action Property Management / Villaigo
    / Unit 101 …) so the walk descends through sub-property folders.
    """
    if not job_path or not os.path.isdir(job_path):
        return []
    units = []
    # BFS so we surface units regardless of which sub-property holds
    # them. (parent_path, depth) — depth 0 = job_path itself.
    frontier = [(job_path, 0)]
    while frontier:
        cur, depth = frontier.pop(0)
        try:
            with os.scandir(cur) as it:
                children = list(it)
        except OSError:
            continue
        for e in children:
            try:
                if not e.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            name = e.name
            if _is_unit_folder(name):
                try:
                    rel = os.path.relpath(e.path, job_path)
                except ValueError:
                    rel = name
                units.append({
                    "name": name,
                    "path": e.path,
                    "num":  _unit_number(name),
                    "rel":  rel,
                })
                # Don't descend INTO a unit folder — its own contents
                # are the unit's job tree, not more units.
                continue
            if depth >= max_depth:
                continue
            # Don't descend into known internal directories.
            if name.lower() in _UNIT_WALK_SKIP_DIRS:
                continue
            frontier.append((e.path, depth + 1))
    units.sort(key=lambda u: (u["num"], u["rel"].lower()))
    return units


def discover_multi_unit_properties():
    """Walk every year-folder and surface any direct-child folder that
    contains ≥1 Unit-pattern subfolder. Returns a list of
    {parent_path, parent_name, year, units: [{name, path}]}.

    Sorting: parents alphabetical; units numeric by parsed unit
    number. Folders with zero unit children are dropped (they're just
    normal single-unit jobs)."""
    out = []
    for y, year_path in _year_folders():
        try:
            with os.scandir(year_path) as it:
                parents = [e for e in it
                           if e.is_dir(follow_symlinks=False)]
        except OSError:
            continue
        for parent in parents:
            try:
                with os.scandir(parent.path) as sub_it:
                    kids = [e for e in sub_it
                            if e.is_dir(follow_symlinks=False)]
            except OSError:
                continue
            unit_kids = [{"name": e.name, "path": e.path}
                         for e in kids if _is_unit_folder(e.name)]
            # NAMED sub-jobs (commercial parent whose sub-jobs are named
            # by site/date). Require ≥2 so a normal job with one
            # "Second Claim" subfolder isn't surfaced as a property.
            named_kids = [{"name": e.name, "path": e.path}
                          for e in kids
                          if not _is_unit_folder(e.name)
                          and e.name.lower() not in _UNIT_WALK_SKIP_DIRS
                          and _folder_has_job_structure(e.path)]
            if not unit_kids and len(named_kids) < 2:
                continue
            units = unit_kids + named_kids
            units.sort(key=lambda u: (_unit_number(u["name"]),
                                       u["name"].lower()))
            out.append({
                "parent_path": parent.path,
                "parent_name": parent.name,
                "year":        y,
                "units":       units,
            })
    out.sort(key=lambda p: p["parent_name"].lower())
    return out


def list_subjob_folders(job_path: str, *, max_depth: int = 3):
    """Like `list_unit_subfolders` but ALSO surfaces NAMED sub-jobs —
    child folders that are their own job (contain EMS/CONTENTS/RECON)
    even when they aren't named "Unit X". Covers commercial parents whose
    sub-jobs are named by site/date (e.g. "Menifee … Kirkpatrick
    Elementary 6.9.26"). Each entry: {name, path, num, rel, kind} where
    kind = "unit" for Unit/Apt folders, "job" for named sub-jobs."""
    if not job_path or not os.path.isdir(job_path):
        return []
    out, seen = [], set()
    frontier = [(job_path, 0)]
    while frontier:
        cur, depth = frontier.pop(0)
        try:
            with os.scandir(cur) as it:
                children = list(it)
        except OSError:
            continue
        for e in children:
            try:
                if not e.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            name = e.name
            low = name.lower()
            is_unit = _is_unit_folder(name)
            is_named = (not is_unit and low not in _UNIT_WALK_SKIP_DIRS
                        and _folder_has_job_structure(e.path))
            if is_unit or is_named:
                if e.path in seen:
                    continue
                seen.add(e.path)
                try:
                    rel = os.path.relpath(e.path, job_path)
                except ValueError:
                    rel = name
                out.append({
                    "name": name, "path": e.path,
                    "num":  _unit_number(name),
                    "rel":  rel,
                    "kind": "unit" if is_unit else "job",
                })
                continue  # it's its own job — don't descend into it
            if depth >= max_depth or low in _UNIT_WALK_SKIP_DIRS:
                continue
            frontier.append((e.path, depth + 1))
    out.sort(key=lambda u: (u["num"], u["rel"].lower()))
    return out
