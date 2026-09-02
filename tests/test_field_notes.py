from datetime import date

import pytest

from field_notes import build_entry, templates
from initial_notes_parser import parse_initial_inspection_notes


def test_templates_are_small_json_safe_forms_for_every_shell():
    result = templates("ems")
    assert [item["key"] for item in result] == ["initial", "monitor", "update"]
    assert result[0]["division"] == "EMS"
    assert next(field for field in result[0]["fields"]
                if field["name"] == "work_date")["default"] == date.today().isoformat()
    assert isinstance(next(field for field in result[0]["fields"]
                           if field["name"] == "category")["options"], list)


def test_initial_note_keeps_existing_parser_labels_and_job_log_shape():
    entry = build_entry("initial", {
        "work_date": "2026-09-01", "arrival_time": "08:30",
        "met_with": "Homeowner", "cause_of_loss": "Supply line",
        "affected_areas": "Kitchen drywall and cabinets",
        "work_completed": "Extracted and placed containment",
        "next_step": "Return tomorrow", "category": "2", "loss_class": "2",
        "readings": "Kitchen drywall 45", "equipment": "2 AM in kitchen",
        "photos_taken": "Yes", "technicians": "Marco",
    }, division="ems", source_id="phone-1")
    assert entry["work_type"] == "Initial inspection"
    assert entry["work_date"] == "2026-09-01"
    assert entry["source"] == "field_note"
    assert entry["source_id"] == "phone-1"
    assert entry["division"] == "EMS"
    assert "Date: 09-01-26" in entry["note"]
    assert "Cause of Loss: Supply line" in entry["note"]
    assert "Equipment Type: 2 AM in kitchen" in entry["note"]
    assert "Readings: Kitchen drywall 45" in entry["equipment"]
    parsed = parse_initial_inspection_notes(entry["note"])[0]
    assert parsed["Affected Areas"] == "Kitchen drywall and cabinets"
    assert parsed["Work Completed"] == "Extracted and placed containment"
    assert parsed["Next Step"] == "Return tomorrow"


def test_monitor_note_is_readable_and_carries_evidence():
    entry = build_entry("monitor", {
        "work_date": "2026-09-01", "areas_checked": "Kitchen and hall",
        "progress": "Improving", "readings": "Drywall 18",
        "equipment_changes": "Moved one AM to hall",
        "next_step": "Check tomorrow",
    })
    assert entry["work_type"] == "Monitor"
    assert "Monitor notes" in entry["note"]
    assert "Drying Progress: Improving" in entry["note"]
    assert "Moisture Readings: Drywall 18" in entry["note"]
    assert "Equipment: Moved one AM to hall" in entry["equipment"]


def test_quick_update_requires_useful_content():
    with pytest.raises(ValueError, match="useful note"):
        build_entry("update", {"work_date": "2026-09-01"})


def test_quick_update_uses_mm_dd_yy_inside_human_note():
    entry = build_entry("update", {
        "work_date": "2026-09-01", "note": "Customer approved demo",
        "next_step": "Schedule crew", "status": "needs_review",
    })
    assert entry["status"] == "needs_review"
    assert "Date: 09-01-26" in entry["note"]
    assert "Next Step: Schedule crew" in entry["note"]
