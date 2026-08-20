"""Search should find a job by its claim number or address.

Schema v6 promoted both to real columns and neither was ever queried:
typing a claim number found nothing, though the office often has the
claim number in front of them and not the spelling of the name.

The scan is GATED on the text looking like a claim/address (a digit, 3+
characters). Without that, every keystroke of an ordinary name search
would scan the jobs table over the network.
"""
import pytest

import audit_web


@pytest.mark.parametrize("text", [
    "017916921", "2601-33412", "750J2L926", "123 Main St",
    "2507388588WTR", "28525 La Piedra",
])
def test_claim_and_address_shapes_are_scanned(text):
    assert audit_web._looks_like_claim_or_address(text) is True


@pytest.mark.parametrize("text", [
    "Abbott", "Abbott, Darlene", "Menifee", "", "  ", "ab", "7",
])
def test_plain_names_are_not(text):
    """A name search must not pay for a jobs scan on every keystroke."""
    assert audit_web._looks_like_claim_or_address(text) is False


def test_the_search_reads_both_columns():
    """Both were promoted in v6; searching one and not the other would be
    an odd half-feature."""
    import inspect
    src = inspect.getsource(audit_web.Api.list_audit_candidates)
    assert "claim_number" in src
    assert "address" in src
    assert "_looks_like_claim_or_address" in src


def test_a_claim_hit_outranks_an_address_hit():
    """A claim number identifies exactly one job; an address can be
    shared by several units of one property."""
    import inspect, re
    src = inspect.getsource(audit_web.Api.list_audit_candidates)
    i = src.index('"claim",')
    j = src.index('"address",')
    claim_score = int(re.search(r"(\d+)\)", src[i:i + 220]).group(1))
    addr_score = int(re.search(r"(\d+)\)", src[j:j + 220]).group(1))
    assert claim_score > addr_score


def test_folder_lookup_never_raises():
    """It runs per candidate; one bad row must not kill the search."""
    assert audit_web._folder_of_job({}) == ""
    assert audit_web._folder_of_job({"canon_key": None}) == ""
