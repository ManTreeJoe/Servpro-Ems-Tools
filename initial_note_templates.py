"""Front Ops-managed Initial Note definitions.

Templates are application data. Every signed-in user may read active templates;
only the existing admin Settings surface may change them. Built-in defaults keep
the job action usable while a new server is receiving the optional table.
"""
from __future__ import annotations

import uuid


DEFAULTS = (
    {
        "template_id": "builtin-initial-inspection",
        "name": "Initial inspection update",
        "division": "EMS",
        "body": ("INITIAL INSPECTION UPDATE\n"
                 "Inspection completed: {date}\n"
                 "Technician / crew: \n"
                 "Cause / source: \n"
                 "Affected areas: \n"
                 "Work performed: \n"
                 "Equipment / readings: \n"
                 "Next step: "),
        "active": True,
        "builtin": True,
    },
    {
        "template_id": "builtin-post-inspection",
        "name": "Post-inspection customer / adjuster update",
        "division": "EMS",
        "body": ("POST-INSPECTION UPDATE\n"
                 "Inspection completed: {date}\n"
                 "Findings: \n"
                 "Scope / next step: \n"
                 "Customer / adjuster contacted: \n"
                 "Follow-up needed: "),
        "active": True,
        "builtin": True,
    },
    {
        "template_id": "builtin-contents",
        "name": "Contents initial update",
        "division": "Contents",
        "body": ("CONTENTS INITIAL UPDATE\n"
                 "Date: {date}\n"
                 "Areas / items affected: \n"
                 "Pack-out or manipulation plan: \n"
                 "Crew: \n"
                 "Next step: "),
        "active": True,
        "builtin": True,
    },
)


def _missing_schema(ex: Exception) -> bool:
    text = str(getattr(ex, "body", "") or ex)
    return "job_note_templates" in text and (
        "PGRST205" in text or "schema cache" in text.lower() or "does not exist" in text.lower())


def list_templates(department: str = "", division: str = "",
                   *, include_inactive: bool = False) -> list[dict]:
    import supabase_client
    params = {"select": "*", "order": "sort_order.asc,name.asc"}
    if department:
        params["department"] = f"eq.{str(department).strip().upper()}"
    if not include_inactive:
        params["active"] = "eq.true"
    try:
        rows = supabase_client.rest("GET", "job_note_templates", params=params) or []
    except Exception as ex:
        if not _missing_schema(ex):
            raise
        rows = []
    if division:
        wanted = str(division).strip().casefold()
        rows = [row for row in rows if str(row.get("division") or "Any").casefold()
                in ("any", wanted)]
    if rows:
        return rows
    return [dict(row) for row in DEFAULTS if not division or
            str(row["division"]).casefold() in ("any", str(division).casefold())]


def save(values: dict) -> dict:
    import supabase_client
    values = values if isinstance(values, dict) else {}
    template_id = str(values.get("template_id") or "").strip()
    row = {
        "department": str(values.get("department") or "").strip().upper(),
        "name": " ".join(str(values.get("name") or "").split()),
        "division": str(values.get("division") or "Any").strip(),
        "body": str(values.get("body") or "").strip(),
        "active": values.get("active") is not False,
        "sort_order": int(values.get("sort_order") or 100),
        "updated_by": (supabase_client.current_user() or {}).get("id"),
    }
    if not row["department"] or not row["name"] or not row["body"]:
        raise ValueError("Franchise, template name, and note text are required.")
    if row["division"] not in ("Any", "EMS", "Contents", "Recon"):
        raise ValueError("Choose a valid division.")
    if template_id and not template_id.startswith("builtin-"):
        rows = supabase_client.rest(
            "PATCH", "job_note_templates",
            params={"template_id": f"eq.{template_id}"}, body=row,
            prefer="return=representation") or []
    else:
        row["template_id"] = str(uuid.uuid4())
        row["created_by"] = row["updated_by"]
        rows = supabase_client.rest("POST", "job_note_templates", body=row,
                                    prefer="return=representation") or []
    if not rows:
        raise RuntimeError("The shared database did not return the saved template.")
    return rows[0]
