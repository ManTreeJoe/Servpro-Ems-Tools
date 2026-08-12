"""Carrier names: fix the spellings we know, never mangle the ones we don't.

The field is free text, so the same insurer arrives spelled several ways.
The tail is real though — Homesite, Bamboo, Lemonade — and new carriers
show up constantly, so anything unrecognised must survive untouched.
"""

import pytest

import carriers


# ── the folds the office asked for ──────────────────────────────────

@pytest.mark.parametrize("typed,expect", [
    ("aaa", "AAA"),
    ("AAA", "AAA"),
    ("state farm", "State Farm"),
    ("state Farm", "State Farm"),
    ("Statefarm", "State Farm"),
    ("usaa", "USAA"),
    ("Aegis", "AEGIS"),
    ("MERCURY", "Mercury"),
    ("Mercury Insurance", "Mercury"),
    ("AmFam", "American Family"),
    ("Self", "Self Pay"),
    ("Self-Pay", "Self Pay"),
    ("self pay", "Self Pay"),
])
def test_known_spellings_canonicalize(typed, expect):
    assert carriers.normalize(typed) == expect


def test_whitespace_is_tidied():
    assert carriers.normalize("  State   Farm  ") == "State Farm"


# ── the tail must survive ───────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "Lemonade", "Homesite", "Bamboo", "Universal", "Safeco",
    "The Hartford", "California Fair Plan", "One Alliance North America",
    "Some Brand New Carrier LLC",
])
def test_unknown_carriers_pass_through_untouched(name):
    assert carriers.normalize(name) == name


def test_a_guess_is_never_resolved_into_a_fact():
    # "Possibly SF" records uncertainty. Folding it to State Farm would
    # launder a guess into a fact.
    assert carriers.normalize("Possibly SF") == "Possibly SF"


def test_blank_in_blank_out():
    assert carriers.normalize("") == ""
    assert carriers.normalize(None) == ""
    assert carriers.normalize("   ") == ""


# ── the status values ───────────────────────────────────────────────

@pytest.mark.parametrize("typed", ["N/A", "n/a", "na", "None"])
def test_no_carrier_values_canonicalize(typed):
    assert carriers.normalize(typed) == carriers.NOT_A_CARRIER


@pytest.mark.parametrize("typed", ["Pending", "pending", "TBD", "unknown"])
def test_waiting_on_info_canonicalizes(typed):
    assert carriers.normalize(typed) == carriers.PENDING


# ── classification ──────────────────────────────────────────────────

@pytest.mark.parametrize("value,expect", [
    ("", ""),
    ("N/A", "none"),
    ("Pending", "pending"),
    ("Self Pay", "self"),
    ("Sedgwick", "tpa"),
    ("George Hills", "tpa"),
    ("AAA", "carrier"),
    ("Lemonade", "carrier"),      # unrecognised is still a carrier
])
def test_kind_classifies(value, expect):
    assert carriers.kind(value) == expect


def test_a_tpa_is_not_counted_as_an_insurer():
    assert carriers.is_tpa("sedgwick") is True
    assert carriers.is_tpa("AAA") is False


def test_pending_does_not_count_as_specified():
    # The whole point of the Pending option: it must not read as covered.
    assert carriers.is_specified("Pending") is False
    assert carriers.is_specified("N/A") is False
    assert carriers.is_specified("") is False
    assert carriers.is_specified("AAA") is True
    assert carriers.is_specified("Sedgwick") is True


# ── picker options ──────────────────────────────────────────────────

def test_options_lead_with_the_status_values():
    opts = carriers.options()
    assert [o["value"] for o in opts[:2]] == list(carriers.SPECIAL_VALUES)


def test_options_label_tpas_separately():
    groups = {o["value"]: o["group"] for o in carriers.options()}
    assert "TPA" in groups["Sedgwick"]
    assert groups["AAA"] == "Carrier"


def test_every_option_is_already_canonical():
    for o in carriers.options():
        assert carriers.normalize(o["value"]) == o["value"]


def test_options_have_no_duplicates():
    vals = [o["value"] for o in carriers.options()]
    assert len(vals) == len(set(vals))
