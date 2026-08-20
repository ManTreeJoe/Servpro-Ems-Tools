"""Bring job-folder names in line with their Trello cards.

The card is the source of the NAME (same rule as
`commercial_naming_audit`): it is the record the office maintains and the
one that carries the client in its canonical spelling. The folder is that
name minus the carrier — `Abbott, Darlene- Farmers` -> `Abbott, Darlene`.

Live, 89 of 626 folders carry a comma and ~537 do not, so the two systems
spell the same client two ways. A handful carry defects on top: ALL CAPS,
a stray carrier (`Abel-Farmers`), a doubled comma
(`CRANKSHAW, LAURA & , JEFFREY`).

Renaming a folder WITHOUT updating its `folder_path` link silently breaks
the job's folder resolution — the same "the write landed, the read
ignored it" failure this codebase keeps producing. So the rename and the
link update happen together, and a folder whose link cannot be updated is
not renamed at all.

Dry-run by default. Nothing moves without `--apply`.

    python rename_job_folders.py                 # the worklist
    python rename_job_folders.py --limit 0       # all of it
    python rename_job_folders.py --apply
"""
import argparse
import io
import os
import re
import sys

import ems_db
import job_folders as jf
import job_undo
from ems_db_common import canon_key

# Trailing noise the folder should never carry.
_STATUS_RE = re.compile(
    r"\s*[-–—(]*\s*\b(paid(\s*full)?|self\s*pay|program|billed|invoiced|"
    r"po\s*#?\s*[a-z0-9]+|wtr|closed)\b[)\s.-]*$", re.I)
_TRAILING_PUNCT = " -–—,.&(_"


def _strip_status(name):
    prev = None
    out = str(name or "")
    while out != prev:
        prev = out
        out = _STATUS_RE.sub("", out).rstrip(_TRAILING_PUNCT)
    return out


def _strip_carrier(name):
    """Drop a trailing carrier: 'Abbott, Darlene- Farmers' -> 'Abbott, Darlene'."""
    try:
        import carriers
    except Exception:
        return name
    out = str(name or "")
    for _ in range(3):
        m = re.search(r"(.*?)[\s,]*[-–—]\s*([^-–—]+?)\s*$", out)
        if not m:
            break
        head, tail = m.group(1).rstrip(_TRAILING_PUNCT), m.group(2).strip()
        if tail and carriers.is_known(tail):
            out = head
            continue
        break
    return out


def _tidy(name):
    """Collapse the punctuation defects seen on the share."""
    s = str(name or "").strip()
    s = re.sub(r"\s{2,}", " ", s)
    s = re.sub(r"\s*,\s*,\s*", ", ", s)        # 'LAURA & , JEFFREY'
    s = re.sub(r"\s*&\s*,\s*", " & ", s)
    s = re.sub(r"\s*,\s*", ", ", s)
    s = re.sub(r"\s*&\s*", " & ", s)
    return s.strip(_TRAILING_PUNCT + " ")


def _fix_caps(name):
    """ALL CAPS -> Title Case, per WORD, leaving acronyms alone.

    'JLA PROPERTY MANAGEMENT' is shouting, but the JLA in it is not —
    title-casing the whole string produced 'Jla Property Management'.
    Short all-caps words (CVS, JLA, AAA, PCM) keep their case; longer
    ones are names.
    """
    s = str(name or "")
    if not any(c.isalpha() for c in s):
        return s

    def _word(m):
        w = m.group(0)
        if any(c.islower() for c in w):
            return w                      # already mixed — leave it
        return w if len(w) <= 3 else w.capitalize()

    return re.sub(r"[A-Za-z']+", _word, s)


def client_from_card(card_name):
    """The CLIENT portion of a card name — what the folder should be.

    Everything from the first STRUCTURAL marker onward belongs to a child
    or to the card's own bookkeeping, never to the client folder:

        'Menifee Union School District - Quail Valley Elementary - Room 15 - 6/4/26'
            -> 'Menifee Union School District'
        'Mansolino, Sayra- AAA - 1st Claim:Bathroom/Garage'
            -> 'Mansolino, Sayra'

    Cutting at the first marker rather than stripping a trailing one is
    what makes the second case work: its carrier is in the MIDDLE.
    """
    s = _strip_status(card_name)
    text = re.sub(r"\s*\([^)]*\)\s*", " ", s)        # (Unit 585G), (2nd Claim)

    cut = len(text)
    try:
        from commercial_naming_audit import (CLAIM_RE, ROOM_RE, UNIT_RE,
                                             DATE_RE, carrier_in)
        for rx in (CLAIM_RE, ROOM_RE, UNIT_RE, DATE_RE):
            m = rx.search(text)
            if m:
                cut = min(cut, m.start())
        carrier = carrier_in(text)
        if carrier:
            m = re.search(re.escape(carrier), text, re.I)
            if m:
                cut = min(cut, m.start())
    except Exception:
        pass
    head = text[:cut]
    # A dangling separator is all that's left of what was cut away.
    head = re.sub(r"[\s,]*[-–—:]+\s*$", "", head)
    return _tidy(_strip_carrier(_strip_status(head)))


def _folder_owners():
    """{lowercased folder path: canon_key}, in one read where possible."""
    owner = {}
    sep = chr(92) + "/"

    def _add(key, value):
        v = (value or "").rstrip(sep).lower()
        if v and key and v not in owner:
            owner[v] = key

    try:
        if ems_db.backend_name() == "supabase":
            import ems_db_supabase as _sb
            for l in _sb._rows("job_links",
                               link_type="eq." + ems_db.LINK_FOLDER,
                               select="canon_key,link_value"):
                _add(l.get("canon_key"), l.get("link_value"))
            return owner
    except Exception:
        owner.clear()
    for j in ems_db.iter_jobs():
        k = j.get("canon_key")
        try:
            for l in (ems_db.get_links(k, ems_db.LINK_FOLDER) or []):
                _add(k, l.get("link_value"))
        except Exception:
            pass
    return owner


_GENERIC_WORDS = {
    "property", "properties", "management", "managment", "company", "inc",
    "llc", "group", "services", "apartments", "apartment", "school",
    "district", "union", "partners", "the", "and", "self", "pay",
}


def _distinctive(name):
    return {w for w in re.split(r"[^a-z0-9]+", str(name or "").lower())
            if len(w) > 2 and w not in _GENERIC_WORDS}


def looks_like_same_client(folder, target):
    """Guard against renaming one client's folder to ANOTHER client's name.

    Live: "Action Property Management" resolved to a job whose card said
    "Athena Property Management". Both are Property Management, so a
    plain word-overlap test passes happily; only the DISTINCTIVE words
    (action vs athena) disagree.

    A rename has to keep at least one distinctive word. Otherwise it is
    not a rename, it is a reassignment.
    """
    a, b = _distinctive(folder), _distinctive(target)
    if not a or not b:
        return True            # nothing to judge on - let it through
    return bool(a & b)



def _cards_by_key():
    """{canon_key: [card_id, ...]}, in one read - same reason."""
    out = {}
    try:
        if ems_db.backend_name() == "supabase":
            import ems_db_supabase as _sb
            for l in _sb._rows("job_links",
                               link_type="eq." + ems_db.LINK_TRELLO,
                               select="canon_key,link_value"):
                out.setdefault(l.get("canon_key"), []).append(
                    l.get("link_value"))
            return out
    except Exception:
        out.clear()
    for j in ems_db.iter_jobs():
        k = j.get("canon_key")
        try:
            out[k] = [l["link_value"] for l in (ems_db.get_links(k) or [])
                      if l["link_type"] == ems_db.LINK_TRELLO]
        except Exception:
            pass
    return out


def _cards_for(key):
    return [l["link_value"] for l in (ems_db.get_links(key) or [])
            if l["link_type"] == ems_db.LINK_TRELLO]


def parse_decisions(text):
    """Read the review page's "Copy for Claude" block.

    The page emits exactly this, so the round trip closes without anyone
    retyping a folder name — which is how a rename lands on the wrong
    folder.

        FOLDER RENAME REVIEW
        skip (2):
          Abel-Farmers
        retarget (1):
          Beckes Robert  ->  Beckes, Robert

    Returns {"skip": {folder, ...}, "retarget": {folder: new_name}}.
    """
    skip, retarget, mode = set(), {}, ""
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith("skip"):
            mode = "skip"
            continue
        if low.startswith("retarget"):
            mode = "retarget"
            continue
        if low.startswith("folder rename review") or low.startswith("nothing"):
            continue
        if mode == "skip":
            skip.add(line)
        elif mode == "retarget" and "->" in line:
            a, b = line.split("->", 1)
            a, b = a.strip(), b.strip()
            if a and b:
                retarget[a] = b
    return {"skip": skip, "retarget": retarget}


def plan(limit_cards=400):
    root = jf.year_dir()
    if not root:
        return {"error": "no year folder"}
    with os.scandir(root) as it:
        folders = sorted(e.name for e in it if e.is_dir(follow_symlinks=False))

    # folder path -> job key, so a rename can update the right link.
    # ONE read. The per-job version was 462 round trips against the
    # shared database, so a single transient 502 anywhere in the
    # sequence killed the whole run. That happened.
    owner = _folder_owners()

    cards_by_key = _cards_by_key()
    import trello_client as tc
    name_cache, fetched = {}, 0

    def card_name(cid):
        nonlocal fetched
        if cid in name_cache:
            return name_cache[cid]
        if fetched >= limit_cards:
            return ""
        fetched += 1
        try:
            c = (tc.get_card_lite(cid) if hasattr(tc, "get_card_lite")
                 else tc.get_card(cid)) or {}
            name_cache[cid] = c.get("name") or ""
        except Exception:
            name_cache[cid] = ""
        return name_cache[cid]

    rows, taken = [], {f.lower() for f in folders}
    for folder in folders:
        path = os.path.join(root, folder)
        key = owner.get(path.rstrip("\\/").lower()) or ""
        if not key:
            j = ems_db.find_job_by_name(folder)
            key = (j or {}).get("canon_key") or ""

        target, source = "", ""
        if key:
            for cid in cards_by_key.get(key, ()):
                nm = card_name(cid)
                if nm:
                    target, source = client_from_card(nm), "card"
                    break
        if not target:
            # No card to copy: clean what is there rather than inventing.
            target, source = _tidy(_fix_caps(_strip_carrier(
                _strip_status(folder)))), "cleanup"

        target = _tidy(_fix_caps(target))
        if not target or target == folder:
            continue
        # A multi-site client's card names the SITE too, and no structural
        # marker separates "Menifee Union School District" from "Quail
        # Valley Elementary". The existing folder is the evidence: when
        # the derived target merely EXTENDS it, the folder is already the
        # client portion and renaming would push a site into the client
        # level — the exact confusion Aperto was.
        if target.lower().startswith(folder.lower()):
            continue
        collide = (target.lower() in taken and target.lower() != folder.lower())
        suspect = not looks_like_same_client(folder, target)
        rows.append({"folder": folder, "target": target, "path": path,
                     "key": key, "source": source, "collides": collide,
                     "suspect": suspect,
                     "linked": bool(owner.get(path.rstrip("\\/").lower()))})
    # Two proposals can want the SAME new name. The check above compares
    # each target against the folders that exist NOW, which cannot see a
    # name another rename is about to create: "Parks Jennifer" and
    # "Parks, Jennifer -Self Pay" both wanted "Parks, Jennifer", the
    # first succeeded, and the second failed at os.rename. Safe, but it
    # belonged in the dry run, not in the apply output.
    import collections as _c
    counts = _c.Counter(r["target"].lower() for r in rows)
    for r in rows:
        if counts[r["target"].lower()] > 1:
            r["collides"] = True

    return {"root": root, "rows": rows, "folders": len(folders),
            "cards_read": fetched}


def _rename_log_path():
    import paths
    stamp = __import__("datetime").datetime.now().strftime("%Y%m%d-%H%M%S")
    d = paths.data("undo")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{stamp}-folder-renames.json")


def apply(root, rows):
    done, failed = 0, []
    keys = sorted({r["key"] for r in rows if r["key"]})
    rec = job_undo.capture(keys, op="folder-rename",
                           note=f"{len(rows)} folders")
    # job_undo records DATABASE state; it cannot put a directory back. So
    # every (old, new) pair is written as it happens — a rename that
    # turns out wrong is then reversible by walking this file backwards,
    # which 190 folders on a live share very much deserves.
    log_path, log = _rename_log_path(), []

    def _flush():
        try:
            io.open(log_path, "w", encoding="utf-8").write(
                __import__("json").dumps(log, indent=1))
        except Exception:
            pass
    for r in rows:
        if r["collides"]:
            failed.append(f"{r['folder']}: target exists")
            continue
        dst = os.path.join(root, r["target"])
        try:
            os.rename(r["path"], dst)
        except OSError as ex:
            failed.append(f"{r['folder']}: {type(ex).__name__}: {ex}")
            continue
        # The link MUST follow the folder, or the job resolves to a path
        # that no longer exists and every lookup silently misses.
        log.append({"from": r["path"], "to": dst, "key": r["key"]})
        _flush()                       # after each one, not at the end
        if r["key"]:
            try:
                ems_db.set_link(r["key"], ems_db.LINK_FOLDER, dst,
                                added_by="folder-rename")
                ems_db.remove_link(r["key"], ems_db.LINK_FOLDER, r["path"])
            except Exception as ex:
                failed.append(f"{r['folder']}: renamed but link failed: {ex}")
        done += 1
    _flush()
    return {"renamed": done, "failed": failed, "log": log_path,
            "undo_id": rec.get("id") if rec.get("ok") else None}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=40,
                    help="rows to print (0 = all)")
    ap.add_argument("--decisions", metavar="FILE",
                    help="the review page's Copy-for-Claude block")
    ap.add_argument("--json", metavar="FILE",
                    help="write the worklist as JSON")
    ap.add_argument("--cards", type=int, default=400,
                    help="max Trello card reads")
    args = ap.parse_args(argv)

    p = plan(limit_cards=args.cards)
    if p.get("error"):
        print(p["error"])
        return 1
    rows = p["rows"]

    # Your marks from the review page. A skip is removed outright; a
    # retarget replaces the proposed name and clears `suspect`, because a
    # human just vouched for it.
    if args.decisions:
        dec = parse_decisions(io.open(args.decisions, encoding="utf-8").read())
        kept = []
        for r in rows:
            if r["folder"] in dec["skip"]:
                continue
            new = dec["retarget"].get(r["folder"])
            if new:
                r["target"] = new
                r["suspect"] = False
                r["source"] = "you"
                r["collides"] = False
            kept.append(r)
        print(f"decisions: {len(dec['skip'])} skipped, "
              f"{len(dec['retarget'])} retargeted")
        rows = kept
        p["rows"] = rows
    from_card = [r for r in rows if r["source"] == "card"]
    collide = [r for r in rows if r["collides"]]
    suspect = [r for r in rows if r.get("suspect")
               and not r["collides"]]
    unlinked = [r for r in rows if not r["linked"]]

    print(f"client folders {p['folders']} · cards read {p['cards_read']}")
    print(f"  would rename        {len(rows)}")
    print(f"    from a card       {len(from_card)}")
    print(f"    cleanup only      {len(rows) - len(from_card)}")
    print(f"  COLLIDES (skipped)  {len(collide)}")
    print(f"  SUSPECT  (skipped)  {len(suspect)}")
    print(f"  no folder link      {len(unlinked)}")

    if args.json:
        import json as _json
        io.open(args.json, "w", encoding="utf-8").write(_json.dumps({
            "root": p["root"], "folders": p["folders"],
            "cards_read": p["cards_read"], "rows": rows}, indent=1))
        print(f"wrote {args.json}")

    show = rows if args.limit == 0 else rows[:args.limit]
    print()
    for r in show:
        flag = "  !! COLLIDES" if r["collides"] else ""
        print(f"    {r['folder']}")
        print(f"      -> {r['target']}   [{r['source']}]{flag}")
    if args.limit and len(rows) > args.limit:
        print(f"    ... and {len(rows) - args.limit} more (--limit 0)")

    if collide:
        print("\n  collisions, left alone:")
        for r in collide:
            print(f"    {r['folder']} -> {r['target']}")

    if not args.apply:
        print("\nDRY RUN — nothing renamed. Re-run with --apply.")
        return 0

    res = apply(p["root"], [r for r in rows
                            if not r["collides"]
                            and not r.get("suspect")])
    print(f"\nrenamed {res['renamed']} folders")
    if res["undo_id"]:
        print(f"undo record: {res['undo_id']}")
    print(f"rename log : {res['log']}")
    for f in res["failed"]:
        print("  FAILED", f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
