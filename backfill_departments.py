"""Stamp `jobs.department` on the shared job index (ems_jobs.db).

A job's owning franchise is derived from its folder root, matched against
each department's configured `audit_base`. The Trello board is deliberately
ignored: IE currently runs recon for both franchises, so an OC-owned job
legitimately lives on an IE board.

Jobs with no folder link stay NULL — unknown is permissive everywhere, so
they keep resolving exactly as they do today. Jobs whose folders span BOTH
franchises are reported, never guessed at.

    python backfill_departments.py --dry     # report only, no writes
    python backfill_departments.py           # apply (backs up the DB first)

Re-runnable. Existing values are left alone unless --overwrite is passed.
"""
import argparse
import os
import shutil
import sys
import time

import config
import ems_db


def _preview(overwrite):
    """What the backfill would do, without writing."""
    stamped, unknown, already, conflicts = {}, 0, 0, []
    for job in ems_db.iter_jobs():
        key = job["canon_key"]
        if job.get("department") and not overwrite:
            already += 1
            continue
        folders = [l["link_value"]
                   for l in ems_db.get_links(key, ems_db.LINK_FOLDER)]
        depts = {d for d in (ems_db.department_for_path(f) for f in folders)
                 if d}
        if not depts:
            unknown += 1
        elif len(depts) > 1:
            conflicts.append({"display_name": job["display_name"],
                              "departments": sorted(depts),
                              "folders": folders})
        else:
            stamped.setdefault(depts.pop(), []).append(job["display_name"])
    return stamped, unknown, already, conflicts


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry", action="store_true",
                    help="report only; make no changes")
    ap.add_argument("--overwrite", action="store_true",
                    help="also re-derive jobs that already have a department")
    args = ap.parse_args(argv)

    if not config.is_multi_dept():
        print("Multi-department mode is OFF — nothing to stamp.")
        return 0

    print("Department roots (from each department's audit_base):")
    roots = ems_db._department_roots()
    if not roots:
        print("  none configured — set audit_base per department first.")
        return 1
    for key, root in roots:
        print(f"  {key:4} {root}")

    stamped, unknown, already, conflicts = _preview(args.overwrite)
    total = sum(len(v) for v in stamped.values()) + unknown + already \
        + len(conflicts)
    print(f"\n{total} jobs:")
    for k in sorted(stamped):
        print(f"  {k:4} {len(stamped[k]):5}")
    print(f"  {'--':4} {unknown:5}  unknown (no folder pin — stays NULL, "
          f"still resolves normally)")
    if already:
        print(f"  {'==':4} {already:5}  already stamped (use --overwrite to "
              f"re-derive)")
    if conflicts:
        print(f"\n  {len(conflicts)} CONFLICT(S) — folders in both "
              f"franchises, left unstamped for a human:")
        for c in conflicts:
            print(f"    - {c['display_name']}: {c['departments']}")
            for f in c["folders"]:
                print(f"        {f}")

    if args.dry:
        print("\n--dry: nothing written.")
        return 1 if conflicts else 0

    backup = f"{ems_db.DB_PATH}.bak_{time.strftime('%Y%m%d_%H%M%S')}_dept"
    shutil.copy2(ems_db.DB_PATH, backup)
    print(f"\nbackup -> {backup}")

    res = ems_db.backfill_departments(overwrite=args.overwrite)
    print(f"stamped={res['stamped']} already={res['already']} "
          f"unknown={res['unknown']} conflicts={len(res['conflicts'])}")
    print("\nby department now:")
    for k, n in ems_db.count_by_department().items():
        print(f"  {k:8} {n}")

    remaining = ems_db.find_department_conflicts()
    if remaining:
        print(f"\n{len(remaining)} job(s) need a human — folders disagree "
              f"with the stored department:")
        for r in remaining:
            print(f"  - {r['display_name']}: stored={r['stored']} "
                  f"folders={r['folder_departments']}")
        return 1
    print("\nClean. Rollback = restore the .bak file above.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
