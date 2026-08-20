"""The levels between a client and a claim.

`job_children` modelled ONE level, so the office's real hierarchy —
management company → property → unit → claim date — was being crammed
into the child's `name`. That is how
'aperto property management- (tres lagos' became a truncated key with two
units hiding behind it, both of which canonicalise to plain 'tres lagos'.

Every example below is a live folder name.
"""
import pytest

from ems_db_common import parse_child_levels as parse
import ems_db_sqlite as db


@pytest.mark.parametrize("name,prop,unit,date", [
    # The convention the office already writes, unprompted.
    ("Tres Lagos - Unit 3208 - 8.13.26", "Tres Lagos", "3208", "8.13.26"),
    ("Tres Lagos - Unit 6204 - 8.17.26", "Tres Lagos", "6204", "8.17.26"),
    ("Avila Apartments (Unit 623) - (6/29/26)", "Avila Apartments", "623",
     "6/29/26"),
    ("Montclair Town homes Unit 62 7-22-26", "Montclair Town homes", "62",
     "7-22-26"),
    # Depth varies: a bare unit has no property above it in the NAME,
    # because the parent folder already supplies it.
    ("Unit 585-G", "", "585-G", ""),
    ("Unit 1416B", "", "1416B", ""),
    ("Unit 311C", "", "311C", ""),
    # A site with a date but no unit — the commercial shape.
    ("Menifee School District - Bell Mountain - 8.14.26",
     "Menifee School District - Bell Mountain", "", "8.14.26"),
    # Neither: a claim, or a plain sub-job folder.
    ("Claim 1 (water)", "Claim 1 (water)", "", ""),
    ("Garage Door", "Garage Door", "", ""),
])
def test_live_folder_names(name, prop, unit, date):
    got = parse(name)
    assert got["property"] == prop
    assert got["unit"] == unit
    assert got["claim_date"] == date


def test_units_stay_text():
    """'585-G' and '1416B' are real units. An int column would lose them,
    and int(unit) would raise on half the property portfolio."""
    assert parse("Unit 585-G")["unit"] == "585-G"
    assert parse("Unit 1416B")["unit"] == "1416B"


def test_no_dangling_bracket_is_ever_produced():
    """Cutting 'Avila Apartments (Unit 623)' at the unit token leaves
    'Avila Apartments (' — and an unbalanced paren IS the Aperto bug.
    But brackets that belong to the name must survive."""
    assert parse("Avila Apartments (Unit 623)")["property"] == "Avila Apartments"
    assert parse("Claim 1 (water)")["property"] == "Claim 1 (water)"
    assert parse("Coreland (Nordstrom Rack - Back Room)")["property"] == \
        "Coreland (Nordstrom Rack - Back Room)"


def test_a_miss_returns_blank_not_a_guess():
    """Inventing a unit number is the confident-but-wrong answer this
    whole effort exists to remove."""
    got = parse("Homeless Encampment")
    assert got["unit"] == "" and got["claim_date"] == ""


# ── storage ────────────────────────────────────────────────────────────

def test_set_child_stores_the_levels(tmp_path):
    db.reset_db_path(str(tmp_path / "t.db"))
    db.upsert_job(display_name="Aperto Property Management")
    key = db.canon_key("Aperto Property Management")

    db.set_child(key, "Tres Lagos - Unit 6204 - 8.17.26",
                 property="Tres Lagos", unit="6204", claim_date="8.17.26")

    c = db.children_of(key)[0]
    assert (c["property"], c["unit"], c["claim_date"]) == \
        ("Tres Lagos", "6204", "8.17.26")


def test_a_later_write_does_not_blank_the_levels(tmp_path):
    """Blank never overwrites — the partial-update rule set_child
    promises. A call that only pins a card must not wipe the unit."""
    db.reset_db_path(str(tmp_path / "t.db"))
    db.upsert_job(display_name="Aperto Property Management")
    key = db.canon_key("Aperto Property Management")
    db.set_child(key, "Tres Lagos - Unit 6204 - 8.17.26",
                 property="Tres Lagos", unit="6204", claim_date="8.17.26")

    db.set_child(key, "Tres Lagos - Unit 6204 - 8.17.26",
                 trello_card="6a839f8bd0ca072308e4f906")

    c = db.children_of(key)[0]
    assert c["unit"] == "6204"
    assert c["property"] == "Tres Lagos"
    assert c["claim_date"] == "8.17.26"
    assert c["trello_card"] == "6a839f8bd0ca072308e4f906"
