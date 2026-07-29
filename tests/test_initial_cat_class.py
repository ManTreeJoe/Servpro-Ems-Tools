"""Category + Class extraction from initial-inspection notes.

Backs the audit Initial-section "🔢 Cat / Class" button, which reads the
notes a tech posts in the Trello comments. The button's backend parses with
initial_notes_parser; these pin that the inline "Category (CAT): 2  Class: 3"
shape yields both fields."""
from initial_notes_parser import parse_initial_inspection_notes


def _cat_class(raw):
    cat = klass = ""
    for b in parse_initial_inspection_notes(raw):
        cat = cat or str(b.get("Category") or "").strip()
        klass = klass or str(b.get("Class") or "").strip()
    return cat, klass


def test_inline_category_and_class():
    raw = (
        "Initial Inspection Field Template\n"
        "Date: 6/30/26\n"
        "Met With: homeowner\n"
        "Cause of Loss: Supply line\n"
        "Category (CAT): 2  Class: 3\n"
        "Levels Affected: 1\n"
    )
    assert _cat_class(raw) == ("2", "3")


def test_separate_lines():
    raw = (
        "Initial notes\n"
        "Date: 6/30/26\n"
        "Cause of Loss: Roof leak\n"
        "Category: 3\n"
        "Class: 2\n"
        "Met With: tenant\n"
    )
    assert _cat_class(raw) == ("3", "2")


def test_no_notes_returns_blank():
    assert _cat_class("just a normal comment, nothing templated here") == ("", "")
