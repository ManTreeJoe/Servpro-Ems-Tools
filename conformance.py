"""Run the same job-graph scenarios against each backend and compare.

The pytest suite can't do this: its fixtures call `reset_db_path()` to get
a throwaway SQLite file, which is meaningless against a hosted database.
So this exercises the public API directly and asserts both backends behave
identically.

SAFE ON LIVE DATA. Every job it creates is prefixed with a unique run tag
(`zzconf-<uuid>-…`), so it cannot collide with a real job, and it deletes
what it made on the way out — including after a failure.

    python conformance.py --backend sqlite
    python conformance.py --backend supabase      # needs a signed-in session
    python conformance.py --both                  # run both, diff the results
"""
from __future__ import annotations

import argparse
import sys
import time
import traceback
import uuid

import ems_db


class Scenario:
    def __init__(self, name, fn):
        self.name = name
        self.fn = fn


SCENARIOS = []


def scenario(name):
    def wrap(fn):
        SCENARIOS.append(Scenario(name, fn))
        return fn
    return wrap


# ── scenarios ───────────────────────────────────────────────────────────
# Each returns a JSON-able value. The two backends must produce EQUAL
# values — that equality is the whole point, so keep returns primitive.

@scenario("upsert + get")
def _s_upsert(db, tag):
    key = db.upsert_job(display_name=f"{tag} Alpha", carrier="AAA")
    job = db.get_job(key)
    return {"key": key, "name": job["display_name"], "carrier": job["carrier"]}


@scenario("partial update never blanks a field")
def _s_partial(db, tag):
    key = db.upsert_job(display_name=f"{tag} Beta", carrier="Mercury")
    db.upsert_job(display_name=f"{tag} Beta", status="active")
    j = db.get_job(key)
    return {"carrier": j["carrier"], "status": j["status"]}


@scenario("alias resolution")
def _s_alias(db, tag):
    key = db.upsert_job(display_name=f"{tag} Charlie - AAA")
    db.add_alias(key, f"{tag} chuck")
    found = db.find_job_by_name(f"{tag} chuck")
    return {"resolved": bool(found),
            "same": (found or {}).get("canon_key") == key,
            "aliases": sorted(db.get_aliases(key))}


@scenario("links round trip")
def _s_links(db, tag):
    key = db.upsert_job(display_name=f"{tag} Delta")
    db.set_link(key, db.LINK_TRELLO, "https://trello.com/c/AbC123/x")
    db.set_link(key, db.LINK_FOLDER, r"X:\IE_Public\2026 Jobs\Delta")
    return {"card": db.get_link(key, db.LINK_TRELLO),
            "n_links": len(db.get_links(key)),
            "by_link": (db.find_job_by_link(db.LINK_TRELLO, "abc123") or
                        {}).get("canon_key") == key}


@scenario("folder pin stamps department")
def _s_department(db, tag):
    key = db.upsert_job(display_name=f"{tag} Echo")
    db.set_link(key, db.LINK_FOLDER, r"X:\IE_Public\2026 Jobs\Echo")
    return {"department": db.get_job(key).get("department")}


@scenario("trello link does NOT stamp department")
def _s_card_no_dept(db, tag):
    key = db.upsert_job(display_name=f"{tag} Foxtrot")
    db.set_link(key, db.LINK_TRELLO, "cardfox")
    return {"department": db.get_job(key).get("department")}


@scenario("resolve_and_link ties a spelling")
def _s_resolve(db, tag):
    j = db.resolve_and_link(f"{tag} Golf", trello_card="cardgolf",
                            create=True, source="conformance")
    again = db.resolve_and_link(f"{tag} golf alt", trello_card="cardgolf",
                                source="conformance")
    return {"created": bool(j),
            "same_job": (again or {}).get("canon_key") == j["canon_key"],
            "alias_learned": any("alt" in a.lower()
                                 for a in db.get_aliases(j["canon_key"]))}


@scenario("cross-franchise match refused")
def _s_conflict(db, tag):
    key = db.upsert_job(display_name=f"{tag} Hotel", department="OC")
    try:
        db.resolve_and_link(f"{tag} Hotel",
                            folder_path=r"X:\IE_Public\2026 Jobs\Hotel",
                            create=True, source="conformance")
        return {"raised": False}
    except Exception as ex:
        return {"raised": type(ex).__name__ == "DepartmentConflict"}
    finally:
        db.get_job(key)


@scenario("children: claims and units")
def _s_children(db, tag):
    parent = db.upsert_job(display_name=f"{tag} India")
    db.set_child(parent, "1st Claim")
    db.set_child(parent, "2nd Claim (Kitchen)")
    db.set_child(parent, "Unit 182", trello_card="cardunit")
    kids = db.children_of(parent)
    return {"names": [k["name"] for k in kids],
            "kinds": [k["kind"] for k in kids],
            "ordinals": [k["ordinal"] for k in kids],
            "by_card": (db.find_child_by_card("cardunit") or {}).get("name")}


@scenario("batched card display names")
def _s_batch(db, tag):
    a = db.upsert_job(display_name=f"{tag} Juliet - AAA")
    db.set_link(a, db.LINK_TRELLO, "cardjuliet")
    db.upsert_job(display_name=f"{tag} Kilo")          # no card
    got = db.card_display_names_for([f"{tag} Juliet - AAA", f"{tag} Kilo"])
    return {"resolved": sorted(got.values()),
            "unresolved_absent": f"{tag} Kilo" not in got}


@scenario("uncarded job does not fall through to an alias")
def _s_precedence(db, tag):
    # The live 'Gabriel Ramirez' case.
    plain = db.upsert_job(display_name=f"{tag} Lima")           # no card
    carded = db.upsert_job(display_name=f"{tag} Lima Full - AAA")
    db.add_alias(carded, f"{tag} Lima")
    db.set_link(carded, db.LINK_TRELLO, "cardlima")
    got = db.card_display_names_for([f"{tag} Lima"])
    return {"empty": got == {}, "plain_exists": bool(db.get_job(plain))}


@scenario("merge folds a duplicate")
def _s_merge(db, tag):
    keep = db.upsert_job(display_name=f"{tag} Mike - AAA")
    dupe = db.upsert_job(display_name=f"{tag} Mike")
    db.set_link(dupe, db.LINK_TRELLO, "cardmike")
    res = db.merge_jobs(keep, [dupe])
    return {"merged": res.get("merged"),
            "dupe_gone": db.get_job(dupe) is None,
            "link_moved": db.get_link(keep, db.LINK_TRELLO) == "cardmike"}


@scenario("merge refuses across franchises")
def _s_merge_conflict(db, tag):
    ie = db.upsert_job(display_name=f"{tag} November - AAA", department="IE")
    oc = db.upsert_job(display_name=f"{tag} November alt", department="OC")
    res = db.merge_jobs(ie, [oc])
    return {"merged": res.get("merged"),
            "skipped": bool(res.get("skipped_department_conflict")),
            "oc_survives": db.get_job(oc) is not None}


@scenario("all_aliases returns every pair in one call")
def _s_all_aliases(db, tag):
    """Type-ahead ranks against the whole alias table. Per-job fetches would
    be the N+1 that cost 36s on the hosted backend, so both backends must
    serve this in one shot — and agree on what comes back."""
    key = db.upsert_job(display_name=f"{tag} Romeo")
    db.add_alias(key, f"{tag} Romeo Alt")
    db.add_alias(key, f"{tag} R. Romeo")
    mine = sorted(r["alias"] for r in db.all_aliases()
                  if (r.get("canon_key") or "") == key)
    return {"count": len(mine), "aliases": mine}


@scenario("iter_jobs is newest-seen first")
def _s_iter_order(db, tag):
    """Every other scenario compares row SETS, so an ordering regression is
    invisible to them. The Supabase backend really did return iter_jobs
    alphabetically for a while, silently breaking any "most recent" list.

    Ties are left unspecified on purpose — SQLite breaks an identical
    last_seen_at by rowid, Postgres by canon_key — so this asserts only
    that the timestamps descend, and spaces the writes so there are no
    ties to argue about."""
    for name in ("Oscar", "Papa", "Quebec"):
        db.upsert_job(display_name=f"{tag} {name}")
        time.sleep(0.01)
    mine = [j for j in db.iter_jobs()
            if (j.get("display_name") or "").startswith(tag)]
    stamps = [j.get("last_seen_at") or "" for j in mine]
    return {"count": len(mine),
            "descending": stamps == sorted(stamps, reverse=True)}


# ── runner ──────────────────────────────────────────────────────────────

def _cleanup(db, tag):
    """Delete everything this run created. Best-effort per job so one
    failure can't strand the rest."""
    removed = 0
    try:
        for job in db.iter_jobs():
            if not (job.get("canon_key") or "").startswith(tag.lower()):
                continue
            key = job["canon_key"]
            try:
                for ch in db.children_of(key):
                    db.remove_child(key, ch["name"])
                for l in db.get_links(key):
                    db.remove_link(key, l["link_type"], l["link_value"])
                db.merge_jobs  # noqa — touch to keep import-time errors early
                _delete_job(db, key)
                removed += 1
            except Exception:
                pass
    except Exception:
        pass
    return removed


def _delete_job(db, key):
    """No public delete_job — use each backend's own path."""
    name = db.backend_name() if hasattr(db, "backend_name") else ""
    if name == "supabase":
        import supabase_client as sb
        sb.rest("DELETE", "jobs", params={"canon_key": f"eq.{key}"})
    else:
        import ems_db_sqlite as s
        with s._LOCK, s._connect() as c:
            c.execute("DELETE FROM jobs WHERE canon_key=?", (key,))
            c.commit()


def run(backend, tag):
    ems_db.use_backend(backend)
    if backend == "supabase":
        # The supabase backend is wrapped by ems_db_offline, which serves
        # from the local SQLite mirror when the network drops. That is
        # right for the app and wrong for this suite: during an outage it
        # would compare SQLite against SQLite and cheerfully report the two
        # backends identical without ever reaching Supabase.
        import ems_db_offline
        ems_db_offline.FALLBACK_ENABLED = False
    results, failures = {}, 0
    print(f"\n=== {backend} ===")
    for sc in SCENARIOS:
        try:
            val = sc.fn(ems_db, tag)
            results[sc.name] = val
            print(f"  ok    {sc.name}")
        except Exception as ex:
            failures += 1
            results[sc.name] = {"__error__": f"{type(ex).__name__}: {ex}"}
            print(f"  ERROR {sc.name}: {type(ex).__name__}: {ex}")
            if "--trace" in sys.argv:
                traceback.print_exc()
    n = _cleanup(ems_db, tag)
    print(f"  (cleaned up {n} test jobs)")
    return results, failures


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backend", choices=["sqlite", "supabase"])
    ap.add_argument("--both", action="store_true")
    ap.add_argument("--trace", action="store_true")
    args = ap.parse_args([a for a in argv if a != "--trace"])

    tag = f"zzconf-{uuid.uuid4().hex[:8]}"
    print(f"run tag: {tag}  ({len(SCENARIOS)} scenarios)")

    if args.both:
        a, fa = run("sqlite", tag)
        b, fb = run("supabase", tag)
        print("\n=== diff ===")
        diffs = 0
        for sc in SCENARIOS:
            if a.get(sc.name) != b.get(sc.name):
                diffs += 1
                print(f"  DIFFERS  {sc.name}")
                print(f"     sqlite  : {a.get(sc.name)}")
                print(f"     supabase: {b.get(sc.name)}")
        if not diffs:
            print("  identical on every scenario ✓")
        return 1 if (diffs or fa or fb) else 0

    if not args.backend:
        ap.error("pass --backend or --both")
    _, failures = run(args.backend, tag)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
