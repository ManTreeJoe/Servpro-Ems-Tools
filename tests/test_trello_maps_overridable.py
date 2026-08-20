"""Trello-derived mappings must be adjustable without a code change.

Lanes get renamed, estimators arrive and leave, checklist items get
reworded. Every time that happened the fix was a code edit — and until
somebody made it the failure was SILENT: an unmapped lane just keeps
yesterday's section, an unmapped checklist item is just an ordinary tick.
SAMANTHA and ESTEBAN both sat broken that way.

Overrides layer over the built-in tables, are read fresh (no restart),
and an empty value REMOVES a built-in — which is how "this lane should
route nowhere" is expressed.
"""
import pytest

import apa_web
import audit_web
import persistence


@pytest.fixture
def store(monkeypatch):
    data = {}
    monkeypatch.setattr(persistence, "get", lambda k, d=None: data.get(k, d))
    monkeypatch.setattr(persistence, "set_value",
                        lambda k, v: data.__setitem__(k, v))
    return data


# ── APA lane -> section ────────────────────────────────────────────────

def test_the_builtin_table_is_the_default(store):
    api = apa_web.Api()
    assert api._suggest_section_for_lane("NEW LOSS") == "Initial Uploads"


def test_an_override_wins(store):
    store["apa_lane_sections"] = {"new loss": "Daily Uploads"}
    assert apa_web.Api()._suggest_section_for_lane("NEW LOSS") == \
        "Daily Uploads"


def test_a_blank_override_removes_a_builtin(store):
    """A lane that should route nowhere — otherwise the only way to stop
    a bad mapping would be editing code."""
    store["apa_lane_sections"] = {"monitor": ""}
    assert apa_web.Api()._suggest_section_for_lane("MONITOR") == ""


def test_a_new_lane_can_be_added(store):
    """The real case: Trello grows a lane nobody wrote a mapping for."""
    store["apa_lane_sections"] = {"storm response": "Initial Uploads"}
    assert apa_web.Api()._suggest_section_for_lane("STORM RESPONSE") == \
        "Initial Uploads"


def test_overrides_are_matched_case_insensitively(store):
    store["apa_lane_sections"] = {"NEW LOSS": "Daily Uploads"}
    assert apa_web.Api()._suggest_section_for_lane("new loss") == \
        "Daily Uploads"


def test_a_broken_override_does_not_break_routing(store):
    """A hand-edited value must never take the panel down."""
    store["apa_lane_sections"] = "not a dict"
    assert apa_web.Api()._suggest_section_for_lane("NEW LOSS") == \
        "Initial Uploads"


# ── checklist tick -> comment ──────────────────────────────────────────

def test_the_builtin_tick_map_is_the_default(store):
    A = audit_web.Api
    assert A.tick_post_map()[A._tick_key("INITIAL UPLOAD")] == \
        ("canned", "upload")


def test_a_renamed_checklist_item_can_be_remapped(store):
    """Rename the item on Trello and the tick stops posting — silently,
    because an unmapped item is just an ordinary tick."""
    A = audit_web.Api
    store["audit_tick_posts"] = {"Upload to WorkCenter": "upload"}
    assert A.tick_post_map()[A._tick_key("Upload to WorkCenter")] == \
        ("canned", "upload")


def test_a_blank_removes_a_tick_mapping(store):
    A = audit_web.Api
    store["audit_tick_posts"] = {"INITIAL UPLOAD": ""}
    assert A._tick_key("INITIAL UPLOAD") not in A.tick_post_map()


def test_docusketch_is_expressible(store):
    """It is a REQUEST, not a canned comment, so it has its own kind."""
    A = audit_web.Api
    store["audit_tick_posts"] = {"Order the sketch": "docusketch"}
    assert A.tick_post_map()[A._tick_key("Order the sketch")] == \
        ("docusketch", "")


def test_a_broken_tick_override_is_ignored(store):
    A = audit_web.Api
    store["audit_tick_posts"] = ["not", "a", "dict"]
    assert A.tick_post_map()[A._tick_key("INITIAL UPLOAD")] == \
        ("canned", "upload")


def test_overrides_never_mutate_the_builtin(store):
    """A dict returned by reference would let one override leak into
    every later call."""
    A = audit_web.Api
    before = dict(A._TICK_POSTS)
    store["audit_tick_posts"] = {"INITIAL UPLOAD": ""}
    A.tick_post_map()
    assert A._TICK_POSTS == before

    lanes_before = dict(apa_web.Api._LANE_TO_SECTION)
    store["apa_lane_sections"] = {"monitor": ""}
    apa_web.Api.lane_section_map()
    assert apa_web.Api._LANE_TO_SECTION == lanes_before
