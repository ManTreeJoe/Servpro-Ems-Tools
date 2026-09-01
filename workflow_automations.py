"""Linguar-owned workflow automation definitions and review-mode evaluator.

This is intentionally a deep, Trello-independent module.  UI code supplies a
small event dictionary; this module owns persistence, validation, matching,
idempotency and the audit trail.  Trello is an optional action adapter later,
never the source of truth for a rule.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

import ems_db_sqlite as _db


TRIGGERS = {
    "job_created": "Job created",
    "stage_changed": "Stage changed",
    "requirement_completed": "Requirement completed",
    "deadline": "Deadline reached",
    "inactive": "Job inactive",
    "division_completed": "Division completed",
    "closeout_requested": "Closeout requested",
    "schedule": "Scheduled time",
    "manual": "Job button",
    "board_button": "Board button",
}

ACTIONS = {
    "move_stage": "Move stage",
    "assign_user": "Assign user",
    "add_tag": "Add tag",
    "remove_tag": "Remove tag",
    "add_log": "Add job-log entry",
    "add_requirements": "Add requirements",
    "set_due_date": "Set due date",
    "notify": "Notify or escalate",
    "complete_division": "Complete division",
    "archive_job": "Archive job",
    "sync_trello": "Mirror to Trello",
}

CATEGORIES = {
    "rule": "Rules",
    "schedule": "Schedule",
    "deadline": "Deadlines",
    "job_button": "Job buttons",
    "board_button": "Board buttons",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _loads(value, fallback):
    try:
        parsed = json.loads(value or "")
        return parsed if isinstance(parsed, type(fallback)) else fallback
    except (TypeError, ValueError):
        return fallback


def _ensure_schema() -> None:
    with _db._LOCK, _db._connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS workflow_automations (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                trigger_json TEXT NOT NULL DEFAULT '{}',
                conditions_json TEXT NOT NULL DEFAULT '[]',
                actions_json TEXT NOT NULL DEFAULT '[]',
                franchise_scope TEXT NOT NULL DEFAULT 'all',
                mode TEXT NOT NULL DEFAULT 'review',
                enabled INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'linguar',
                created_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS workflow_automation_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                automation_id TEXT NOT NULL,
                event_key TEXT NOT NULL,
                job_id TEXT,
                outcome TEXT NOT NULL,
                detail_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                UNIQUE(automation_id, event_key)
            );
            CREATE INDEX IF NOT EXISTS idx_workflow_runs_job
                ON workflow_automation_runs(job_id, created_at);
        """)
        conn.commit()


STARTER_RULES = (
    {
        "name": "Prepare the next stage requirements",
        "category": "rule", "trigger_type": "stage_changed",
        "trigger": {},
        "conditions": [{"field": "stage", "operator": "is_not", "value": "closed"}],
        "actions": [{"type": "add_requirements", "value": "stage_template"}],
        "summary": "When a job changes stage, add that stage's requirements and carry unfinished work forward.",
    },
    {
        "name": "Flag overdue assigned work",
        "category": "deadline", "trigger_type": "deadline",
        "trigger": {"when": "overdue"},
        "conditions": [{"field": "status", "operator": "is_not", "value": "complete"}],
        "actions": [{"type": "notify", "value": "assigned_user_then_manager"}],
        "summary": "When required work becomes overdue, notify the assignee first and escalate after the configured delay.",
    },
    {
        "name": "Request division closeout",
        "category": "job_button", "trigger_type": "manual",
        "trigger": {"button": "Request closeout"},
        "conditions": [{"field": "required_progress", "operator": "equals", "value": 100}],
        "actions": [{"type": "complete_division", "value": "request_admin_confirmation"}],
        "summary": "A user requests closeout after Mandatory and Required items are complete; an admin confirms it.",
    },
    {
        "name": "Daily stalled-job review",
        "category": "schedule", "trigger_type": "schedule",
        "trigger": {"frequency": "weekdays", "time": "08:00"},
        "conditions": [{"field": "inactive_days", "operator": "greater_than", "value": 2}],
        "actions": [{"type": "notify", "value": "owner"}],
        "summary": "Each weekday, collect active jobs with no recent progress into one review list.",
    },
    {
        "name": "Mirror reviewed changes to Trello",
        "category": "rule", "trigger_type": "stage_changed",
        "trigger": {}, "conditions": [{"field": "trello_link", "operator": "exists", "value": True}],
        "actions": [{"type": "sync_trello", "value": "stage_comment_requirements"}],
        "summary": "While Trello is connected, mirror approved Linguar changes without making Trello the owner.",
    },
)


def seed_starter_rules() -> int:
    """Create disabled review drafts once. Safe on every startup."""
    _ensure_schema()
    with _db._LOCK, _db._connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM workflow_automations").fetchone()[0]
        if count:
            return 0
        now = _now()
        for rule in STARTER_RULES:
            conn.execute(
                """INSERT INTO workflow_automations
                (id,name,category,trigger_type,trigger_json,conditions_json,
                 actions_json,mode,enabled,source,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), rule["name"], rule["category"], rule["trigger_type"],
                 json.dumps(rule["trigger"]), json.dumps(rule["conditions"]),
                 json.dumps(rule["actions"]), "review", 0, "starter", now, now))
        conn.commit()
    return len(STARTER_RULES)


def _row(row) -> dict:
    item = dict(row)
    item["trigger"] = _loads(item.pop("trigger_json", "{}"), {})
    item["conditions"] = _loads(item.pop("conditions_json", "[]"), [])
    item["actions"] = _loads(item.pop("actions_json", "[]"), [])
    item["enabled"] = bool(item["enabled"])
    item["category_label"] = CATEGORIES.get(item["category"], item["category"])
    item["trigger_label"] = TRIGGERS.get(item["trigger_type"], item["trigger_type"])
    return item


def list_rules() -> list[dict]:
    seed_starter_rules()
    with _db._connect() as conn:
        return [_row(r) for r in conn.execute(
            "SELECT * FROM workflow_automations ORDER BY category,name")]


def set_enabled(rule_id: str, enabled: bool, *, admin: bool = False) -> dict:
    """Activation is admin-only; disabling remains safe for every caller."""
    _ensure_schema()
    if enabled and not admin:
        return {"ok": False, "error": "Admin review is required before activation."}
    with _db._LOCK, _db._connect() as conn:
        cur = conn.execute(
            "UPDATE workflow_automations SET enabled=?, updated_at=? WHERE id=?",
            (1 if enabled else 0, _now(), rule_id))
        conn.commit()
    return {"ok": bool(cur.rowcount), "enabled": bool(enabled)}


def inventory() -> dict:
    rules = list_rules()
    return {
        "mode": "review",
        "rules": rules,
        "counts": {key: sum(r["category"] == key for r in rules) for key in CATEGORIES},
        "catalog": {"categories": CATEGORIES, "triggers": TRIGGERS, "actions": ACTIONS},
        "trello": {
            "status": "reference_adapter",
            "note": "Trello history can verify outcomes, but exact Butler definitions require a one-time visual review.",
        },
    }


def recent_runs(limit: int = 50) -> list[dict]:
    _ensure_schema()
    with _db._connect() as conn:
        rows = conn.execute(
            """SELECT r.*, a.name AS automation_name
               FROM workflow_automation_runs r
               LEFT JOIN workflow_automations a ON a.id=r.automation_id
               ORDER BY r.id DESC LIMIT ?""", (max(1, min(int(limit), 200)),)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["detail"] = _loads(item.pop("detail_json", "{}"), {})
        result.append(item)
    return result

