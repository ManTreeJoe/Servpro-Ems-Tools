"""Guard against pinning a job into another client's folder.

The bug this came from: "Neely, Maria - AAA (2nd Claim)" — a 2026 job —
was folder-pinned to `2025 jobs\alvarez diane - 2nd claim\2nd claim`.
The only thing the two names shared was the words "2nd claim", which
every second-claim job on the share carries.
"""

import os

import pytest

from web_helpers import folder_pin_mismatch


def _p(*parts):
    """Build a share-style path with the platform separator."""
    return os.sep.join(("x:", "ie_public") + parts)


# ── the real bug ────────────────────────────────────────────────────

def test_the_neely_alvarez_mispin_is_flagged():
    warn = folder_pin_mismatch(
        "Neely, Maria - AAA (2nd Claim)",
        _p("2025 jobs", "alvarez diane - 2nd claim", "2nd claim"))
    assert warn
    assert "Neely, Maria - AAA (2nd Claim)" in warn


def test_shared_structural_words_alone_do_not_excuse_a_mismatch():
    # "2nd claim" on both sides is not evidence of anything.
    assert folder_pin_mismatch("Smith, John (2nd Claim)",
                               _p("2026 jobs", "garcia luis - 2nd claim"))


# ── pins that must stay silent ──────────────────────────────────────

def test_the_right_folder_passes():
    assert folder_pin_mismatch(
        "Neely, Maria - AAA (2nd Claim)",
        _p("2026 jobs", "neely, maria", "2nd claim")) == ""


def test_a_unit_subfolder_matches_via_its_parent():
    # The pinned leaf carries no name; the parent does.
    assert folder_pin_mismatch(
        "Avila, Jose",
        _p("2026 jobs", "Avila Jose - Menifee", "Unit 526 2-28-26")) == ""


def test_reversed_name_order_still_matches():
    assert folder_pin_mismatch("Valek, Linda",
                               _p("2026 jobs", "Linda Valek")) == ""


def test_a_spelling_wobble_is_not_a_mismatch():
    # Neely / Neeley and Gonzalez / Gonzales are the same person filed twice.
    assert folder_pin_mismatch("Neely, Maria",
                               _p("2026 jobs", "Neeley, Maria")) == ""
    assert folder_pin_mismatch("Gonzalez, Ana",
                               _p("2026 jobs", "Gonzales, Ana")) == ""


def test_short_tokens_do_not_fuzzy_match():
    # "Ann" vs "Amy" are close in edit distance but are different people;
    # only tokens long enough for a high ratio to mean something may fuzz.
    assert folder_pin_mismatch("Ann, Bob", _p("2026 jobs", "Amy, Bob")) == ""


# ── stay quiet when there is nothing to judge ───────────────────────

def test_address_only_folder_is_not_flagged():
    # Legitimately-filed folders often carry no personal name at all.
    assert folder_pin_mismatch(
        "Smith, John", _p("2026 jobs", "10882 Cochran Ave Riverside")) == ""


def test_a_bare_unit_folder_is_not_flagged():
    assert folder_pin_mismatch("Smith, John",
                               _p("2026 jobs", "Unit 5")) == ""


def test_client_with_no_identity_tokens_is_not_flagged():
    assert folder_pin_mismatch("2nd Claim",
                               _p("2026 jobs", "garcia luis")) == ""


@pytest.mark.parametrize("client,path", [
    ("", _p("2026 jobs", "garcia")),
    ("Smith, John", ""),
    (None, None),
])
def test_missing_input_is_never_a_warning(client, path):
    assert folder_pin_mismatch(client, path) == ""


# ── the share root must not launder a match ─────────────────────────

def test_year_folder_and_share_root_cannot_supply_the_match():
    # "ie_public" / "2026 jobs" sit above the depth window; a client
    # literally named "Public" must not match on the share root.
    assert folder_pin_mismatch("Public, Joe",
                               _p("2026 jobs", "garcia luis"))


def test_forward_slashes_are_handled():
    assert folder_pin_mismatch(
        "Neely, Maria",
        "x:/ie_public/2025 jobs/alvarez diane - 2nd claim/2nd claim")
