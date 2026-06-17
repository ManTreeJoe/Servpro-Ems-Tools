"""Multi-unit folder cleanup — dry-run by default.

Walks every `<YYYY> Jobs\\` directory on the audit base, finds multi-unit
properties (umbrellas with 2+ unit subfolders), and proposes renames
into the canonical `Unit <NUM> <M-D-YY>` format. Dates are pulled from
each unit's pinned Trello card when available; otherwise the existing
folder name's date suffix is preserved.

This is intentionally read-only by default — the rename pass only runs
when the script is invoked with `--execute`. The dry-run output is
designed to be scanned for surprises (e.g., a "Unit 1234" that has no
matching Trello card and no existing date) before committing.

Usage (from the scripts/ directory):

    python multi_unit_cleanup.py              # dry-run report
    python multi_unit_cleanup.py --execute    # apply renames

Public API for programmatic use:
    find_multi_unit_properties(base_dir) -> list[PropertyReport]
    propose_renames_for(property_path)   -> list[Rename]
    execute_renames(renames, *, dry_run) -> dict
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime


# ── Data models ─────────────────────────────────────────────────────────

@dataclass
class Rename:
    """One proposed rename. `reason` documents why we picked this target
    so the dry-run report shows the user the decision rationale."""
    src: str
    dst: str
    reason: str = ""
    skip: bool = False
    skip_reason: str = ""


@dataclass
class PropertyReport:
    """One multi-unit property's view: the umbrella path + every
    proposed unit rename within it."""
    path: str
    renames: list[Rename] = field(default_factory=list)


# ── Helpers ─────────────────────────────────────────────────────────────

# Canonical target: "Unit <NUM> <M-D-YY>" — no `#`, no `()`, no `.`.
# NUM may carry an uppercase letter suffix (561-I, 565-E).
_CANONICAL_RE = re.compile(
    r"^Unit\s+\d{2,4}(?:-[A-Z])?\s+\d{1,2}-\d{1,2}-\d{2}$")

# Match an existing unit folder's number + optional letter suffix
# (e.g. 561-I, 561-J, '313 C' — different inspections of the same
# physical unit). The letter suffix is preserved in the canonical
# name so two inspections of unit 561 don't collide on rename.
# Accepts dash, underscore, OR space as the separator before the
# letter; the canonical renderer normalizes to dash.
#
# Requires the literal "Unit" / "UNIT" / "Apt" prefix so we don't
# treat folders like "Caprock\1740 - 1_30" (different naming scheme,
# building+date) as units.
_UNIT_RE = re.compile(
    r"^(?:unit\s*#?\s*|apt\s*)"
    r"(?P<num>\d{2,4}(?:[-_\s]+[A-Za-z])?)"
    r"(?=\s|$|[-_])",
    re.IGNORECASE)
_DATE_TAIL_RE = re.compile(
    r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})\s*$")

# Folder names that look like jobs but aren't units (umbrella admin
# subfolders, common service-line folders). Excluded from the unit set
# so we don't try to rename them.
_NON_UNIT_NAMES = {
    "ems", "recon", "contents", "docs", "pics", "photos",
    "_property", "logs", "billing",
}


def _looks_like_unit_folder(name: str) -> bool:
    """True for folders that should be treated as units of a property.
    Rejects admin subfolders + folders without any digit token."""
    if not name:
        return False
    if name.lower() in _NON_UNIT_NAMES:
        return False
    return bool(_UNIT_RE.search(name))


def _canonical_unit_name(unit_num: str, date_str: str) -> str:
    """Render the canonical 'Unit <NUM> <M-D-YY>' form. The unit_num
    may include a letter suffix (561-I, 561-J, '313 C') — preserved
    in the output so different inspections of the same unit don't
    collide. Separator normalized to dash; letter uppercased."""
    norm_num = re.sub(r"[-_\s]+([a-zA-Z])$",
                       lambda m: f"-{m.group(1).upper()}", unit_num)
    return f"Unit {norm_num} {date_str}"


def _format_date(d: datetime) -> str:
    return f"{d.month}-{d.day}-{str(d.year)[-2:]}"


# Trailing digit run of length 6-8 (M[M]D[D] + YYYY). Real folder names:
#   '612025'   = 6-1-2025
#   '4142025'  = 4-14-2025
#   '10272025' = 10-27-2025
_BARE_DATE_RE = re.compile(r"(?<!\d)(\d{6,8})\s*$")


def _date_from_folder_name(name: str) -> str:
    """Extract M-D-YY from existing folder names that already carry a
    date. Handles three formats:
      • separators: 5-23-25, 5/23/25, 5.23.25
      • bare digits (6-8): M[M]D[D]YYYY parsed by trying valid splits
    Returns "" when nothing matches or no split produces a valid date."""
    m = _DATE_TAIL_RE.search(name)
    if m:
        mm, dd, yy = m.group(1), m.group(2), m.group(3)
        if len(yy) == 4:
            yy = yy[-2:]
        return f"{int(mm)}-{int(dd)}-{yy}"
    # Bare-digit fallback. The trailing 4 digits are always the year;
    # the leading 2-4 digits encode month + day in one of three layouts.
    # We try each split and pick the first that yields a valid date.
    bm = _BARE_DATE_RE.search(name)
    if not bm:
        return ""
    s = bm.group(1)
    yyyy = s[-4:]
    head = s[:-4]
    try:
        yi = int(yyyy)
    except ValueError:
        return ""
    if not (2000 <= yi <= 2100):
        return ""
    # Build candidate (month_str, day_str) splits in preference order.
    # Longer-month-first means '10272025' parses as 10-27 (not 1-02-7).
    candidates: list[tuple[str, str]] = []
    L = len(head)
    if L == 4:
        candidates.append((head[:2], head[2:4]))           # MM + DD
    elif L == 3:
        candidates.append((head[:2], head[2:3]))           # MM + D
        candidates.append((head[:1], head[1:3]))           # M + DD
    elif L == 2:
        candidates.append((head[:1], head[1:2]))           # M + D
    for mm, dd in candidates:
        try:
            mi, di = int(mm), int(dd)
        except ValueError:
            continue
        if 1 <= mi <= 12 and 1 <= di <= 31:
            return f"{mi}-{di}-{str(yi)[-2:]}"
    return ""


# ── Trello date lookup ──────────────────────────────────────────────────

def _trello_date_for(property_name: str, unit_num: str) -> str:
    """Best-effort lookup of "Date Received" for a unit. Returns
    'M-D-YY' or '' on miss. Each lookup is one Trello search + a card
    fetch — fine for ~10-20 units per run, but if this script grows to
    many properties we'd want to cache search results."""
    try:
        import trello_client as tc
    except Exception:
        return ""
    # Property name is matched as a substring; the unit number must
    # appear as a standalone token in the card name to avoid 526 → 5260.
    try:
        hits = tc.find_cards_by_name(property_name, max_results=40)
    except Exception:
        return ""
    candidates = []
    pat = re.compile(r"\b" + re.escape(unit_num) + r"\b")
    for h in hits:
        if pat.search(h.get("name", "")):
            candidates.append(h)
    if not candidates:
        return ""
    # Prefer WORK IN PROGRESS > LOGS > AR (matches the Avila cleanup
    # heuristic used earlier — active boards have the cleanest dates).
    def _score(h):
        b = h.get("board", "")
        if "WORK IN PROGRESS" in b:
            return 0
        if "LOGS" in b:
            return 1
        if "AR" in b:
            return 2
        return 3
    candidates.sort(key=_score)
    for h in candidates:
        try:
            card = tc.get_card(h["card_id"])
            d = tc.card_received_date(card)
        except Exception:
            d = None
        if d:
            return _format_date(d)
    return ""


# ── Discovery + proposal ────────────────────────────────────────────────

def find_multi_unit_properties(base_dir: str,
                                 *, min_units: int = 2,
                                 year_filter: int | None = None,
                                 ) -> list[PropertyReport]:
    """Walk every `<YYYY> Jobs\\` subfolder under `base_dir` and return
    one PropertyReport per property folder with `≥ min_units` unit
    subfolders. Skips folders we can't read.

    `year_filter`: when set, only walk `<YYYY> Jobs\\` matching that
    year. Default None walks every year folder — almost always the
    wrong call for cleanup runs since closed-out historical jobs
    shouldn't be renamed.
    """
    if not base_dir or not os.path.isdir(base_dir):
        return []
    reports: list[PropertyReport] = []
    # Years are directly under base_dir — folders matching `<YYYY> Jobs`.
    try:
        year_dirs = []
        for e in os.listdir(base_dir):
            m = re.match(r"^(\d{4})\s+jobs?$", e, re.IGNORECASE)
            if not m:
                continue
            yr = int(m.group(1))
            if year_filter is not None and yr != year_filter:
                continue
            p = os.path.join(base_dir, e)
            if os.path.isdir(p):
                year_dirs.append(p)
    except OSError:
        return []
    for yd in year_dirs:
        try:
            entries = os.listdir(yd)
        except OSError:
            continue
        for prop_name in entries:
            prop_path = os.path.join(yd, prop_name)
            if not os.path.isdir(prop_path):
                continue
            try:
                children = os.listdir(prop_path)
            except OSError:
                continue
            unit_folders = [
                c for c in children
                if os.path.isdir(os.path.join(prop_path, c))
                and _looks_like_unit_folder(c)
            ]
            if len(unit_folders) >= min_units:
                reports.append(PropertyReport(path=prop_path))
    return reports


def _strip_property_suffix(property_folder_name: str) -> str:
    """'Avila Apartments 2026' → 'Avila Apartments' (drop year suffix
    so the Trello search uses the bare property name)."""
    return re.sub(r"\s*\d{4}\s*$", "", property_folder_name).strip()


def propose_renames_for(property_path: str) -> list[Rename]:
    """For each unit subfolder under `property_path`, produce one
    `Rename` describing the proposed canonical name (or a skip with
    reason when we don't have enough info).

    Two-pass to handle multiple jobs on the same physical unit:
      1. First pass picks the best date per folder (Trello preferred,
         folder-name fallback).
      2. If two sibling folders would collide on the SAME target,
         we retry each one with its own folder-name date — different
         folder names usually carry different baked-in dates that
         differentiate two claims on one unit (e.g. 'Unit 226 12302025'
         vs 'Unit 226 1292025').
    """
    prop_folder = os.path.basename(property_path.rstrip("\\/"))
    property_name = _strip_property_suffix(prop_folder)
    try:
        children = os.listdir(property_path)
    except OSError as ex:
        return [Rename(src=property_path, dst="",
                       skip=True, skip_reason=f"listdir failed: {ex}")]

    # Cache `unit_num → trello date` so the same property doesn't
    # re-search Trello for siblings of the same unit number.
    trello_date_cache: dict[str, str] = {}

    def _pick_date(child_name: str, unit_num: str
                    ) -> tuple[str, str]:
        """Return (date_str, source_reason). Trello first, folder
        name fallback. Empty date_str means we have nothing."""
        if unit_num not in trello_date_cache:
            trello_date_cache[unit_num] = _trello_date_for(
                property_name, unit_num)
        if trello_date_cache[unit_num]:
            return trello_date_cache[unit_num], "from Trello Date Received"
        folder_date = _date_from_folder_name(child_name)
        if folder_date:
            return folder_date, "from existing folder name"
        return "", ""

    renames: list[Rename] = []
    # Track (canonical_target → list of (rename_index, child_name,
    # unit_num)) so we can detect intra-property collisions and retry.
    target_index: dict[str, list[tuple[int, str, str]]] = {}

    for child in sorted(children):
        cp = os.path.join(property_path, child)
        if not os.path.isdir(cp):
            continue
        if not _looks_like_unit_folder(child):
            continue
        if _CANONICAL_RE.match(child):
            renames.append(Rename(
                src=cp, dst=cp, skip=True,
                skip_reason="already canonical"))
            continue
        unit_match = _UNIT_RE.search(child)
        if not unit_match:
            renames.append(Rename(
                src=cp, dst="", skip=True,
                skip_reason="no unit number detected"))
            continue
        unit_num = unit_match.group("num")
        date_str, reason = _pick_date(child, unit_num)
        if not date_str:
            renames.append(Rename(
                src=cp, dst="", skip=True,
                skip_reason="no date available "
                            "(no Trello card + no date in name)"))
            continue
        new_name = _canonical_unit_name(unit_num, date_str)
        if new_name == child:
            renames.append(Rename(
                src=cp, dst=cp, skip=True,
                skip_reason="already canonical"))
            continue
        target_path = os.path.join(property_path, new_name)
        target_index.setdefault(target_path, []).append(
            (len(renames), child, unit_num))
        renames.append(Rename(src=cp, dst=target_path, reason=reason))

    # Second pass: for any target shared by 2+ folders, retry each
    # collider with its own folder-name date. If that produces unique
    # targets per folder, use them — that means the same physical unit
    # has multiple separate jobs differentiated by date.
    for target, hits in target_index.items():
        if len(hits) < 2:
            continue
        # Try folder-name dates per collider.
        retry: list[tuple[int, str, str]] = []
        for idx, child, unit_num in hits:
            folder_date = _date_from_folder_name(child)
            if not folder_date:
                # No fallback date — leave this one in collision state;
                # the execute_renames CONFLICT detector will surface it.
                continue
            retry.append((idx, child, unit_num, folder_date))
        # Only auto-resolve when EVERY collider has a folder-name date
        # AND each date produces a unique target. Partial auto-resolve
        # would silently rename one and leave the other colliding,
        # which is worse than the original conflict.
        if len(retry) != len(hits):
            continue
        retry_targets = [
            os.path.join(
                property_path,
                _canonical_unit_name(un, fd))
            for (_idx, _ch, un, fd) in retry
        ]
        if len(set(retry_targets)) != len(retry_targets):
            continue
        # Apply the retry — rewrite each collider's Rename to use the
        # folder-name date instead.
        for (idx, _ch, un, fd), new_target in zip(retry, retry_targets):
            renames[idx] = Rename(
                src=renames[idx].src,
                dst=new_target,
                reason=("from folder-name date (Trello collision — "
                        "multiple claims on same unit)"))
    return renames


# ── Execution ───────────────────────────────────────────────────────────

def execute_renames(renames: list[Rename], *, dry_run: bool = True) -> dict:
    """Run (or simulate) the renames. Always-safe defaults:
      - dry_run=True (no FS writes)
      - never overwrites — if the target already exists on disk OR is
        another candidate's target, skip BOTH with a CONFLICT reason
        so the user can resolve manually. Two siblings collapsing to
        one target is almost always a bug (mismatched Trello date or
        an ambiguous source folder), not the intent.
    """
    # First pass: detect intra-batch target collisions so two sibling
    # folders that propose the same canonical name BOTH get flagged
    # instead of letting one rename and the second fail at runtime.
    target_counts: dict[str, int] = {}
    for r in renames:
        if r.skip or not r.dst or r.dst == r.src:
            continue
        target_counts[r.dst] = target_counts.get(r.dst, 0) + 1
    conflicting_targets = {t for t, n in target_counts.items() if n >= 2}

    summary = {"renamed": 0, "skipped": 0, "failed": 0,
                "events": [], "conflicts": sorted(conflicting_targets)}
    for r in renames:
        if r.skip:
            summary["skipped"] += 1
            summary["events"].append((r.src, r.dst, "SKIP", r.skip_reason))
            continue
        if not r.dst or r.dst == r.src:
            summary["skipped"] += 1
            summary["events"].append(
                (r.src, r.dst, "SKIP", "no change"))
            continue
        if r.dst in conflicting_targets:
            summary["skipped"] += 1
            summary["events"].append(
                (r.src, r.dst, "CONFLICT",
                 "two sibling folders want this same target — resolve manually"))
            continue
        if os.path.exists(r.dst):
            summary["skipped"] += 1
            summary["events"].append(
                (r.src, r.dst, "SKIP", "target exists"))
            continue
        if dry_run:
            summary["renamed"] += 1
            summary["events"].append((r.src, r.dst, "DRY", r.reason))
            continue
        try:
            os.rename(r.src, r.dst)
            summary["renamed"] += 1
            summary["events"].append((r.src, r.dst, "OK", r.reason))
        except OSError as ex:
            summary["failed"] += 1
            summary["events"].append(
                (r.src, r.dst, "FAIL", str(ex)))
    return summary


# ── CLI ─────────────────────────────────────────────────────────────────

def _print_report(reports: list[PropertyReport], summary: dict,
                   *, dry_run: bool) -> None:
    """Human-readable dump of the proposed changes. Designed for the
    user to skim and spot bad picks before committing.

    Per-row prefixes match the event statuses in `summary["events"]`
    so the high-level counts at the bottom line up with the inline
    annotations:
        RENAME  → will rename
        SKIP    → already canonical / no date / target exists
        CONFLICT→ two siblings want the same target — surfaces a
                  problem the user should resolve manually
    """
    header = "DRY RUN — no changes" if dry_run else "EXECUTING RENAMES"
    print(f"\n=== {header} ===\n")
    # Index events by src for the CONFLICT annotation.
    ev_by_src = {e[0]: e for e in summary.get("events", [])}
    for rep in reports:
        if not rep.renames:
            continue
        print(f"  📂 {rep.path}")
        for r in rep.renames:
            src_name = os.path.basename(r.src)
            ev = ev_by_src.get(r.src)
            ev_status = ev[2] if ev else None
            if ev_status == "CONFLICT":
                dst_name = os.path.basename(r.dst)
                print(f"      ⚠ CONFLICT {src_name!r:42s}  → "
                      f"{dst_name!r}  ({ev[3]})")
            elif r.skip:
                print(f"      SKIP   {src_name!r:42s}  — {r.skip_reason}")
            else:
                dst_name = os.path.basename(r.dst)
                print(f"      RENAME {src_name!r:42s}  → "
                      f"{dst_name!r}  ({r.reason})")
        print()
    if summary.get("conflicts"):
        print(f"⚠ {len(summary['conflicts'])} target collisions — "
              "resolve manually before re-running:")
        for t in summary["conflicts"]:
            print(f"    {t}")
        print()
    print(f"renamed: {summary['renamed']}  "
          f"skipped: {summary['skipped']}  "
          f"failed:  {summary['failed']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Normalize multi-unit job folder names to "
                    "'Unit <NUM> <M-D-YY>'. Default = dry run, "
                    "current year only.")
    parser.add_argument(
        "--execute", action="store_true",
        help="Actually perform the renames. Without this flag, the "
             "script only prints what it WOULD do.")
    parser.add_argument(
        "--base-dir", default=None,
        help="Override the audit base. Defaults to config.audit_base.")
    parser.add_argument(
        "--year", default="current",
        help="'current' (default — only walks this year's Jobs "
             "folder), 'all' (every year), or a specific year like "
             "'2026'. Historical years are closed-out and almost "
             "never the right cleanup target.")
    args = parser.parse_args(argv)

    base = args.base_dir
    if not base:
        try:
            import config
            base = config.load().get("audit_base") or ""
        except Exception:
            base = ""
    if not base:
        print("ERROR: no audit_base configured (run Settings first)",
              file=sys.stderr)
        return 2

    # Resolve the year filter once. 'all' becomes None (no filter);
    # 'current' becomes today's year; bare digits become that year.
    year_arg = (args.year or "current").strip().lower()
    if year_arg == "all":
        year_filter = None
    elif year_arg == "current":
        year_filter = datetime.today().year
    else:
        try:
            year_filter = int(year_arg)
        except ValueError:
            print(f"ERROR: --year must be 'current', 'all', or a "
                  f"4-digit year, got {args.year!r}", file=sys.stderr)
            return 2

    reports = find_multi_unit_properties(base, year_filter=year_filter)
    if not reports:
        print(f"No multi-unit properties found under {base!r}")
        return 0

    all_renames: list[Rename] = []
    for rep in reports:
        rep.renames = propose_renames_for(rep.path)
        all_renames.extend(rep.renames)

    summary = execute_renames(all_renames, dry_run=not args.execute)
    _print_report(reports, summary, dry_run=not args.execute)
    return 0


if __name__ == "__main__":
    sys.exit(main())
