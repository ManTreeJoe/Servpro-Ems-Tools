import sqlite3

import pytest


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    import ems_db_sqlite as db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "crm.db"))
    db._init_schema()
    return db


def test_new_job_has_permanent_id_and_starts_at_intake(fresh):
    key = fresh.upsert_job(display_name="Jones, Taylor")
    job = fresh.get_master_job(key)
    assert job["job_id"]
    assert job["lifecycle_stage"] == "intake"
    assert fresh.get_job_by_id(job["job_id"])["canon_key"] == key


def test_three_work_environments_share_one_master_job(fresh):
    key = fresh.upsert_job(display_name="River Apartments - Unit 4")
    job_id = fresh.get_job(key)["job_id"]
    fresh.set_work_environment_state(key, "EMS", stage="active", owner="Sam")
    fresh.set_work_environment_state(key, "Contents", stage="scheduled")
    fresh.set_work_environment_state(key, "Recon", stage="estimating")
    master = fresh.get_master_job(key)
    assert master["job_id"] == job_id
    assert [x["work_environment"] for x in master["work_environments"]] == [
        "EMS", "Contents", "Recon"]
    assert master["work_environments"][0]["owner"] == "Sam"


def test_overall_lifecycle_is_separate_from_trello_status(fresh):
    key = fresh.upsert_job(display_name="Morgan, Avery", status="On Site")
    fresh.set_master_job_state(
        key, lifecycle_stage="active", job_type="insurance", priority="high")
    job = fresh.get_job(key)
    assert job["status"] == "On Site"
    assert job["lifecycle_stage"] == "active"
    assert job["job_type"] == "insurance"
    assert job["priority"] == "high"
    assert job["stage_entered_at"]


def test_invalid_master_values_are_rejected(fresh):
    key = fresh.upsert_job(display_name="Invalid Example")
    with pytest.raises(ValueError):
        fresh.set_master_job_state(key, lifecycle_stage="whatever")
    with pytest.raises(ValueError):
        fresh.set_work_environment_state(key, "Roofing")


def test_existing_database_is_preserved_and_marked_legacy(tmp_path, monkeypatch):
    import ems_db_sqlite as db
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as c:
        c.executescript("""
            CREATE TABLE jobs (
                canon_key TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                status TEXT
            );
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
            INSERT INTO jobs(canon_key, display_name, status)
            VALUES ('old job', 'Old Job', 'In Progress');
        """)
    monkeypatch.setattr(db, "DB_PATH", str(path))
    db._init_schema()
    job = db.get_job("old job")
    assert job["display_name"] == "Old Job"
    assert job["status"] == "In Progress"
    assert job["job_id"]
    assert job["lifecycle_stage"] == "legacy_unclassified"


def test_jobs_can_be_related_without_being_merged(fresh):
    parent = fresh.upsert_job(display_name="Avana Springs Management")
    child = fresh.upsert_job(display_name="River Claim")
    parent_id = fresh.get_job(parent)["job_id"]
    child_id = fresh.get_job(child)["job_id"]
    assert fresh.relate_jobs(parent, child, "parent_child", created_by="Nathan")
    assert not fresh.relate_jobs(parent, child, "parent_child")
    relationships = fresh.get_master_job(parent)["relationships"]
    assert relationships[0]["related_canon_key"] == child
    assert relationships[0]["related_display_name"] == "River Claim"
    assert fresh.get_job(parent)["job_id"] == parent_id
    assert fresh.get_job(child)["job_id"] == child_id
    assert fresh.remove_job_relationship(parent, child, "parent_child")
    assert fresh.get_job_relationships(parent) == []


def test_relationships_reject_self_links_and_unknown_types(fresh):
    key = fresh.upsert_job(display_name="One Job")
    other = fresh.upsert_job(display_name="Other Job")
    with pytest.raises(ValueError):
        fresh.relate_jobs(key, key, "related_claim")
    with pytest.raises(ValueError):
        fresh.relate_jobs(key, other, "made_up")
