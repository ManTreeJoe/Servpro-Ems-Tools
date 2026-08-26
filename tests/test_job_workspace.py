from pathlib import Path

import pytest


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    import audit_web
    import ems_db
    import ems_db_sqlite as db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "workspace.db"))
    db._init_schema()
    ems_db.use_backend("sqlite")
    yield db, audit_web.Api()
    ems_db.invalidate_backend()


def test_workspace_loads_master_and_three_department_states(workspace):
    db, api = workspace
    key = db.upsert_job(display_name="Taylor Jones")
    db.set_work_environment_state(key, "EMS", stage="active", owner="Sam")
    result = api.crm_job_workspace("Taylor Jones")
    assert result["ok"]
    assert result["job_id"]
    assert result["lifecycle_stage"] == "intake"
    assert result["work_environments"][0]["work_environment"] == "EMS"


def test_workspace_edit_is_marked_manual(workspace):
    db, api = workspace
    key = db.upsert_job(display_name="Avery Morgan")
    result = api.save_crm_job_workspace("Avery Morgan", {
        "lifecycle_stage": "monitoring",
        "job_type": "commercial",
        "priority": "urgent",
    })
    assert result["ok"]
    job = db.get_job(key)
    assert job["lifecycle_stage"] == "monitoring"
    assert job["job_type"] == "commercial"
    assert job["priority"] == "urgent"
    assert job["lifecycle_source"] == "manual"


def test_workspace_is_part_of_shared_job_detail():
    root = Path(__file__).resolve().parents[1]
    js = (root / "web_shared" / "audit_detail.js").read_text(encoding="utf-8")
    assert 'id="crm-workspace"' in js
    assert "crm_job_workspace" in js
    assert "save_crm_job_workspace" in js
    assert '["EMS", "Contents", "Recon"]' in js
    assert "@media(max-width:700px)" in js
