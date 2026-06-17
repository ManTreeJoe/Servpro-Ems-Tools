"""Tests for initial_notes_parser — field-template extraction.

The user-provided example is the canonical anchor: a real tech-filed
initial-inspection block with the mix of Yes-No prompts, inline
secondary labels (Category + Class), and free-text values that the
parser has to handle without choking on partial entries."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from initial_notes_parser import (
    parse_initial_inspection_notes,
    format_initial_notes,
    _resolve_yes_no,
)


# The exact text the user said is "given" to the snapshot — a real
# tech inspection note with all the messy cases:
#   - "Cause of Loss (COL):fridge line" — no space after colon
#   - "Category (CAT):   2 Class: 2" — inline secondary label
#   - "Leak Detection Recommended:/ No" — slash-prefix Yes/No
#   - "Photos Taken: Yes /" — slash-suffix
#   - "Met With (Insured" — incomplete label, no value
USER_EXAMPLE = """Initial notes

Date:5-11-26

Time of Inspections:3:00 pm
Met With (Insured

Cause of Loss (COL):fridge line
Category (CAT):   2 Class: 2
Plumbing Repairs Completed: No
Leak Detection Recommended:/ No
Re-inspection Needed:  No

Water Heater Temp Set:  No

STRUCTURE & DAMAGE SUMMARY

Number of Levels Affected:
Areas Affected – List by Level & Room/Materials:

Upstairs:

Downstairs: liv hall closet mbed laundry laminate drywall, kitchen laminate drywall cabinets, bath drywall cabinet

TESTING

Asbestos/Lead Testing Needed: Yes /
Areas/Materials Needing Testing:drywall

CONTENTS

Packout Required:  No
Content Manipulation : Yes /
Storage Type: POD / Onsite / Offsite
Where Are Contents Being Stored:shift around

MOLD

Visible Mold Present:  No
Rooms Affected:
Greater or Less Than 10 Sq Ft:

EQUIPMENT

Equipment Placed: / No
Type & Quantity (List by Room):

Specialty EQ and Why:

PAPERWORK

Signed Today: / No
Types (WA, COS, etc.):

CUSTOMER CONCERNS / NOTES:OFFICE FOLLOW-UP

Photos Taken: Yes /
Video Taken: Yes /
DocuSketch Completed: Yes /

Additional Field Notes / Observations: Initial notes

Condo unit. Need to check limits. Needs testing. Owner wants to speak with insurance first.
"""


def test_parses_user_example():
    blocks = parse_initial_inspection_notes(USER_EXAMPLE)
    assert len(blocks) == 1
    b = blocks[0]
    # Core captured fields
    assert b.get("Date") == "5-11-26"
    assert b.get("Time") == "3:00 pm"
    assert b.get("Cause of Loss") == "fridge line"
    assert b.get("Category") == "2"
    assert b.get("Class") == "2"
    assert b.get("Plumbing Repairs") == "No"
    assert b.get("Leak Detection") == "No"
    assert b.get("Re-inspection") == "No"
    assert b.get("Water Heater Temp") == "No"
    assert "laminate drywall" in (b.get("Downstairs") or "")
    assert b.get("Asbestos/Lead Test") == "Yes"
    assert b.get("Test Areas") == "drywall"
    assert b.get("Packout Required") == "No"
    assert b.get("Content Manipulation") == "Yes"
    assert b.get("Storage Location") == "shift around"
    assert b.get("Visible Mold") == "No"
    assert b.get("Equipment Placed") == "No"
    assert b.get("Signed Today") == "No"
    assert b.get("Photos Taken") == "Yes"
    assert b.get("Video Taken") == "Yes"
    assert b.get("DocuSketch Done") == "Yes"
    # Continuation: the "Condo unit. Need to check limits..." sentence
    # belongs to Additional Notes.
    notes = b.get("Additional Notes") or ""
    assert "Condo unit" in notes
    assert "insurance first" in notes


def test_empty_returns_empty_list():
    assert parse_initial_inspection_notes("") == []
    assert parse_initial_inspection_notes(None) == []
    assert parse_initial_inspection_notes("just a random comment") == []


def test_unanswered_yes_no_dropped():
    """A line that still reads `Yes / No` with both sides intact should
    not surface as a field — there's no answer to report."""
    raw = "Initial notes\n\nPhotos Taken: Yes / No\nVideo Taken: Yes /\n"
    blocks = parse_initial_inspection_notes(raw)
    assert blocks
    # Photos Taken was unanswered → should NOT be in the dict
    assert "Photos Taken" not in blocks[0]
    # Video Taken: Yes /  → resolves to Yes
    assert blocks[0].get("Video Taken") == "Yes"


def test_resolve_yes_no_variants():
    assert _resolve_yes_no("Yes /") == "Yes"
    assert _resolve_yes_no("/ No") == "No"
    assert _resolve_yes_no(":/ No".lstrip(":")) == "No"
    assert _resolve_yes_no("Yes / No") == ""
    assert _resolve_yes_no("No / Yes") == ""
    assert _resolve_yes_no("Yes") == "Yes"
    assert _resolve_yes_no("No") == "No"
    assert _resolve_yes_no("fridge line") == "fridge line"
    assert _resolve_yes_no("") == ""
    assert _resolve_yes_no("  ") == ""


def test_inline_secondary_label():
    """The Category line packs Class on the same row."""
    raw = "Initial Inspection\n\nCategory (CAT):   3 Class: 4\nDate: 5-1-26\n"
    blocks = parse_initial_inspection_notes(raw)
    assert blocks[0].get("Category") == "3"
    assert blocks[0].get("Class") == "4"


def test_format_outputs_only_captured_fields():
    parsed = [{
        "Date": "5-11-26",
        "Cause of Loss": "fridge line",
        "Photos Taken": "Yes",
    }]
    out = format_initial_notes(parsed)
    assert "Date: 5-11-26" in out
    assert "Cause of Loss: fridge line" in out
    assert "Photos Taken: Yes" in out
    # Nothing else should be in the output
    assert "Category" not in out
    assert "Mold" not in out


def test_format_handles_multiple_blocks():
    """When a card has two inspections, each gets its own header."""
    raw = (
        "Initial notes\nDate: 5-11-26\nCause of Loss (COL): fridge\n"
        "Photos Taken: Yes /\nVideo Taken: Yes /\n"
        "DocuSketch Completed: Yes /\n"
        "\n"
        "Initial notes\nDate: 5-13-26\nCause of Loss (COL): toilet\n"
        "Photos Taken: Yes /\nVideo Taken: Yes /\n"
        "DocuSketch Completed: Yes /\n")
    blocks = parse_initial_inspection_notes(raw)
    assert len(blocks) == 2
    out = format_initial_notes(blocks)
    assert "Inspection 1 (5-11-26):" in out
    assert "Inspection 2 (5-13-26):" in out


def test_format_returns_empty_when_nothing_parsed():
    assert format_initial_notes([]) == ""


def test_implicit_block_without_header():
    """A tech pasted the filled template body without the 'Initial notes'
    title — as long as it has Date: plus enough recognizable labels,
    the parser still treats it as one block."""
    raw = (
        "Date: 5-11-26\n"
        "Time of Inspections: 3:00 pm\n"
        "Cause of Loss (COL): fridge\n"
        "Photos Taken: Yes /\n"
    )
    blocks = parse_initial_inspection_notes(raw)
    assert len(blocks) == 1
    assert blocks[0].get("Date") == "5-11-26"
    assert blocks[0].get("Cause of Loss") == "fridge"


def test_continuation_lines_attach_to_previous_field():
    """A free-text Additional Notes paragraph wraps across lines and
    should be joined under the same field, not lost."""
    raw = (
        "Initial notes\n"
        "Date: 5-11-26\n"
        "Cause of Loss (COL): fridge\n"
        "Photos Taken: Yes /\n"
        "Video Taken: Yes /\n"
        "DocuSketch Completed: Yes /\n"
        "Additional Field Notes / Observations:\n"
        "First line of free notes.\n"
        "Second line continues.\n"
    )
    blocks = parse_initial_inspection_notes(raw)
    notes = blocks[0].get("Additional Notes") or ""
    assert "First line of free notes." in notes
    assert "Second line continues." in notes
