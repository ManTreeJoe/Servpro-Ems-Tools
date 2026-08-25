"""Job index — storage-backend façade.

Every tool imports `ems_db` and calls the same functions it always has.
This module owns nothing except the choice of WHERE those calls land:

    ems_db.py            <- you are here; picks a backend, delegates
      ems_db_sqlite.py     local SQLite (default, offline, today)
      ems_db_supabase.py   shared Postgres over PostgREST

The seam is at the FUNCTION boundary, not at SQL. `ems_db` was already a
repository API — `find_job_by_name`, `set_link`, `resolve_and_link` — so a
second implementation only has to satisfy those ~40 functions. Abstracting
at SQL instead would have meant a dialect translator plus rewriting all 71
statements, and would still leave the client holding a database password.

Delegation is by module `__getattr__` rather than a hand-written wrapper
per function, deliberately: a wrapper list silently rots the moment someone
adds a function to a backend and forgets the façade (the same failure mode
as the setattr-binding rule elsewhere in this codebase). With `__getattr__`
there is no list to forget.

Because Python only calls module `__getattr__` for names NOT found normally,
`monkeypatch.setattr(ems_db, "find_job_by_name", ...)` still works: the
patched attribute is found first and shadows the delegation.

Switching backends
------------------
Set `ems_db_backend` in config.json to "sqlite" (default) or "supabase".
An unknown value falls back to sqlite with a logged warning rather than
taking the app down. Call `invalidate_backend()` after changing it — the
resolved backend is cached, since re-reading config on every attribute
access would deep-copy the config dict thousands of times per render.
"""
import importlib

_BACKENDS = {
    "sqlite":   "ems_db_sqlite",
    # Not ems_db_supabase directly: ems_db_offline wraps it so a dropped
    # connection degrades to the local mirror instead of raising into the
    # UI. It is a pass-through whenever the network is fine.
    "supabase": "ems_db_offline",
}
_DEFAULT = "sqlite"

_active_mod = None
_active_name = None


def _resolve_name():
    """Backend key from config, defaulting to sqlite. Never raises — a
    broken config must not make the job index unreachable."""
    try:
        import config
        name = (config.load().get("ems_db_backend") or "").strip().lower()
    except Exception:
        return _DEFAULT
    if not name:
        return _DEFAULT
    if name not in _BACKENDS:
        try:
            import ems_log
            ems_log.warn("ems_db",
                         f"unknown ems_db_backend {name!r}; using {_DEFAULT}")
        except Exception:
            pass
        return _DEFAULT
    return name


def _backend():
    global _active_mod, _active_name
    if _active_mod is None:
        name = _resolve_name()
        _active_mod = importlib.import_module(_BACKENDS[name])
        _active_name = name
    return _active_mod


def backend_name() -> str:
    """Which backend is serving calls right now ('sqlite' / 'supabase')."""
    _backend()
    return _active_name


def use_backend(name: str):
    """Force a backend for this process, ignoring config. Returns the
    module. Used by the conformance suite to run the SAME tests against
    both implementations, which is what proves them equivalent."""
    name = (name or "").strip().lower()
    if name not in _BACKENDS:
        raise ValueError(f"unknown backend {name!r}; "
                         f"expected one of {sorted(_BACKENDS)}")
    global _active_mod, _active_name
    _active_mod = importlib.import_module(_BACKENDS[name])
    _active_name = name
    return _active_mod


def invalidate_backend():
    """Drop the cached backend so the next call re-reads config. Call after
    a settings save or a department switch."""
    global _active_mod, _active_name
    _active_mod = None
    _active_name = None


def __getattr__(name):
    # Dunders are asked for by the import machinery, pickle, and inspect —
    # answering them from a backend module would be wrong and can recurse.
    if name.startswith("__") and name.endswith("__"):
        raise AttributeError(name)
    return getattr(_backend(), name)


def __dir__():
    try:
        return sorted(set(globals()) | set(dir(_backend())))
    except Exception:
        return sorted(globals())


# ── merge: the one call that rewrites identity ──────────────────────────
#
# Defined here rather than left to __getattr__ on purpose. A merge folds
# jobs together and DELETES rows; it is the single most destructive thing
# the index can do, and it had neither a preview nor a way back. Putting
# both at the façade means every caller gets them without being changed —
# the same chokepoint argument as the shim's _track.
#
# Six of the seven callers route through here. `migrate_canon_carrier_keys`
# imports ems_db_sqlite directly and so bypasses this; it is a one-off
# maintenance script, and any NEW repair script should import ems_db.


def merge_preview(into_key: str, from_keys) -> dict:
    """What a merge would move, before it moves it.

    Read-only. Returns the survivor, a per-loser breakdown, and totals —
    including each child by NAME, because "3 children" and "Unit 585-G,
    Unit 561-I, Unit 880-A" are very different things to read in a
    confirmation dialog.
    """
    b = _backend()
    into_key = (into_key or "").strip()
    into = None
    try:
        into = b.get_job(into_key)
    except Exception:
        pass
    into_dept = (into or {}).get("department")

    losers, missing, conflicts = [], [], []
    for fk in from_keys or ():
        fk = (fk or "").strip()
        if not fk or fk == into_key:
            continue
        try:
            row = b.get_job(fk)
        except Exception:
            row = None
        if row is None:
            missing.append(fk)
            continue
        # Mirrors merge_jobs' own rule so the preview cannot promise a
        # fold the merge will refuse.
        if into_dept and row.get("department") and \
                row["department"] != into_dept:
            conflicts.append(fk)
            continue
        try:
            aliases = list(b.get_aliases(fk) or [])
        except Exception:
            aliases = []
        try:
            links = list(b.get_links(fk) or [])
        except Exception:
            links = []
        try:
            kids = list(b.children_of(fk) or [])
        except Exception:
            kids = []
        losers.append({
            "canon_key": fk,
            "display_name": row.get("display_name") or fk,
            "aliases": len(aliases),
            "links": len(links),
            "link_types": sorted({l.get("link_type") for l in links
                                  if l.get("link_type")}),
            "children": [c.get("name") for c in kids],
        })

    return {
        "into": {"canon_key": into_key,
                 "display_name": (into or {}).get("display_name") or into_key,
                 "exists": into is not None},
        "from": losers,
        "missing": missing,
        "department_conflicts": conflicts,
        "totals": {
            "jobs": len(losers),
            "aliases": sum(l["aliases"] for l in losers),
            "links": sum(l["links"] for l in losers),
            "children": sum(len(l["children"]) for l in losers),
        },
    }


def merge_jobs(into_key: str, from_keys, *, undo: bool = True,
               note: str = "") -> dict:
    """Fold jobs together, recording a way back first.

    The undo captures the SURVIVOR as well as the losers: a merge changes
    the survivor too (it gains their aliases, links and children), so a
    record of only the losers describes half the change.

    `undo=False` exists for tests and for callers already inside their own
    transaction. A failed capture does NOT block the merge — it downgrades
    the safety net rather than breaking the tool — but `undo_id` is then
    absent from the result, which is how a caller can tell.
    """
    keys = [into_key] + [k for k in (from_keys or ())]
    rec = None
    if undo:
        try:
            import job_undo
            rec = job_undo.capture(
                keys, op="merge",
                note=note or f"merge {len(keys) - 1} into {into_key}")
        except Exception:
            rec = None
    res = _backend().merge_jobs(into_key, from_keys) or {}
    if isinstance(res, dict) and rec and rec.get("ok"):
        res["undo_id"] = rec["id"]
    return res


def delete_job(canon_key: str, *, undo: bool = True,
               note: str = "") -> dict:
    """Remove one Hub job record, recording its identity first.

    This never deletes an OD folder or an external Trello/CompanyCam job;
    those are links recorded on the job, not resources owned by this index.
    """
    canon_key = (canon_key or "").strip()
    if not canon_key:
        return {"deleted": 0}
    rec = None
    if undo:
        try:
            import job_undo
            rec = job_undo.capture(
                [canon_key], op="delete",
                note=note or f"delete {canon_key}")
        except Exception:
            rec = None
    res = _backend().delete_job(canon_key) or {}
    if isinstance(res, dict) and rec and rec.get("ok"):
        res["undo_id"] = rec["id"]
    return res
