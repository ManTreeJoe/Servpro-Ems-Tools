"""Populate `job_children` from the folder tree, and clear the broken
name-inferred parent_canon / unit_number values it replaces.

The hierarchy comes from DISK, never from parsing a name. The old
inference had, on live data, populated 21 rows whose parent did not exist
('store', 'stater bros', 'monterey apartments ga').

Two things this deliberately does NOT do:

  * treat a second folder as a child just because a job has two. Live data
    has 19 such jobs and most are MISSPELLINGS filed twice
    ('abbott darlene' + 'abotte darlene'). Only a folder physically INSIDE
    a client folder becomes a child.
  * bless a mis-pin. 'action property management' is linked to
    'mendiola mary', a different client's folder at the same level. Those
    are reported for a human, not migrated.

    python backfill_children.py --dry      # report only
    python backfill_children.py            # apply (backs the DB up first)
"""
import argparse
import os
import shutil
import sys
import time

import config
import ems_db
import job_folders


def _scan(base="", year=None):
    """Walk the year folder → clients → children. Returns (children, notes)."""
    yd = job_folders.year_dir(base=base, year=year)
    if not yd:
        return [], ["no current-year jobs folder"]
    found, notes = [], []
    try:
        with os.scandir(yd) as it:
            clients = [e for e in it if e.is_dir(follow_symlinks=False)]
    except OSError as ex:
        return [], [f"scan failed: {ex}"]
    for cl in clients:
        for name in job_folders.list_children(cl.path):
            path = os.path.join(cl.path, name)
            if not job_folders._has_job_structure(path):
                # A bare paperwork folder (FIELD DOCS) is not a child job.
                continue
            kind, ordinal = ems_db.classify_child(name)
            found.append({
                "parent_display": cl.name,
                "parent_canon": ems_db.canon_key(cl.name),
                "name": name, "kind": kind, "ordinal": ordinal,
                "folder_path": path,
                "department": ems_db.department_for_path(path) or "",
            })
    return found, notes


def _suspect_pins(base="", year=None):
    """Jobs linked to two or more TOP-LEVEL folders — i.e. the same job
    filed twice, usually under a misspelling.

    Only folders sitting directly in the year folder count. An earlier
    version flagged any job whose linked folders weren't nested in EACH
    OTHER, which wrongly reported every property-management client: PCM's
    three links are siblings of one another but all children of PCM, so
    the nesting was real and simply invisible to that test.
    """
    yd = job_folders.year_dir(base=base, year=year)
    if not yd:
        return []
    yd_norm = os.path.normcase(os.path.normpath(yd))
    out = []
    for job in ems_db.iter_jobs():
        paths = [l["link_value"] for l in
                 ems_db.get_links(job["canon_key"], ems_db.LINK_FOLDER)]
        top = [p for p in paths
               if os.path.normcase(os.path.normpath(os.path.dirname(p)))
               == yd_norm]
        if len(top) < 2:
            continue
        out.append({"canon_key": job["canon_key"],
                    "display_name": job.get("display_name") or "",
                    "folders": [os.path.basename(p) for p in top]})
    return out


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry", action="store_true", help="report only")
    ap.add_argument("--keep-legacy", action="store_true",
                    help="don't clear jobs.parent_canon / unit_number")
    args = ap.parse_args(argv)

    children, notes = _scan()
    for n in notes:
        print("NOTE:", n)

    by_kind = {}
    for ch in children:
        by_kind.setdefault(ch["kind"], []).append(ch)
    print(f"\n{len(children)} child folders found under "
          f"{len({c['parent_canon'] for c in children})} clients:")
    for k in sorted(by_kind):
        print(f"   {k:8} {len(by_kind[k])}")
    for k in sorted(by_kind):
        for ch in by_kind[k][:6]:
            print(f"      {k:7} {ch['parent_display'][:26]:28} / {ch['name']}")
        if len(by_kind[k]) > 6:
            print(f"      … and {len(by_kind[k]) - 6} more")

    suspect = _suspect_pins()
    if suspect:
        print(f"\n{len(suspect)} job(s) with sibling folder links — "
              f"misspellings or mis-pins, NOT migrated:")
        for s in suspect[:12]:
            print(f"   {s['display_name'][:34]:36} {s['folders']}")

    legacy = [j for j in ems_db.iter_jobs()
              if (j.get("parent_canon") or j.get("unit_number"))]
    print(f"\n{len(legacy)} job row(s) still carry the old inferred "
          f"parent_canon / unit_number")

    if args.dry:
        print("\n--dry: nothing written.")
        return 0

    backup = f"{ems_db.DB_PATH}.bak_{time.strftime('%Y%m%d_%H%M%S')}_children"
    shutil.copy2(ems_db.DB_PATH, backup)
    print(f"\nbackup -> {os.path.basename(backup)}")

    written = 0
    for ch in children:
        if ems_db.set_child(ch["parent_canon"], ch["name"], kind=ch["kind"],
                            ordinal=ch["ordinal"],
                            folder_path=ch["folder_path"],
                            department=ch["department"]):
            written += 1
    print(f"job_children rows written: {written}")

    cleared = 0
    if not args.keep_legacy:
        with ems_db._LOCK, ems_db._connect() as c:
            cur = c.execute("UPDATE jobs SET parent_canon=NULL, "
                            "unit_number=NULL WHERE parent_canon IS NOT NULL "
                            "OR unit_number IS NOT NULL")
            cleared = cur.rowcount
            c.commit()
        print(f"legacy parent_canon/unit_number cleared on {cleared} rows")

    print("\nRollback = restore the .bak file above.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
