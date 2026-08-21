"""A Scope is paperwork, so it goes to DOCS, not into the PICS stages.

The tag is exactly "Scope" on the live account (id 26578715) — checked
against GET /tags, not assumed from the user's spelling.
"""
import os

import companycam_api as cc


def _photo(*tags):
    # classify_tags takes plain strings — that is the shape attach_tags
    # leaves on the photo.
    return {"id": "p1", "captured_at": 1_700_000_000, "tags": list(tags)}


def test_a_scope_photo_goes_to_the_docs_division():
    r = cc.route_photo(_photo("Scope"), split_docs=True)
    assert r["division"] == "DOCS"


def test_it_stays_in_pics_when_the_caller_has_not_opted_in():
    """Every existing caller must land exactly where it always has."""
    r = cc.route_photo(_photo("Scope"))
    assert r["division"] == "EMS"
    assert r["stage"] == "Scope"


def test_the_stage_folder_is_dropped():
    """The division already says what it is; a DOCS/Scope/ level is noise."""
    r = cc.route_photo(_photo("Scope"), split_docs=True)
    assert "Scope" not in r["parts"]


def test_a_room_tag_does_not_bury_it():
    """A scope covers the job, not a room. Keeping the room tag would file
    one scope under Kitchen and the next under Garage."""
    r = cc.route_photo(_photo("Scope", "Kitchen"), split_docs=True)
    assert r["room"] == ""
    assert "Kitchen" not in r["parts"]


def test_the_visit_folder_is_kept():
    """Several scopes across several visits must not collide."""
    r = cc.route_photo(_photo("Scope"), tech="FB", split_docs=True,
                       force_tech=True)
    assert r["parts"], "expected the tech/date box"


def test_it_still_reads_as_scope_in_the_preview():
    """No stage FOLDER, but the preview must not say '(no stage tag)'."""
    r = cc.route_photo(_photo("Scope"), split_docs=True)
    assert r["stage_label"] == "Scope"


def test_contents_still_wins_its_own_division():
    r = cc.route_photo(_photo("Contents"), split_contents=True, split_docs=True)
    assert r["division"] == "CONTENTS"


def test_an_ordinary_photo_is_untouched():
    r = cc.route_photo(_photo("Demo", "Kitchen"), split_contents=True,
                       split_docs=True)
    assert r["division"] == "EMS"
    assert r["room"] == "Kitchen"


# ── the base directory each division hangs off ─────────────────────────

def test_docs_photos_land_under_the_docs_root():
    assert cc._base_for("DOCS", "P", "C", "D") == "D"


def test_a_caller_that_has_not_been_taught_docs_still_works():
    """Falling back to dest_dir keeps an un-updated caller working instead
    of writing to an empty path."""
    assert cc._base_for("DOCS", "P", "C", "") == "P"


def test_the_other_divisions_are_unaffected():
    assert cc._base_for("CONTENTS", "P", "C", "D") == "C"
    assert cc._base_for("EMS", "P", "C", "D") == "P"


# ── where DOCS is on disk ──────────────────────────────────────────────

def test_the_docs_dir_is_the_sibling_of_pics(monkeypatch):
    import companycam_web_api as cwa
    api = object.__new__(cwa.CompanyCamApi)
    monkeypatch.setattr(cwa.CompanyCamApi, "_cc_pics_dir",
                        lambda self, c: os.path.join("X:", "jobs", "Doe, Jane",
                                                     "EMS", "PICS"))
    got = cwa.CompanyCamApi._cc_docs_dir(api, "Doe, Jane")
    assert got.endswith(os.path.join("EMS", "DOCS"))
    assert "PICS" not in got


def test_no_pics_means_no_docs(monkeypatch):
    import companycam_web_api as cwa
    api = object.__new__(cwa.CompanyCamApi)
    monkeypatch.setattr(cwa.CompanyCamApi, "_cc_pics_dir", lambda self, c: "")
    assert cwa.CompanyCamApi._cc_docs_dir(api, "x") == ""


def test_scope_is_a_stage_not_a_room():
    """It was neither, so it fell through to the room branch and became a
    folder called Scope sitting beside Kitchen and Garage — the same
    mistake Contents made before it was taught the word."""
    import companycam_import as cci
    assert cci.room_stage_from_label("Scope") == ("", "Scope")
    assert cc.classify_tags(["Scope", "Kitchen"]) == ("Kitchen", "Scope", "")
