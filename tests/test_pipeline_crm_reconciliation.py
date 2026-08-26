import pytest


@pytest.fixture()
def crm(tmp_path, monkeypatch):
    import ems_db_sqlite as db
    import pipeline_stages as ps
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "crm.db"))
    db._init_schema()
    monkeypatch.setattr(ps, "ems_db", db)
    return db, ps


def _row(name, pipeline_stage, board="IE EMS", activity="2026-08-01"):
    return {
        "card_id": f"{name}-{pipeline_stage}-{board}",
        "client_display": name,
        "current_stage": pipeline_stage,
        "board_name": board,
        "last_activity_at": activity,
        "owner": "",
    }


def test_one_trello_track_updates_master_and_department(crm):
    db, ps = crm
    key = db.upsert_job(display_name="Jones, Taylor")
    result = ps.reconcile_crm_lifecycle([
        _row("Jones, Taylor", "mitigation")])
    job = db.get_master_job(key)
    assert result["master_stages"] == 1
    assert job["lifecycle_stage"] == "active"
    assert job["lifecycle_source"] == "trello"
    assert job["work_environments"][0]["work_environment"] == "EMS"
    assert job["work_environments"][0]["stage"] == "mitigation"


def test_manual_master_stage_is_never_overwritten(crm):
    db, ps = crm
    key = db.upsert_job(display_name="Morgan, Avery")
    db.set_master_job_state(key, lifecycle_stage="monitoring", source="manual")
    result = ps.reconcile_crm_lifecycle([
        _row("Morgan, Avery", "closeout")])
    job = db.get_master_job(key)
    assert result["manual_preserved"] == 1
    assert job["lifecycle_stage"] == "monitoring"
    assert job["work_environments"][0]["stage"] == "closeout"


def test_conflicting_departments_are_preserved_for_review(crm):
    db, ps = crm
    key = db.upsert_job(display_name="River Apartments - Unit 4")
    result = ps.reconcile_crm_lifecycle([
        _row("River Apartments - Unit 4", "mitigation", "IE EMS"),
        _row("River Apartments - Unit 4", "estimating", "IE Recon"),
    ])
    job = db.get_master_job(key)
    assert result["master_stages"] == 0
    assert result["ambiguous"] == [{
        "canon_key": key, "stages": ["active", "ready_for_billing"]}]
    assert job["lifecycle_stage"] == "intake"
    assert {x["work_environment"] for x in job["work_environments"]} == {
        "EMS", "Recon"}


def test_unknown_trello_card_is_reported_not_created(crm):
    db, ps = crm
    result = ps.reconcile_crm_lifecycle([
        _row("Not In The Job Index", "new")])
    assert result["unknown"][0]["name"] == "Not In The Job Index"
    assert db.iter_jobs() == []
