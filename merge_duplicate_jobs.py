"""Merge the duplicate job rows left behind by the folder rename.

The index holds pairs like `Cross, Heather  - AAA` and `cross heather`:
the same loss, entered twice under two spellings. The properly-named row
carries the Trello card, the lowercase one carries the folder — so no
single row has both, and whichever one a tool happens to resolve decides
whether it can find the card or the photos.

Survivor is the row with the Trello card, then the one written
`Last, First`, then the longer name. The card is the part that cannot be
recreated by hand.

    python merge_duplicate_jobs.py            # show the plan, write nothing
    python merge_duplicate_jobs.py --apply    # do it, capturing undo

Every merge is captured for undo (see job_undo). The undo ids are written
to merge_undo.jsonl one line at a time, so a run that dies halfway is
still fully reversible.
"""
import collections
import io
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import ems_db                      # noqa: E402
import ems_db_common as C          # noqa: E402
import supabase_client as sb       # noqa: E402

_STOP = {"and", "the", "of", "llc", "inc"}
UNDO_LOG = os.path.join(_HERE, "merge_undo.jsonl")


def _tokens(s):
    s = re.sub(r"[^a-z0-9& ]+", " ", (s or "").lower())
    return frozenset(t for t in s.split() if len(t) > 1 and t not in _STOP)


_CLAIM_RE = re.compile(r"\b(\d+)\s*(?:st|nd|rd|th)\s+claim\b", re.I)


def claim_evidence(names, folders):
    """Why this group may be SEPARATE CLAIMS rather than one job twice.

    Same-name-different-claim is the failure this whole effort keeps
    running into: `canon_key` strips at " - ", so every claim of a client
    collapses to one key and two genuinely different losses look like a
    duplicate. Merging them is not a tidy-up, it is data loss — one
    client's second claim absorbing the first.

    Returns a reason string, or "" if nothing objects.
    """
    marked = {n: _CLAIM_RE.search(n).group(1) for n in names
              if _CLAIM_RE.search(n)}
    for f in folders:
        try:
            kids = [d for d in os.listdir(f)
                    if os.path.isdir(os.path.join(f, d))
                    and _CLAIM_RE.search(d)]
        except OSError:
            continue
        if len(kids) > 1:
            return (f"the folder holds {len(kids)} claim subfolders "
                    f"({', '.join(sorted(kids))}) — this is a client with "
                    f"several claims, not a duplicate row")
    if marked:
        return (f"named for a specific claim ({', '.join(sorted(set(marked.values())))}), "
                f"so another claim exists that this row is not")
    return ""


def _load():
    jobs = sb.rest("GET", "jobs", params={
        "select": "canon_key,display_name", "limit": "5000"}) or []
    links = sb.rest("GET", "job_links", params={
        "select": "canon_key,link_type,link_value", "limit": "20000"}) or []
    by = collections.defaultdict(lambda: collections.defaultdict(list))
    for h in links:
        by[h["canon_key"]][h["link_type"]].append(h["link_value"])
    return jobs, by


def plan():
    """Groups of rows that are the same job. Reads only."""
    jobs, by = _load()

    def score(j):
        l = by[j["canon_key"]]
        return (1 if l.get("trello_card") else 0,
                1 if "," in (j["display_name"] or "") else 0,
                len(j["display_name"] or ""))

    groups = collections.defaultdict(list)
    for j in jobs:
        t = _tokens(C.canon_key(j["display_name"] or ""))
        if t:
            groups[t].append(j)

    out = []
    for v in groups.values():
        if len(v) < 2:
            continue
        ranked = sorted(v, key=score, reverse=True)
        keep, lose = ranked[0], ranked[1:]
        names = [x["display_name"] for x in ranked]
        folders = [f for x in ranked
                   for f in (by[x["canon_key"]].get("folder_path") or [])
                   if os.path.isdir(f)]
        out.append({
            "into": keep["canon_key"], "into_name": keep["display_name"],
            "from": [x["canon_key"] for x in lose],
            "from_names": [x["display_name"] for x in lose],
            "links": {k: len(v2) for k, v2 in by[keep["canon_key"]].items()},
            "hold": claim_evidence(names, folders),
        })
    return out, by


def main():
    apply = "--apply" in sys.argv
    rows, by = plan()

    def desc(k):
        l = by.get(k) or {}
        return " ".join(f"{t.split('_')[0]}={len(v)}"
                        for t, v in sorted(l.items())) or "no links"

    go = [p for p in rows if not p["hold"]]
    held = [p for p in rows if p["hold"]]

    print(f"{len(go)} duplicate job pair(s) to merge\n")
    for p in go:
        print(f"  KEEP  {p['into_name']!r:<46} {desc(p['into'])}")
        for k, n in zip(p["from"], p["from_names"]):
            print(f"  merge {n!r:<46} {desc(k)}")
        print()

    if held:
        print(f"HELD BACK — not duplicates ({len(held)}):\n")
        for p in held:
            print(f"  {p['into_name']!r}")
            for n in p["from_names"]:
                print(f"    + {n!r}")
            print(f"    -> {p['hold']}\n")

    if not apply:
        print("Nothing written. Re-run with --apply to merge.")
        return 0

    done, failed = 0, []
    with io.open(UNDO_LOG, "a", encoding="utf-8") as log:
        for p in go:
            try:
                res = ems_db.merge_jobs(p["into"], p["from"], undo=True,
                                        note="duplicate job rows, "
                                             "pre-rename twins")
                uid = res.get("undo_id") if isinstance(res, dict) else None
                # Flushed per merge: a run that dies halfway must still be
                # fully reversible.
                log.write(json.dumps({"into": p["into"], "from": p["from"],
                                      "undo_id": uid}) + "\n")
                log.flush()
                print(f"  merged -> {p['into_name']!r}   undo={uid}")
                done += 1
            except Exception as ex:
                failed.append((p["into"], f"{type(ex).__name__}: {ex}"))
                print(f"  FAILED {p['into_name']!r}: {ex}")

    print(f"\nmerged {done}, failed {len(failed)}")
    print(f"undo ids -> {UNDO_LOG}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
