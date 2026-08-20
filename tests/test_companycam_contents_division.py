"""Contents photos belong to the CONTENTS division, not to PICS.

A photo tagged Contents is contents work. The office already files it
under `<job>\\CONTENTS` — 99 live folders do — and that is where the
audit's contents check looks. Routing it to `EMS\\PICS\\Contents` put it
somewhere nothing reads.

Inside CONTENTS the layout is `<tech date>\\<room>`: no stage folder,
because the division already says what these are.

Live case (Adele Pacheco, project 112233520): 120 photos, 2 tagged
['Contents', 'Garage', 'Initial Inspection'].
"""
import pytest

import companycam_api as cc


def _photo(tags, captured="2026-08-19T15:00:00Z"):
    return {"id": "p1", "tags": list(tags), "captured_at": captured,
            "creator_name": "Maria Escobar"}


def test_contents_goes_to_its_own_division():
    r = cc.route_photo(_photo(["Contents", "Garage", "Initial Inspection"]),
                       tech="ME", split_contents=True)
    assert r["division"] == "CONTENTS"
    assert r["room"] == "Garage"


def test_the_stage_folder_is_dropped_inside_contents():
    """`CONTENTS\\Contents\\...` says the same thing twice."""
    r = cc.route_photo(_photo(["Contents", "Garage"]), tech="ME",
                       split_contents=True)
    assert "Contents" not in r["parts"]
    assert r["parts"][-1] == "Garage"


def test_the_layout_is_tech_date_then_room():
    r = cc.route_photo(_photo(["Contents", "Garage"]), tech="ME",
                       split_contents=True)
    assert len(r["parts"]) == 2
    assert r["parts"][1] == "Garage"
    assert "ME" in r["parts"][0]        # the tech/date box


def test_everything_else_still_goes_to_ems():
    r = cc.route_photo(_photo(["Initial Inspection", "Kitchen"]), tech="ME",
                       split_contents=True)
    assert r["division"] == "EMS"
    assert r["parts"][0] == "Initial"


def test_the_split_is_opt_in():
    """Off by default, so every existing caller lands where it always
    has — this changes where real photos go on the share."""
    r = cc.route_photo(_photo(["Contents", "Garage"]), tech="ME")
    assert r["division"] == "EMS"
    assert r["parts"][0] == "Contents"


def test_an_untagged_photo_is_unaffected():
    r = cc.route_photo(_photo([]), tech="ME", split_contents=True)
    assert r["division"] == "EMS"


def test_a_room_qualifier_still_nests_under_the_room():
    """Equipment is gear photographed IN a room, so it stays below it
    even in the contents division."""
    r = cc.route_photo(_photo(["Contents", "Garage", "Equipment"]),
                       tech="ME", split_contents=True)
    assert r["division"] == "CONTENTS"
    assert r["parts"][-2:] == ["Garage", "Equipment"]


def test_preview_and_download_cannot_disagree():
    """Both paths call route_photo, which is the whole reason it exists —
    a preview showing a different folder than the download uses is worse
    than no preview."""
    p = _photo(["Contents", "Garage"])
    a = cc.route_photo(p, tech="ME", split_contents=True)
    b = cc.route_photo(p, tech="ME", split_contents=True)
    assert a == b


def test_the_preview_still_calls_them_contents():
    """The stage is dropped from the PATH (the division already says it)
    but not from the LABEL — a preview reading "(no stage tag)" for
    photos CompanyCam has tagged is the untagged-lie this whole area
    keeps producing."""
    r = cc.route_photo(_photo(["Contents", "Garage"]), tech="ME",
                       split_contents=True)
    assert r["stage_label"] == "Contents"
    assert r["stage"] == ""             # not a folder in the path


def test_the_label_matches_the_folder_for_everything_else():
    r = cc.route_photo(_photo(["Initial Inspection", "Kitchen"]), tech="ME",
                       split_contents=True)
    assert r["stage_label"] == r["stage"] == "Initial"
