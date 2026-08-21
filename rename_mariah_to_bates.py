"""Rename Mariah Property Management -> Bates Homes Property Management.

The job was named after the CONTACT (Mariah Vehorn) rather than the
company. The name is wrong in five places at once — the job index, the
folder on disk, the Trello card, the CompanyCam project, and this PC's
caches — and a rename that fixes only some of them is worse than none,
because the surfaces then disagree about which job this is.

    python rename_mariah_to_bates.py            # show the plan, write nothing
    python rename_mariah_to_bates.py --apply    # do it

Old spellings are KEPT as aliases pointing at the new key. Somebody will
type "Mariah" for months, and an alias is how that keeps resolving
instead of creating a second job.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import ems_db                      # noqa: E402
import ems_db_common as C          # noqa: E402
import supabase_client as sb       # noqa: E402

OLD_NAME = "Mariah Property Management- 8/15/26"
NEW_NAME = "Bates Homes Property Management- 8/15/26"
CONTACT = "Mariah Vehorn"

# This alias points at ATHENA, not Mariah — a cross-link from the folder
# rename pass. Renaming without correcting it would carry the error
# forward under a new name.
BAD_ALIAS = "Mariah Property Management"
BAD_ALIAS_POINTS_AT = "athena property management"


def survey():
    """Everything that carries the old name. Reads only."""
    jobs = sb.rest("GET", "jobs", params={
        "select": "canon_key,display_name", "limit": "5000"}) or []
    job = next((j for j in jobs
                if (j["display_name"] or "").strip() == OLD_NAME), None)
    out = {"job": job, "links": [], "aliases": [], "bad_alias": None}
    if not job:
        return out
    out["links"] = sb.rest("GET", "job_links", params={
        "select": "link_type,link_value",
        "canon_key": f"eq.{job['canon_key']}", "limit": "50"}) or []
    al = sb.rest("GET", "job_aliases", params={
        "select": "alias,canon_key", "limit": "5000"}) or []
    for a in al:
        if "mariah" in (a.get("alias") or "").lower():
            if BAD_ALIAS_POINTS_AT in (a.get("canon_key") or "").lower():
                out["bad_alias"] = a
            else:
                out["aliases"].append(a)
    return out


def main():
    apply = "--apply" in sys.argv
    s = survey()
    job = s["job"]
    if not job:
        print(f"No job named {OLD_NAME!r} — nothing to do.")
        return 0

    print(f"JOB   {job['display_name']!r}")
    print(f"  ->  {NEW_NAME!r}")
    print(f"      contact stays {CONTACT!r} (a person, not the company)")
    print()
    print("CARRIES THE OLD NAME:")
    for l in s["links"]:
        print(f"   {l['link_type']:<20} {l['link_value']}")
    for a in s["aliases"]:
        print(f"   {'alias':<20} {a['alias']!r}  (kept, re-pointed)")
    if s["bad_alias"]:
        b = s["bad_alias"]
        print()
        print(f"   !! alias {b['alias']!r} points at {b['canon_key']!r}")
        print("      That is a DIFFERENT job. It is corrected, not carried.")

    if not apply:
        print()
        print("Nothing written. Re-run with --apply.")
        print("NOTE: the Trello card, the CompanyCam project and the folder")
        print("are renamed by hand or by a follow-up — this script does the")
        print("index and the local caches only, so nothing outward-facing")
        print("changes without you asking for it.")
        return 0

    # 1. the job row. merge_jobs is what can change a canon_key; a plain
    #    upsert would leave the old key in place and create a second row.
    old_key = job["canon_key"]
    new_key = C.canon_key(NEW_NAME)
    try:
        ems_db.upsert_job(display_name=NEW_NAME)
        res = ems_db.merge_jobs(new_key, [old_key], undo=True,
                                note=f"renamed from {OLD_NAME}")
        print(f"   index: {old_key!r} -> {new_key!r}  "
              f"undo={(res or {}).get('undo_id')}")
    except Exception as ex:
        print(f"   index FAILED: {type(ex).__name__}: {ex}")
        return 1

    # 2. old spellings keep resolving.
    for alias in (OLD_NAME, BAD_ALIAS, "Mariah Property Managment"):
        try:
            ems_db.add_alias(alias, new_key, force=True)
            print(f"   alias kept: {alias!r} -> {new_key!r}")
        except Exception as ex:
            print(f"   alias {alias!r} FAILED: {ex}")

    # 3. this PC's caches, keyed by name.
    try:
        import persistence
        m = persistence.rename_client(OLD_NAME, NEW_NAME)
        print(f"   local state: {m or 'nothing cached'}")
    except Exception as ex:
        print(f"   local state FAILED: {ex}")

    print()
    print("Index done. Still to rename BY HAND (outward-facing):")
    for l in s["links"]:
        print(f"   {l['link_type']:<20} {l['link_value']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
