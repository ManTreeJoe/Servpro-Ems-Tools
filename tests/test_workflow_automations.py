import workflow_automations as wa
import ems_db_sqlite as db


def test_starter_rules_are_review_only_and_trello_independent(tmp_path):
    original = db.DB_PATH
    try:
        db.reset_db_path(str(tmp_path / "jobs.db"))
        inventory = wa.inventory()
        assert inventory["mode"] == "review"
        assert len(inventory["rules"]) == 5
        assert all(not rule["enabled"] for rule in inventory["rules"])
        assert inventory["trello"]["status"] == "reference_adapter"
        assert {r["category"] for r in inventory["rules"]} >= {"rule", "schedule", "deadline", "job_button"}
    finally:
        db.reset_db_path(original)


def test_non_admin_cannot_activate_rule(tmp_path):
    original = db.DB_PATH
    try:
        db.reset_db_path(str(tmp_path / "jobs.db"))
        rule_id = wa.list_rules()[0]["id"]
        denied = wa.set_enabled(rule_id, True, admin=False)
        assert denied["ok"] is False
        assert wa.list_rules()[0]["enabled"] is False
    finally:
        db.reset_db_path(original)
