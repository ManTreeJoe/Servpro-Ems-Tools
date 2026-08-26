"""Batched carrier lookup behind the row's carrier chip.

Batched for the same reason card_display_names_for is: the audit shapes
hundreds of rows at once, and the per-row form of this cost ~600 round
trips — invisible on local SQLite, ruinous on a hosted one.
"""
import pytest
from pathlib import Path

import ems_db_sqlite as sq


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def db(tmp_path):
    sq.reset_db_path(str(tmp_path / "t.db"))
    return sq


def _job(db, name, carrier=None):
    """A job, optionally with a carrier. upsert_job treats a blank as
    "don't overwrite", so a carrier-less job simply omits it."""
    if carrier is None:
        db.upsert_job(display_name=name)
    else:
        db.upsert_job(display_name=name, carrier=carrier)
    return db.canon_key(name)


def test_returns_the_carrier_for_a_known_job(db):
    _job(db, "Smith, John", "AAA")
    assert db.carriers_for(["Smith, John"]) == {"Smith, John": "AAA"}


def test_job_without_a_carrier_is_absent_not_blank(db):
    """The chip renders on presence, so a blank must not appear as a key
    — 45% of live jobs have no carrier and would all get an empty chip."""
    _job(db, "Smith, John")
    assert db.carriers_for(["Smith, John"]) == {}


def test_unknown_name_is_absent(db):
    assert db.carriers_for(["Nobody At All"]) == {}


def test_empty_input_costs_nothing(db):
    assert db.carriers_for([]) == {}
    assert db.carriers_for(None) == {}


def test_many_names_in_one_call(db):
    for n, c in (("A One", "AAA"), ("B Two", "Mercury"), ("C Three", None)):
        _job(db, n, c)
    got = db.carriers_for(["A One", "B Two", "C Three", "D Four"])
    assert got == {"A One": "AAA", "B Two": "Mercury"}


def test_whitespace_carrier_counts_as_none(db):
    _job(db, "Smith, John", "   ")
    assert db.carriers_for(["Smith, John"]) == {}


def test_lookup_is_by_canon_key_not_exact_spelling(db):
    """The audit passes run-doc spellings, which vary."""
    _job(db, "Smith, John", "Farmers")
    got = db.carriers_for(["smith,  john"])
    assert list(got.values()) == ["Farmers"]


def test_alias_resolves_to_its_job(db):
    _job(db, "Ramirez, Gabriella - Farmers", "Farmers")
    db.add_alias(db.canon_key("Ramirez, Gabriella - Farmers"), "Gabby Ramirez")
    assert db.carriers_for(["Gabby Ramirez"]) == {"Gabby Ramirez": "Farmers"}


def test_a_name_that_is_its_own_job_never_falls_through_to_an_alias(db):
    """The live trap card_display_names_for documents: 'Gabriel Ramirez'
    is a real uncarded job AND an alias of 'Ramirez, Gabriella'. Falling
    through labels the row with a DIFFERENT customer's carrier."""
    _job(db, "Gabriel Ramirez")                     # real job, no carrier
    _job(db, "Ramirez, Gabriella - Farmers", "Farmers")
    db.add_alias(db.canon_key("Ramirez, Gabriella - Farmers"),
                 "Gabriel Ramirez")
    assert db.carriers_for(["Gabriel Ramirez"]) == {}


def test_self_pay_is_returned_like_any_other_value(db):
    """Self Pay is already a carrier value on live jobs — no special
    casing in the data layer; the chip colours it differently."""
    _job(db, "Cash Customer", "Self Pay")
    assert db.carriers_for(["Cash Customer"]) == {"Cash Customer": "Self Pay"}


def test_duplicate_names_in_the_request_all_get_answered(db):
    _job(db, "Smith, John", "AAA")
    got = db.carriers_for(["Smith, John", "Smith, John"])
    assert got == {"Smith, John": "AAA"}


def test_audit_job_row_renders_the_carrier_tag():
    js = (ROOT / "audit_web_assets" / "app.js").read_text(encoding="utf-8")
    assert "const carrierChip = carrierChipHtml(r.carrier);" in js
    assert "if (carrierChip) subChips.push(carrierChip);" in js
    assert "window.AuditDetail.carrierChip(carrier, \"mini-chip\")" in js
