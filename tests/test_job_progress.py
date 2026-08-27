from job_progress import evaluate


def _master(stage="active", envs=None, job_type="insurance"):
    return {"lifecycle_stage": stage, "job_type": job_type,
            "work_environments": envs or [
                {"work_environment": "EMS", "stage": "active"}]}


def test_previous_requirements_carry_forward_as_overdue():
    result = evaluate(_master("active"), {
        "form_issues": ["Auth to Perform"], "photo_issues": ["Initial pics"],
        "requirements": [], "found": True, "folder": "X:/job",
        "trello_card_id": "card-1",
    }, [])
    by_key = {item["key"]: item for item in result["items"]}
    assert by_key["ems_atp"]["status"] == "overdue"
    assert by_key["initial_photos"]["status"] == "required_now"
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


def test_clean_compact_ui_markers_exist():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "web_shared" /
          "audit_detail.js").read_text(encoding="utf-8")
    for marker in ("crm-progress-rail", "Overdue from earlier stages",
                   "Required now", "Completed &amp; history"):
        assert marker in js

