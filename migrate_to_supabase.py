"""Mirror the local SQLite job index into Supabase.

One-way copy, SQLite -> Supabase, safe to re-run: every table is upserted
on its natural key, so a second run updates in place instead of
duplicating. Run it again whenever the local DB has moved ahead.

Order matters. `job_aliases`, `job_links`, `job_events` and `job_children`
all carry a real foreign key to `jobs` in Postgres (SQLite does not
enforce it), so `jobs` goes first and a child whose parent is missing is
REPORTED, never silently dropped. Run `backfill_parent_jobs.py` first if
that count is not zero.

Two tables have no natural key — `job_events` and `job_stage_transitions`
are identity-PK append logs. Re-upserting them is meaningless, so they are
mirrored: existing rows are deleted, then re-inserted. Their `id` column
is `generated always as identity` and must never be sent.

RLS applies to every write, as the signed-in user. That is the point: a
job whose department you cannot see is refused by the database, not by
this script. `department = ''` is normalised to NULL, because the policy
treats NULL as "unknown, visible to all" but would reject an empty string.

    python migrate_to_supabase.py --dry     # report only, no writes
    python migrate_to_supabase.py           # copy
    python migrate_to_supabase.py --verify  # compare counts only
"""
import argparse
import sqlite3
import sys

import ems_db_sqlite
import supabase_client

# table -> (natural key columns for upsert, or None to mirror by delete+insert)
TABLES = [
    ("jobs",                  ["canon_key"]),
    ("job_aliases",           ["canon_key", "alias_canon"]),
    ("job_links",             ["canon_key", "link_type", "link_value"]),
    ("job_children",          ["parent_canon", "name"]),
    ("job_lifecycle",         ["card_id"]),
    ("job_events",            None),
    ("job_stage_transitions", None),
]

# Identity columns Postgres generates. Sending one is an error, not a hint.
GENERATED = {"id"}

# PostgREST rejects very large bodies and Supabase caps statement time;
# 500 rows/request keeps the 3175-row lifecycle table to 7 round trips.
CHUNK = 500


def _local_rows(table):
    con = sqlite3.connect(ems_db_sqlite.DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(f"SELECT * FROM {table}")]
    finally:
        con.close()


def _clean(table, rows):
    out = []
    for r in rows:
        r = {k: v for k, v in r.items() if k not in GENERATED}
        # '' is not NULL to a WHERE clause. The department policy reads
        # NULL as "unknown, visible to everyone"; an empty string matches
        # no department and the row would be refused on insert.
        if "department" in r and not (r["department"] or "").strip():
            r["department"] = None
        out.append(r)
    return out


def _chunks(rows):
    for i in range(0, len(rows), CHUNK):
        yield rows[i:i + CHUNK]


def _remote_count(table):
    """Count remote rows by paging.

    PostgREST caps a select at `db-max-rows` (1000 on Supabase) and says
    so only in the Content-Range header, which `rest()` does not surface.
    Counting one unpaged response therefore reports 1000 for any larger
    table — job_lifecycle has 3175 — and a migration that worked looks
    like it lost 2175 rows."""
    page, offset = 1000, 0
    total = 0
    while True:
        got = supabase_client.rest(
            "GET", table,
            params={"select": _pk(table), "limit": str(page),
                    "offset": str(offset), "order": _pk(table)})
        total += len(got)
        if len(got) < page:
            return total
        offset += page


def _pk(table):
    keys = dict(TABLES).get(table)
    return keys[0] if keys else "id"


def _orphans():
    """Child rows whose parent job is missing locally — these are exactly
    the rows Postgres will refuse on the foreign key."""
    con = sqlite3.connect(ems_db_sqlite.DB_PATH)
    try:
        out = {}
        for tbl, col in (("job_aliases", "canon_key"),
                         ("job_links", "canon_key"),
                         ("job_events", "canon_key"),
                         ("job_children", "parent_canon")):
            n = con.execute(
                f"SELECT COUNT(*) FROM {tbl} x "
                f"LEFT JOIN jobs j ON j.canon_key = x.{col} "
                f"WHERE j.canon_key IS NULL").fetchone()[0]
            if n:
                out[tbl] = n
        return out
    finally:
        con.close()


def push(table, keys, dry=False):
    rows = _clean(table, _local_rows(table))
    if dry:
        return len(rows), 0

    if keys is None:
        # Append log with a generated id: mirror rather than upsert.
        # `id=gte.0` is PostgREST's "match everything" — a bare DELETE
        # with no filter is refused, by design.
        supabase_client.rest("DELETE", table, params={"id": "gte.0"})
        prefer, params = "return=minimal", None
    else:
        prefer = "resolution=merge-duplicates,return=minimal"
        params = {"on_conflict": ",".join(keys)}

    sent = 0
    for chunk in _chunks(rows):
        supabase_client.rest("POST", table, params=params, body=chunk,
                             prefer=prefer)
        sent += len(chunk)
        print(f"      {sent}/{len(rows)}", end="\r", flush=True)
    return len(rows), sent


def prune(table, keys, apply=False):
    """Remote rows whose natural key no longer exists locally.

    Upserting alone is not a mirror: a row DELETED locally stays remote
    forever. That is how three pruned dead folder links and a removed
    Trello card link survived a "successful" sync and made the counts
    disagree.

    Deleting is opt-in because the remote database is SHARED — a row
    missing locally might be one a colleague added from another machine,
    and local is only authoritative when you know it is. Without --prune
    this just reports.
    """
    local = {tuple(str(r.get(k) or "") for k in keys)
             for r in _clean(table, _local_rows(table))}
    remote_rows, offset = [], 0
    while True:
        got = supabase_client.rest(
            "GET", table, params={"select": ",".join(keys), "limit": "1000",
                                  "offset": str(offset),
                                  "order": ",".join(keys)})
        remote_rows.extend(got)
        if len(got) < 1000:
            break
        offset += 1000

    extra = [r for r in remote_rows
             if tuple(str(r.get(k) or "") for k in keys) not in local]
    if apply:
        for r in extra:
            params = {k: f"eq.{r.get(k)}" for k in keys}
            supabase_client.rest("DELETE", table, params=params)
    return [tuple(r.get(k) for k in keys) for r in extra]


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry", action="store_true", help="report only")
    ap.add_argument("--verify", action="store_true",
                    help="compare local vs remote counts, write nothing")
    ap.add_argument("--prune", action="store_true",
                    help="also DELETE remote rows that no longer exist "
                         "locally (makes remote exactly match local)")
    args = ap.parse_args(argv)

    h = supabase_client.health()
    if not h["configured"]:
        print("Supabase is not configured — set the URL and anon key in "
              "Settings first.")
        return 1
    if not h["signed_in"]:
        print("Not signed in. Sign in from Settings, then re-run.")
        return 1
    print(f"signed in as {h['user']['email']}  ->  "
          f"{supabase_client.creds()[0]}\n")

    if args.verify:
        print(f"{'table':24} {'local':>8} {'remote':>8}")
        bad = 0
        for table, _keys in TABLES:
            local = len(_local_rows(table))
            try:
                remote = _remote_count(table)
            except Exception as ex:
                print(f"{table:24} {local:>8}   ERR {str(ex)[:40]}")
                bad += 1
                continue
            mark = "" if local == remote else "   <-- differs"
            if local != remote:
                bad += 1
            print(f"{table:24} {local:>8} {remote:>8}{mark}")
        return 1 if bad else 0

    orphans = _orphans()
    if orphans:
        print("Child rows whose parent job does not exist locally — "
              "Postgres will refuse these:")
        for tbl, n in orphans.items():
            print(f"   {tbl:22} {n}")
        print("Run `python backfill_parent_jobs.py` first.\n")
        if not args.dry:
            return 1

    total = 0
    for table, keys in TABLES:
        how = "mirror" if keys is None else f"upsert on {','.join(keys)}"
        print(f"{table:24} {how}")
        n, sent = push(table, keys, dry=args.dry)
        total += sent
        print(f"   {'would send' if args.dry else 'sent'} {n if args.dry else sent}"
              f" row(s)          ")
        if keys and not args.dry:
            gone = prune(table, keys, apply=args.prune)
            if gone:
                verb = "deleted" if args.prune else "remote-only (use --prune)"
                print(f"   {len(gone)} {verb}")
                for g in gone[:5]:
                    print(f"      {g}")

    if args.dry:
        print("\n--dry: nothing written.")
        return 0

    print(f"\n{total} row(s) written. Verifying…\n")
    return main(["--verify"])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
