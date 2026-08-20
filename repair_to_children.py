"""Move a conflated parent's Trello cards and folders onto real children.

Some clients accumulated every unit's card on ONE job row: Carnero holds
8, Greystar 7, Aperto 2. Because `get_link` returns the OLDEST row, all
but the first card is ignored forever — a pin, an import or a comment
aimed at one unit lands on another, or on nothing.

The fix is not to split them into sibling JOBS (that is what
`repair_conflated_job.py` did, under the older model). It is to give the
client the children it always had: one `job_children` row per unit or
claim, each carrying its own folder, card and CompanyCam project, with
`property` / `unit` / `claim_date` filled in from the folder name the
office already writes.

Matching is derived, never guessed. A card joins a folder only when both
name the SAME unit, and anything unmatched is printed for a human rather
than attached to whatever looked closest.

Dry-run by default. `--apply` captures an undo record first, so the whole
thing reverses with `job_undo.restore(<id>, dry_run=False)`.

    python repair_to_children.py "aperto property management- (tres lagos"
    python repair_to_children.py "<key>" --apply
    python repair_to_children.py "<key>" --apply --rekey "Aperto Property Management"
"""
import argparse
import os
import re
import sys

import ems_db
import job_undo
from ems_db_common import canon_key, parse_child_levels


def _card_names(card_ids):
    import trello_client as tc
    out = {}
    for cid in card_ids:
        try:
            c = tc.get_card_lite(cid) if hasattr(tc, "get_card_lite") \
                else tc.get_card(cid)
            out[cid] = (c or {}).get("name") or ""
        except Exception:
            out[cid] = ""
    return out


def _project_names(project_ids):
    out = {}
    try:
        import companycam_api as cc
    except Exception:
        return {p: "" for p in project_ids}
    for pid in project_ids:
        try:
            out[pid] = (cc.get_project(pid) or {}).get("name") or ""
        except Exception:
            out[pid] = ""
    return out


def _unit_key(text):
    """The comparable identity of a unit -- '585G', '545O', '' --
    however the office wrote it.

    parse_child_levels wants a "Unit" word and the live cards do not
    always have one: "Greystar (Avana Springs) - 545-O" names the unit
    with no keyword, and "Unit 565 E" separates the letter with a
    space where the folder uses a dash. Both went unmatched and their
    cards stayed stranded on the parent.

    The DATE is stripped first, or the "26" of "5/7/26" is a
    perfectly good two-digit unit number.
    """
    raw = str(text or "")
    lv = parse_child_levels(raw)
    parsed = (lv.get("unit") or "").replace("-", "").replace(" ", "").upper()
    body = re.sub(r"(?<![0-9])[0-9]{1,2}[/.\-][0-9]{1,2}(?:[/.\-][0-9]{2,4})?(?![0-9])", " ", raw)
    m = re.search(r"(?<![0-9])([0-9]{3,4})\s*[-\s]?\s*([A-Za-z])?(?![0-9A-Za-z])", body)
    if not m:
        return parsed
    loose = (m.group(1) + (m.group(2) or "")).upper()
    # Prefer whichever is more specific. parse_child_levels stops at the
    # space in "Unit 565 E" and yields "565", which would then match ANY
    # 565 unit - including 565-E's neighbour.
    return loose if len(loose) > len(parsed) else (parsed or loose)


def plan(parent_key):
    job = ems_db.get_job(parent_key)
    if job is None:
        return {"error": f"no job {parent_key!r}"}
    links = ems_db.get_links(parent_key) or []

    folders = [l["link_value"] for l in links
               if l["link_type"] == ems_db.LINK_FOLDER]
    cards = [l["link_value"] for l in links
             if l["link_type"] == ems_db.LINK_TRELLO]
    projects = [l["link_value"] for l in links
                if l["link_type"] == "companycam_project"]

    # The parent folder is the shortest linked path that the others sit
    # under; failing that, the shortest one.
    root = min(folders, key=len) if folders else ""
    on_disk = []
    if root and os.path.isdir(root):
        with os.scandir(root) as it:
            on_disk = sorted(e.name for e in it
                             if e.is_dir(follow_symlinks=False))

    card_names = _card_names(cards)
    proj_names = _project_names(projects)

    children, unmatched_cards, unmatched_projects = [], [], []
    used_cards, used_projects = set(), set()

    for folder in on_disk:
        lv = parse_child_levels(folder)
        uk = (lv["unit"] or "").replace("-", "").upper()
        path = os.path.join(root, folder)

        card = ""
        if uk:
            for cid, nm in card_names.items():
                if cid not in used_cards and _unit_key(nm) == uk:
                    card, _ = cid, used_cards.add(cid)
                    break
        proj = ""
        if uk:
            for pid, nm in proj_names.items():
                if pid not in used_projects and _unit_key(nm) == uk:
                    proj, _ = pid, used_projects.add(pid)
                    break

        children.append({"name": folder, "path": path, "card": card,
                         "companycam": proj, **lv})

    for cid, nm in card_names.items():
        if cid not in used_cards:
            unmatched_cards.append((cid, nm))
    for pid, nm in proj_names.items():
        if pid not in used_projects:
            unmatched_projects.append((pid, nm))

    # What the parent should stop claiming: every link now owned by a
    # child. The parent keeps its own folder.
    drop = [(ems_db.LINK_FOLDER, c["path"]) for c in children
            if any(os.path.normcase(f).rstrip("\\/") ==
                   os.path.normcase(c["path"]).rstrip("\\/") for f in folders)]
    drop += [(ems_db.LINK_TRELLO, c["card"]) for c in children if c["card"]]
    drop += [("companycam_project", c["companycam"])
             for c in children if c["companycam"]]

    return {"job": job, "root": root, "children": children,
            "unmatched_cards": unmatched_cards,
            "unmatched_projects": unmatched_projects, "drop": drop}


def apply(parent_key, p, rekey=""):
    rec = job_undo.capture([parent_key], op="to-children",
                           note=f"{len(p['children'])} children")
    key = parent_key
    notes = []

    if rekey:
        new_key = canon_key(rekey)
        if new_key and new_key != parent_key:
            ems_db.upsert_job(display_name=rekey)
            res = ems_db.merge_jobs(new_key, [parent_key])
            notes.append(f"re-keyed -> {new_key!r} ({res})")
            key = new_key

    made = 0
    for c in p["children"]:
        ems_db.set_child(key, c["name"], folder_path=c["path"],
                         trello_card=c["card"] or "",
                         companycam=c["companycam"] or "",
                         property=c["property"], unit=c["unit"],
                         claim_date=c["claim_date"],
                         department=(p["job"] or {}).get("department") or "")
        made += 1

    for lt, lv in p["drop"]:
        try:
            # remove_link returns None whether or not it matched, so the
            # count comes from re-reading below rather than from trusting
            # the call — the difference between "removed 4" and "removed
            # nothing and said 4" is the whole point of this exercise.
            ems_db.remove_link(key, lt, lv)
        except Exception as ex:
            notes.append(f"remove_link {lt} failed: {ex}")

    left = {(l["link_type"], l["link_value"])
            for l in ems_db.get_links(key) or []}
    from ems_db_common import _norm_link
    still = [(lt, lv) for lt, lv in p["drop"]
             if (lt, _norm_link(lt, lv)) in left]
    for lt, lv in still:
        notes.append(f"STILL ON PARENT: {lt} = {lv}")

    return {"children": made, "links_dropped": len(p["drop"]) - len(still),
            "still_attached": len(still), "notes": notes,
            "undo_id": rec.get("id") if rec.get("ok") else None, "key": key}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("parent", help="canon_key of the conflated job")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--rekey", default="",
                    help="also fix a truncated key, e.g. 'Aperto Property "
                         "Management'")
    args = ap.parse_args(argv)

    p = plan(args.parent)
    if p.get("error"):
        print(p["error"])
        return 1

    print(f"parent : {p['job'].get('display_name')!r}")
    print(f"key    : {args.parent!r}")
    print(f"folder : {p['root']}")
    if args.rekey:
        print(f"re-key : -> {canon_key(args.rekey)!r}  ({args.rekey!r})")

    print(f"\nchildren to create: {len(p['children'])}")
    for c in p["children"]:
        print(f"    {c['name']!r}")
        print(f"        property={c['property']!r} unit={c['unit']!r} "
              f"claim_date={c['claim_date']!r}")
        print(f"        card={c['card'] or '-'}  companycam="
              f"{c['companycam'] or '-'}")

    if p["unmatched_cards"]:
        print("\nCARDS THAT MATCHED NO FOLDER — left on the parent:")
        for cid, nm in p["unmatched_cards"]:
            print(f"    {cid}  {nm!r}")
    if p["unmatched_projects"]:
        print("\nCOMPANYCAM PROJECTS THAT MATCHED NO FOLDER:")
        for pid, nm in p["unmatched_projects"]:
            print(f"    {pid}  {nm!r}")

    print(f"\nlinks to remove from the parent: {len(p['drop'])}")
    for lt, lv in p["drop"]:
        print(f"    {lt} = {lv}")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply.")
        return 0

    res = apply(args.parent, p, rekey=args.rekey)
    print(f"\ncreated {res['children']} children on {res['key']!r}")
    print(f"removed {res['links_dropped']} links from the parent")
    for n in res["notes"]:
        print("   ", n)
    if res["undo_id"]:
        print(f"undo record: {res['undo_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
