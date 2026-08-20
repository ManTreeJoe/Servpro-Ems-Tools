"""Carried APA items must land in TODAY's section, not yesterday's.

`create_doc` carries active items forward keeping their old section, then
`refresh_doc_lanes` re-routes each one from its Trello card's current
lane. An item whose lane maps to NOTHING stays where it was — silently —
which is the "it never changes when we transfer it over" complaint.

Live, two lanes carrying real jobs mapped to nothing:

    UPCOMING/PENDING   a real WIP lane, never in the table
    NEW LOSS           the key was "tbs new loss", which is LONGER than
                       the lane, and the walk looks for key-inside-lane

The second is the subtle one: a longer key can never match a shorter
lane, so adding the specific variant did not cover the general one.
"""
import pytest

import apa_logic as apa
import apa_web


@pytest.fixture(scope="module")
def api():
    return apa_web.Api()


@pytest.mark.parametrize("lane,section", [
    ("UPCOMING/PENDING", apa.SEC_FINAL_UPLOADS),
    ("NEW LOSS", apa.SEC_INITIAL_UPLOADS),
])
def test_the_lanes_that_used_to_map_to_nothing(api, lane, section):
    assert api._suggest_section_for_lane(lane) == section


@pytest.mark.parametrize("lane,section", [
    # Waiting lanes all land in Final Uploads — the family
    # UPCOMING/PENDING was missing from.
    ("ON HOLD", apa.SEC_FINAL_UPLOADS),
    ("PENDING APPROVALS/INSURANCE/SELF PAY", apa.SEC_FINAL_UPLOADS),
    ("PENDING APPROVALS/PROPERTY MANAGEMENT/COMMERCIAL",
     apa.SEC_FINAL_UPLOADS),
    ("MONITOR", apa.SEC_FINAL_UPLOADS),
    ("WORK IN PROGRESS", apa.SEC_FINAL_UPLOADS),
    # Intake lanes land in Initial Uploads.
    ("TBS NEW LOSS/RE-INSPECTION", apa.SEC_INITIAL_UPLOADS),
    ("TBS MITIGATION", apa.SEC_INITIAL_UPLOADS),
    ("INITIAL INSPECTIONS/RE-INSPECTIONS", apa.SEC_INITIAL_UPLOADS),
])
def test_the_existing_routes_are_unchanged(api, lane, section):
    """The new keys must not shadow any lane that already worked."""
    assert api._suggest_section_for_lane(lane) == section


@pytest.mark.parametrize("lane", [
    "MARKETING TEAM", "CUSTOMER CONCERNS", "TEMPLATES", "SPACER",
    "ON CALL TEAMS", "",
])
def test_lanes_that_are_not_job_stages_still_map_to_nothing(api, lane):
    """Not every lane is a place a job lives. Inventing a section for
    these would file real jobs under a heading nobody works from."""
    assert api._suggest_section_for_lane(lane) == ""


# Lane targets that are NOT current sections. Cards in these lanes route
# to a section that does not exist, so refresh_doc_lanes rejects the
# suggestion and the item keeps yesterday's section — silently, which is
# the same failure this file exists for.
#
# SAMANTHA was one of these and is fixed: her lane is shared
# ("SAMANTHA / AL JR") and she has no section, so it routes to AARON L —
# the half that can actually receive the work.
#
# ESTEBAN was the same shape and is fixed too: he shares KIM's lane
# ("kim+esteban"), so the bare lane routes to KIM.
#
# The set is now EMPTY, which is the state to defend — a new dead target
# means somebody added a lane for a person with no section, and those
# items would silently keep yesterday's.
KNOWN_STALE_TARGETS = set()


def test_every_mapped_section_actually_exists():
    """A target that isn't a real section routes nowhere — the table's
    own warning. New ones must not creep in unnoticed."""
    valid = set(apa.SECTION_ORDER) | KNOWN_STALE_TARGETS
    for lane, sec in apa_web.Api._LANE_TO_SECTION.items():
        assert sec in valid, f"{lane!r} -> {sec!r} is not a real section"


def test_estebans_shared_lane_goes_to_the_half_with_a_section():
    api = apa_web.Api()
    for lane in ("ESTEBAN", "KIM+ESTEBAN"):
        assert api._suggest_section_for_lane(lane) == "KIM"


def test_samanthas_shared_lane_goes_to_the_half_with_a_section():
    """Combo lanes normally take the FIRST name, but Samantha has no APA
    section, so that rule sent the item to a section that doesn't exist
    and it silently kept yesterday's."""
    api = apa_web.Api()
    for lane in ("SAMANTHA / AL JR", "SAMANTHA/AL JR", "SAMANTHA"):
        assert api._suggest_section_for_lane(lane) == "AARON L"


def test_no_lane_routes_to_a_section_that_does_not_exist():
    """Every lane target must be a real section. One that isn't routes
    nowhere and the item silently keeps yesterday's — the whole bug this
    file is about. Both known cases (SAMANTHA, ESTEBAN) are fixed, so the
    set is empty and must stay that way."""
    valid = set(apa.SECTION_ORDER)
    stale = {sec for sec in apa_web.Api._LANE_TO_SECTION.values()
             if sec not in valid}
    assert stale == KNOWN_STALE_TARGETS, (
        f"the set of dead lane targets changed: {stale}")


def test_a_longer_key_cannot_match_a_shorter_lane(api):
    """Why 'NEW LOSS' was missed: the walk asks whether a KEY appears
    inside the LANE, so 'tbs new loss' could never match 'NEW LOSS'.
    Both directions need their own entry."""
    assert "tbs new loss" not in "new loss"
    assert api._suggest_section_for_lane("NEW LOSS") == apa.SEC_INITIAL_UPLOADS
    assert api._suggest_section_for_lane(
        "TBS NEW LOSS/RE-INSPECTION") == apa.SEC_INITIAL_UPLOADS
