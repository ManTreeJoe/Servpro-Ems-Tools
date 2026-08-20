"""Teach the index the folder names it already can't see.

The office writes folders "Last First"; Trello and the database write
"Last, First". `canon_key` keeps the comma, so those are two different
identities and 521 of 624 client folders on the share resolve to no job
at all. 166 of them match a real job the moment you stop caring about
punctuation and word order.

The tempting fix — loosen `canon_key` — is the wrong one, and the data
says so itself:

    'Menifee Union School District -Callie Kirkpatrick Elementary - 6/9/26 - Room 33'
    'Menifee Union School District (Callie Kirkpatrick Elementary) - 6/30/26 - Room 34'

Punctuation- and order-insensitive matching calls those the same job.
They are two rooms on two dates. Loosening canonicalisation would fix 166
lookups and silently fold apart-jobs together across all 464 rows at
once — trading a visible problem for an invisible one.

So identity is left alone and the ALIAS table does the work, which is
what it is for. Each folder name becomes an alias of the job it belongs
to, plus a folder_path link. Additive, individually reversible, and
inspectable afterwards.

Ambiguous folders — where the loose form matches more than one job — are
never guessed. They are printed for a human, because that is exactly the
class of mistake this whole effort is undoing.

    python backfill_folder_aliases.py              # dry run (default)
    python backfill_folder_aliases.py --apply
    python backfill_folder_aliases.py --dupes      # duplicate job pairs
"""
import argparse
import os
import re
import sys
from collections import defaultdict

import ems_db
import job_folders as jf
import job_undo
from ems_db_common import canon_key


def loose(s: str) -> str:
    """Identity with the punctuation and word order taken out.

    Used ONLY for matching, never for storage — see the module docstring
    for why this must not become `canon_key`.
    """
    s = canon_key(s or "")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return " ".join(sorted(s.split()))


def _jobs_by_loose():
    out = defaultdict(list)
    names = {}
    for j in ems_db.iter_jobs():
        k = j.get("canon_key")
        nm = j.get("display_name") or ""
        if not k:
            continue
        names[k] = nm
        out[loose(nm)].append(k)
        # A job is also findable by its own key, which is not always the
        # canonicalisation of its display name (renames, folds).
        if loose(k) != loose(nm):
            out[loose(k)].append(k)
    return out, names


def _folder_owners():
    """{lowercased folder path: {canon_key, ...}} — in ONE read.

    The obvious version calls get_links() per job. That is 464 network
    round trips against Supabase and turns a two-second dry run into a
    two-minute one, so the shared backend gets a single bulk select and
    everything else falls back to the per-job loop.
    """
    owner = {}

    def _add(key, value):
        v = (value or "").rstrip("\\/").lower()
        if v and key:
            owner.setdefault(v, set()).add(key)

    try:
        if ems_db.backend_name() == "supabase":
            import ems_db_supabase as _sb
            for l in _sb._rows("job_links",
                               link_type=f"eq.{ems_db.LINK_FOLDER}",
                               select="canon_key,link_value"):
                _add(l.get("canon_key"), l.get("link_value"))
            return owner
    except Exception:
        owner.clear()                      # fall through to the slow path

    for j in ems_db.iter_jobs():
        k = j.get("canon_key")
        try:
            for l in ems_db.get_links(k, ems_db.LINK_FOLDER) or []:
                _add(k, l.get("link_value"))
        except Exception:
            pass
    return owner


def plan():
    """Work out what to add. Reads only."""
    root = jf.year_dir()
    if not root:
        return {"error": "no year folder"}
    with os.scandir(root) as it:
        folders = [e.name for e in it if e.is_dir(follow_symlinks=False)]

    by_loose, names = _jobs_by_loose()
    known = set(names)

    # Who already owns each folder path, so a backfill can never hand a
    # folder to a second job. On the first run this found 0 conflicts and
    # 124 folders already linked to exactly the job the name matched —
    # independent corroboration that the loose match is right, which is
    # why the guard is worth keeping rather than assuming.
    owner = _folder_owners()

    proposals, ambiguous, unresolved, taken = [], [], [], []
    for name in sorted(folders):
        if canon_key(name) in known:
            continue                       # already resolves; nothing to do
        hits = sorted(set(by_loose.get(loose(name), ())))
        if not hits:
            unresolved.append(name)
            continue
        if len(hits) > 1:
            ambiguous.append((name, [names[k] for k in hits]))
            continue
        path = os.path.join(root, name)
        held = owner.get(path.rstrip("\\/").lower(), set())
        if held and hits[0] not in held:
            # Someone else already claims this folder. Adding a second
            # claim is how `get_link` oldest-wins starts returning the
            # wrong answer forever.
            taken.append((name, names[hits[0]], sorted(held)))
            continue
        proposals.append({"folder": name, "path": path,
                          "key": hits[0], "job": names[hits[0]]})
    return {"root": root, "proposals": proposals, "ambiguous": ambiguous,
            "unresolved": unresolved, "conflicts": taken,
            "folders": len(folders)}


def duplicate_pairs():
    """Job rows that are the same name wearing two different keys."""
    by_loose, names = _jobs_by_loose()
    out = []
    for lk, keys in by_loose.items():
        uniq = sorted(set(keys))
        if len(uniq) > 1:
            out.append([(k, names[k]) for k in uniq])
    return out


def _already_aliased():
    """{(canon_key, alias.casefold())} already present — one read.

    A run that dies partway (the first one wrote 99 of 163 before being
    killed) must be resumable without redoing the network calls it
    already made. add_alias is idempotent, so this is about time, not
    correctness.
    """
    have = set()
    try:
        if ems_db.backend_name() == "supabase":
            import ems_db_supabase as _sb
            for a in _sb._rows("job_aliases", select="canon_key,alias"):
                have.add((a.get("canon_key"),
                          (a.get("alias") or "").casefold()))
    except Exception:
        pass
    return have


def apply(proposals) -> dict:
    """Write the aliases and folder links. Records an undo first."""
    have = _already_aliased()
    todo = [p for p in proposals
            if (p["key"], p["folder"].casefold()) not in have]
    skipped = len(proposals) - len(todo)
    keys = sorted({p["key"] for p in todo})
    rec = job_undo.capture(keys, op="folder-aliases",
                           note=f"{len(todo)} folder names")
    added, failed = 0, []
    for p in todo:
        try:
            # force=False on purpose: the uniqueness guard is the last
            # line of defence against one alias naming two jobs, and a
            # backfill is precisely when you want it awake.
            ems_db.add_alias(p["key"], p["folder"], source="folder-backfill")
            ems_db.set_link(p["key"], ems_db.LINK_FOLDER, p["path"],
                            added_by="folder-backfill")
            added += 1
        except Exception as ex:
            failed.append(f"{p['folder']}: {type(ex).__name__}: {ex}")
    return {"added": added, "skipped": skipped, "failed": failed,
            "undo_id": rec.get("id") if rec.get("ok") else None}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="actually write (default is a dry run)")
    ap.add_argument("--dupes", action="store_true",
                    help="list duplicate job pairs instead")
    ap.add_argument("--limit", type=int, default=30)
    args = ap.parse_args(argv)

    if args.dupes:
        pairs = duplicate_pairs()
        print(f"job rows that are one job wearing two keys: {len(pairs)}\n")
        for grp in pairs:
            for k, nm in grp:
                print(f"    {nm!r}")
                print(f"        key {k!r}")
            print()
        print("These are merge candidates, not alias candidates — merging")
        print("DELETES a row, so they are deliberately left to a human.")
        print("ems_db.merge_preview(keep, [drop]) shows the blast radius.")
        return 0

    p = plan()
    if p.get("error"):
        print(p["error"])
        return 1

    print(f"client folders on the share: {p['folders']}")
    print(f"  already resolve:           "
          f"{p['folders'] - len(p['proposals']) - len(p['ambiguous']) - len(p['unresolved'])}")
    print(f"  would gain an alias:       {len(p['proposals'])}")
    print(f"  ambiguous (left alone):    {len(p['ambiguous'])}")
    print(f"  no job at all:             {len(p['unresolved'])}")

    print(f"\n--- proposed (first {args.limit}) ---")
    for q in p["proposals"][:args.limit]:
        print(f"    {q['folder']!r}")
        print(f"        -> {q['job']!r}")
    if len(p["proposals"]) > args.limit:
        print(f"    ... and {len(p['proposals']) - args.limit} more")

    if p["ambiguous"]:
        print("\n--- AMBIGUOUS, needs a human ---")
        for name, jobs in p["ambiguous"]:
            print(f"    folder {name!r} matches:")
            for j in jobs:
                print(f"        {j!r}")

    if p.get("conflicts"):
        print("\n--- SKIPPED, folder already claimed by another job ---")
        for name, want, held in p["conflicts"]:
            print(f"    folder {name!r}")
            print(f"        matched {want!r} but held by {held}")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply.")
        return 0

    res = apply(p["proposals"])
    if res.get("skipped"):
        print(f"\nskipped {res['skipped']} already written by an earlier run")
    print(f"added {res['added']} folder aliases + links")
    if res["undo_id"]:
        print(f"undo record: {res['undo_id']}")
    for f in res["failed"]:
        print("  FAILED", f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
