"""Detecting one insured typed two ways.

The job key comes from the name, so "Seth Knudsen" and
"Knudsen, Seth - Mercury" are two jobs for one person and the carrier,
claim and photos land on whichever row a tool happened to resolve.

The detector only PROPOSES. Folding two people who share a surname is
worse than the split, so the tests below care most about what it must
NOT claim.
"""
import pytest

import job_name_issues as jni


# ── swapped_name ──────────────────────────────────────────────────────

@pytest.mark.parametrize("name,want", [
    ("Knudsen, Seth", "Seth Knudsen"),
    ("Knudsen, Seth - Mercury", "Seth Knudsen"),
    ("Seth Knudsen", "Knudsen, Seth"),
    ("Ochoa, Edward- AAA", "Edward Ochoa"),
    ("Greer, Tesal - Mercury - FIRE", "Tesal Greer"),
])
def test_swaps_the_obvious_forms(name, want):
    assert jni.swapped_name(name) == want


@pytest.mark.parametrize("name", [
    "Athena Management Property",      # three words, not a person
    "Aperto Property Management",
    "",
    "   ",
    "Smith",                           # one word — nothing to swap
])
def test_refuses_names_it_cannot_read(name):
    """A guess nobody can confirm is worse than no suggestion: it trains
    people to click through the review without reading it."""
    assert jni.swapped_name(name) == ""


def test_multi_word_first_name_survives_the_comma_form():
    assert jni.swapped_name("Miles, Bridgitte & Anthony - AAA") \
        == "Bridgitte & Anthony Miles"


def test_swapping_twice_returns_the_original_shape():
    once = jni.swapped_name("Seth Knudsen")
    assert jni.swapped_name(once) == "Seth Knudsen"


# ── find_split_pairs ──────────────────────────────────────────────────

def _job(key, name, **kw):
    d = {"canon_key": key, "display_name": name}
    d.update(kw)
    return d


def test_finds_a_split_pair():
    jobs = [_job("seth knudsen", "Seth Knudsen"),
            _job("knudsen, seth", "Knudsen, Seth - Mercury")]
    pairs = jni.find_split_pairs(jobs)
    assert len(pairs) == 1


def test_a_pair_is_reported_once_not_twice():
    """Both rows point at each other; the review must not list it twice."""
    jobs = [_job("seth knudsen", "Seth Knudsen"),
            _job("knudsen, seth", "Knudsen, Seth")]
    assert len(jni.find_split_pairs(jobs)) == 1


def test_unrelated_jobs_are_not_paired():
    jobs = [_job("smith, john", "Smith, John"),
            _job("jones, mary", "Jones, Mary")]
    assert jni.find_split_pairs(jobs) == []


def test_a_lone_job_is_not_a_pair():
    """The swapped form must actually EXIST as another job — otherwise
    every job in the book looks like half a pair."""
    assert jni.find_split_pairs([_job("seth knudsen", "Seth Knudsen")]) == []


def test_ignored_pairs_are_not_offered_again():
    jobs = [_job("seth knudsen", "Seth Knudsen"),
            _job("knudsen, seth", "Knudsen, Seth")]
    sig = jni.pair_key("seth knudsen", "knudsen, seth")
    assert jni.find_split_pairs(jobs, ignored={sig}) == []


def test_pair_key_is_order_independent():
    """"Different people" has to stick whichever way round it's next
    seen."""
    assert jni.pair_key("a", "b") == jni.pair_key("b", "a")


# ── describe ──────────────────────────────────────────────────────────

def test_matching_carrier_reads_as_probably_the_same():
    a = _job("tesal greer", "Tesal Greer", carrier="Mercury")
    b = _job("greer, tesal", "Greer, Tesal - Mercury", carrier="Mercury")
    d = jni.describe(a, b)
    assert d["likely_same"] is True
    assert "carrier" in d["agrees"]


def test_conflicting_claim_numbers_are_flagged_not_hidden():
    """Two different claim numbers usually means two real jobs. That has
    to reach the person deciding."""
    a = _job("smith, john", "Smith, John", claim_number="AAA-1")
    b = _job("john smith", "John Smith", claim_number="BBB-2")
    d = jni.describe(a, b)
    assert "claim_number" in d["conflicts"]
    assert d["likely_same"] is False


def test_no_shared_details_is_not_a_recommendation():
    """Nothing to compare must not read as "safe to merge"."""
    d = jni.describe(_job("a b", "A B"), _job("b, a", "B, A"))
    assert d["likely_same"] is False
    assert d["agrees"] == [] and d["conflicts"] == []


def test_blank_on_one_side_is_not_a_conflict():
    """A field only one row carries is what folding would RECOVER."""
    a = _job("smith, john", "Smith, John", carrier="AAA")
    b = _job("john smith", "John Smith", carrier="")
    d = jni.describe(a, b)
    assert d["conflicts"] == []


def test_case_differences_are_not_conflicts():
    a = _job("smith, john", "Smith, John", carrier="aaa")
    b = _job("john smith", "John Smith", carrier="AAA")
    assert jni.describe(a, b)["conflicts"] == []


def test_describe_carries_both_keys_for_the_merge_call():
    d = jni.describe(_job("a b", "A B"), _job("b, a", "B, A"))
    assert d["a"]["canon_key"] and d["b"]["canon_key"]
    assert d["pair_key"] == jni.pair_key("a b", "b, a")


def test_a_hyphenated_surname_is_not_mistaken_for_a_carrier():
    """"Michael-Mercury" is a carrier suffix; "Smith-Jones" is a surname.
    Punctuation can't tell them apart, so the strip asks what the word
    IS. Getting this wrong pairs Mary Smith-Jones with a Mary Smith who
    may be somebody else entirely."""
    assert jni.swapped_name("Mary Smith-Jones") == "Smith-Jones, Mary"
    assert jni.swapped_name("Ensign, Michael-Mercury") == "Michael Ensign"


@pytest.mark.parametrize("name,want", [
    ("Greer, Tesal - Mercury - FIRE", "Tesal Greer"),   # carrier + loss type
    ("Smith, John - Water", "John Smith"),
    ("Doe, Jane - AAA - MOLD", "Jane Doe"),
])
def test_stacked_job_decoration_is_stripped(name, want):
    assert jni.swapped_name(name) == want


def test_an_unknown_trailing_word_is_kept():
    """Only recognised decoration comes off — an unknown word might be
    part of the name, and cutting it invents a person."""
    assert jni.swapped_name("Smith, John - Wossname") != "John Smith"
