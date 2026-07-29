"""Xactimate 'new estimate from scratch' prep.

A valid .esx can't be generated outside Xactimate (Verisk's proprietary
format + pricing engine), so this removes the manual work AROUND building
one by hand: it remembers the price list you use per carrier and hands you
a clean, copy-paste-ready block of the job's fields for the New Estimate
dialog. Pure data layer; UI lives in web_shared/xactimate_prep.js.

The carrier→price-list map is learnable: set it once per carrier and it
sticks (persistence `xa_pricelists`).
"""
from __future__ import annotations

import persistence

# Field order for the copy block — the order Xactimate's New Estimate
# dialog roughly asks for them.
_BLOCK_ORDER = [
    ("insured",      "Insured"),
    ("address",      "Property address"),
    ("carrier",      "Carrier"),
    ("claim",        "Claim #"),
    ("date_of_loss", "Date of loss"),
    ("loss_type",    "Type of loss"),
]


def _carrier_key(carrier: str) -> str:
    """Normalize a carrier name to a stable map key (casefold + collapse
    whitespace). 'Mercury Insurance' and 'mercury  insurance' converge."""
    return " ".join((carrier or "").lower().split())


def get_map() -> dict:
    try:
        return persistence._load().get("xa_pricelists") or {}
    except Exception:
        return {}


def pricelist_for(carrier: str) -> str:
    return get_map().get(_carrier_key(carrier), "")


def set_pricelist(carrier: str, pricelist: str) -> dict:
    """Remember (or clear) the Xactimate price list for a carrier."""
    key = _carrier_key(carrier)
    if not key:
        return {"ok": False, "error": "no carrier"}
    try:
        state = persistence._load()
        m = state.setdefault("xa_pricelists", {})
        pl = (pricelist or "").strip()
        if pl:
            m[key] = pl
        else:
            m.pop(key, None)
        persistence._save(state)
        return {"ok": True, "pricelist": pl}
    except Exception as ex:
        return {"ok": False, "error": str(ex)}


def resolve(client: str) -> dict:
    """Pre-fill what we already know about a job (insured / claim / carrier
    + the remembered price list). Blank fields are for the user to fill in
    the dialog. Never raises."""
    insured = (client or "").strip()
    claim, carrier = "", ""
    try:
        import ems_db
        j = ems_db.find_job_by_name(client)
        if j:
            claim = (j.get("claim_number") or "").strip()
            carrier = (j.get("carrier") or "").strip()
    except Exception:
        pass
    return {
        "insured":      insured,
        "claim":        claim,
        "carrier":      carrier,
        "pricelist":    pricelist_for(carrier) if carrier else "",
        "loss_type":    "",
        "date_of_loss": "",
        "address":      "",
    }


def field_block(fields: dict) -> str:
    """A labeled block of the job's fields for pasting into Xactimate,
    one field per line; blank fields are omitted."""
    lines = []
    for key, label in _BLOCK_ORDER:
        v = str((fields or {}).get(key) or "").strip()
        if v:
            lines.append(f"{label}: {v}")
    return "\n".join(lines)
