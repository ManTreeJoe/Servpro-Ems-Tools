"""Schema v6 — the job facts become queryable columns.

`job_settings` has always parsed ~30 facts off the Trello card, but only
four had columns; the rest sat in `metadata_json` where nothing can
filter, group or report on them. v6 promotes the ones people ask
questions about, including the WorkCenter project id.
"""
import pytest

import ems_db_sqlite as db
import job_settings


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "ems_jobs.db"))
    db._init_schema()
    return db


# ── the columns exist and round-trip ───────────────────────────────────
def test_every_crm_column_round_trips(fresh):
    vals = {c: f"v-{c}" for c in db.CRM_COLUMNS}
    key = fresh.upsert_job(display_name="Smith, David - Mercury", **vals)
    job = fresh.get_job(key)
    for col, want in vals.items():
        assert job[col] == want, col


def test_wc_project_id_is_stored_and_queryable(fresh):
    fresh.upsert_job(display_name="Smith, David - Mercury",
                     wc_project_id="2607-379246WTR")
    import sqlite3
    c = sqlite3.connect(fresh.DB_PATH)
    got = c.execute("SELECT canon_key FROM jobs WHERE wc_project_id=?",
                    ("2607-379246WTR",)).fetchall()
    assert [r[0] for r in got] == ["smith, david"]


def test_partial_update_never_blanks_a_crm_field(fresh):
    """The whole point of the rule: a Trello sync that knows nothing
    about the adjuster must not erase one somebody typed."""
    key = fresh.upsert_job(display_name="Smith, David - Mercury",
                           adjuster_name="Jane Doe",
                           wc_project_id="2607-379246WTR")
    fresh.upsert_job(display_name="Smith, David - Mercury", carrier="Mercury")
    job = fresh.get_job(key)
    assert job["adjuster_name"] == "Jane Doe"
    assert job["wc_project_id"] == "2607-379246WTR"
    assert job["carrier"] == "Mercury"


def test_a_supplied_value_does_overwrite(fresh):
    key = fresh.upsert_job(display_name="Smith, David - Mercury",
                           adjuster_name="Jane Doe")
    fresh.upsert_job(display_name="Smith, David - Mercury",
                     adjuster_name="John Roe")
    assert fresh.get_job(key)["adjuster_name"] == "John Roe"


def test_unknown_keyword_raises_rather_than_vanishing(fresh):
    """Driving the columns off one list means a typo would otherwise be
    swallowed into **crm and silently dropped."""
    with pytest.raises(TypeError) as ex:
        fresh.upsert_job(display_name="X", adjustor_name="typo")
    assert "adjustor_name" in str(ex.value)


def test_schema_version_is_10(fresh):
    """A fresh file must STAMP v10 — the migration runner and the Supabase
    side both branch on this."""
    import sqlite3
    assert db.SCHEMA_VERSION == 10
    c = sqlite3.connect(fresh.DB_PATH)
    got = c.execute("SELECT value FROM meta WHERE key='schema_version'"
                    ).fetchone()
    assert got and int(got[0]) == 10


def test_columns_are_added_to_a_pre_v6_database(tmp_path, monkeypatch):
    """Existing installs get the columns by ALTER, not by recreate — the
    CREATE TABLE is a no-op once the file exists."""
    import sqlite3
    p = tmp_path / "old.db"
    c = sqlite3.connect(str(p))
    c.executescript("""
        CREATE TABLE jobs (
            canon_key TEXT PRIMARY KEY, display_name TEXT NOT NULL,
            claim_number TEXT, carrier TEXT, loss_type TEXT, year INTEGER,
            status TEXT, date_received TEXT, first_seen_at TEXT,
            last_seen_at TEXT, metadata_json TEXT);
    """)
    c.execute("INSERT INTO jobs (canon_key, display_name) VALUES (?,?)",
              ("smith, david", "Smith, David - Mercury"))
    c.commit()
    c.close()

    monkeypatch.setattr(db, "DB_PATH", str(p))
    db._init_schema()
    cols = {r[1] for r in sqlite3.connect(str(p)).execute(
        "PRAGMA table_info(jobs)")}
    assert set(db.CRM_COLUMNS) <= cols
    # and the pre-existing row survived
    assert db.get_job("smith, david")["display_name"] == "Smith, David - Mercury"


# ── job_settings writes them ───────────────────────────────────────────
def test_column_fields_cover_the_crm_columns():
    """Every promoted column must be reachable from a card field, or the
    column exists and nothing can ever fill it."""
    mapped = set(job_settings.COLUMN_FIELDS.values())
    missing = set(db.CRM_COLUMNS) - mapped
    assert not missing, f"columns with no card field: {sorted(missing)}"


def test_column_fields_reference_real_fields():
    for fid in job_settings.COLUMN_FIELDS:
        assert fid in job_settings.BY_ID, f"{fid} is not a declared field"


def test_column_fields_reference_real_columns():
    known = set(db._TEXT_COLUMNS)
    for fid, col in job_settings.COLUMN_FIELDS.items():
        assert col in known, f"{fid} maps to unknown column {col}"


def test_stored_values_prefers_the_column_over_the_blob(fresh):
    """A column and a stale blob entry can disagree; the column wins,
    otherwise promoting the field changed nothing."""
    rec = {"adjuster_name": "From Column",
           "metadata_json": '{"settings": {"adjuster_name": "From Blob"}}'}
    assert job_settings.stored_values(rec)["adjuster_name"] == "From Column"


def test_blank_column_falls_back_to_the_blob(fresh):
    rec = {"adjuster_name": "",
           "metadata_json": '{"settings": {"adjuster_name": "From Blob"}}'}
    assert job_settings.stored_values(rec)["adjuster_name"] == "From Blob"


# ── both backends agree on the field list ──────────────────────────────
def test_supabase_upsert_accepts_the_same_fields():
    """The two backends import ONE column list; if they drift, a field
    saved locally silently disappears on the cloud backend."""
    import inspect

    import ems_db_supabase as sb
    src = inspect.getsource(sb.upsert_job)
    assert "CRM_COLUMNS" in src and "_TEXT_COLUMNS" in src
    sig = inspect.signature(sb.upsert_job)
    assert any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values())


def test_supabase_migration_covers_every_column():
    """005_crm_columns.sql must add every CRM column, or a cloud save
    400s on the missing one."""
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sql = open(os.path.join(here, "supabase", "005_crm_columns.sql"),
               encoding="utf-8").read().lower()
    for col in db.CRM_COLUMNS:
        assert f"add column if not exists {col} " in sql, \
            f"{col} missing from the Supabase migration"
