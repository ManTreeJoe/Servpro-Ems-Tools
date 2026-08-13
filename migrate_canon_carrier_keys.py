"""Re-key jobs stranded by the old carrier-suffix rule.

`canon_key` used to strip a no-space carrier suffix only when the carrier
was a SINGLE word, so "Smith, John- AAA" folded but "Smith, John- State
Farm" did not — and most carriers are two words. Those rows are keyed on
the un-stripped spelling, which the fixed `canon_key` will never compute
again: the job is unreachable by its own display name, and the next
upsert quietly creates a SECOND row for the same insured.

This walks `jobs`, recomputes each key from `display_name`, and moves any
row whose key changed. Column values are copied across FIRST, because
`merge_jobs` moves aliases, links and events but NOT fields — folding
without the copy silently blanks carrier, claim number and the rest.

Dry-run by default. `--apply` backs the database up and then commits.

    python migrate_canon_carrier_keys.py
    python migrate_canon_carrier_keys.py --apply
"""
import argparse
import datetime as _dt
import shutil
import sqlite3
import sys

import ems_db_sqlite as db
from ems_db_common import canon_key


def _plan(con):
    """Return (moves, collisions) without touching anything.

    A move is safe only when the new key is free. A collision means two
    real jobs would share one key — that is a MERGE decision about which
    row wins, not a re-key, so it is reported and skipped rather than
    guessed at.
    """
    rows = con.execute("SELECT canon_key, display_name FROM jobs").fetchall()
    keys = {r["canon_key"] for r in rows}
    moves, collisions = [], []
    for r in rows:
        old = r["canon_key"]
        name = r["display_name"] or old
        new = canon_key(name)
        if not new or new == old:
            continue
        (collisions if new in keys else moves).append((old, new, name))
    return moves, collisions


def _copy_row(con, old, new):
    """Duplicate a job row under `new`, carrying EVERY column.

    Built from PRAGMA table_info rather than a hand-written column list so
    a schema change (v6 added several) can't silently drop a field here.
    """
    cols = [c["name"] for c in con.execute("PRAGMA table_info(jobs)")]
    if "canon_key" not in cols:
        raise RuntimeError("jobs table has no canon_key column")
    sel = ", ".join("?" if c == "canon_key" else f'"{c}"' for c in cols)
    con.execute(
        f'INSERT OR IGNORE INTO jobs ({", ".join(chr(34) + c + chr(34) for c in cols)}) '
        f"SELECT {sel} FROM jobs WHERE canon_key = ?",
        (new, old))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="commit the changes (default is a dry run)")
    args = ap.parse_args(argv)

    con = sqlite3.connect(db.DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        moves, collisions = _plan(con)
    finally:
        con.close()

    print(f"database: {db.DB_PATH}")
    print(f"rows to re-key: {len(moves)}")
    for old, new, name in moves:
        print(f"  {name!r}\n      {old!r}  ->  {new!r}")
    if collisions:
        print(f"\nSKIPPED — target key already belongs to another job "
              f"({len(collisions)}). These need a merge decision, not a "
              f"re-key; fold them by hand with ems_db.merge_jobs:")
        for old, new, name in collisions:
            print(f"  {name!r}: {old!r} -> {new!r}")
    if not moves:
        print("\nnothing to do")
        return 0
    if not args.apply:
        print("\nDRY RUN — re-run with --apply to commit")
        return 0

    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = f"{db.DB_PATH}.{stamp}.bak"
    shutil.copy2(db.DB_PATH, backup)
    print(f"\nbackup: {backup}")

    # Copy the columns across first, in one transaction. merge_jobs opens
    # its own connection, so this one is closed before it runs.
    con = sqlite3.connect(db.DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        with con:
            for old, new, _ in moves:
                _copy_row(con, old, new)
    finally:
        con.close()

    # Now fold the stale key into the fresh one: aliases, links and the
    # event history move, the old row goes away.
    done = 0
    for old, new, name in moves:
        res = db.merge_jobs(new, [old])
        done += int(res.get("merged") or 0)
        print(f"  moved {name!r}")

    con = sqlite3.connect(db.DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        left, _ = _plan(con)
    finally:
        con.close()
    print(f"\nre-keyed {done} job(s); {len(left)} still stale")
    return 0 if not left else 1


if __name__ == "__main__":
    sys.exit(main())
