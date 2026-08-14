"""Pinning a CompanyCam project must REPLACE the old one.

"It keeps seeing it as empty" — and it did, permanently, no matter how
many times the right project was picked.

`job_links` is keyed on (job, type, VALUE), so pinning a different
project ADDS a row instead of replacing one, and `get_link` returns the
OLDEST match. Once an auto-match had written the wrong project, every
later pin was faithfully recorded and then ignored, and the job resolved
to the first answer forever.

Live: Bell Mountain had 112272489 (0 photos) cached ahead of 112251669
(29 photos, uploaded by Rudy Quintero). The manual picker had the same
defect, so it was never a way out either.

A job has exactly ONE CompanyCam project, so picking one is a
replacement. Trello cards are deliberately many-per-job — a job
duplicated across boards links to all of them — which is why the same
rule must NOT be applied to them.
"""
import pytest

import companycam_web_api as cw
import ems_db


@pytest.fixture
def job(tmp_path):
    """A real job row in the isolated test DB."""
    name = "Menifee Union School District (Bell Mountain ) - 8/14"
    ems_db.resolve_and_link(name, create=True, source="test")
    ck = ems_db.find_job_by_name(name)["canon_key"]
    return name, ck


@pytest.fixture
def api():
    return cw.CompanyCamApi.__new__(cw.CompanyCamApi)


def test_the_pin_takes_effect(api, job):
    """The whole bug in one test."""
    name, ck = job
    api.companycam_pin(name, "112272489")          # the empty one, first
    api.companycam_pin(name, "112251669")          # the one with photos
    assert ems_db.get_link(ck, ems_db.LINK_COMPANYCAM) == "112251669"


def test_the_stale_project_is_removed_not_just_outranked(api, job):
    name, ck = job
    api.companycam_pin(name, "112272489")
    api.companycam_pin(name, "112251669")
    vals = [l["link_value"]
            for l in ems_db.get_links(ck, ems_db.LINK_COMPANYCAM)]
    assert vals == ["112251669"]


def test_it_reports_what_it_replaced(api, job):
    name, _ = job
    api.companycam_pin(name, "112272489")
    res = api.companycam_pin(name, "112251669")
    assert res["ok"] is True
    assert res["replaced"] == ["112272489"]


def test_repinning_the_same_project_is_a_no_op(api, job):
    name, ck = job
    api.companycam_pin(name, "112251669")
    res = api.companycam_pin(name, "112251669")
    assert res["replaced"] == []
    assert ems_db.get_link(ck, ems_db.LINK_COMPANYCAM) == "112251669"


def test_trello_cards_are_still_many_per_job(api, job):
    """A job duplicated across boards links to every card. The
    replacement rule is for single-valued links only."""
    name, ck = job
    ems_db.resolve_and_link(name, trello_card="card-a", source="test")
    ems_db.resolve_and_link(name, trello_card="card-b", source="test")
    api.companycam_pin(name, "112251669")
    cards = ems_db.get_links(ck, ems_db.LINK_TRELLO)
    assert len(cards) == 2, "pinning a project must not touch the cards"


def test_a_pin_with_no_project_is_refused(api, job):
    name, _ = job
    assert api.companycam_pin(name, "")["ok"] is False


def test_a_pin_with_no_client_is_refused(api):
    assert api.companycam_pin("", "112251669")["ok"] is False


def test_get_link_returning_the_oldest_is_what_made_this_bite():
    """Documents the mechanism, so a future reader doesn't 'simplify' the
    replacement away. If get_link ever returns the NEWEST link, this
    test should be revisited — not deleted."""
    import inspect
    import ems_db_sqlite
    src = inspect.getsource(ems_db_sqlite.get_link)
    assert "ASC" in src and "LIMIT 1" in src
