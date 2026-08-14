"""Split a job row that reconcile folded several real jobs into.

`reconcile_jobs` (2026-07-22) collapsed duplicate spellings onto one row.
Where the "duplicates" were actually different UNITS of one property it
folded distinct jobs together: `avila apartments- unit 226` ended up
holding 12 Trello cards — units 226, 516 x2, 526 x2, 527, 2216, 1413,
1416, 1017, 2413, plus the board's blank template card — and a folder
link pointing at Unit 1413's folder. Every one of those cards resolves to
the same job, so a pin, an import or a comment aimed at one unit lands on
another.

The card NAME says which unit it is, so the split is derivable rather
than guessed: each card goes to the job its own name canonicalizes to,
creating that job when it doesn't exist yet. A folder link moves with it
when the folder's name matches the unit.

Dry-run by default. `--apply` writes a JSON backup of every link it
touches first, so the whole thing can be put back with `--undo`.

    python repair_conflated_job.py "avila apartments- unit 226"
    python repair_conflated_job.py "avila apartments- unit 226" --apply
    python repair_conflated_job.py --undo repair_<stamp>.json
"""
import argparse
import datetime as _dt
import io
import json
import os
import re
import sys

import ems_db
import paths as _paths
import trello_client as tc
from ems_db_common import canon_key

# "(Unit #)" / "(Date Recieved)" — the board's blank template, cloned for
# each new loss. It is not a job and must not become one.
_TEMPLATE_RE = re.compile(r"\(\s*unit\s*#|\(\s*date\s+reci?e?ived", re.I)

_UNIT_RE = re.compile(r"(\d{3,4})")


def _unit_of(name):
    """The unit number a card or folder name carries, or ""."""
    m = _UNIT_RE.search(str(name or ""))
    return m.group(1) if m else ""


def plan(source_key):
    """What the split would do. Reads only."""
    cards = [l["link_value"]
             for l in (ems_db.get_links(source_key, ems_db.LINK_TRELLO) or [])]
    folders = [l["link_value"]
               for l in (ems_db.get_links(source_key, ems_db.LINK_FOLDER) or [])]
    src = ems_db.get_job(source_key) or {}
    src_name = src.get("display_name") or source_key

    moves, skipped = [], []
    for cid in cards:
        card = tc.get_card_lite(cid) or {}
        cname = (card.get("name") or "").strip()
        if not cname:
            skipped.append((cid, "card unreadable — left where it is"))
            continue
        if _TEMPLATE_RE.search(cname):
            skipped.append((cid, f"{cname!r} is the blank template card"))
            continue
        target = canon_key(cname)
        if not target or target == source_key:
            skipped.append((cid, f"{cname!r} already belongs to this job"))
            continue
        unit = _unit_of(cname)
        folder = ""
        for f in folders:
            base = os.path.basename(f.rstrip("\\/"))
            if unit and _unit_of(base) == unit:
                folder = f
                break
        moves.append({"card": cid, "card_name": cname, "target": target,
                      "unit": unit, "folder": folder,
                      "exists": bool(ems_db.get_job(target))})
    return {"source": source_key, "source_name": src_name,
            "moves": moves, "skipped": skipped, "folders": folders}


def _backup_path(stamp):
    return os.path.join(_paths.data(""), f"repair_{stamp}.json")


def apply(p):
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    undo = {"source": p["source"], "moves": []}
    for m in p["moves"]:
        # Create the per-unit job before moving anything onto it.
        # No `source=` — upsert_job takes CRM columns through **crm and
        # the Supabase backend rejects anything not in CRM_COLUMNS. The
        # provenance goes on the LINKS via added_by instead.
        if not m["exists"]:
            ems_db.upsert_job(display_name=m["card_name"])
        ems_db.set_link(m["target"], ems_db.LINK_TRELLO, m["card"],
                        added_by="repair")
        ems_db.remove_link(p["source"], ems_db.LINK_TRELLO, m["card"])
        rec = {"card": m["card"], "target": m["target"], "folder": ""}
        if m["folder"]:
            ems_db.set_link(m["target"], ems_db.LINK_FOLDER, m["folder"],
                            added_by="repair")
            ems_db.remove_link(p["source"], ems_db.LINK_FOLDER, m["folder"])
            rec["folder"] = m["folder"]
        undo["moves"].append(rec)
        print(f"  moved {m['card_name']!r} -> {m['target']!r}")
    path = _backup_path(stamp)
    io.open(path, "w", encoding="utf-8").write(json.dumps(undo, indent=2))
    print(f"\nundo file: {path}")
    return path


def undo(path):
    data = json.loads(io.open(path, encoding="utf-8").read())
    src = data["source"]
    for m in data["moves"]:
        ems_db.set_link(src, ems_db.LINK_TRELLO, m["card"], added_by="undo")
        ems_db.remove_link(m["target"], ems_db.LINK_TRELLO, m["card"])
        if m.get("folder"):
            ems_db.set_link(src, ems_db.LINK_FOLDER, m["folder"],
                            added_by="undo")
            ems_db.remove_link(m["target"], ems_db.LINK_FOLDER, m["folder"])
        print(f"  put {m['card']} back on {src!r}")
    return len(data["moves"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", nargs="?", help="canon_key of the tangled job")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--undo", metavar="FILE")
    args = ap.parse_args(argv)

    if args.undo:
        print(f"undoing {args.undo}")
        print(f"restored {undo(args.undo)} link(s)")
        return 0
    if not args.source:
        ap.error("give a canon_key (or --undo FILE)")

    p = plan(args.source)
    print(f"source: {p['source']!r}  ({p['source_name']})")
    print(f"cards to move: {len(p['moves'])}\n")
    for m in p["moves"]:
        mark = "" if m["exists"] else "  [creates job]"
        print(f"  {m['card_name']!r}")
        print(f"      -> {m['target']!r}{mark}")
        if m["folder"]:
            print(f"      folder: {m['folder']}")
    if p["skipped"]:
        print("\nleft alone:")
        for cid, why in p["skipped"]:
            print(f"  {cid}: {why}")
    if not p["moves"]:
        print("\nnothing to do")
        return 0
    if not args.apply:
        print("\nDRY RUN — re-run with --apply")
        return 0
    print()
    apply(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
