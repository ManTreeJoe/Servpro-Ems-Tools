"""Operational ownership clocks for Front Operations, Field, and Estimating.

The official SERVPRO franchise scorecard answers *how the franchise scored*.
This module answers the internal question needed to improve it: *which group
owned each part of the elapsed time?*

The projection is intentionally pure.  Trello transitions, Linguar Hub job
events, mobile notes, and future integrations can all be adapted into the
small event interface below without teaching the calculator about a vendor.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from statistics import median


GROUP_ORDER = ("front_ops", "field", "estimating")

GROUPS = {
    "front_ops": {
        "label": "Front Operations",
        "purpose": "Intake, customer contact, scheduling, closeout, and receivables handoffs.",
    },
    "field": {
        "label": "Field",
        "purpose": "Initial inspection, active production, monitoring, and field completion evidence.",
    },
    "estimating": {
        "label": "Estimating",
        "purpose": "Estimate preparation, submission, revision, and estimating-file completion.",
    },
}

# This maps the Pipeline stages already used by the app to the group that owns
# the clock.  It does not replace division-specific stages.  EMS, Contents,
# and Recon keep their own detail while rolling up to the same three groups.
STAGE_OWNERSHIP = {
    "new": "front_ops",
    "initial": "field",
    "mitigation": "field",
    "closeout": "front_ops",
    "estimating": "estimating",
    "submitted": "estimating",
    "approved": "front_ops",
    "ar": "front_ops",
    "paid": None,
}

# These are the existing configurable Pipeline thresholds.  They are kept in
# one visible specification here so department reporting and the board agree.
# They are current app defaults, not a claim that every client program has the
# same SLA.  More-specific configured rules override them.
DEFAULT_STAGE_TARGET_DAYS = {
    "new": 2,
    "initial": 3,
    "mitigation": 14,
    "closeout": 5,
    "estimating": 7,
    "submitted": 14,
    "approved": 5,
    "ar": 30,
}

ACTIONS = ("start", "pause", "resume", "complete", "handoff", "reopen")
APPROVED_PAUSE_CATEGORIES = (
    "customer", "carrier", "weather", "access", "material", "subcontractor",
)


def _parse_at(value) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str:
    return value.astimezone(timezone.utc).isoformat() if value else ""


def _seconds(start: datetime | None, end: datetime | None) -> float:
    if not start or not end:
        return 0.0
    return max(0.0, (end - start).total_seconds())


def _new_group(key: str) -> dict:
    return {
        "key": key,
        "label": GROUPS[key]["label"],
        "status": "not_started",
        "owner": "",
        "periods": [],
        "total_seconds": 0.0,
        "paused_seconds": 0.0,
        "controllable_seconds": 0.0,
        "target_seconds": None,
        "due_at": "",
        "overdue": False,
    }


def _target_seconds(group: str, stage: str, targets: dict) -> float | None:
    """Most-specific target wins: stage, then group, otherwise unset."""
    stage_value = (targets.get("stages") or {}).get(stage)
    group_value = (targets.get("groups") or {}).get(group)
    value = stage_value if stage_value is not None else group_value
    if value is None:
        return None
    try:
        return max(0.0, float(value)) * 86400.0
    except (TypeError, ValueError):
        return None


def project(events: list[dict], *, now=None, targets: dict | None = None) -> dict:
    """Project raw ownership events into department clocks.

    Required event fields are ``at``, ``group``, and ``action``.  A handoff
    may also include ``to_group``.  Approved pauses stop controllable time;
    custom/unapproved reasons remain visible but do not stop that clock.
    Reopen begins a new work period so the original completion remains intact.
    """
    now_dt = _parse_at(now or datetime.now(timezone.utc))
    targets = targets or {}
    groups = {key: _new_group(key) for key in GROUP_ORDER}
    normalized = []
    warnings = []
    for index, raw in enumerate(events or []):
        try:
            at = _parse_at(raw.get("at") or raw.get("event_at"))
        except (TypeError, ValueError):
            warnings.append(f"event {index + 1} has no valid timestamp")
            continue
        group = str(raw.get("group") or "").strip().lower()
        action = str(raw.get("action") or "").strip().lower()
        if group not in groups or action not in ACTIONS:
            warnings.append(f"event {index + 1} has an unknown group or action")
            continue
        normalized.append({**raw, "at": at, "group": group, "action": action,
                           "_order": index})
    normalized.sort(key=lambda item: (item["at"], item["_order"]))

    active = {key: None for key in GROUP_ORDER}
    for event in normalized:
        group, action, at = event["group"], event["action"], event["at"]
        state = groups[group]
        period = active[group]

        if action in ("start", "reopen"):
            if period and not period.get("ended_at"):
                warnings.append(f"{state['label']} started again before its open period ended")
                continue
            period = {
                "started_at": _iso(at), "ended_at": "", "stage": event.get("stage") or "",
                "owner": event.get("owner") or "", "pauses": [], "active_pause": None,
                "source": event.get("source") or "", "source_id": event.get("source_id") or "",
                "reopened": action == "reopen",
            }
            state["periods"].append(period)
            active[group] = period
            state["owner"] = period["owner"] or state["owner"]
            state["status"] = "active"
            continue

        if not period:
            warnings.append(f"{state['label']} received {action} before start")
            continue

        if action == "pause":
            if period.get("active_pause"):
                warnings.append(f"{state['label']} received a second pause without resume")
                continue
            category = str(event.get("category") or "").strip().lower()
            approved = bool(event.get("approved")) or category in APPROVED_PAUSE_CATEGORIES
            pause = {"started_at": _iso(at), "ended_at": "", "category": category,
                     "reason": event.get("reason") or "", "approved": approved,
                     "owner": event.get("owner") or ""}
            period["pauses"].append(pause)
            period["active_pause"] = pause
            state["status"] = "paused"
            continue

        if action == "resume":
            pause = period.get("active_pause")
            if not pause:
                warnings.append(f"{state['label']} resumed without an active pause")
                continue
            pause["ended_at"] = _iso(at)
            period["active_pause"] = None
            state["status"] = "active"
            continue

        if action in ("complete", "handoff"):
            pause = period.get("active_pause")
            if pause:
                pause["ended_at"] = _iso(at)
                period["active_pause"] = None
            period["ended_at"] = _iso(at)
            active[group] = None
            state["status"] = "completed"
            if action == "handoff":
                to_group = str(event.get("to_group") or "").strip().lower()
                if to_group not in groups:
                    warnings.append(f"{state['label']} handoff has no valid destination")
                elif active[to_group]:
                    warnings.append(f"{GROUPS[to_group]['label']} already has an open period")
                else:
                    next_period = {
                        "started_at": _iso(at), "ended_at": "",
                        "stage": event.get("to_stage") or "", "owner": event.get("to_owner") or "",
                        "pauses": [], "active_pause": None,
                        "source": event.get("source") or "", "source_id": event.get("source_id") or "",
                        "reopened": False,
                    }
                    groups[to_group]["periods"].append(next_period)
                    groups[to_group]["owner"] = next_period["owner"] or groups[to_group]["owner"]
                    groups[to_group]["status"] = "active"
                    active[to_group] = next_period

    for key, state in groups.items():
        for period in state["periods"]:
            started = _parse_at(period["started_at"])
            ended = _parse_at(period["ended_at"]) if period["ended_at"] else now_dt
            total = _seconds(started, ended)
            approved_pause = 0.0
            for pause in period["pauses"]:
                pause_start = _parse_at(pause["started_at"])
                pause_end = _parse_at(pause["ended_at"]) if pause["ended_at"] else now_dt
                seconds = _seconds(pause_start, min(pause_end, ended))
                pause["seconds"] = round(seconds, 3)
                if pause["approved"]:
                    approved_pause += seconds
            period["total_seconds"] = round(total, 3)
            period["paused_seconds"] = round(approved_pause, 3)
            period["controllable_seconds"] = round(max(0.0, total - approved_pause), 3)
            state["total_seconds"] += total
            state["paused_seconds"] += approved_pause
            state["controllable_seconds"] += max(0.0, total - approved_pause)

        for field in ("total_seconds", "paused_seconds", "controllable_seconds"):
            state[field] = round(state[field], 3)
        open_period = active[key]
        stage = (open_period or {}).get("stage") or ""
        target = _target_seconds(key, stage, targets)
        state["target_seconds"] = target
        if open_period and target is not None:
            start = _parse_at(open_period["started_at"])
            approved = sum(float(p.get("seconds") or 0) for p in open_period["pauses"]
                           if p.get("approved"))
            due = start + timedelta(seconds=target + approved)
            state["due_at"] = _iso(due)
            state["overdue"] = now_dt > due
            if state["status"] == "active":
                state["status"] = "overdue" if state["overdue"] else "on_track"
        elif open_period and target is None and state["status"] == "active":
            state["status"] = "needs_target"

    return {
        "groups": [groups[key] for key in GROUP_ORDER],
        "warnings": warnings,
        "generated_at": _iso(now_dt),
        "clock_policy": "total elapsed and approved-pause-adjusted controllable time",
    }


def project_stage_history(transitions: list[dict], current: dict | None = None,
                          *, now=None, thresholds: dict | None = None) -> dict:
    """Adapt existing Pipeline history into the department-clock summary.

    Old history has completed stage durations but no pause events, so its
    controllable time is explicitly marked as estimated rather than silently
    presented as exact.
    """
    now_dt = _parse_at(now or datetime.now(timezone.utc))
    thresholds = {**DEFAULT_STAGE_TARGET_DAYS, **(thresholds or {})}
    groups = {key: _new_group(key) for key in GROUP_ORDER}
    segments = []
    for row in transitions or []:
        stage = str(row.get("from_stage") or "").strip().lower()
        group = STAGE_OWNERSHIP.get(stage)
        if group not in groups:
            continue
        try:
            days = max(0.0, float(row.get("days_in_from_stage")))
        except (TypeError, ValueError):
            continue
        seconds = days * 86400.0
        segments.append({"stage": stage, "group": group, "seconds": seconds,
                         "ended_at": row.get("transitioned_at") or "", "active": False})

    current = current or {}
    current_stage = str(current.get("current_stage") or "").strip().lower()
    current_group = STAGE_OWNERSHIP.get(current_stage)
    if current_group in groups and current_stage != "paid":
        try:
            entered = _parse_at(current.get("stage_entered_at") or current.get("updated_at"))
            seconds = _seconds(entered, now_dt)
        except (TypeError, ValueError):
            entered, seconds = None, 0.0
        segments.append({"stage": current_stage, "group": current_group,
                         "seconds": seconds, "started_at": _iso(entered), "active": True})

    for segment in segments:
        state = groups[segment["group"]]
        state["total_seconds"] += segment["seconds"]
        state["controllable_seconds"] += segment["seconds"]
        if segment["active"]:
            target_days = thresholds.get(segment["stage"])
            target_seconds = float(target_days) * 86400.0 if target_days is not None else None
            state["target_seconds"] = target_seconds
            state["overdue"] = target_seconds is not None and segment["seconds"] > target_seconds
            state["status"] = "overdue" if state["overdue"] else (
                "on_track" if target_seconds is not None else "needs_target")
            state["owner"] = current.get("owner") or ""
        elif state["status"] == "not_started":
            state["status"] = "completed"

    for state in groups.values():
        state["total_seconds"] = round(state["total_seconds"], 3)
        state["controllable_seconds"] = round(state["controllable_seconds"], 3)
    return {
        "groups": [groups[key] for key in GROUP_ORDER],
        "segments": segments,
        "clock_quality": "estimated_from_stage_history",
        "generated_at": _iso(now_dt),
    }


def rollup(jobs: list[dict]) -> dict:
    """Aggregate independently projected jobs for group KPI reporting."""
    out = []
    for key in GROUP_ORDER:
        rows = [group for job in (jobs or []) for group in (job.get("groups") or [])
                if group.get("key") == key and group.get("status") != "not_started"]
        totals = [float(row.get("total_seconds") or 0) / 86400.0 for row in rows]
        controllable = [float(row.get("controllable_seconds") or 0) / 86400.0
                        for row in rows]
        out.append({
            "key": key, "label": GROUPS[key]["label"], "jobs": len(rows),
            "active": sum(row.get("status") in ("on_track", "overdue", "paused", "needs_target")
                          for row in rows),
            "overdue": sum(bool(row.get("overdue")) for row in rows),
            "avg_total_days": round(sum(totals) / len(totals), 1) if totals else None,
            "median_total_days": round(median(totals), 1) if totals else None,
            "avg_controllable_days": round(sum(controllable) / len(controllable), 1)
            if controllable else None,
            "median_controllable_days": round(median(controllable), 1)
            if controllable else None,
        })
    return {"groups": out, "jobs": len(jobs or [])}


def specification() -> dict:
    return {
        "groups": deepcopy(GROUPS),
        "group_order": list(GROUP_ORDER),
        "stage_ownership": deepcopy(STAGE_OWNERSHIP),
        "default_stage_target_days": deepcopy(DEFAULT_STAGE_TARGET_DAYS),
        "actions": list(ACTIONS),
        "approved_pause_categories": list(APPROVED_PAUSE_CATEGORIES),
        "rules": {
            "ownership": "one active owner clock per operational group and work period",
            "reopen": "reopen creates a new tracked work period",
            "pauses": "approved pauses stop controllable time; total elapsed time never stops",
            "handoff": "one timestamp completes the source group and starts the destination group",
            "precedence": "stage/client-program overrides group/franchise defaults",
            "history": "retain completed periods and source evidence; never overwrite prior work",
        },
    }
