"""Fill the job record from the Trello cards that already hold it.

    python backfill_job_facts.py --dry        # report, write nothing
    python backfill_job_facts.py              # write
    python backfill_job_facts.py --limit 20   # try a handful first

`job_settings` has always been able to parse the job facts out of a
Trello card description — customer, adjuster, carrier, claim number,
date of loss, XA id, WorkCenter project id. Nothing ever ran it in bulk,
so exactly ONE job of 418 had any of them stored while ~300 pinned cards
sat there holding the data.

This reads each carded job's description, parses it, and writes the
schema-v6 columns.

Deliberately conservative:

  * It only ever FILLS BLANKS. An existing non-blank value is never
    overwritten, because the Hub value may have been corrected by hand
    and the card is not automatically more right. `upsert_job` enforces
    the same rule, so this is belt and braces.
  * It does not touch the card. Nothing is pushed back to Trello — this
    is a read.
  * It does not set `trello_base` (the 3-way merge baseline). Recording
    a baseline we never pushed would make the next real save read the
    card's value as already-agreed and silently drop a genuine edit.
"""
import argparse
import sys
import time

import ems_db
import job_settings


def _card_desc(card_id):
    import trello_client as tc
    card = tc.get_card(card_id, actions_limit=0) or {}
    return card.get("desc") or ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true",
                    help="report what would change, write nothing")
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after N jobs (smoke test)")
    args = ap.parse_args()

    jobs = list(ems_db.iter_jobs())
    carded = []
    for j in jobs:
        cid = ems_db.get_link(j["canon_key"], ems_db.LINK_TRELLO)
        if cid:
            carded.append((j, cid))
    if args.limit:
        carded = carded[:args.limit]

    print(f"{len(jobs)} jobs, {len(carded)} with a Trello card"
          + (f" (limited to {len(carded)})" if args.limit else ""))
    print("DRY RUN — nothing will be written\n" if args.dry else "")

    cols = sorted(set(job_settings.COLUMN_FIELDS.values()))
    filled = {c: 0 for c in cols}
    changed_jobs = no_change = failed = 0
    t0 = time.perf_counter()

    for i, (job, card_id) in enumerate(carded, 1):
        name = job.get("display_name") or job["canon_key"]
        try:
            desc = _card_desc(card_id)
        except Exception as ex:
            failed += 1
            print(f"  [{i}/{len(carded)}] {name}: card read failed — "
                  f"{type(ex).__name__}: {ex}")
            continue
        if not desc.strip():
            no_change += 1
            continue

        # from_card also derives xa_id out of the XactAnalysis URL when the
        # card carries no explicit one, so that column fills for free.
        parsed = job_settings.from_card(desc)
        updates = {}
        for fid, col in job_settings.COLUMN_FIELDS.items():
            val = (parsed.get(fid) or "").strip()
            if not val:
                continue
            if (job.get(col) or "").strip():
                continue                      # never overwrite
            updates[col] = val

        if not updates:
            no_change += 1
            continue

        changed_jobs += 1
        for col in updates:
            filled[col] += 1
        if args.dry:
            shown = ", ".join(f"{k}={v[:26]!r}" for k, v in
                              sorted(updates.items())[:4])
            more = f" (+{len(updates) - 4} more)" if len(updates) > 4 else ""
            print(f"  [{i}/{len(carded)}] {name}: {shown}{more}")
        else:
            try:
                ems_db.upsert_job(display_name=name, **updates)
            except Exception as ex:
                failed += 1
                changed_jobs -= 1
                print(f"  [{i}/{len(carded)}] {name}: write failed — "
                      f"{type(ex).__name__}: {ex}")
                continue
        if not args.dry and i % 25 == 0:
            print(f"  …{i}/{len(carded)}")

    dt = time.perf_counter() - t0
    print(f"\n{'would fill' if args.dry else 'filled'} "
          f"{changed_jobs} job(s) · {no_change} already complete or blank "
          f"· {failed} failed · {dt:.0f}s")
    print("\nper column:")
    for col in cols:
        if filled[col]:
            print(f"   {col:16} {filled[col]}")
    return 1 if failed and not changed_jobs else 0


if __name__ == "__main__":
    raise SystemExit(main())
