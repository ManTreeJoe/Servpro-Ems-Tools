"""Create the missing CLIENT rows that `job_children` rows point at.

`backfill_children.py` writes a child row for every job folder nested
inside a client folder. Nothing guarantees the CLIENT itself has a row in
`jobs`, though: job rows are born from Trello cards, and an umbrella
client usually has no card of its own — only its claims and units do. On
live data that left 75 of 115 child rows (65%) pointing at a parent that
does not exist.

SQLite never noticed because it does not enforce the foreign key. Postgres
does, so those 75 rows cannot be migrated until their parents exist.

This is the canonical shape from `reference_job_hierarchy`: year -> client
-> claim/unit, where the client is ONE jobs row and each child carries its
own folder and card.

Deliberately ADDITIVE — it inserts client rows and nothing else:

  * it never merges, reparents, or deletes. Several of these clients also
    have a UNIT registered as a top-level job ('avila apartments 1017'
    alongside the umbrella 'avila apartments 2026'). Folding those into
    children is the umbrella redesign's job, needs human judgment, and is
    not made harder by the parent existing first.
  * the parent folder comes from `dirname(child.folder_path)` — disk is
    the authority, same rule as jobs.department. A parent whose folder is
    gone, or whose children disagree about where it is, is reported and
    skipped rather than guessed at.

    python backfill_parent_jobs.py --dry    # report only
    python backfill_parent_jobs.py          # apply (backs the DB up first)
"""
import argparse
import os
import shutil
import sqlite3
import sys
import time

import ems_db
import ems_db_sqlite


def find_missing_parents():
    """Return (ready, problems). `ready` rows are safe to create."""
    con = sqlite3.connect(ems_db_sqlite.DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT ch.parent_canon, COUNT(*) AS n, "
            "       GROUP_CONCAT(ch.folder_path, char(10)) AS fps "
            "FROM job_children ch "
            "LEFT JOIN jobs j ON j.canon_key = ch.parent_canon "
            "WHERE j.canon_key IS NULL "
            "GROUP BY ch.parent_canon ORDER BY ch.parent_canon").fetchall()
    finally:
        con.close()

    ready, problems = [], []
    for r in rows:
        dirs = {os.path.dirname(p) for p in (r["fps"] or "").split("\n") if p}
        live = sorted(d for d in dirs if os.path.isdir(d))
        if len(dirs) != 1 or not live:
            problems.append({
                "parent_canon": r["parent_canon"], "children": r["n"],
                "reason": ("children disagree on the parent folder"
                           if len(dirs) != 1 else "parent folder is gone"),
                "dirs": sorted(dirs),
            })
            continue
        folder = live[0]
        ready.append({
            "parent_canon": r["parent_canon"],
            "children": r["n"],
            "display_name": os.path.basename(folder),
            "folder": folder,
            "department": ems_db.department_for_path(folder) or "",
        })
    return ready, problems


def _year_of(folder):
    """Year folder name -> int, e.g. '.../2026 EMS Files/Smith' -> 2026."""
    for part in os.path.normpath(folder).split(os.sep):
        head = part[:4]
        if head.isdigit() and 2000 <= int(head) <= 2100:
            return int(head)
    return None


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry", action="store_true", help="report only")
    args = ap.parse_args(argv)

    ready, problems = find_missing_parents()

    print(f"{len(ready)} client row(s) to create, covering "
          f"{sum(r['children'] for r in ready)} orphaned child rows:\n")
    for r in ready:
        dept = r["department"] or "-"
        print(f"   {dept:3} {r['display_name'][:38]:40} "
              f"{r['children']:>2} child(ren)")

    if problems:
        print(f"\n{len(problems)} parent(s) SKIPPED — disk cannot confirm "
              f"where they live:")
        for p in problems:
            print(f"   {p['parent_canon'][:34]:36} {p['reason']}")

    if args.dry:
        print("\n--dry: nothing written.")
        return 0
    if not ready:
        print("\nNothing to do.")
        return 0

    backup = (f"{ems_db_sqlite.DB_PATH}.bak_"
              f"{time.strftime('%Y%m%d_%H%M%S')}_parents")
    shutil.copy2(ems_db_sqlite.DB_PATH, backup)
    print(f"\nbackup -> {os.path.basename(backup)}")

    created = 0
    for r in ready:
        key = ems_db.upsert_job(display_name=r["display_name"],
                                year=_year_of(r["folder"]),
                                department=r["department"])
        if key != r["parent_canon"]:
            # canon_key is derived from the display name, so this should be
            # an identity. If it is not, the child rows would still be
            # orphans — say so instead of leaving a silent mismatch.
            print(f"   !! {r['display_name'][:34]:36} created as {key!r}, "
                  f"children point at {r['parent_canon']!r}")
            continue
        ems_db.set_link(key, ems_db.LINK_FOLDER, r["folder"],
                        added_by="backfill_parent_jobs")
        created += 1

    print(f"client rows created: {created}")

    _, still = find_missing_parents()
    remaining = sum(p["children"] for p in still)
    print(f"orphaned child rows remaining: {remaining}")
    print("\nRollback = restore the .bak file above.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
