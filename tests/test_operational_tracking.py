from operational_tracking import (
    project, project_stage_history, rollup, specification,
)


def test_handoff_closes_front_ops_and_starts_field():
    result = project([
        {"at": "2026-09-01T08:00:00Z", "group": "front_ops", "action": "start",
         "stage": "new", "owner": "Sam"},
        {"at": "2026-09-01T10:00:00Z", "group": "front_ops", "action": "handoff",
         "to_group": "field", "to_stage": "initial", "to_owner": "Marco"},
    ], now="2026-09-01T12:00:00Z",
       targets={"stages": {"new": 2, "initial": 1}})
    front, field, estimating = result["groups"]
    assert front["status"] == "completed"
    assert front["total_seconds"] == 7200
    assert field["status"] == "on_track"
    assert field["owner"] == "Marco"
    assert field["total_seconds"] == 7200
    assert estimating["status"] == "not_started"


def test_approved_pause_stops_controllable_clock_but_not_total():
    result = project([
        {"at": "2026-09-01T08:00:00Z", "group": "field", "action": "start"},
        {"at": "2026-09-01T09:00:00Z", "group": "field", "action": "pause",
         "category": "carrier", "reason": "Waiting for approval"},
        {"at": "2026-09-01T11:00:00Z", "group": "field", "action": "resume"},
        {"at": "2026-09-01T12:00:00Z", "group": "field", "action": "complete"},
    ], now="2026-09-01T12:00:00Z")
    field = result["groups"][1]
    assert field["total_seconds"] == 4 * 3600
    assert field["paused_seconds"] == 2 * 3600
    assert field["controllable_seconds"] == 2 * 3600


def test_custom_unapproved_pause_does_not_hide_controllable_delay():
    result = project([
        {"at": "2026-09-01T08:00:00Z", "group": "estimating", "action": "start"},
        {"at": "2026-09-01T09:00:00Z", "group": "estimating", "action": "pause",
         "category": "other", "reason": "Busy"},
        {"at": "2026-09-01T11:00:00Z", "group": "estimating", "action": "resume"},
        {"at": "2026-09-01T12:00:00Z", "group": "estimating", "action": "complete"},
    ], now="2026-09-01T12:00:00Z")
    estimating = result["groups"][2]
    assert estimating["paused_seconds"] == 0
    assert estimating["controllable_seconds"] == 4 * 3600


def test_reopen_preserves_first_period_and_tracks_second():
    result = project([
        {"at": "2026-09-01T08:00:00Z", "group": "estimating", "action": "start"},
        {"at": "2026-09-01T10:00:00Z", "group": "estimating", "action": "complete"},
        {"at": "2026-09-02T08:00:00Z", "group": "estimating", "action": "reopen"},
        {"at": "2026-09-02T09:00:00Z", "group": "estimating", "action": "complete"},
    ], now="2026-09-02T09:00:00Z")
    estimating = result["groups"][2]
    assert len(estimating["periods"]) == 2
    assert estimating["periods"][1]["reopened"] is True
    assert estimating["total_seconds"] == 3 * 3600


def test_missing_target_is_visible_instead_of_invented():
    result = project([
        {"at": "2026-09-01T08:00:00Z", "group": "field", "action": "start",
         "stage": "custom_stage"},
    ], now="2026-09-01T09:00:00Z")
    field = result["groups"][1]
    assert field["status"] == "needs_target"
    assert field["target_seconds"] is None


def test_existing_pipeline_history_rolls_up_by_operational_group():
    result = project_stage_history([
        {"from_stage": "new", "days_in_from_stage": 1, "transitioned_at": "2026-08-02"},
        {"from_stage": "initial", "days_in_from_stage": 2, "transitioned_at": "2026-08-04"},
        {"from_stage": "mitigation", "days_in_from_stage": 4, "transitioned_at": "2026-08-08"},
        {"from_stage": "estimating", "days_in_from_stage": 3, "transitioned_at": "2026-08-11"},
    ], {"current_stage": "closeout", "stage_entered_at": "2026-09-01T00:00:00Z"},
       now="2026-09-03T00:00:00Z")
    front, field, estimating = result["groups"]
    assert front["total_seconds"] == 3 * 86400
    assert field["total_seconds"] == 6 * 86400
    assert estimating["total_seconds"] == 3 * 86400
    assert result["clock_quality"] == "estimated_from_stage_history"


def test_rollup_reports_group_overdue_and_controllable_time():
    job = project_stage_history([], {
        "current_stage": "estimating", "stage_entered_at": "2026-08-20T00:00:00Z"
    }, now="2026-09-01T00:00:00Z", thresholds={"estimating": 7})
    result = rollup([job])
    estimating = result["groups"][2]
    assert estimating["jobs"] == 1
    assert estimating["active"] == 1
    assert estimating["overdue"] == 1
    assert estimating["avg_controllable_days"] == 12.0


def test_spec_keeps_official_groups_and_pause_rules_machine_readable():
    spec = specification()
    assert spec["group_order"] == ["front_ops", "field", "estimating"]
    assert spec["stage_ownership"]["closeout"] == "front_ops"
    assert "carrier" in spec["approved_pause_categories"]
    assert spec["rules"]["reopen"].startswith("reopen creates")
