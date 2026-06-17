"""Scope parser — pins the format the user actually pastes.

Earlier the parser:
  - split blocks on any blank line, so a double-spaced paste (one
    blank between every scope line) became a sequence of 1-line
    blocks and the ≥3-material gate never tripped → no scope
    detected.
  - only counted material/dimension keywords, missing scope-action
    verbs (Removed vanity, Detached 2 doors) and curly-quoted
    dimensions (26’6’’) that auto-correct in Word/iOS pastes.

This test pins the user-reported paste so neither regresses."""
import snapshot_gui


# The user's actual paste, double-spaced as it came from Trello.
USER_DOUBLE_SPACED_SCOPE = """\
Scope

Garage

Drywall removed-50 sq ft.

Ceiling drywall removed-180 sq ft

Living room

Drywall removed-26’6’’x 2’

Insulation removed-6x2

Laminate removed-160 sq ft

Base removed-26’6’’

Containment-23x12 4 poles  1 zipper

Hall/laundry

Drywall removed-31x2

Base removed 31’

Detached 2 doors

Removed 2 door jambs

Door trim removed-28’

Laminate removed 33 sq ft

Tile removed 25 sq ft

Removed full height cabinet

Detached washer /dryer

Bath

Removed vanity

Drywall removed 13x2

Base removed 9’

Detached door

Door trim removed 28’

Removed 2 door jambs

Tile removed 22 sq ft

Detached toilet

Bedroom

Laminate removed 160 sq ft

Drywall removed 24’6’’x2’

Base removed 51’

Detached 4 doors

Removed 2 door jambs

Door trim removed 28’
"""


def test_double_spaced_paste_is_parsed():
    rooms = snapshot_gui.parse_scope(USER_DOUBLE_SPACED_SCOPE)
    assert rooms, "scope was not detected at all"
    names = [r["room"] for r in rooms]
    # The five real rooms must all show up; "Scope" header must NOT
    # become a room (it has no items so the empty-room filter drops it).
    for expected in ("Garage", "Living room", "Hall/laundry",
                      "Bath", "Bedroom"):
        assert expected in names, (
            f"room {expected!r} missing from parsed list: {names}")
    assert "Scope" not in names


def test_action_verb_lines_are_treated_as_items():
    """Lines that start with Removed/Detached are scope ITEMS, not
    new room headers — so 'Removed 2 door jambs' under Hall/laundry
    must end up under Hall/laundry, not as its own room."""
    rooms = snapshot_gui.parse_scope(USER_DOUBLE_SPACED_SCOPE)
    by_name = {r["room"]: r["items"] for r in rooms}
    hall_items = " | ".join(by_name.get("Hall/laundry", []))
    assert "Detached 2 doors" in hall_items
    assert "Removed 2 door jambs" in hall_items
    assert "Removed full height cabinet" in hall_items
    bath_items = " | ".join(by_name.get("Bath", []))
    assert "Removed vanity" in bath_items
    assert "Detached toilet" in bath_items


def test_curly_quote_dimensions_count_as_materials():
    """`26’6’’` (curly quotes from Word/iOS) must register as a
    dimension just like ASCII `26'6"` does. Without this support the
    line falls back to room-header treatment and breaks grouping."""
    rooms = snapshot_gui.parse_scope(USER_DOUBLE_SPACED_SCOPE)
    # The 'Drywall removed-26’6’’x 2’' line must end up under Living
    # room (not as its own room).
    by_name = {r["room"]: r["items"] for r in rooms}
    living_items = " | ".join(by_name.get("Living room", []))
    assert "26" in living_items and ("’" in living_items or "'" in living_items)


def test_room_table_continuation_header_says_cont():
    """When a room's items span pages, the repeated header on the
    continuation half must read '<Name> (cont.)' rather than just
    re-printing the original room name. Locks in the cont. patch
    inside `_RoomTable.split`."""
    from reportlab.lib.units import inch
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph

    base_style = getSampleStyleSheet()["Normal"]
    room_style = ParagraphStyle("R", parent=base_style,
                                 fontName="Helvetica-Bold", fontSize=11)
    item_style = ParagraphStyle("I", parent=base_style,
                                 fontName="Helvetica", fontSize=9)

    # Long enough that splitting at a tight availHeight is forced.
    data = [[Paragraph("Bedroom", room_style)]]
    for n in range(20):
        data.append([Paragraph(f"Item {n}", item_style)])

    tbl = snapshot_gui._RoomTable(
        data, colWidths=[7 * inch], repeatRows=1,
        room_name="Bedroom", room_style=room_style)
    # ReportLab tables need a wrap before split.
    tbl.wrap(7 * inch, 11 * inch)
    parts = tbl.split(7 * inch, 1.2 * inch)  # forces a split early
    assert len(parts) == 2, (
        "expected the table to actually split with a small availHeight")
    second = parts[1]
    second.wrap(7 * inch, 11 * inch)
    # Row 0 of the continuation should be the patched cont. paragraph.
    cont_cell = second._cellvalues[0][0]
    cont_text = (cont_cell.getPlainText()
                  if hasattr(cont_cell, "getPlainText")
                  else str(cont_cell))
    assert "Bedroom" in cont_text and "cont" in cont_text.lower(), (
        f"continuation header didn't get patched: {cont_text!r}")


def test_two_blank_lines_still_break_scope_from_other_text():
    """Single-blank tolerance shouldn't merge the scope with unrelated
    text below — two consecutive blanks (or a long paragraph between)
    must still cleanly separate."""
    paste = """\
Garage

Drywall removed 50 sq ft

Base removed 12'

Detached 2 doors


Hello team — quick update on a totally unrelated topic that goes on
for a long while and includes some plumbing repairs not related to
the scope above. We can talk tomorrow.
"""
    rooms = snapshot_gui.parse_scope(paste)
    names = [r["room"] for r in rooms]
    assert "Garage" in names
    # The unrelated email-style paragraph must NOT become a room
    assert not any("Hello team" in n for n in names)
