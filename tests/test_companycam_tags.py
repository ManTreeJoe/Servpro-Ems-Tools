"""CompanyCam export tag → (room, stage) routing.

Locks the real export formats seen on disk (Linda Lowe job, 2026-06-17):
CompanyCam joins a photo's tags into the filename label in no fixed
order, so the stage tag can lead, trail, or sit in the middle. The
distinguishing room is whatever's left after the stage tag is removed.
"""
import companycam_import as cc


def test_stage_tag_leading_room_trailing():
    # "Initial Inspection Master Bath-11-..." → stage Initial, room Master Bath
    room, stage = cc.parse_room_stage(
        "Initial Inspection Master Bath-11-Jun 17 2026 11_35am-6oWw.jpg")
    assert stage == "Initial"
    assert room == "Master Bath"


def test_room_leading_stage_trailing_multiword():
    # "Garage Initial Inspection-10-..." → stage Initial, room Garage
    room, stage = cc.parse_room_stage(
        "Garage Initial Inspection-10-Jun 17 2026 11_32am-fhi5.jpg")
    assert stage == "Initial"
    assert room == "Garage"


def test_stage_only_no_room():
    room, stage = cc.parse_room_stage(
        "Initial Inspection-1-Jun 17 2026 11_25am-n7At.jpg")
    assert stage == "Initial"
    assert room == ""


def test_legacy_trailing_post_tag():
    room, stage = cc.parse_room_stage(
        "Kitchen Post-1-Jun 15 2026 12_03pm-yZ87.jpg")
    assert stage == "Post"
    assert room == "Kitchen"


def test_room_only_no_stage():
    room, stage = cc.parse_room_stage(
        "Master Bedroom-19-Jun 15 2026 02_13pm-nCFi.jpg")
    assert stage == ""
    assert room == "Master Bedroom"


def test_reinspection_not_mistaken_for_initial_inspection():
    # "reinspection" contains "inspection" — must resolve to Reinspection,
    # not Initial, and not leave a stray "re" as the room.
    room, stage = cc.parse_room_stage(
        "Reinspection-2-Jun 17 2026 09_00am-abcd.jpg")
    assert stage == "Reinspection"
    assert room == ""


def test_post_mold_prep_beats_mold_and_post():
    room, stage = cc.parse_room_stage(
        "Post Mold Prep Hallway-3-Jun 17 2026 10_00am-zzzz.jpg")
    assert stage == "Post Mold Prep"
    assert room == "Hallway"
