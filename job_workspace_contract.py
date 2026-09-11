"""Versioned job-workspace contract shared by desktop and future web clients.

The rest of Linguar Hub still exposes its legacy workspace fields while screens
migrate.  This module is the seam: storage rows, Trello pins and audit results
enter here; callers receive one Client -> Claim -> Division document without
needing to know which adapter supplied each fact.

Keep this module pure.  It must never perform database, network or filesystem
I/O, which makes the same fixtures usable by the Python desktop and L OPS.
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from ems_db_common import canon_key, normalize_division


CONTRACT_NAME = "linguar.job-workspace"
CONTRACT_VERSION = 1
DIVISIONS = ("EMS", "CONTENTS", "RECON")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _mapping(value: Any) -> dict:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return dict(parsed) if isinstance(parsed, Mapping) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def _job_facts(job: Mapping[str, Any]) -> dict:
    """Flatten durable columns plus legacy ``metadata_json.settings``."""
    facts = dict(job or {})
    metadata = _mapping(facts.get("metadata_json"))
    settings = _mapping(metadata.get("settings"))
    for key, value in settings.items():
        if not _text(facts.get(key)):
            facts[key] = value
    return facts


def _legacy_id(kind: str, value: str) -> str:
    stable = canon_key(value) or "unknown"
    return f"legacy-{kind}:{stable}"


def _trello_by_division(cards: Sequence[Mapping[str, Any]]) -> dict[str, dict]:
    result = {}
    for raw in cards or ():
        card = dict(raw or {})
        division = normalize_division(card.get("division"))
        card_id = _text(card.get("card_id"))
        result[division] = {
            "id": card_id,
            "url": _text(card.get("url")) or (
                f"https://trello.com/c/{card_id}" if card_id else ""),
            "pinned": bool(card.get("pinned") or card_id),
            "source": "trello",
        }
    return result


def build_job_workspace(
    *,
    requested_name: str,
    job: Mapping[str, Any] | None,
    crm: Mapping[str, Any] | None,
    audit: Mapping[str, Any] | None,
    division_cards: Sequence[Mapping[str, Any]] | None,
    selected_division: str = "EMS",
    opened_card_id: str = "",
    reconciliation: Mapping[str, Any] | None = None,
) -> dict:
    """Adapt current Linguar Hub records to contract version 1.

    Existing durable IDs always win.  Legacy fallback IDs are visibly marked
    and deterministic, so they can be replaced during data migration without
    pretending a Trello card or mutable display name is the claim identity.
    """
    job = _job_facts(job or {})
    crm = dict(crm or {})
    audit = dict(audit or {})
    reconciliation = dict(reconciliation or {})

    claim_name = (_text(job.get("display_name")) or _text(requested_name)
                  or _text(audit.get("client")))
    customer_name = (_text(job.get("customer_name"))
                     or _text(job.get("insured_name"))
                     or claim_name)
    client_id = (_text(job.get("client_id"))
                 or _text(crm.get("client_id"))
                 or _legacy_id("client", customer_name))
    claim_id = (_text(job.get("claim_id")) or _text(job.get("job_id"))
                or _text(crm.get("job_id"))
                or _legacy_id("claim", claim_name))
    franchise = (_text(job.get("department"))
                 or _text(job.get("franchise"))
                 or _text(crm.get("franchise")))
    selected = normalize_division(selected_division)
    trello = _trello_by_division(division_cards or ())
    opened_card_id = _text(opened_card_id)
    if opened_card_id:
        trello[selected] = {
            "id": opened_card_id,
            "url": f"https://trello.com/c/{opened_card_id}",
            "pinned": True,
            "source": "trello",
        }

    environment_rows = {
        normalize_division(row.get("work_environment")): dict(row)
        for row in (crm.get("work_environments") or ())
        if isinstance(row, Mapping)
    }
    divisions = []
    for division in DIVISIONS:
        environment = environment_rows.get(division, {})
        divisions.append({
            "id": f"{claim_id}:{division.lower()}",
            "type": division,
            "selected": division == selected,
            "stage": _text(environment.get("stage")) or "not_applicable",
            "status": _text(environment.get("status")) or "",
            "owner": _text(environment.get("owner")),
            "external_references": {"trello": trello.get(division, {
                "id": "", "url": "", "pinned": False, "source": "trello",
            })},
        })

    conflicts = [dict(item) for item in (reconciliation.get("divisions") or ())
                 if isinstance(item, Mapping)
                 and _text(item.get("state")) in {"conflict", "ambiguous"}]
    return {
        "contract": {"name": CONTRACT_NAME, "version": CONTRACT_VERSION},
        "organization": {"franchise": franchise},
        "client": {
            "id": client_id,
            "display_name": customer_name,
            "phone": _text(job.get("phone")),
            "email": _text(job.get("email")),
        },
        "claim": {
            "id": claim_id,
            "display_name": claim_name,
            "claim_number": _text(job.get("claim_number")),
            "carrier": _text(job.get("carrier")),
            "status": _text(job.get("status")),
            "loss_type": _text(job.get("loss_type")),
            "date_of_loss": _text(job.get("date_of_loss")),
            "date_received": _text(job.get("date_received")),
            "address": _text(job.get("address")),
            "folder_path": _text(audit.get("path")) or _text(job.get("folder_path")),
        },
        "selected_division": selected,
        "divisions": divisions,
        "sync": {
            "state": "conflict" if conflicts else "ready",
            "conflicts": conflicts,
        },
    }

