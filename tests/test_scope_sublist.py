"""parse_scope must preserve multi-line sub-lists, not drop them.

Regression for the user-reported bug where a "Foo:" sub-header followed by
several bare lines (e.g. Detached Appliances: / Microwave / Refrigerator /
Dishwasher) lost every bare line after the first — the 2nd+ were misread as
empty room headers and filtered out. Also covers the PDF indent classifier
(_scope_item_kinds)."""
from snapshot_logic import parse_scope, _scope_item_kinds

SCOPE = """Upstairs Bathroom

Removed Baseboards (Paint Finish): 20 FT (including trim)

Removed Vinyl Flooring: 50 SF

⸻

Kitchen

Supported Countertops

Removed Base Cabinets: 10 FT

Detached Appliances:

Microwave

Refrigerator

Dishwasher

Containment:

Plastic: 35 FT

2 Poles

2 Zipper Doors

Drywall Removal: 125 SF

Insulation Removal: 125 SF"""


def _items(rooms, room_name):
    for r in rooms:
        if r["room"] == room_name:
            return r["items"]
    return []


def test_two_rooms_parsed():
    rooms = parse_scope(SCOPE)
    names = [r["room"] for r in rooms]
    assert names == ["Upstairs Bathroom", "Kitchen"], names


def test_bare_sublist_points_preserved():
    """Every appliance under "Detached Appliances:" survives."""
    items = _items(parse_scope(SCOPE), "Kitchen")
    for appliance in ("Microwave", "Refrigerator", "Dishwasher"):
        assert appliance in items, appliance


def test_separator_dropped_not_a_room():
    rooms = parse_scope(SCOPE)
    assert all(r["room"] != "⸻" for r in rooms)
    assert all("⸻" not in r["items"] for r in rooms)


def test_note_subheader_stays_item():
    """A bare note like "Supported Countertops" stays an item under Kitchen
    rather than becoming a room that swallows the lines below it."""
    items = _items(parse_scope(SCOPE), "Kitchen")
    assert "Supported Countertops" in items


def test_item_kinds_classification():
    items = _items(parse_scope(SCOPE), "Kitchen")
    kinds = dict(zip(items, _scope_item_kinds(items)))
    assert kinds["Detached Appliances:"] == "head"
    assert kinds["Microwave"] == "sub"
    assert kinds["Refrigerator"] == "sub"
    assert kinds["Containment:"] == "head"
    assert kinds["Plastic: 35 FT"] == "sub"
    # A removal action resumes the top level (not indented).
    assert kinds["Drywall Removal: 125 SF"] == "item"
    assert kinds["Insulation Removal: 125 SF"] == "item"
