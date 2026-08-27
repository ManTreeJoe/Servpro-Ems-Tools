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


def test_job_log_is_editable_and_keeps_revision_history(workspace):
    db, api = workspace
    db.upsert_job(display_name="Jordan Taylor")
    created = api.save_crm_job_log("Jordan Taylor", {
        "work_date": "2026-08-27", "work_type": "Monitor",
        "status": "scheduled", "technicians": "FB",
        "note": "Scheduled for today", "equipment": "2 AM",
    })
    assert created["ok"]
    entry = created["entry"]
    edited = api.save_crm_job_log("Jordan Taylor", {
        **entry, "status": "completed", "note": "Dry; equipment removed",
    })
    assert edited["ok"]
    rows = db.list_job_log_entries(db.canon_key("Jordan Taylor"))
    assert len(rows) == 1
    assert rows[0]["status"] == "completed"
    assert rows[0]["note"] == "Dry; equipment removed"
    history = db.job_log_history(entry["entry_id"])
    assert len(history) == 2


def test_workspace_returns_job_log(workspace):
    db, api = workspace
    key = db.upsert_job(display_name="Morgan Lee")
    db.save_job_log_entry(key, {
        "work_date": "2026-08-27", "work_type": "Demo",
        "status": "completed", "source": "pc",
    })
    result = api.crm_job_workspace("Morgan Lee")
    assert result["job_log"][0]["work_type"] == "Demo"


def test_shared_workspace_ui_has_log_editor_and_trello_import():
    root = Path(__file__).resolve().parents[1]
    js = (root / "web_shared" / "audit_detail.js").read_text(encoding="utf-8")
    for marker in ("data-log-new", "data-log-edit", "data-log-save",
                   "import_crm_job_log_from_trello", "crm_job_log_history"):
        assert marker in js


def test_trello_job_log_import_is_idempotent(workspace, monkeypatch):
    db, api = workspace
    db.upsert_job(display_name="Casey Morgan")
    monkeypatch.setattr("trello_client.get_all_comments", lambda _card: [{
        "id": "comment-1", "date": "2026-08-27T18:00:00.000Z",
        "memberCreator": {"fullName": "Field Supervisor"},
        "data": {"text": "Demo completed today."},
    }])
    first = api.import_crm_job_log_from_trello("Casey Morgan", "card-1")
    second = api.import_crm_job_log_from_trello("Casey Morgan", "card-1")
    assert first["ok"] and first["imported"] == 1
    assert second["ok"] and second["imported"] == 0
    rows = db.list_job_log_entries(db.canon_key("Casey Morgan"))
    assert len(rows) == 1
    assert len(db.job_log_history(rows[0]["entry_id"])) == 1
