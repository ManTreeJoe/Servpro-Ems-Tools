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
    ("greystar-property-management", "Greystar Property Management", "6aa0814e774c3665df7b69a1", "Greystar Property Management - (Property/Site - Unit or Work Order) - Date Received", "Varies by property", "Property contact", "", "", "Use the property/site name and unit on each job."),
    ("val-verde-unified-school-district", "Val Verde Unified School District", "6aa08150e95387e24ea36b6c", "Val Verde Unified School District - (Property/Site - Unit or Work Order) - Date Received", "Kayla Cain", "Account contact", "951-940-6100 ext 10859", "kcain@valverde.edu", "School/site varies by job."),
    ("coreland-property-management", "Coreland Property Management", "6aa08152d3f6d48cc5bbd440", "Coreland Property Management - (Property/Site - Unit or Work Order) - Date Received", "Raylene Sanchez", "Account contact", "714-210-6717", "rsanchez@coreland.com", "Office: 714-573-7780."),
    ("rainey-property-management", "Rainey Property Management", "6aa08154006105f9ea1fcdaa", "Rainey Property Management - (Property/Site - Unit or Work Order) - Date Received", "Elena Rivera", "Property contact", "", "creeksidemanager@raineypm.com", "Property/site contact may vary."),
    ("progressive-association-management", "Progressive Association Management", "6aa08156b17ed82ec2d0634b", "Progressive Association Management - (Property/Site - Unit or Work Order) - Date Received", "Stacy Serna", "HOA contact", "657-534-3514", "s.serna@progressive-am.com", "HOA account; property/site varies by job."),
    ("5-star-property-management", "5 Star Property Management", "6aa081586f32014edbf74ba1", "5 Star Property Management - (Property/Site - Unit or Work Order) - Date Received", "", "", "949-394-8660", "", "Confirm the property/site contact before dispatch."),
    ("prime-property-management", "Prime Property Management", "6aa0815ad4696ff37bb7a459", "Prime Property Management - (Property/Site - Unit or Work Order) - Date Received", "", "", "951-227-2864", "", "Confirm the property/site contact before dispatch."),
    ("next-door-property-management", "Next Door Property Management", "6aa0815cd22260b2bd10763d", "Next Door Property Management - (Property/Site - Unit or Work Order) - Date Received", "", "", "", "", "Confirm the property/site contact before dispatch."),
    ("advanced-property-services", "Advanced Property Services", "6aa0815dfba187f0cd61f9be", "Advanced Property Services - (Property/Site - Unit or Work Order) - Date Received", "", "", "951-666-5720", "", "Citrus Circle is a known property/site."),
    ("jla", "JLA", "6aa0815f6ba5d57fc68af043", "JLA - (Property/Site - Unit or Work Order) - Date Received", "Andy Romero", "Account contact", "951-784-0999", "andy@jlareg.com", "Property/site and work order vary by job."),
    ("keystone-pacific-property-management", "Keystone Pacific Property Management", "6aa08161ba44efc08943fa94", "Keystone Pacific Property Management - (Property/Site - Unit or Work Order) - Date Received", "Shanna Ghale", "Property contact", "", "shanna.ghale@keystonepacific.com", "Highland Village is a known property/site."),
    ("hyder-and-company", "Hyder & Company", "6aa0816378e474909dbbc3a1", "Hyder & Company - (Property/Site - Unit or Work Order) - Date Received", "Ralph Corral", "Maintenance Supervisor", "760-330-7623", "marvetmaint@hyderco.com", "Las Palmeras is a known property/site. Maria Vega: 760-398-3357; laspalmeras@hyderco.com."),
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
