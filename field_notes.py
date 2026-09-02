"""Small, field-first note interface shared by Operations clients.

The website, desktop shell, and a future mobile client should not each invent
their own technician forms.  They ask this module for a template and submit
the answers back here.  The result is an ordinary structured Job Log entry,
so existing revision history, Snapshot, and reporting keep one source of
truth.
"""
from __future__ import annotations

from datetime import date


def _field(name, label, kind="text", **extra):
    return {"name": name, "label": label, "type": kind, **extra}


_TEMPLATES = (
    {
        "key": "initial",
        "label": "Initial visit",
        "short_label": "Initial",
        "description": "Capture the loss, affected areas, and what happens next.",
        "work_type": "Initial inspection",
        "save_label": "Save initial note",
        "fields": (
            _field("work_date", "Visit date", "date", required=True),
            _field("arrival_time", "Arrival time", "time"),
            _field("met_with", "Met with", placeholder="Customer, tenant, manager…"),
            _field("cause_of_loss", "What caused the loss?", "textarea", rows=2,
                   placeholder="Known cause or what is still being investigated"),
            _field("affected_areas", "Areas and materials affected", "textarea", rows=3,
                   placeholder="Kitchen cabinets, hall drywall, bedroom carpet…"),
            _field("work_completed", "What did you do today?", "textarea", rows=3,
                   placeholder="Inspection, extraction, demo, containment…"),
            _field("next_step", "What needs to happen next?", "textarea", rows=2,
                   placeholder="Testing, approval, return visit, demo…"),
            _field("category", "Category", "select", group="details",
                   options=("", "1", "2", "3")),
            _field("loss_class", "Class", "select", group="details",
                   options=("", "1", "2", "3", "4")),
            _field("readings", "Initial readings", "textarea", rows=2, group="details",
                   placeholder="Room / material / reading"),
            _field("equipment", "Equipment placed", "textarea", rows=2, group="details",
                   placeholder="Type, quantity, and room"),
            _field("photos_taken", "Photos taken?", "select", group="details",
                   options=("", "Yes", "No")),
            _field("technicians", "Other technicians", group="details",
                   placeholder="You are added automatically"),
        ),
    },
    {
        "key": "monitor",
        "label": "Monitor",
        "short_label": "Monitor",
        "description": "Record drying progress, readings, and equipment changes.",
        "work_type": "Monitor",
        "save_label": "Save monitor note",
        "fields": (
            _field("work_date", "Visit date", "date", required=True),
            _field("areas_checked", "Areas checked", "textarea", rows=2,
                   placeholder="Rooms and materials checked today"),
            _field("progress", "Drying progress", "select",
                   options=("", "Improving", "Dry in checked areas", "No change", "Needs attention")),
            _field("readings", "Moisture readings", "textarea", rows=3,
                   placeholder="Room / material / reading"),
            _field("equipment_changes", "Equipment changes", "textarea", rows=2,
                   placeholder="Added, moved, adjusted, or removed"),
            _field("work_completed", "Work completed", "textarea", rows=2,
                   placeholder="What was done during this visit"),
            _field("next_step", "Next step / next visit", "textarea", rows=2,
                   placeholder="Return date, pickup plan, approval needed…"),
            _field("issues", "Problem or exception", "textarea", rows=2, group="details",
                   placeholder="Access issue, customer concern, new damage…"),
            _field("technicians", "Other technicians", group="details",
                   placeholder="You are added automatically"),
        ),
    },
    {
        "key": "update",
        "label": "Job update",
        "short_label": "Update",
        "description": "Post a quick field update without filling out a full form.",
        "work_type": "Job update",
        "save_label": "Save job update",
        "fields": (
            _field("work_date", "Update date", "date", required=True),
            _field("note", "What happened?", "textarea", rows=4, required=True,
                   placeholder="Work completed, findings, customer update…"),
            _field("next_step", "Next step", "textarea", rows=2,
                   placeholder="What needs to happen next and who owns it"),
            _field("status", "Status", "select", group="details",
                   options=("completed", "scheduled", "rescheduled", "needs_review", "cancelled", "skipped")),
            _field("equipment", "Equipment / readings", "textarea", rows=2, group="details"),
            _field("technicians", "Other technicians", group="details",
                   placeholder="You are added automatically"),
        ),
    },
)


def templates(division: str = "EMS") -> list[dict]:
    """Return JSON-safe form definitions with today's local date prefilled."""
    today = date.today().isoformat()
    result = []
    for template in _TEMPLATES:
        item = {key: value for key, value in template.items() if key != "fields"}
        item["division"] = str(division or "EMS").upper()
        item["fields"] = []
        for raw in template["fields"]:
            field = dict(raw)
            field["options"] = list(field.get("options") or [])
            if field["name"] == "work_date":
                field["default"] = today
            item["fields"].append(field)
        result.append(item)
    return result


def _clean(values: dict, key: str) -> str:
    return str((values or {}).get(key) or "").strip()


def _display_date(iso_value: str) -> str:
    try:
        parsed = date.fromisoformat(iso_value)
        return parsed.strftime("%m-%d-%y")
    except ValueError:
        return iso_value


def _lines(title: str, pairs) -> str:
    lines = [title]
    for label, value in pairs:
        value = str(value or "").strip()
        if value:
            lines.extend(("", f"{label}: {value}"))
    return "\n".join(lines)


def build_entry(note_type: str, values: dict, *, division: str = "EMS",
                source_id: str = "") -> dict:
    """Validate field answers and turn them into one canonical Job Log entry."""
    note_type = str(note_type or "").strip().lower()
    template = next((item for item in _TEMPLATES if item["key"] == note_type), None)
    if not template:
        raise ValueError("unknown field note type")
    values = values if isinstance(values, dict) else {}
    work_date = _clean(values, "work_date") or date.today().isoformat()
    try:
        date.fromisoformat(work_date)
    except ValueError as ex:
        raise ValueError("visit date is invalid") from ex

    content_keys = {
        "initial": ("cause_of_loss", "affected_areas", "work_completed", "next_step",
                    "readings", "equipment"),
        "monitor": ("areas_checked", "progress", "readings", "equipment_changes",
                    "work_completed", "next_step", "issues"),
        "update": ("note", "next_step", "equipment"),
    }[note_type]
    if not any(_clean(values, key) for key in content_keys):
        raise ValueError("Add at least one useful note before saving")

    shown_date = _display_date(work_date)
    equipment = ""
    if note_type == "initial":
        equipment = "\n".join(filter(None, (
            f"Readings: {_clean(values, 'readings')}" if _clean(values, "readings") else "",
            f"Equipment placed: {_clean(values, 'equipment')}" if _clean(values, "equipment") else "",
        )))
        note = _lines("Initial notes", (
            ("Date", shown_date), ("Time of Inspections", _clean(values, "arrival_time")),
            ("Met With", _clean(values, "met_with")),
            ("Cause of Loss", _clean(values, "cause_of_loss")),
            ("Category", _clean(values, "category")),
            ("Class", _clean(values, "loss_class")),
            ("Areas Affected", _clean(values, "affected_areas")),
            ("Equipment Placed", "Yes" if _clean(values, "equipment") else ""),
            ("Equipment Type", _clean(values, "equipment")),
            ("Photos Taken", _clean(values, "photos_taken")),
            ("Work Completed", _clean(values, "work_completed")),
            ("Next Step", _clean(values, "next_step")),
            ("Additional Notes", _clean(values, "additional_notes")),
        ))
    elif note_type == "monitor":
        equipment = "\n".join(filter(None, (
            f"Readings: {_clean(values, 'readings')}" if _clean(values, "readings") else "",
            f"Equipment: {_clean(values, 'equipment_changes')}" if _clean(values, "equipment_changes") else "",
        )))
        note = _lines("Monitor notes", (
            ("Date", shown_date), ("Areas Checked", _clean(values, "areas_checked")),
            ("Drying Progress", _clean(values, "progress")),
            ("Moisture Readings", _clean(values, "readings")),
            ("Equipment Changes", _clean(values, "equipment_changes")),
            ("Work Completed", _clean(values, "work_completed")),
            ("Next Step", _clean(values, "next_step")),
            ("Problem / Exception", _clean(values, "issues")),
        ))
    else:
        equipment = _clean(values, "equipment")
        note = _lines("Job update", (
            ("Date", shown_date), ("Update", _clean(values, "note")),
            ("Next Step", _clean(values, "next_step")),
        ))

    return {
        "work_date": work_date,
        "work_type": template["work_type"],
        "status": _clean(values, "status") or "completed",
        "technicians": _clean(values, "technicians"),
        "note": note,
        "equipment": equipment,
        "source": "field_note",
        "source_id": str(source_id or "").strip(),
        "division": str(division or "EMS").upper(),
    }
