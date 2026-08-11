"""An alias may only ever name ONE job.

Real defect this pins: a CompanyCam project called "David Smith" was
fuzzy-matched onto `bernardo, froilan-aaa` and written as an alias while
a real `Smith, David - Mercury` already existed. `find_job_by_name`'s
alias fallback was `LIMIT 1` with no ORDER BY, so which of the two you
got depended on rowid order — it happened to return the right one, which
is exactly why nobody noticed.
"""
import pytest

import ems_db_sqlite as db


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Point the module at a scratch DB and initialise the schema."""
    p = tmp_path / "ems_jobs.db"
    monkeypatch.setattr(db, "DB_PATH", str(p))
    db._init_schema()
    return p


def _job(name, **kw):
    db.upsert_job(display_name=name, **kw)   # keyed on canon_key(display_name)


# ── the guard ──────────────────────────────────────────────────────────
def test_alias_refused_when_it_is_another_jobs_canon_key(fresh_db):
    _job("Smith, David - Mercury")          # canon_key "smith, david"
    _job("Bernardo, Froilan-AAA")
    ok = db.add_alias("bernardo, froilan-aaa", "Smith, David",
                      source="companycam")
    assert ok is False
    assert db.get_aliases("bernardo, froilan-aaa") == []


def test_alias_refused_when_already_an_alias_of_another_job(fresh_db):
    """The live shape: 'david smith' was already an alias of the real
    Smith job (comma-swap) three hours before CompanyCam guessed."""
    _job("Smith, David - Mercury")
    _job("Bernardo, Froilan-AAA")
    assert db.add_alias("smith, david", "David Smith", source="reconcile")
    ok = db.add_alias("bernardo, froilan-aaa", "David Smith",
                      source="companycam")
    assert ok is False
    assert db.get_aliases("bernardo, froilan-aaa") == []
    assert "David Smith" in db.get_aliases("smith, david")


def test_the_established_mapping_still_resolves(fresh_db):
    _job("Smith, David - Mercury")
    _job("Bernardo, Froilan-AAA")
    db.add_alias("smith, david", "David Smith", source="reconcile")
    db.add_alias("bernardo, froilan-aaa", "David Smith", source="companycam")
    j = db.find_job_by_name("David Smith")
    assert j["display_name"] == "Smith, David - Mercury"


# ── the guard must not break ordinary aliasing ─────────────────────────
def test_first_claimant_is_recorded(fresh_db):
    _job("Smith, David - Mercury")
    assert db.add_alias("smith, david", "David Smith") is True
    assert db.find_job_by_name("David Smith")["canon_key"] == "smith, david"


def test_re_adding_the_same_alias_is_still_idempotent(fresh_db):
    _job("Smith, David - Mercury")
    assert db.add_alias("smith, david", "David Smith") is True
    assert db.add_alias("smith, david", "David Smith") is True   # no-op, not refused
    assert db.get_aliases("smith, david").count("David Smith") == 1


def test_self_alias_still_refused(fresh_db):
    _job("Smith, David - Mercury")
    assert db.add_alias("smith, david", "Smith, David - Mercury") is False


def test_a_job_can_still_hold_many_distinct_aliases(fresh_db):
    _job("Smith, David - Mercury")
    assert db.add_alias("smith, david", "David Smith")
    assert db.add_alias("smith, david", "Dave Smith")
    assert set(db.get_aliases("smith, david")) == {"David Smith", "Dave Smith"}


# ── folding must still work (the guard is against GUESSES) ─────────────
def test_force_bypasses_the_guard(fresh_db):
    """merge_jobs / reconcile / import pull one job's spellings onto
    another while both rows are still live — there the collision IS the
    operation, so the guard must not fire."""
    _job("Smith, David - Mercury")
    _job("Bernardo, Froilan-AAA")
    assert db.add_alias("bernardo, froilan-aaa", "Smith, David") is False
    assert db.add_alias("bernardo, froilan-aaa", "Smith, David",
                        force=True) is True


def test_reconcile_still_folds_spellings(fresh_db):
    """reconcile aliases each live spelling onto the winner BEFORE
    merge_jobs deletes it. Without force that loop recorded nothing."""
    _job("Volkmann, Arnold")
    _job("Volkman Arnold")               # misspelt duplicate
    ems_db_add = db.add_alias("volkmann, arnold", "Volkman Arnold",
                              source="reconcile", force=True)
    assert ems_db_add is True
    db.merge_jobs("volkmann, arnold", ["volkman arnold"])
    j = db.find_job_by_name("Volkman Arnold")
    assert j is not None and j["canon_key"] == "volkmann, arnold"


def test_merge_keeps_the_losers_aliases(fresh_db):
    _job("Volkmann, Arnold")
    _job("Volkman Arnold")
    db.add_alias("volkman arnold", "Arnie Volkman")
    db.merge_jobs("volkmann, arnold", ["volkman arnold"])
    assert db.find_job_by_name("Arnie Volkman")["canon_key"] == "volkmann, arnold"


# ── deterministic resolution for rows predating the guard ──────────────
def test_ambiguous_legacy_rows_resolve_to_the_oldest(fresh_db):
    """Rows written before the guard are still in the live DB. Whatever
    they are, resolution must be stable — not rowid roulette."""
    _job("Smith, David - Mercury")
    _job("Bernardo, Froilan-AAA")
    import sqlite3
    c = sqlite3.connect(str(fresh_db))
    # Insert the wrong claimant FIRST so rowid order favours it; the
    # older added_at must still win.
    c.execute("INSERT INTO job_aliases VALUES (?,?,?,?,?)",
              ("bernardo, froilan-aaa", "David Smith", "david smith",
               "companycam", "2026-07-22T18:19:49"))
    c.execute("INSERT INTO job_aliases VALUES (?,?,?,?,?)",
              ("smith, david", "David Smith", "david smith",
               "reconcile", "2026-07-22T15:35:46"))
    c.commit()
    c.close()
    for _ in range(3):                       # stable across repeat calls
        j = db.find_job_by_name("David Smith")
        assert j["display_name"] == "Smith, David - Mercury"
