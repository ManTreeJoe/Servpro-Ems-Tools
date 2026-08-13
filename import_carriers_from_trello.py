"""Fill in `jobs.carrier` from the pinned Trello cards.

The carrier has always been on the card — INSURANCE INFORMATION →
INSURANCE COMPANY — and nothing ever copied it into the job index.
`backfill_carriers.py` is a different job: it canonicalises spellings
ALREADY stored. This is what puts them there in the first place.

Measured before writing this: of one day's 13 run-doc jobs, 9 cards
carried a carrier and 1 job row had one. Across the book, 197 of 437
rows were blank — not unknown, just never imported.

Writes through `ems_db`, NOT sqlite directly, so it lands in whichever
backend is live. `backfill_carriers.py` predates the Supabase backend and
writes to the local file; doing that here would fill a mirror the app
isn't reading.

Blank rows only, unless you ask otherwise: a stored carrier may have been
corrected by hand, and the card is not automatically righter than a
person. `--overwrite` re-imports everything.

Dry-run by default. Nothing is written without `--apply`.

    python import_carriers_from_trello.py              # show the plan
    python import_carriers_from_trello.py --apply      # write it
    python import_carriers_from_trello.py --limit 20   # try a few first
"""

import argparse
import collections
import sys

import carriers
import ems_db
import persistence
import trello_client as tc


def _card_ids():
    """[(canon_key, card_id)] for every pinned job."""
    try:
        pins = persistence._load().get("trello_card_ids") or {}
    except Exception:
        return []
    out = []
    for key, val in (pins or {}).items():
        cid = ""
        if isinstance(val, list) and val:
            cid = str(val[0] or "")
        elif isinstance(val, str):
            cid = val
        if key and cid:
            out.append((key, cid))
    return out


def carrier_on_card(card):
    """The card's stated carrier, canonicalised. "" when it has none."""
    try:
        fields = tc.parse_card_desc((card or {}).get("desc") or "") or {}
    except Exception:
        return ""
    ins = fields.get("INSURANCE INFORMATION") or {}
    raw = (ins.get("INSURANCE COMPANY") or ins.get("CARRIER") or "").strip()
    return carriers.normalize(raw) if raw else ""


def plan(*, overwrite=False, limit=0, progress=None):
    """[(canon_key, display_name, old, new)] for rows that would change."""
    changes, skipped, unpinned = [], 0, 0
    pairs = _card_ids()
    if limit:
        pairs = pairs[:limit]
    for i, (key, cid) in enumerate(pairs, 1):
        if progress:
            progress(i, len(pairs))
        # get_job is an exact canon_key hit; a pin is often keyed by the
        # run-doc spelling while the job row carries the Trello card's
        # name. Fall back to the resolver, which follows aliases — on a
        # 25-card sample that was the difference between 8 rows found and
        # 25.
        job = ems_db.get_job(key) or {}
        if not job:
            try:
                job = ems_db.find_job_by_name(key) or {}
            except Exception:
                job = {}
        if not job:
            unpinned += 1
            continue
        old = (job.get("carrier") or "").strip()
        if old and not overwrite:
            skipped += 1
            continue
        try:
            card = tc.get_card(cid, actions_limit=0) or {}
        except Exception:
            continue          # a card we can't read is not a reason to stop
        new = carrier_on_card(card)
        if new and new != old:
            changes.append((key, job.get("display_name") or key, old, new))
    return changes, skipped, unpinned


def apply(changes):
    """Write through ems_db so the active backend gets it."""
    written = 0
    for _key, display_name, _old, new in changes:
        try:
            ems_db.upsert_job(display_name=display_name, carrier=new)
            written += 1
        except Exception as ex:
            print(f"  ! {display_name}: {type(ex).__name__}: {ex}")
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="write the changes (default is a dry run)")
    ap.add_argument("--overwrite", action="store_true",
                    help="also replace carriers already stored")
    ap.add_argument("--limit", type=int, default=0,
                    help="only look at the first N pinned cards")
    args = ap.parse_args(argv)

    def _tick(i, n):
        if i == 1 or i % 25 == 0 or i == n:
            print(f"  reading card {i}/{n}…", flush=True)

    print("Reading pinned Trello cards (one API call each)…")
    changes, skipped, unpinned = plan(overwrite=args.overwrite,
                                      limit=args.limit, progress=_tick)
    print()
    if skipped:
        print(f"{skipped} row(s) already have a carrier — left alone "
              f"(use --overwrite to replace).")
    if unpinned:
        print(f"{unpinned} pinned card(s) have no job row.")
    if not changes:
        print("Nothing to fill in.")
        return 0

    counts = collections.Counter(new for _k, _d, _o, new in changes)
    print(f"\n{len(changes)} job(s) would gain a carrier:")
    for name, n in counts.most_common():
        print(f"  {n:4}  {name}")
    print("\nfirst few:")
    for _k, disp, old, new in changes[:10]:
        print(f"  {disp[:38]:38}  {old or '(blank)'!r} -> {new!r}")

    if not args.apply:
        print("\nDry run. Re-run with --apply to write.")
        return 0

    written = apply(changes)
    print(f"\nWrote {written} of {len(changes)} row(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
