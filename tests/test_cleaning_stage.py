"""Cleaning is a real CompanyCam tag the app did not know.

Untaught, it fell through to the room branch and became a folder called
Cleaning sitting beside Kitchen and Garage — the same mistake Contents
and Scope made before they were taught the word.
"""
import companycam_api as cc
import companycam_import as cci
import stages


def test_cleaning_is_a_stage_not_a_room():
    assert cci.room_stage_from_label("Cleaning") == ("", "Cleaning")


def test_a_cleaning_photo_routes_to_its_own_stage_folder():
    p = {"id": "1", "captured_at": 1_700_000_000,
         "tags": ["Cleaning", "Kitchen"]}
    r = cc.route_photo(p, tech="FB", force_tech=True)
    assert r["stage"] == "Cleaning"
    assert r["room"] == "Kitchen"


def test_post_cleaning_files_exactly_as_it_did_before():
    """The rules return on the FIRST match. Putting Cleaning before
    "post" would re-file every existing Post Cleaning photo as stage
    Cleaning with a ROOM called "Post"."""
    assert cci.room_stage_from_label("Post Cleaning") == ("Cleaning", "Post")


def test_clean_up_is_not_cleaning():
    """The account has a project literally named
    'PCM - (Homeless Encampment Clean Up)'. A looser rule files it as a
    cleaning stage."""
    room, stage = cci.room_stage_from_label("Homeless Encampment Clean Up")
    assert stage == ""


def test_the_rest_of_the_app_can_name_it():
    """A stage the pull can produce but the audit cannot name is a folder
    nobody ever checks."""
    assert "Cleaning" in stages.LABELS


def test_it_does_not_become_a_new_requirement():
    """Requiring it would mark every existing job as missing cleaning
    photos nobody asked them for. That is a separate decision."""
    assert stages.NEEDS_PHOTOS["Cleaning"] is False


def test_the_other_stages_are_unchanged():
    for label, expect in (("Demo", "Demo"), ("Post", "Post"),
                          ("Contents", "Contents"), ("Scope", "Scope")):
        assert cci.room_stage_from_label(label)[1] == expect
