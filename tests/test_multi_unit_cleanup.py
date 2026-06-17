"""Unit tests for multi_unit_cleanup parsing helpers.

The cleanup script is a one-shot CLI but the regex / date parsers are
load-bearing — a mis-parse triggers folder renames on a server share.
These tests pin the parsing rules so future tweaks don't silently break
the date / unit-number extraction.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import multi_unit_cleanup as muc


# ── Unit number detection ───────────────────────────────────────────────

def test_unit_prefix_required():
    """Bare-digit folders like 'Caprock\\1740' must NOT be detected as
    units — they're a different organizational scheme."""
    assert not muc._looks_like_unit_folder("1740 - 1_30")
    assert not muc._looks_like_unit_folder("3000")
    assert not muc._looks_like_unit_folder("abc")


def test_unit_prefix_matches_common_forms():
    assert muc._looks_like_unit_folder("Unit 1416")
    assert muc._looks_like_unit_folder("Unit 1416 5-9-26")
    assert muc._looks_like_unit_folder("UNIT 216")
    assert muc._looks_like_unit_folder("Unit #216")
    assert muc._looks_like_unit_folder("Apt 101")


def test_unit_prefix_excludes_service_subfolders():
    """Don't try to rename EMS / Recon / Contents / Docs / Pics."""
    for n in ("EMS", "Recon", "Contents", "DOCS", "Pics",
              "_PROPERTY"):
        assert not muc._looks_like_unit_folder(n), f"shouldn't match {n!r}"


def test_unit_re_captures_letter_suffix():
    """'Unit 561-I' must capture num='561-I' so renamed canonical form
    preserves the letter and two inspections don't collide."""
    m = muc._UNIT_RE.search("Unit 561-I")
    assert m is not None
    assert m.group("num") == "561-I"


def test_unit_re_captures_space_separated_letter_suffix():
    """'Unit 313 C - 3.20.26' has the letter separated by a space.
    Same intent as '561-I' — preserve the suffix."""
    m = muc._UNIT_RE.search("Unit 313 C - 3.20.26")
    assert m is not None
    assert "C" in m.group("num")
    # And the canonical form should normalize the separator to dash:
    assert muc._canonical_unit_name(m.group("num"), "3-19-26") == \
        "Unit 313-C 3-19-26"


def test_unit_re_captures_bare_number():
    m = muc._UNIT_RE.search("Unit 1416 5-9-26")
    assert m is not None
    assert m.group("num") == "1416"


# ── Date parsing from folder name ───────────────────────────────────────

def test_date_separator_forms():
    assert muc._date_from_folder_name("Unit 147 - 3.4.26") == "3-4-26"
    assert muc._date_from_folder_name("Unit 313 C - 3.20.26") == "3-20-26"
    assert muc._date_from_folder_name("Unit 1416 5/9/26") == "5-9-26"
    assert muc._date_from_folder_name("Unit 216 12-30-25") == "12-30-25"


def test_date_bare_mmddyyyy_form():
    """Variable-length bare-digit dates (M[M]D[D] + YYYY) all parse.
    Real-world examples pulled from the live audit base."""
    # 8 digits: 10-27-2025
    assert muc._date_from_folder_name("Unit 1612 10272025") == "10-27-25"
    assert muc._date_from_folder_name("Unit 218 10022025") == "10-2-25"
    # 7 digits: 4-14-2025 (single-digit month, double-digit day)
    assert muc._date_from_folder_name("Unit 514 4142025") == "4-14-25"
    assert muc._date_from_folder_name("Unit 1006 252025") == "2-5-25"
    # 6 digits: 6-1-2025 (both single-digit)
    assert muc._date_from_folder_name("Unit 411 612025") == "6-1-25"


def test_date_invalid_bare_mmddyyyy_returns_blank():
    """13-32-2025 isn't a real date — reject."""
    assert muc._date_from_folder_name("Unit X 13322025") == ""
    # Year out of range
    assert muc._date_from_folder_name("Unit X 12011999") == ""


def test_date_no_date_returns_blank():
    assert muc._date_from_folder_name("Unit 1611") == ""
    assert muc._date_from_folder_name("Unit 2417") == ""


# ── Canonical name rendering ────────────────────────────────────────────

def test_canonical_form_basic():
    assert muc._canonical_unit_name("1416", "5-9-26") == "Unit 1416 5-9-26"


def test_canonical_form_preserves_letter_suffix():
    """561-I and 561-J should NOT collapse to the same canonical
    name — preserve the letter so the inspections stay distinct."""
    assert muc._canonical_unit_name("561-I", "2-2-26") == "Unit 561-I 2-2-26"
    assert muc._canonical_unit_name("561-J", "2-2-26") == "Unit 561-J 2-2-26"


def test_canonical_form_uppercases_and_normalizes_letter_suffix():
    """Underscore separator + lowercase letter normalize to dash + upper."""
    assert muc._canonical_unit_name("561_i", "2-2-26") == "Unit 561-I 2-2-26"


def test_canonical_re_accepts_canonical_form():
    assert muc._CANONICAL_RE.match("Unit 1416 5-9-26")
    assert muc._CANONICAL_RE.match("Unit 561-I 2-2-26")
    assert not muc._CANONICAL_RE.match("Unit 1416")
    assert not muc._CANONICAL_RE.match("UNIT 1416 5-9-26")  # case-sensitive


# ── Property-name suffix stripping ──────────────────────────────────────

def test_property_year_suffix_stripped():
    assert muc._strip_property_suffix("Avila Apartments 2026") == "Avila Apartments"
    assert muc._strip_property_suffix("Avila Apartments") == "Avila Apartments"
    # No suffix to strip
    assert muc._strip_property_suffix("Metro at Main") == "Metro at Main"


# ── Conflict detection in execute_renames ──────────────────────────────

def test_execute_flags_same_target_collisions():
    """Two source folders proposing the SAME target should BOTH skip
    with status='CONFLICT' so the user resolves manually."""
    renames = [
        muc.Rename(src="/x/Unit 226 12302025",
                   dst="/x/Unit 226 1-29-25",
                   reason="from Trello"),
        muc.Rename(src="/x/Unit 226 1292025",
                   dst="/x/Unit 226 1-29-25",
                   reason="from Trello"),
        muc.Rename(src="/x/Unit 310",
                   dst="/x/Unit 310 4-25-25",
                   reason="from Trello"),
    ]
    summary = muc.execute_renames(renames, dry_run=True)
    statuses = {e[0]: e[2] for e in summary["events"]}
    assert statuses["/x/Unit 226 12302025"] == "CONFLICT"
    assert statuses["/x/Unit 226 1292025"] == "CONFLICT"
    assert statuses["/x/Unit 310"] == "DRY"
    assert "/x/Unit 226 1-29-25" in summary["conflicts"]
