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
