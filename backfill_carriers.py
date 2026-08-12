"""Canonicalize the carrier spellings already in the job index.

`carriers.normalize` fixes new input at the point it's typed; this
applies the same rule to rows written before it existed. Idempotent —
re-running changes nothing once clean.

Dry-run by default. Nothing is written without `--apply`.

    python backfill_carriers.py            # show what would change
    python backfill_carriers.py --apply    # write it
"""

import argparse
import collections
import shutil
import sqlite3
import sys
from datetime import datetime

import carriers
import ems_db_sqlite as db


def plan():
    """Rows whose stored carrier isn't already canonical.
    Returns [(canon_key, old, new)]."""
    con = sqlite3.connect(db.DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT canon_key, carrier FROM jobs "
            "WHERE carrier IS NOT NULL AND carrier <> ''").fetchall()
    finally:
        con.close()
    out = []
    for r in rows:
        old = (r["carrier"] or "").strip()
        new = carriers.normalize(old)
        if new != old:
            out.append((r["canon_key"], old, new))
    return out


def apply(changes):
    """Write the planned changes. Backs the DB up first — this rewrites a
    column across many rows and there is no undo."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = f"{db.DB_PATH}.pre-carrier-backfill-{stamp}"
    shutil.copy2(db.DB_PATH, backup)
    con = sqlite3.connect(db.DB_PATH)
    try:
        con.executemany("UPDATE jobs SET carrier=? WHERE canon_key=?",
                        [(new, key) for key, _old, new in changes])
        con.commit()
    finally:
        con.close()
    return backup


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="write the changes (default is a dry run)")
    args = ap.parse_args(argv)

    changes = plan()
    if not changes:
        print("Nothing to do — every stored carrier is already canonical.")
        return 0

    counts = collections.Counter((old, new) for _k, old, new in changes)
    print(f"{len(changes)} row(s) would change, "
          f"across {len(counts)} spelling(s):")
    for (old, new), n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:3}  {old!r} -> {new!r}")

    if not args.apply:
        print("\nDry run. Re-run with --apply to write.")
        return 0

    backup = apply(changes)
    print(f"\nWrote {len(changes)} row(s).")
    print(f"Backup: {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
