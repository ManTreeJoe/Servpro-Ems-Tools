from job_progress import evaluate


def _master(stage="active", envs=None, job_type="insurance"):
    return {"lifecycle_stage": stage, "job_type": job_type,
            "work_environments": envs or [
                {"work_environment": "EMS", "stage": "active"}]}


def test_previous_requirements_carry_forward_without_inventing_a_deadline():
    result = evaluate(_master("active"), {
        "form_issues": ["Auth to Perform"], "photo_issues": ["Initial pics"],
        "requirements": [], "found": True, "folder": "X:/job",
        "trello_card_id": "card-1",
    }, [])
    by_key = {item["key"]: item for item in result["items"]}
    assert by_key["ems_atp"]["status"] == "todo"
    assert by_key["ems_atp"]["carried_forward"] is True
    assert by_key["ems_atp"]["overdue"] is False
    assert by_key["initial_photos"]["status"] == "todo"
    assert by_key["trello_card"]["status"] == "completed"


def test_work_type_requirements_are_per_job():
    contents = evaluate(_master(envs=[
        {"work_environment": "Contents", "stage": "active"}]), {}, [])
    keys = {item["key"] for item in contents["items"]}
    assert "contents_inventory" in keys
    assert "ems_drying_report" not in keys


def test_job_type_adds_commercial_requirements():
    result = evaluate(_master(stage="contacted", job_type="commercial"), {}, [])
    assert {"commercial_agreement", "commercial_poc"}.issubset(
        {item["key"] for item in result["items"]})


def test_completed_requirements_remain_visible():
    result = evaluate(_master("monitoring"), {
        "form_issues": [], "photo_issues": [], "requirements": [],
        "found": True, "folder": "X:/job", "trello_card_id": "card-1",
    }, [{"work_type": "Monitor", "status": "completed",
          "note": "Moisture readings complete; equipment removed"}])
    assert result["counts"]["completed"] > 0
    assert any(item["status"] == "completed" and
               item["key"] == "moisture_readings" for item in result["items"])


def test_manual_requirement_states_count_as_satisfied():
    master = _master("active")
    master["metadata"] = {"requirement_overrides": {
        "scope": {"state": "completed", "actor": "Nathan", "at": "2026-08-31T10:00:00-07:00", "note": "Reviewed"},
        "initial_photos": {"state": "not_applicable", "actor": "Nathan", "at": "2026-08-31T10:01:00-07:00", "note": "Service call"},
    }}
    result = evaluate(master, {}, [])
    by_key = {item["key"]: item for item in result["items"]}
    assert by_key["scope"]["status"] == "completed"
    assert by_key["scope"]["manual_actor"] == "Nathan"
    assert by_key["initial_photos"]["status"] == "not_applicable"
    assert result["counts"]["not_applicable"] == 1


def test_automatic_evidence_wins_over_manual_not_applicable():
    master = _master("active")
    master["metadata"] = {"requirement_overrides": {
        "initial_photos": {"state": "not_applicable", "actor": "Nathan"},
    }}
    result = evaluate(master, {"photo_issues": [], "form_issues": [],
                               "requirements": [], "found": True}, [])
    item = next(item for item in result["items"] if item["key"] == "initial_photos")
    assert item["status"] == "completed"
    assert item["evidence"] == "latest audit"


def test_blocked_follow_up_date_drives_overdue_label():
    master = _master("active")
    master["metadata"] = {"requirement_overrides": {
        "scope": {"state": "blocked", "assignee": "Office",
                  "blocked_reason": "Waiting for approval",
                  "follow_up_at": "2020-01-01T08:00:00-08:00"},
    }}
    item = next(item for item in evaluate(master, {}, [])["items"]
                if item["key"] == "scope")
    assert item["status"] == "blocked"
    assert item["overdue"] is True


def test_clean_compact_ui_markers_exist():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "web_shared" /
          "audit_detail.js").read_text(encoding="utf-8")
    for marker in ("crm-progress-rail", "Overdue from earlier stages",
                   "Required now", "Completed &amp; history"):
        assert marker in js
