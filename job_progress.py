"""Cumulative job requirements and progress reporting.

Requirements are introduced by lifecycle stage and never disappear later in
the job.  Audit findings provide evidence: a required audited item is either
missing or verified.  Operational milestones stay pending until a matching
job-log entry or lifecycle transition exists.
"""
from __future__ import annotations

from datetime import datetime


STAGES = ("intake", "contacted", "scheduled", "active", "monitoring",
          "ready_for_billing", "closeout", "closed")
STAGE_LABELS = {s: s.replace("_", " ").title() for s in STAGES}

BASE = {
    "intake": (
        ("customer_info", "Customer information verified", "office"),
        ("trello_card", "Trello card linked", "office"),
        ("job_folder", "Job folder created", "office"),
    ),
    "contacted": (
        ("customer_contact", "Customer contact confirmed", "office"),
        ("authorization", "Work authorization completed", "office"),
    ),
    "scheduled": (("initial_visit", "Initial visit scheduled", "operations"),),
    "active": (
        ("initial_photos", "Initial photos", "operations"),
        ("scope", "Scope documented", "operations"),
        ("daily_log", "Job activity recorded", "operations"),
    ),
    "monitoring": (
        ("monitor_notes", "Daily monitoring notes", "operations"),
        ("moisture_readings", "Moisture readings", "operations"),
        ("equipment_log", "Equipment placement and movement", "operations"),
    ),
    "ready_for_billing": (
        ("final_photos", "Final photos", "operations"),
        ("completion_docs", "Completion documents", "operations"),
        ("estimate_ready", "Estimate and billing file ready", "estimating"),
    ),
    "closeout": (
        ("job_log_complete", "Job Log reviewed", "office"),
        ("snapshot_complete", "Snapshot completed", "office"),
        ("destination_selected", "Destination lane selected", "office"),
    ),
    "closed": (("closed_confirmed", "Job closure confirmed", "office"),),
}

ENVIRONMENT = {
    "EMS": (
        ("ems_atp", "Authorization to Perform", "contacted", "office"),
        ("ems_cif", "Customer Information Form", "contacted", "office"),
        ("ems_initial_report", "Initial photo report", "active", "operations"),
        ("ems_drying_report", "Drying report", "ready_for_billing", "operations"),
    ),
    "Contents": (
        ("contents_authorization", "Contents authorization", "contacted", "office"),
        ("contents_inventory", "Contents inventory", "active", "operations"),
        ("contents_room_photos", "Room and item photos", "active", "operations"),
        ("contents_completion", "Pack-out or pack-back completion", "ready_for_billing", "operations"),
    ),
    "Recon": (
        ("recon_approved_scope", "Approved reconstruction scope", "active", "estimating"),
        ("recon_estimate", "Reconstruction estimate", "active", "estimating"),
        ("recon_schedule", "Reconstruction schedule", "scheduled", "operations"),
        ("recon_completion", "Reconstruction completion certificate", "ready_for_billing", "operations"),
    ),
}

JOB_TYPE = {
    "self_pay": (
        ("selfpay_contract", "Home improvement or service contract", "contacted", "office"),
        ("selfpay_deposit", "Deposit terms documented", "scheduled", "office"),
    ),
    "commercial": (
        ("commercial_agreement", "Commercial service agreement or work order", "contacted", "office"),
        ("commercial_poc", "Commercial billing contact verified", "intake", "office"),
    ),
    "management": (
        ("management_work_order", "Property-management work order", "contacted", "office"),
        ("management_poc", "Property manager and site contact verified", "intake", "office"),
    ),
}

AUDIT_ALIASES = {
    "authorization": ("auth to perform", "authorization", "atp"),
    "ems_atp": ("auth to perform", "atp"),
    "ems_cif": ("customer info", "cif"),
    "initial_photos": ("initial pics", "initial photos"),
    "ems_initial_report": ("initial photo report",),
    "scope": ("scope",),
    "final_photos": ("final pics", "final photos", "post pics", "post photos"),
    "completion_docs": ("cert of satisfaction", "certificate of completion", "cos", "cer"),
    "ems_drying_report": ("drying report",),
    "contents_inventory": ("inventory",),
    "contents_room_photos": ("room photos",),
}


def _stage_index(stage: str) -> int:
    try:
        return STAGES.index(stage)
    except ValueError:
        return 0


def _log_text(entries: list[dict]) -> str:
    return " ".join(" ".join(str(e.get(k) or "") for k in
                    ("work_type", "status", "note", "equipment"))
                    for e in entries).lower()


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _is_past(value, now):
    parsed = _parse_time(value)
    if not parsed:
        return False
    if parsed.tzinfo and not now.tzinfo:
        now = now.astimezone()
    elif now.tzinfo and not parsed.tzinfo:
        parsed = parsed.astimezone()
    return parsed < now


def evaluate(master: dict, audit: dict | None = None,
             log_entries: list[dict] | None = None) -> dict:
    audit = audit or {}
    logs = log_entries or []
    stage = master.get("lifecycle_stage") or "intake"
    if stage == "legacy_unclassified":
        stage = "intake"
    current_i = _stage_index(stage)
    findings = [str(x) for key in ("form_issues", "photo_issues", "note_issues", "requirements")
                for x in (audit.get(key) or [])]
    missing_text = " | ".join(findings).lower()
    log_text = _log_text(logs)
    trello_linked = bool(audit.get("trello_card_id"))
    folder_found = audit.get("found") is not False and bool(audit.get("folder") or audit.get("path"))
    audit_ran = any(key in audit for key in ("form_issues", "photo_issues", "requirements"))
    metadata = master.get("metadata") if isinstance(master.get("metadata"), dict) else {}
    overrides = metadata.get("requirement_overrides") or {}
    if not isinstance(overrides, dict):
        overrides = {}
    history = metadata.get("requirement_history") or []
    if not isinstance(history, list):
        history = []

    rules = []
    for introduced, entries in BASE.items():
        for key, label, owner in entries:
            rules.append((key, label, introduced, owner))
    for env in master.get("work_environments") or []:
        if (env.get("stage") or "not_applicable") == "not_applicable":
            continue
        rules.extend(ENVIRONMENT.get(env.get("work_environment"), ()))
    rules.extend(JOB_TYPE.get(master.get("job_type") or "", ()))

    now = datetime.now().astimezone()
    items = []
    for key, label, introduced, owner in rules:
        introduced_i = _stage_index(introduced)
        if introduced_i > current_i:
            continue
        aliases = AUDIT_ALIASES.get(key, ())
        explicitly_missing = any(alias in missing_text for alias in aliases)
        completed = False
        evidence = ""
        if key == "trello_card":
            completed, evidence = trello_linked, "Trello"
        elif key == "job_folder":
            completed, evidence = folder_found, "job folder"
        elif key == "daily_log":
            completed, evidence = bool(logs), "Job Log"
        elif key in ("monitor_notes", "moisture_readings", "equipment_log"):
            needles = {"monitor_notes": ("monitor", "reading"),
                       "moisture_readings": ("moisture", "reading"),
                       "equipment_log": ("equipment", "placed", "pickup", "removed")}[key]
            completed = any(n in log_text for n in needles)
            evidence = "Job Log" if completed else ""
        elif aliases and audit_ran:
            completed = not explicitly_missing
            evidence = "latest audit" if completed else ""
        elif key == "closed_confirmed":
            completed = master.get("lifecycle_stage") == "closed"
            evidence = "lifecycle"

        manual = overrides.get(key) if isinstance(overrides.get(key), dict) else {}
        manual_state = manual.get("state") or ""
        if manual_state == "reopen":
            manual_state = "todo"
        # Real evidence has precedence over a manual N/A. The manual record
        # remains in metadata/history, but the requirement reads as verified
        # as soon as the app can prove the work happened.
        if not completed and manual_state in ("completed", "not_applicable"):
            completed = manual_state == "completed"
            status = manual_state
            evidence = "manual"
        elif completed:
            status = "completed"
        else:
            status = manual_state if manual_state in ("in_progress", "blocked", "todo") else "todo"
        carried_forward = not completed and status != "not_applicable" and introduced_i < current_i
        deadline = manual.get("due_at") or ""
        follow_up = manual.get("follow_up_at") or ""
        overdue = (status not in ("completed", "not_applicable") and
                   (_is_past(deadline, now) or
                    (status == "blocked" and _is_past(follow_up, now))))
        importance = manual.get("importance") or "required"
        items.append({"key": key, "label": label, "introduced_stage": introduced,
                      "introduced_stage_label": STAGE_LABELS.get(introduced, introduced),
                      "owner": owner, "assignee": manual.get("assignee") or "",
                      "status": status, "evidence": evidence,
                      "importance": importance,
                      "overdue": overdue, "carried_forward": carried_forward,
                      "due_at": deadline, "follow_up_at": follow_up,
                      "blocked_reason": manual.get("blocked_reason") or "",
                      "manual_state": manual_state,
                      "manual_actor": manual.get("actor") or "",
                      "manual_at": manual.get("at") or "",
                      "manual_note": manual.get("note") or "",
                      "history": [entry for entry in history
                                  if isinstance(entry, dict) and
                                  entry.get("key") == key][-20:]})

    importance_rank = {"mandatory": 0, "required": 1, "recommended": 2}
    status_rank = {"blocked": 1, "in_progress": 2, "todo": 3,
                   "completed": 4, "not_applicable": 5}
    items.sort(key=lambda x: (
        0 if x["importance"] == "mandatory" and x["status"] not in
        ("completed", "not_applicable") else 1,
        0 if x["overdue"] else 1,
        status_rank.get(x["status"], 3),
        importance_rank.get(x["importance"], 1),
        x.get("follow_up_at") or x.get("due_at") or "9999",
        x["label"]))
    counts = {name: sum(1 for item in items if item["status"] == name)
              for name in status_rank}
    counts["overdue"] = sum(1 for item in items if item["overdue"])
    counts["carried_forward"] = sum(1 for item in items if item["carried_forward"])
    scored = [item for item in items if item["importance"] in
              ("mandatory", "required")]
    satisfied = sum(1 for item in scored if item["status"] in
                    ("completed", "not_applicable"))
    return {"stage": stage, "stage_label": STAGE_LABELS.get(stage, stage),
            "items": items, "counts": counts,
            "percent_complete": round(100 * satisfied / len(scored)) if scored else 100,
            "generated_at": datetime.now().isoformat(timespec="seconds")}
