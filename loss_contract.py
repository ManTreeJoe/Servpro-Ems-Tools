"""Shared Loss view contract. No I/O, provider matching, or inferred identity.

The legacy job-workspace v1 stays supported while screens migrate. This contract
requires explicit organization and Loss IDs; claims are children of a Loss.
"""
from copy import deepcopy


DIVISIONS = ("EMS", "CONTENTS", "RECON")


def _id(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def build_loss_view(record, *, selected_division=None):
    """Project a canonical record for a list row or one division board card.

    Caller supplies an authorized record. This projection is not authorization.
    Unknown facts remain None; never fabricate dates, ownership, or readiness.
    """
    organization_id = _id(record.get("organization_id"), "organization_id")
    loss_id = _id(record.get("id"), "loss.id")
    divisions = deepcopy(record.get("divisions", []))
    seen = set()
    division_ids = set()
    for division in divisions:
        kind = division.get("type")
        if kind not in DIVISIONS or kind in seen:
            raise ValueError("Division types must be valid and unique per Loss")
        seen.add(kind)
        division_id = _id(division.get("id"), "division.id")
        if division_id in division_ids:
            raise ValueError("Division IDs must be unique within a Loss")
        division_ids.add(division_id)
    if selected_division is not None and selected_division not in seen:
        raise ValueError("Selected Division does not belong to this Loss")
    claims = deepcopy(record.get("claims", []))
    claim_ids = [_id(claim.get("id"), "claim.id") for claim in claims]
    if len(set(claim_ids)) != len(claim_ids):
        raise ValueError("Claim IDs must be unique within a Loss")
    selected = next((d for d in divisions if d["type"] == selected_division), None)
    return {
        "contract": {"name": "linguar.loss-view", "version": 1},
        "organization_id": organization_id,
        "id": loss_id,
        "client_id": record.get("client_id"),
        "number": record.get("number"),
        "customer": record.get("customer"),
        "properties": deepcopy(record.get("properties", [])),
        "claims": claims,
        "divisions": divisions,
        "selected_division": selected_division,
        "stage": selected.get("stage") if selected else None,
        "next_action": deepcopy(selected.get("next_action")) if selected else None,
        "identity": {"state": "canonical"},
    }


def division_cards(records, division):
    """One card per Loss on the selected division board, with stable identity."""
    if division not in DIVISIONS:
        raise ValueError("Unknown Division")
    seen = set()
    cards = []
    for record in records:
        key = (_id(record.get("organization_id"), "organization_id"),
               _id(record.get("id"), "loss.id"))
        if key in seen:
            raise ValueError("Duplicate Loss in input; reconcile before rendering")
        seen.add(key)
        view = build_loss_view(record)
        if any(d["type"] == division for d in view["divisions"]):
            cards.append(build_loss_view(record, selected_division=division))
    return cards
