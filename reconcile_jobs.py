"""Reconcile the job index to Trello card NAMES + collapse duplicate pins.

The rule (user, 2026-07-22): a job is identified by the name on its
pinned Trello card, and all differently-spelled pins of the SAME job
(they share a Trello card) are ONE job.

This walks persistence pins, groups every spelling that shares a Trello
card (transitively), names each group by its Trello card, and folds the
duplicates into a single canonical ems_db job — aliasing every spelling
and merging the folder links onto the winner. Re-runnable + idempotent;
supports a read-only dry run.

    python reconcile_jobs.py --dry     # report only, no writes
    python reconcile_jobs.py           # apply

Back up %APPDATA%\\EMS Automation\\{state.json,ems_jobs.db} before applying.
"""
import collections

import persistence as P
import ems_db
import trello_client as tc


def _components(pins):
    """Union-find over pin keys: two keys are the same job when they
    share a Trello card. Returns {root: set(keys)}."""
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    card_to_keys = collections.defaultdict(list)
    for k, ids in pins.items():
        parent.setdefault(k, k)
        for cid in (ids or []):
            card_to_keys[cid].append(k)
    for _cid, ks in card_to_keys.items():
        for k in ks[1:]:
            union(ks[0], k)

    comps = collections.defaultdict(set)
    for k in list(parent):
        comps[find(k)].add(k)
    return comps


def reconcile(dry_run=True, name_cache=None, progress=False):
    state = P._load()
    pins = state.get("trello_card_ids", {}) or {}
    folders = state.get("folder_paths", {}) or {}
    comps = _components(pins)
    name_cache = {} if name_cache is None else name_cache

    def card_name(cid):
        if cid in name_cache:
            return name_cache[cid]
        try:
            c = tc.get_card(cid, actions_limit=0)
            nm = (c or {}).get("name", "") or ""
        except Exception:
            nm = ""
        name_cache[cid] = nm
        return nm

    rep = {"components_with_cards": 0, "jobs_named": 0, "spellings_folded": 0,
           "skipped_no_name": 0, "samples": []}

    for _root, keys in comps.items():
        card_ids = []
        for k in keys:
            for cid in (pins.get(k) or []):
                if cid not in card_ids:
                    card_ids.append(cid)
        if not card_ids:
            continue                      # no pinned card → cannot card-name
        rep["components_with_cards"] += 1
        chosen = ""
        for cid in sorted(card_ids):
            nm = card_name(cid)
            if nm:
                chosen = nm
                break
        into_key = ems_db.canon_key(chosen) if chosen else ""
        if not into_key:
            rep["skipped_no_name"] += 1
            continue
        spelling_keys = {ems_db.canon_key(k) for k in keys}
        spelling_keys.discard("")
        from_keys = sorted(spelling_keys - {into_key})
        if len(rep["samples"]) < 30:
            rep["samples"].append({
                "card_name": chosen, "into_key": into_key,
                "spellings": sorted(keys), "cards": card_ids,
                "fold_in": from_keys})
        if progress and rep["components_with_cards"] % 25 == 0:
            print(f"  …{rep['components_with_cards']} groups")
        if dry_run:
            rep["jobs_named"] += 1
            rep["spellings_folded"] += len(from_keys)
            continue
        # ---- APPLY ----
        ems_db.upsert_job(display_name=chosen)
        for cid in card_ids:
            ems_db.set_link(into_key, ems_db.LINK_TRELLO, cid,
                            added_by="reconcile")
        for k in keys:
            ems_db.add_alias(into_key, k, source="reconcile")
            fp = folders.get(k)
            if fp:
                ems_db.set_link(into_key, ems_db.LINK_FOLDER, fp,
                                added_by="reconcile")
        res = ems_db.merge_jobs(into_key, from_keys)
        rep["jobs_named"] += 1
        rep["spellings_folded"] += res.get("merged", 0)
    return rep


if __name__ == "__main__":
    import sys
    dry = "--dry" in sys.argv or "-n" in sys.argv
    print(f"{'DRY RUN' if dry else 'APPLYING'} pin→card reconciliation…")
    r = reconcile(dry_run=dry, progress=True)
    print("\n=== result ===")
    for k in ("components_with_cards", "jobs_named", "spellings_folded",
              "skipped_no_name"):
        print(f"  {k}: {r[k]}")
    print("\n=== sample groups (up to 30) ===")
    for s in r["samples"][:30]:
        print(f"  '{s['card_name']}'  (key={s['into_key']})")
        print(f"      folds {len(s['spellings'])} spellings; cards={len(s['cards'])}")
