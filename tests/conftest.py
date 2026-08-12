"""Make the scripts/ folder importable from tests/."""
import os
import sys

import pytest

_SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)


@pytest.fixture(scope="session", autouse=True)
def _isolate_job_db(tmp_path_factory):
    """Point the shared job index at a scratch file for the whole run.

    Without this the suite writes to the REAL `%APPDATA%\\Linguar Hub\\
    ems_jobs.db`. That is not theoretical — it already happened:
    `test_companycam_api` calls `find_project_id(...)`, which defaults to
    `use_graph=True` and writes its match back through
    `ems_db.resolve_and_link`. The mocked project ids `proj_1` / `proj_2`
    are sitting in live `job_links` against `bernardo, froilan-aaa` and
    `millar, john`, and that is how the bogus "David Smith" → Bernardo
    alias was created — no real CompanyCam call was ever involved.

    `reset_db_path` was written for exactly this and never wired up.
    Session-scoped + autouse so it covers every test, including ones
    added later that don't know they touch the graph.
    """
    import ems_db_sqlite as _db
    live = _db.DB_PATH
    _db.reset_db_path(str(tmp_path_factory.mktemp("jobdb") / "ems_jobs.db"))
    try:
        yield _db.DB_PATH
    finally:
        _db.reset_db_path(live)


@pytest.fixture(scope="session", autouse=True)
def _pin_db_backend(monkeypatch_session):
    """Run against SQLite regardless of what the app is set to.

    `ems_db._backend()` reads `ems_db_backend` from the live config.json,
    so flipping Settings → ☁ Shared job database → Use shared changed what
    the SUITE did. Observed 2026-08-12: 1804 passed → 8 failed / 118 errors
    with no code change, all `NotImplementedError` from the Supabase
    backend's deliberate refusals for bulk operations.

    A test result must not depend on a checkbox. This also keeps the suite
    off the network and out of the shared database entirely — the same
    instinct as `_isolate_job_db` above, one layer up.
    """
    import config
    _orig = config.load

    def _load(*a, **kw):
        cfg = _orig(*a, **kw)
        try:
            cfg["ems_db_backend"] = "sqlite"
        except Exception:
            pass
        return cfg

    monkeypatch_session.setattr(config, "load", _load)
    try:
        import ems_db
        ems_db.invalidate_backend()
    except Exception:
        pass
    yield
    try:
        import ems_db
        ems_db.invalidate_backend()
    except Exception:
        pass


@pytest.fixture(scope="session")
def monkeypatch_session():
    """Session-scoped monkeypatch — pytest's own is function-scoped."""
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="session", autouse=True)
def _isolate_log(tmp_path_factory):
    """Keep the suite out of the real ems.log.

    It was writing straight into `%APPDATA%\\Linguar Hub\\ems.log`: 536
    lines carrying fixture ids (`card-abc`, `zzconf-…`), plus ~900
    warnings from cases that fail on purpose — `rebrand migration failed
    (No space left on device)` is pytest simulating a failed copy, not a
    real disk problem. All of that buried the four genuine
    `state.json write failed: Access is denied` errors in the same file,
    which is the one thing the log is for.

    Autouse + session-scoped, like the job-DB isolation above, so a test
    added later doesn't have to know it logs.
    """
    import ems_log
    live = ems_log.log_path()
    ems_log.reset_log_path(
        str(tmp_path_factory.mktemp("emslog") / "ems.log"))
    try:
        yield ems_log.log_path()
    finally:
        ems_log.reset_log_path(live)


@pytest.fixture(scope="session")
def tk_root():
    """Single Tk root shared across the whole test session.

    Tk doesn't allow multiple roots in one process — module-scoped
    fixtures in different test files would conflict and the later module
    would skip. Hoisting to session scope lets every Tk-using test share
    one withdrawn root.
    """
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
    except Exception as ex:
        pytest.skip(f"Tk display not available: {ex}")
    yield r
    try:
        r.destroy()
    except Exception:
        pass
