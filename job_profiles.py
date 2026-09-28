"""Admin-managed Job Profiles and immutable per-job snapshots.

This module owns selector normalization, matching, persistence, and snapshot
creation. UI code should not reproduce these rules.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import re
import uuid


PAYER_TYPES = ("any", "insurance", "self_pay", "commercial", "management")
DIVISIONS = ("Any", "EMS", "Contents", "Recon")


def _text(value) -> str:
    return " ".join(str(value or "").strip().split())


def _fold(value) -> str:
    return _text(value).casefold()


def _requirements(value) -> list[str]:
    if isinstance(value, str):
        value = value.replace("\r", "").split("\n")
    if not isinstance(value, list):
        value = []
    out, seen = [], set()
    for item in value:
        label = _text(item.get("label") if isinstance(item, dict) else item)
        folded = label.casefold()
        if label and folded not in seen:
            seen.add(folded)
            out.append(label)
    return out


def normalize(values: dict, *, require_id: bool = False) -> dict:
    values = values if isinstance(values, dict) else {}
    payer = _text(values.get("payer_type") or "any").lower().replace("-", "_").replace(" ", "_")
    division_raw = _text(values.get("division") or "Any")
    division = next((d for d in DIVISIONS if d.casefold() == division_raw.casefold()), "")
    row = {
        "department": _text(values.get("department")).upper(),
        "name": _text(values.get("name")),
        "payer_type": payer,
        "carrier_or_client": _text(values.get("carrier_or_client")) or None,
        "loss_type": _text(values.get("loss_type")) or None,
        "division": division,
        "required_items": _requirements(values.get("required_items")),
        "active": values.get("active") is not False,
    }
    if require_id:
        row["profile_id"] = _text(values.get("profile_id"))
    if payer not in PAYER_TYPES:
        raise ValueError("Choose a valid payer type.")
    if not division:
        raise ValueError("Choose a valid division.")
    if not row["department"]:
        raise ValueError("Choose a franchise.")
    if not row["name"]:
        raise ValueError("Profile name is required.")
    if not row["required_items"]:
        raise ValueError("Add at least one required item.")
    if require_id and not row.get("profile_id"):
        raise ValueError("Profile ID is required.")
    return row


def list_profiles(department: str = "", *, include_inactive: bool = True) -> list[dict]:
    import supabase_client
    params = {"select": "*", "order": "department.asc,name.asc"}
    if department:
        params["department"] = f"eq.{_text(department).upper()}"
    if not include_inactive:
        params["active"] = "eq.true"
    with supabase_client.interactive_requests():
        rows = supabase_client.rest("GET", "job_profiles", params=params) or []
    return rows if isinstance(rows, list) else []


def save(values: dict) -> dict:
    import supabase_client
    profile_id = _text((values or {}).get("profile_id"))
    row = normalize(values)
    row["updated_by"] = (supabase_client.current_user() or {}).get("id")
    with supabase_client.interactive_requests():
        if profile_id:
            rows = supabase_client.rest(
                "PATCH", "job_profiles", params={"profile_id": f"eq.{profile_id}"},
                body=row, prefer="return=representation") or []
        else:
            row["created_by"] = row["updated_by"]
            rows = supabase_client.rest("POST", "job_profiles", body=row,
                                        prefer="return=representation") or []
    if not rows:
        raise RuntimeError("The shared database did not return the saved profile.")
    return rows[0]


def set_active(profile_id: str, active: bool) -> dict:
    import supabase_client
    with supabase_client.interactive_requests():
        rows = supabase_client.rest(
            "PATCH", "job_profiles", params={"profile_id": f"eq.{_text(profile_id)}"},
            body={"active": bool(active), "updated_by": (supabase_client.current_user() or {}).get("id")},
            prefer="return=representation") or []
    if not rows:
        raise RuntimeError("Job Profile was not found.")
    return rows[0]


def delete(profile_id: str) -> dict:
    """Remove an inactive library template, never a job's applied snapshot.

    Filtering active=false in the DELETE itself protects against another admin
    enabling the template between the UI confirmation and this request.
    """
    import supabase_client
    try:
        profile_id = str(uuid.UUID(_text(profile_id)))
    except (ValueError, AttributeError) as error:
        raise ValueError("A valid Job Profile ID is required.") from error
    with supabase_client.interactive_requests():
        rows = supabase_client.rest(
            "DELETE", "job_profiles",
            params={"profile_id": f"eq.{profile_id}", "active": "eq.false"},
            prefer="return=representation") or []
    if not isinstance(rows, list) or len(rows) != 1 or str(rows[0].get("profile_id")) != profile_id:
        raise RuntimeError("Deletion was not confirmed. Refresh the library; the profile may be active, missing, or inaccessible.")
    return rows[0]


def _job_value(job: dict, *keys):
    metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
    settings = metadata.get("settings") if isinstance(metadata.get("settings"), dict) else {}
    for key in keys:
        value = job.get(key)
        if value not in (None, ""):
            return value
        value = settings.get(key)
        if value not in (None, ""):
            return value
    return ""


def match_score(profile: dict, job: dict, division: str = "Any") -> int | None:
    if not profile.get("active", True):
        return None
    if _fold(profile.get("department")) != _fold(job.get("department")):
        return None
    payer = _fold(profile.get("payer_type") or "any").replace("-", "_").replace(" ", "_")
    job_payer = _fold(_job_value(job, "job_type", "payer_type")).replace("-", "_").replace(" ", "_")
    if payer != "any" and payer != job_payer:
        return None
    profile_division = _fold(profile.get("division") or "Any")
    if profile_division != "any" and profile_division != _fold(division):
        return None
    carrier = _fold(profile.get("carrier_or_client"))
    haystack = " | ".join((_fold(_job_value(job, "carrier", "insurance_company")),
                             _fold(_job_value(job, "customer_name", "client_name")),
                             _fold(job.get("display_name"))))
    if carrier and carrier not in haystack:
        return None
    loss_type = _fold(profile.get("loss_type"))
    if loss_type and loss_type != _fold(_job_value(job, "loss_type")):
        return None
    return sum((payer != "any", profile_division != "any", bool(carrier), bool(loss_type)))


def matching(profiles: list[dict], job: dict, division: str = "Any") -> list[dict]:
    scored = [(match_score(p, job, division), p) for p in profiles]
    return [deepcopy(p) for score, p in sorted(
        ((s, p) for s, p in scored if s is not None),
        key=lambda item: (-item[0], _fold(item[1].get("name")), str(item[1].get("profile_id") or "")))]


def snapshot(profile: dict, *, applied_at: str = "") -> dict:
    clean = normalize(profile)
    pid = _text(profile.get("profile_id")) or str(uuid.uuid4())
    stamp = applied_at or datetime.now().astimezone().isoformat(timespec="seconds")
    requirements = []
    for index, label in enumerate(clean["required_items"], 1):
        slug = re.sub(r"[^a-z0-9]+", "-", label.casefold()).strip("-")[:48] or str(index)
        requirements.append({"key": f"profile:{pid}:{slug}:{index}", "label": label,
                             "division": clean["division"], "introduced_stage": "intake",
                             "owner": "office", "importance": "required"})
    return {"profile_id": pid, "profile_name": clean["name"],
            "applied_at": stamp,
            "selectors": {key: clean[key] for key in
                          ("payer_type", "carrier_or_client", "loss_type", "division")},
            "requirements": requirements}


def suggestions(job: dict, profiles: list[dict] | None = None) -> list[dict]:
    """Return unapplied matches, most-specific first across active divisions."""
    if profiles is None:
        profiles = list_profiles(job.get("department") or "", include_inactive=False)
    metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
    applied = {str(item.get("profile_id") or "") for item in
               (metadata.get("applied_job_profiles") or []) if isinstance(item, dict)}
    divisions = ["Any"]
    for environment in job.get("work_environments") or []:
        if not isinstance(environment, dict):
            continue
        if (environment.get("stage") or "not_applicable") != "not_applicable":
            divisions.append(environment.get("work_environment") or "Any")
    found = {}
    for division in divisions:
        for profile in matching(profiles, job, division):
            pid = str(profile.get("profile_id") or "")
            if pid and pid not in applied:
                found.setdefault(pid, profile)
    return list(found.values())


def apply_to_job(job: dict, profile: dict) -> dict:
    """Return a copied metadata object with one immutable profile snapshot."""
    metadata = deepcopy(job.get("metadata") if isinstance(job.get("metadata"), dict) else {})
    applied = list(metadata.get("applied_job_profiles") or [])
    pid = str(profile.get("profile_id") or "")
    if any(isinstance(item, dict) and str(item.get("profile_id") or "") == pid
           for item in applied):
        return metadata
    applied.append(snapshot(profile))
    metadata["applied_job_profiles"] = applied
    return metadata
