"""Adding a claim or unit: adopt what exists, create only what doesn't.

Work starts in Trello here, so a provision-everything flow would create a
SECOND card beside the one somebody already made — the duplicate-identity
problem reintroduced at the front door. Every step looks first.

The other rule is that a partial result is never reported as success.
Offline the folder succeeds locally while Trello and CompanyCam cannot,
and "half provisioned, silently" is the failure this whole effort has
been unwinding.
"""
import os

import pytest

import child_provision as cp
import ems_db_sqlite as db


@pytest.fixture
def job(tmp_path, monkeypatch):
    """A client with a folder, on the local backend."""
    import ems_db
    monkeypatch.setattr(ems_db, "_backend", lambda: db)
    db.reset_db_path(str(tmp_path / "t.db"))
    root = tmp_path / "Aperto Property Management"
    root.mkdir()
    db.upsert_job(display_name="Aperto Property Management")
    key = db.canon_key("Aperto Property Management")
    db.set_link(key, db.LINK_FOLDER, str(root))
    monkeypatch.setattr(cp, "_find_cards", lambda *a, **k: [])
    monkeypatch.setattr(cp, "_find_project", lambda *a, **k: None)
    return key, root


# ── planning ───────────────────────────────────────────────────────────

def test_the_levels_come_from_the_name(job):
    key, _ = job
    p = cp.plan_child(key, "Tres Lagos - Unit 6204 - 8.17.26")
    assert p["levels"] == {"property": "Tres Lagos", "unit": "6204",
                           "claim_date": "8.17.26"}


def test_an_existing_folder_is_adopted_not_recreated(job):
    key, root = job
    (root / "Tres Lagos - Unit 6204 - 8.17.26").mkdir()
    p = cp.plan_child(key, "Tres Lagos - Unit 6204 - 8.17.26")
    assert p["folder"]["exists"] is True


def test_a_folder_match_ignores_case(job):
    key, root = job
    (root / "2nd Claim").mkdir()
    assert cp.plan_child(key, "2ND CLAIM")["folder"]["exists"] is True


def test_planning_writes_nothing(job):
    key, root = job
    cp.plan_child(key, "Unit 999")
    assert not (root / "Unit 999").exists()
    assert db.children_of(key) == []


def test_an_existing_child_is_reported_as_such(job):
    """Adding a child that is already there is an edit, not an add."""
    key, _ = job
    db.set_child(key, "2nd Claim")
    p = cp.plan_child(key, "2nd Claim")
    assert p["existing_child"] is not None


def test_an_already_linked_child_shows_its_own_card(job, monkeypatch):
    """Searching Trello for a name the card was never given would report
    'none found' for a job that is already linked."""
    key, _ = job
    db.set_child(key, "2nd Claim", trello_card="6a839f8bd0ca072308e4f906",
                 companycam="112531938")
    p = cp.plan_child(key, "2nd Claim")
    assert p["cards"][0]["id"] == "6a839f8bd0ca072308e4f906"
    assert p["project"]["id"] == "112531938"


# ── applying ───────────────────────────────────────────────────────────

def test_the_folder_is_created_and_the_child_recorded(job):
    key, root = job
    res = cp.apply_child(key, "Unit 585-G")
    assert res["ok"] is True
    assert res["steps"]["folder"]["action"] == "created"
    assert (root / "Unit 585-G").is_dir()
    kids = db.children_of(key)
    assert [c["name"] for c in kids] == ["Unit 585-G"]
    assert kids[0]["unit"] == "585-G"


def test_an_adopted_folder_is_not_recreated(job):
    key, root = job
    (root / "Unit 585-G").mkdir()
    res = cp.apply_child(key, "Unit 585-G")
    assert res["steps"]["folder"]["action"] == "adopted"


def test_a_chosen_card_is_recorded_on_the_child(job):
    key, _ = job
    cp.apply_child(key, "Unit 585-G", card_id="6a839f8bd0ca072308e4f906")
    assert db.children_of(key)[0]["trello_card"] == \
        "6a839f8bd0ca072308e4f906"


def test_no_card_chosen_is_not_a_failure(job):
    """A unit often exists before its card does. Refusing to record the
    child until Trello catches up would leave the folder unowned."""
    key, _ = job
    res = cp.apply_child(key, "Unit 585-G")
    assert res["ok"] is True
    assert res["steps"]["card"]["action"] == "none"


def test_a_project_is_only_created_when_asked(job):
    key, _ = job
    res = cp.apply_child(key, "Unit 585-G")
    assert res["steps"]["project"]["action"] == "none"


def test_a_failed_step_is_not_reported_as_success(job, monkeypatch):
    """The whole point: the folder can succeed while CompanyCam cannot,
    and a green result would hide it."""
    key, _ = job

    class _Boom:
        @staticmethod
        def create_project(*a, **k):
            raise RuntimeError("no write scope")

    import sys
    monkeypatch.setitem(sys.modules, "companycam_api", _Boom)
    res = cp.apply_child(key, "Unit 585-G", create_project=True)

    assert res["ok"] is False
    assert res["failed"] == ["project"]
    # ...and the parts that DID work are still done, not rolled back.
    assert res["steps"]["folder"]["ok"] is True
    assert db.children_of(key)


def test_every_step_reports_itself(job):
    key, _ = job
    res = cp.apply_child(key, "Unit 585-G")
    assert set(res["steps"]) == {"folder", "card", "project", "child"}
    for name, step in res["steps"].items():
        assert "ok" in step and "action" in step, name


def test_a_missing_client_is_an_error_not_a_crash(job):
    assert cp.plan_child("no such job", "Unit 1")["ok"] is False
    assert cp.apply_child("no such job", "Unit 1")["ok"] is False


def test_a_blank_child_name_is_refused(job):
    key, _ = job
    assert cp.plan_child(key, "   ")["ok"] is False


def test_the_skeleton_never_copies_the_parent(job):
    """The parent CONTAINS the new child, so walking it to build a
    skeleton recreates the walker's own output without end — it hung the
    suite and on the share it would have made folders until the path
    limit."""
    key, root = job
    assert cp._a_sibling(str(root), str(root / "Unit 1")) is None

    (root / "Unit 585-G").mkdir()
    sib = cp._a_sibling(str(root), str(root / "Unit 999"))
    assert sib is not None
    assert os.path.normcase(sib) != os.path.normcase(str(root))


def test_a_second_child_finishes(job):
    """The regression itself: creating a child when siblings already
    exist must terminate."""
    key, root = job
    cp.apply_child(key, "Unit 585-G")
    res = cp.apply_child(key, "Unit 585-H")
    assert res["ok"] is True
    assert (root / "Unit 585-H").is_dir()
    assert len(db.children_of(key)) == 2
