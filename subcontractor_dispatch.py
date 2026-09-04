"""Build a reviewable subcontractor dispatch email from saved job facts.

This module deliberately only creates a draft.  Sending remains an explicit
Outlook action so a typo, stale adjuster, or wrong vendor can be caught first.
"""
from __future__ import annotations

import datetime as _dt
import re


def _clean(value) -> str:
    return " ".join(str(value or "").strip().split())


def _multiline(value) -> str:
    return "\n".join(line.strip() for line in str(value or "").splitlines()
                     if line.strip())


def _display_date(value) -> str:
    raw = _clean(value)
    if not raw:
        return ""
    for fmt in ("%Y-%m-%d", "%m-%d-%Y", "%m/%d/%Y", "%m-%d-%y", "%m/%d/%y"):
        try:
            return _dt.datetime.strptime(raw, fmt).strftime("%m-%d-%y")
        except ValueError:
            pass
    return raw


def _customer_name(fields: dict) -> str:
    return _clean(fields.get("customer_name") or fields.get("insured_name")
                  or fields.get("client"))


def _subject_name(name: str) -> str:
    """Prefer the office's ``Last, First`` subject convention."""
    if not name or "," in name:
        return name
    words = name.split()
    return f"{words[-1]}, {' '.join(words[:-1])}" if len(words) > 1 else name


def compose(fields: dict | None = None, options: dict | None = None) -> dict:
    """Return ``to``, ``cc``, ``subject``, ``body`` and missing essentials."""
    fields, options = fields or {}, options or {}
    name = _customer_name(fields)
    claim = _clean(fields.get("claim_number"))
    service = _clean(options.get("service")) or "subcontractor service"
    service_title = service.title()
    ready = _display_date(options.get("ready_date"))
    notes = _multiline(options.get("scope_notes"))
    greeting = _clean(options.get("greeting")) or "Good Morning,"

    adjuster_email = _clean(fields.get("adjuster_email"))
    vendor_email = _clean(options.get("vendor_email"))
    to = "; ".join(x for x in (vendor_email, adjuster_email) if x)
    cc = _clean(options.get("cc")) or "EMS@servpro10100.com"
    subject = f"{_subject_name(name) or 'Customer'}"
    if claim:
        subject += f" - Claim Number: {claim}"
    subject += f" - {service_title}"

    request = f"Please dispatch for {service.lower()} for the following"
    if ready:
        request += f". This will be ready by {ready}"
    request += "."

    body_lines = [greeting, "", request]
    if notes:
        body_lines.extend(["", notes])
    body_lines.extend([
        "", "CUSTOMER INFORMATION",
        f"Customer Name: {name}",
        f"Address: {_clean(fields.get('address'))}",
        f"Phone Number: {_clean(fields.get('phone'))}",
        f"Email: {_clean(fields.get('email'))}",
        f"Additional Contacts: {_clean(fields.get('additional_contacts'))}",
        f"Source of Lead: {_clean(fields.get('source_of_lead'))}",
        "", "INSURANCE INFORMATION",
        f"Inspection Fee (Self Pay): {_clean(fields.get('inspection_fee'))}",
        f"Insurance Company: {_clean(fields.get('carrier') or fields.get('insurance_company'))}",
        f"Claim Number: {claim}",
        f"Adjuster Name: {_clean(fields.get('adjuster_name'))}",
        f"Adjuster Email: {adjuster_email}",
        f"Adjuster Number: {_clean(fields.get('adjuster_number') or fields.get('adjuster_phone'))}",
        "", "Regards,",
    ])
    body = "\n".join(body_lines)
    missing = []
    for label, value in (("subcontractor email", vendor_email),
                         ("customer name", name), ("service", service),
                         ("address", fields.get("address"))):
        if not _clean(value):
            missing.append(label)
    return {"ok": True, "to": to, "cc": cc, "subject": subject,
            "body": body, "missing": missing}

