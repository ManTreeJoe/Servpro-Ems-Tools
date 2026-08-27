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


def test_each_work_type_can_be_changed_for_one_job(workspace):
    db, api = workspace
    key = db.upsert_job(display_name="Riley Stone")
    result = api.save_crm_work_environment(
        "Riley Stone", "Recon", "active", "Recon crew")
    assert result["ok"]
    master = db.get_master_job(key)
    assert master["work_environments"][0]["work_environment"] == "Recon"
    assert master["work_environments"][0]["stage"] == "active"
    assert master["work_environments"][0]["owner"] == "Recon crew"


def test_work_type_can_be_marked_not_part_of_job(workspace):
    db, api = workspace
    db.upsert_job(display_name="Only Water")
    result = api.save_crm_work_environment(
        "Only Water", "Contents", "not_applicable")
    assert result["ok"]
    loaded = api.crm_job_workspace("Only Water")
    assert loaded["work_environments"][0]["stage"] == "not_applicable"


def test_one_clear_trello_match_is_pinned_automatically(workspace, monkeypatch):
    _db, api = workspace
    monkeypatch.setattr("audit_web.persistence.get_trello_card_ids", lambda _n: [])
    monkeypatch.setattr(api, "search_trello", lambda _n: [{
        "card_id": "card-one", "name": "Stone, Riley", "board": "EMS",
        "lane": "Work in progress", "tier": "active", "score": 1.1,
    }])
    pinned = []
    monkeypatch.setattr(api, "pin_trello", lambda n, c: pinned.append((n, c)) or {"ok": True, "card_id": c})
    result = api.reconcile_crm_trello_pin("Riley Stone")
    assert result["state"] == "auto_pinned"
    assert pinned == [("Riley Stone", "card-one")]


def test_multiple_strong_trello_matches_are_a_conflict(workspace, monkeypatch):
    _db, api = workspace
    monkeypatch.setattr("audit_web.persistence.get_trello_card_ids", lambda _n: [])
    monkeypatch.setattr(api, "search_trello", lambda _n: [
        {"card_id": "a", "name": "Morgan Lee", "tier": "active", "score": 1.0},
        {"card_id": "b", "name": "Lee, Morgan", "tier": "active", "score": 1.0},
    ])
    result = api.reconcile_crm_trello_pin("Morgan Lee")
    assert result["state"] == "conflict"
    assert result["reason"] == "multiple_matches"


def test_disagreeing_saved_trello_pin_is_flagged(workspace, monkeypatch):
    _db, api = workspace
    monkeypatch.setattr("audit_web.persistence.get_trello_card_ids", lambda _n: ["old"])
    monkeypatch.setattr(api, "search_trello", lambda _n: [
        {"card_id": "new", "name": "Casey Morgan", "tier": "active", "score": 1.0},
    ])
    result = api.reconcile_crm_trello_pin("Casey Morgan")
    assert result["state"] == "conflict"
    assert result["reason"] == "saved_pin_disagrees"


def test_workspace_is_part_of_shared_job_detail():
    root = Path(__file__).resolve().parents[1]
    js = (root / "web_shared" / "audit_detail.js").read_text(encoding="utf-8")
    assert 'id="crm-workspace"' in js
    assert "crm_job_workspace" in js
    assert "save_crm_job_workspace" in js
    assert "save_crm_work_environment" in js
    assert "reconcile_crm_trello_pin" in js
    assert "Trello card conflict" in js
    for work_type in ('["EMS", "💧"', '["Contents", "▣"', '["Recon", "🔨"'):
        assert work_type in js
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


def test_job_workspace_starts_compact_and_remembers_expansion():
    root = Path(__file__).resolve().parents[1]
    js = (root / "web_shared" / "audit_detail.js").read_text(encoding="utf-8")
    for marker in ("crm-workspace-toggle", "crm-workspace-summary",
                   "crm-workspace-body", "aria-expanded",
                   "linguar.crm.workspace.expanded", "data-crm-trello-summary"):
        assert marker in js
    assert "let workspaceExpanded = false" in js


def test_job_actions_keep_primary_work_visible_and_collapse_clutter():
    root = Path(__file__).resolve().parents[1]
    js = (root / "web_shared" / "audit_detail.js").read_text(encoding="utf-8")
    assert "More job actions" in js
    assert "secondary-action" in js
    assert "show-secondary" in js


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
