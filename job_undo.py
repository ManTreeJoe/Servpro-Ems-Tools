"""A way back from an operation that rewrites job identity.

Merges, re-keys and bulk folds are the operations that hurt: they move
aliases, links and children between jobs and then delete a `jobs` row.
Every one of them was irreversible, and the damage is the quiet kind —
nothing errors, the panel repaints, and the wrong answer looks exactly
like the right one until someone goes looking weeks later.

`capture()` writes the BEFORE state of the affected keys to a dated JSON
file; `restore()` puts it back. Both go through the `ems_db` facade, so
one implementation covers SQLite and Supabase — a rule this codebase has
already been bitten by ignoring.

What restore does NOT do, said plainly rather than discovered later:

  * It rebuilds identity — the job rows, aliases, links and children —
    through the public API, so `first_seen_at` and event timestamps are
    the restore's, not the original's. Identity is what these operations
    destroy; the timestamps are not worth a second write path.
  * It does not un-delete anything the operation never touched, and it
    does not undo folder moves on disk. It is a database undo.
  * It is additive: restoring does not remove rows the operation added
    to the survivor. Re-running a merge after a restore is safe; the
    alias and link writes are idempotent.

The undo file is the artifact of record either way — even when restore
can't fully unwind something, the file says exactly what was there.
"""
import io
import json
import os

import paths

KEEP = 40                      # undo records retained
_DIRNAME = "undo"


def undo_dir():
    return paths.data(_DIRNAME)


def _stamp():
    import datetime as _dt
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _capture_key(db, key):
    """Everything that makes one job what it is."""
    out = {"canon_key": key}
    try:
        out["job"] = db.get_job(key)
    except Exception:
        out["job"] = None
    for name, fn in (("aliases", "get_aliases"),
                     ("links", "get_links"),
                     ("children", "children_of")):
        try:
            out[name] = list(getattr(db, fn)(key) or [])
        except Exception:
            out[name] = []
    return out


def _capture_bulk(keys):
    """The same per-key capture, in four reads instead of four per key.

    `_capture_key` costs get_job + get_aliases + get_links + children_of.
    That is fine for a merge of two jobs and catastrophic for a backfill:
    163 keys meant ~650 network round trips, which ran for five minutes
    and got killed halfway through the writes it was protecting.

    Whole tables are small here (a few thousand rows all told), so pull
    each once and bucket in memory. Returns None when this isn't the
    shared backend, so the caller falls back.
    """
    try:
        import ems_db as db
        if db.backend_name() != "supabase":
            return None
        import ems_db_supabase as sb
    except Exception:
        return None

    want = set(keys)
    try:
        jobs = {j["canon_key"]: j for j in sb._rows("jobs")
                if j.get("canon_key") in want}
        aliases, links, kids = {}, {}, {}
        for a in sb._rows("job_aliases"):
            if a.get("canon_key") in want:
                aliases.setdefault(a["canon_key"], []).append(a.get("alias"))
        for l in sb._rows("job_links"):
            if l.get("canon_key") in want:
                links.setdefault(l["canon_key"], []).append(l)
        for c in sb._rows("job_children"):
            if c.get("parent_canon") in want:
                kids.setdefault(c["parent_canon"], []).append(c)
    except Exception:
        return None

    return [{"canon_key": k, "job": jobs.get(k),
             "aliases": aliases.get(k, []), "links": links.get(k, []),
             "children": kids.get(k, [])} for k in keys]


def capture(keys, *, op: str, note: str = "") -> dict:
    """Record the BEFORE state of `keys`. Returns {ok, id, path, counts}.

    Never raises: a failure to write the undo file must not stop the
    operation the user asked for — it downgrades the safety net, it does
    not break the tool. The caller gets ok=False and can decide.
    """
    keys = [k for k in ({} if keys is None else keys) if (k or "").strip()]
    rec = {"op": op, "note": note, "taken_at": "", "keys": keys,
           "jobs": []}
    try:
        import ems_db as db
        from ems_db_common import _now_iso
        rec["taken_at"] = _now_iso()
        rec["backend"] = db.backend_name()
        bulk = _capture_bulk(keys) if len(keys) > 4 else None
        if bulk is not None:
            rec["jobs"] = bulk
        else:
            for k in keys:
                rec["jobs"].append(_capture_key(db, k))
    except Exception as ex:
        return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    rid = f"{_stamp()}-{op}"
    path = os.path.join(undo_dir(), f"{rid}.json")
    try:
        os.makedirs(undo_dir(), exist_ok=True)
        tmp = path + ".part"
        with io.open(tmp, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        _prune()
    except Exception as ex:
        return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    counts = {
        "jobs": sum(1 for j in rec["jobs"] if j.get("job")),
        "aliases": sum(len(j.get("aliases") or []) for j in rec["jobs"]),
        "links": sum(len(j.get("links") or []) for j in rec["jobs"]),
        "children": sum(len(j.get("children") or []) for j in rec["jobs"]),
    }
    return {"ok": True, "id": rid, "path": path, "counts": counts}


def _prune():
    try:
        mine = sorted((f for f in os.listdir(undo_dir())
                       if f.endswith(".json")), reverse=True)
        for old in mine[KEEP:]:
            try:
                os.remove(os.path.join(undo_dir(), old))
            except OSError:
                pass
    except OSError:
        pass


def list_records(limit: int = 25) -> list:
    """Newest first — {id, op, note, taken_at, keys, path}."""
    out = []
    try:
        names = sorted((f for f in os.listdir(undo_dir())
                        if f.endswith(".json")), reverse=True)
    except OSError:
        return out
    for n in names[:limit]:
        p = os.path.join(undo_dir(), n)
        try:
            with io.open(p, encoding="utf-8") as fh:
                rec = json.load(fh)
        except Exception:
            continue
        out.append({"id": n[:-5], "op": rec.get("op"),
                    "note": rec.get("note"), "taken_at": rec.get("taken_at"),
                    "keys": rec.get("keys") or [], "path": p})
    return out


def load(rec_id: str) -> dict:
    p = rec_id if os.path.isabs(rec_id) else os.path.join(
        undo_dir(), f"{rec_id}.json")
    with io.open(p, encoding="utf-8") as fh:
        return json.load(fh)


def restore(rec_id: str, *, dry_run: bool = True) -> dict:
    """Put a captured state back. Dry-run by DEFAULT.

    Returns {ok, would/did: {...}, errors: [...]}. The default matters:
    every repair script in this codebase defaults to dry-run because the
    one that didn't is how nine keys got re-written before anyone had
    read the plan.
    """
    try:
        rec = load(rec_id)
    except Exception as ex:
        return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    plan = {"jobs": [], "aliases": 0, "links": 0, "children": 0}
    for j in rec.get("jobs") or []:
        if j.get("job"):
            plan["jobs"].append(j["job"].get("display_name")
                                or j.get("canon_key"))
        plan["aliases"] += len(j.get("aliases") or [])
        plan["links"] += len(j.get("links") or [])
        plan["children"] += len(j.get("children") or [])

    if dry_run:
        return {"ok": True, "dry_run": True, "would": plan}

    errors = []
    import ems_db as db
    for j in rec.get("jobs") or []:
        key = j.get("canon_key")
        row = j.get("job") or {}
        try:
            if row.get("display_name"):
                db.upsert_job(display_name=row["display_name"],
                              claim_number=row.get("claim_number") or "",
                              carrier=row.get("carrier") or "")
        except Exception as ex:
            errors.append(f"job {key}: {ex}")
        for a in j.get("aliases") or []:
            # get_aliases() hands back bare STRINGS; get_links() hands back
            # dicts. Assuming one shape for both is what made the first
            # restore fail on its own capture.
            alias = a.get("alias") if isinstance(a, dict) else a
            if not alias:
                continue
            try:
                # force: the alias guard exists to stop one alias naming
                # two jobs, but here the other claimant is precisely what
                # we are undoing.
                db.add_alias(key, alias, source="undo", force=True)
            except Exception as ex:
                errors.append(f"alias {key}: {ex}")
        for l in j.get("links") or []:
            try:
                db.set_link(key, l.get("link_type"), l.get("link_value"),
                            added_by="undo")
            except Exception as ex:
                errors.append(f"link {key}: {ex}")
        for c in j.get("children") or []:
            try:
                db.set_child(key, c.get("name") or "",
                             kind=c.get("kind") or "",
                             ordinal=c.get("ordinal"),
                             folder_path=c.get("folder_path") or "",
                             trello_card=c.get("trello_card") or "",
                             companycam=c.get("companycam") or "",
                             department=c.get("department") or "")
            except Exception as ex:
                errors.append(f"child {key}/{c.get('name')}: {ex}")

    return {"ok": not errors, "did": plan, "errors": errors}
