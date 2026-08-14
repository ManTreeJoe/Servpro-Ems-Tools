"""Contents photos belong in PICS/Contents, whichever way they arrive.

`audit_logic` has routed the run-doc's Contents / Pack-out / Pack-in
activities to a `Contents` folder all along — see its `priority` table,
where Pack-out and Pack-in absorb INTO Contents. The TAG paths never knew
the word, so a photo tagged "Contents" in CompanyCam became a ROOM folder
called Contents instead: one level down, and outside the stage the audit
looks in.

Three transports have to agree or one job pulled two ways lands in two
layouts: the CompanyCam API pull, the zip export, and the WorkCenter /
filename path.
"""
import pytest

import companycam_api as cc
import companycam_import as ci
import import_grouping as ig


# ── the tag paths ────────────────────────────────────────────────────
@pytest.mark.parametrize("label", [
    "Contents", "contents", "Contents Room",
    "Pack Out", "pack-out", "packout", "Pack In", "pack-in", "packin",
])
def test_contents_tags_become_the_contents_stage(label):
    _room, stage = ci.room_stage_from_label(label)
    assert stage == "Contents", f"{label!r} -> {stage!r}"


def test_the_room_survives_the_contents_tag():
    """"Pack-Out Master Bath" is a room AND a stage, like every other
    stage tag — the room must not be swallowed."""
    room, stage = ci.room_stage_from_label("Pack-Out Master Bath")
    assert (room, stage) == ("Master Bath", "Contents")


def test_the_api_pull_agrees_with_the_zip_export():
    """Same tags, two transports. They classify identically or one job
    pulled both ways ends up in two different folder layouts."""
    room, stage, _q = cc.classify_tags(["Contents", "Master Bath"])
    assert stage == "Contents"
    assert room == "Master Bath"


def test_a_packing_room_is_not_contents():
    """The word-boundary case: without it "pack..in" matches inside
    "Packing Room" and a ROOM gets filed as a stage."""
    _room, stage = ci.room_stage_from_label("Packing Room")
    assert stage != "Contents"


# ── the filename path ────────────────────────────────────────────────
@pytest.mark.parametrize("name,want", [
    ("Contents 7-1-26.jpg", "Contents"),
    ("Pack Out kitchen.jpg", "Contents"),
    ("pack-in 3.jpg", "Contents"),
    ("Packing Room.jpg", None),
    ("packing supplies.jpg", None),
    ("Demo kitchen.jpg", "Demo"),
])
def test_filename_routing(name, want):
    got = ig.stage_for_filename(name) if hasattr(ig, "stage_for_filename") \
        else _stage_via_patterns(name)
    assert got == want, f"{name!r} -> {got!r}"


def _stage_via_patterns(name):
    for stage, pat in ig._STAGE_PATTERNS:
        if pat.search(name):
            return stage
    return None


def test_the_contents_pattern_has_word_boundaries():
    """It was written with a literal backspace instead of \\b, which made
    the whole pack-out branch dead — it required an invisible control
    character to match."""
    pat = dict(ig._STAGE_PATTERNS)["Contents"].pattern
    assert chr(8) not in pat, "a control char got baked into the regex"
    assert pat.count(chr(92) + "b") >= 3


def test_no_control_characters_in_the_stage_tables():
    """Guards the whole file, not just the one pattern."""
    import io
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for fn in ("import_grouping.py", "companycam_import.py"):
        src = io.open(os.path.join(here, fn), encoding="utf-8").read()
        for bad in (chr(7), chr(8), chr(11), chr(12)):
            assert bad not in src, f"{fn} contains a control character"


# ── the picker offers it ─────────────────────────────────────────────
def test_the_stage_picker_offers_contents():
    """Not offering it meant a hand-picked contents photo could only be
    filed somewhere it didn't belong."""
    import io
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    js = io.open(os.path.join(here, "web_shared", "stage_picker.js"),
                 encoding="utf-8").read()
    block = js[js.index("const STAGES = ["):js.index("window.PICS_STAGES")]
    assert '"Contents"' in block


def test_the_audit_still_routes_contents_there():
    """The reason this is a restoration, not a new invention: the run-doc
    path never stopped filing Contents / Pack-out / Pack-in under
    Contents."""
    import audit_logic as al
    assert al.resolve_pics_subfolder(["Contents"])[0] == "Contents"
    assert al.resolve_pics_subfolder(["Pack-out"])[0] == "Contents"
    assert al.resolve_pics_subfolder(["Pack-in"])[0] == "Contents"
