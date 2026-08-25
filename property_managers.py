"""Editable property-management account and Trello-template directory."""
from __future__ import annotations

import copy
import re
from datetime import datetime

import ems_db
from ems_db_common import canon_key

PROFILE_KEY = "property_manager_profile"
DEFAULT_NAMING = "Management Company - (Property/Site - Unit or Work Order) - Date Received"

_SEEDS = [
    ("avila-apartments", "Avila Apartments", "69c571c9e01d340ec687c526", "Avila Apartments (Unit #) - Date Received", "Krystal Kohlberg", "Property Manager", "951-672-0600", "krystal@avilaapts.com", "Able Arechiga — Maintenance Supervisor · 951-796-5855 · maintenance@avilaapts.com"),
    ("menifee-union-school-district", "Menifee Union School District", "6a2c6f891106407b80757ab7", "Menifee Union School District (Name of school) - Date", "", "", "", "", ""),
    ("stater-bros", "Stater Bros", "69c576eabfbc9f2bfcd017ae", "Stater Bros - (Service or Work order #) - Date Received", "Haney Hana", "", "", "Haney.Hana@staterbros.com", ""),
    ("action-property-management", "Action Property Management", "6a8e08c11df6b44b591515cd", "Action Property Management - (Property/Site - Unit or Work Order) - Date Received", "", "", "", "", ""),
    ("aperto-property-management", "Aperto Property Management", "6a8e08c23c5e5a5c82191670", "Aperto Property Management - (Property/Site - Unit or Work Order) - Date Received", "", "", "", "", ""),
    ("athena-property-management", "Athena Property Management", "6a8e08c4bb36eb3f6911f216", "Athena Property Management - (Property/Site - Unit or Work Order) - Date Received", "", "", "", "", ""),
    ("bates-homes-property-management", "Bates Homes Property Management", "6a8e08c6ad3e5d23ed607497", "Bates Homes Property Management - (Property/Site - Unit or Work Order) - Date Received", "", "", "", "", ""),
    ("pcm", "PCM", "6a8e08c803435b43c1ee749c", "PCM - (Property/Site - Unit or Work Order) - Date Received", "", "", "", "", ""),
    ("seabreeze-property-management", "Seabreeze Property Management", "6a8e08ca28204670ee968bc8", "Seabreeze Property Management - (Property/Site - Unit or Work Order) - Date Received", "", "", "", "", ""),
    ("elite-property-management", "Elite Property Management", "6a8e08cc8932c664193fe420", "Elite Property Management - (Property/Site - Unit or Work Order) - Date Received", "", "", "", "", ""),
]


def _seed_records():
    return [{"id": i, "company_name": n, "template_card_id": cid,
             "template_card_name": cname, "naming_format": DEFAULT_NAMING,
             "contact_name": contact, "contact_role": role, "phone": phone,
             "email": email, "notes": notes, "active": True,
             "updated_at": "2026-08-25T00:00:00"}
            for i, n, cid, cname, contact, role, phone, email, notes in _SEEDS]


def list_records():
    rows = []
    for job in ems_db.iter_jobs():
        profile = (job.get("metadata") or {}).get(PROFILE_KEY)
        if isinstance(profile, dict):
            row = copy.deepcopy(profile)
            row["id"] = job.get("canon_key")
            row["company_name"] = (row.get("company_name")
                                   or job.get("display_name") or "")
            rows.append(row)
    # First open upgrades the current secured jobs database in place. Resume
    # safely if an earlier seed stopped halfway through.
    seeded_ids = {r.get("template_card_id") for r in rows}
    missing = [r for r in _seed_records()
               if r.get("template_card_id") not in seeded_ids]
    if missing:
        for record in missing:
            save_record(record)
        return list_records()
    return sorted(copy.deepcopy(rows),
                  key=lambda r: (not bool(r.get("active", True)),
                                 (r.get("company_name") or "").lower()))


def save_record(values: dict):
    if not isinstance(values, dict):
        raise ValueError("Property manager details are required")
    name = (values.get("company_name") or "").strip()
    if not name:
        raise ValueError("Company name is required")
    rid = (values.get("id") or "").strip()
    old_job = ems_db.get_job(rid) if rid else None
    old = copy.deepcopy((old_job or {}).get("metadata", {}).get(PROFILE_KEY))
    allowed = ("company_name", "template_card_id", "template_card_name",
               "naming_format", "contact_name", "contact_role", "phone",
               "email", "notes")
    record = dict(old or {})
    for key in allowed:
        record[key] = (values.get(key) or "").strip()
    record["naming_format"] = record["naming_format"] or DEFAULT_NAMING
    record["active"] = bool(values.get("active", True))
    record["updated_at"] = datetime.now().isoformat(timespec="seconds")
    old_md = copy.deepcopy((old_job or {}).get("metadata") or {})
    old_md[PROFILE_KEY] = record
    try:
        import config
        department = (config.load().get("active_department") or "").strip()
    except Exception:
        department = ""
    new_id = ems_db.upsert_job(display_name=name, department=department,
                               metadata=old_md)
    # A real company rename changes its canonical account key. Fold the old
    # row into the new one so properties, units, links and history follow it.
    if rid and rid != new_id and old_job:
        ems_db.merge_jobs(new_id, [rid])
    record["id"] = new_id
    return copy.deepcopy(record), copy.deepcopy(old)


def trello_name(record: dict) -> str:
    """Build the live template title after a company rename."""
    current = (record.get("template_card_name") or "").strip()
    old_company = (record.get("previous_company_name") or "").strip()
    company = (record.get("company_name") or "").strip()
    if current and old_company:
        return re.sub(r"^" + re.escape(old_company), company, current,
                      count=1, flags=re.I)
    return f"{company} - (Property/Site - Unit or Work Order) - Date Received"
