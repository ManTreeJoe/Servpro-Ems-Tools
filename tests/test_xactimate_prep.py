"""Xactimate prep — learnable carrier price-list map + copy block."""
import persistence
import ems_db
import xactimate_prep as xp


def test_pricelist_map_roundtrip(monkeypatch):
    state = {}
    monkeypatch.setattr(persistence, "_load", lambda: state)
    monkeypatch.setattr(persistence, "_save", lambda s: state.update(s))
    assert xp.pricelist_for("Mercury") == ""
    xp.set_pricelist("Mercury Insurance", "CA_SoCal")
    # Case/whitespace-insensitive lookup.
    assert xp.pricelist_for("mercury  insurance") == "CA_SoCal"
    # Clearing removes it.
    xp.set_pricelist("Mercury Insurance", "")
    assert xp.pricelist_for("Mercury Insurance") == ""
    # No carrier → error, not a crash.
    assert xp.set_pricelist("", "x")["ok"] is False


def test_resolve_prefills_from_db(monkeypatch):
    monkeypatch.setattr(ems_db, "find_job_by_name",
                        lambda c: {"claim_number": "CLM-9", "carrier": "Mercury"})
    state = {"xa_pricelists": {"mercury": "CA_SoCal"}}
    monkeypatch.setattr(persistence, "_load", lambda: state)
    monkeypatch.setattr(persistence, "_save", lambda s: state.update(s))
    r = xp.resolve("Mims, Stewart")
    assert r["insured"] == "Mims, Stewart"
    assert r["claim"] == "CLM-9" and r["carrier"] == "Mercury"
    assert r["pricelist"] == "CA_SoCal"


def test_resolve_survives_no_db(monkeypatch):
    def _boom(c):
        raise RuntimeError("db down")
    monkeypatch.setattr(ems_db, "find_job_by_name", _boom)
    monkeypatch.setattr(persistence, "_load", lambda: {})
    r = xp.resolve("Doe, Jane")
    assert r["insured"] == "Doe, Jane" and r["claim"] == "" and r["carrier"] == ""


def test_field_block_labels_and_skips_blanks():
    block = xp.field_block({
        "insured": "Mims, Stewart", "claim": "CLM-9", "carrier": "Mercury",
        "address": "", "loss_type": "Water", "date_of_loss": "7/14/26",
    })
    lines = block.splitlines()
    assert "Insured: Mims, Stewart" in lines
    assert "Claim #: CLM-9" in lines
    assert "Type of loss: Water" in lines
    # Blank address omitted.
    assert not any(l.startswith("Property address") for l in lines)
