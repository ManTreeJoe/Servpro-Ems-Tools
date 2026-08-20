"""Folding two jobs together must not cost the children.

`merge_jobs` moved aliases, links and events onto the survivor and then
deleted the loser's `jobs` row — with nothing at all done about
`job_children`. The two backends then failed in opposite directions:

  * Supabase — `parent_canon references jobs (canon_key) on delete
    cascade` (003_job_children.sql:20), so the delete CASCADED and the
    units/claims were destroyed. No orphan was left behind to notice,
    because the foreign key makes orphans impossible by construction.
  * SQLite — no foreign key at all, so the same call ORPHANED them:
    rows pointing at a canon_key that names no job, invisible to
    `children_of()` from then on.

Live, `avana springs greystar` carries seven unit rows, each with its own
folder, Trello card and CompanyCam project. Merging it would have taken
all seven.

The suite runs on SQLite (conftest forces it), so the Supabase half is
held by reading its source — the ordering there is the whole fix, and
getting it backwards fails silently and permanently.
"""
import io
import os
import re

import pytest

import ems_db_sqlite as db


@pytest.fixture
def two_jobs(tmp_path, monkeypatch):
    """A survivor and a loser, the loser carrying children."""
    db.reset_db_path(str(tmp_path / "t.db"))
    db.upsert_job(display_name="Avana Springs Greystar")
    db.upsert_job(display_name="Greystar")
    keep = db.canon_key("Avana Springs Greystar")
    drop = db.canon_key("Greystar")
    return keep, drop


def test_children_move_to_the_survivor(two_jobs):
    keep, drop = two_jobs
    db.set_child(drop, "Unit 585-G", folder_path=r"X:\a\Unit 585-G",
                 trello_card="card585", companycam="cc585")
    db.set_child(drop, "Unit 561-I", folder_path=r"X:\a\Unit 561-I")

    res = db.merge_jobs(keep, [drop])

    assert res["merged"] == 1
    assert res["children_moved"] == 2
    names = sorted(c["name"] for c in db.children_of(keep))
    assert names == ["Unit 561-I", "Unit 585-G"]
    # ...and the links each child carried came with it. Losing those is
    # what makes the deletion expensive rather than merely annoying.
    got = {c["name"]: c for c in db.children_of(keep)}
    assert got["Unit 585-G"]["trello_card"] == "card585"
    assert got["Unit 585-G"]["companycam"] == "cc585"


def test_no_child_is_left_pointing_at_the_deleted_job(two_jobs):
    """The SQLite-specific failure: survives the delete, invisible after."""
    keep, drop = two_jobs
    db.set_child(drop, "Unit 585-G")
    db.merge_jobs(keep, [drop])
    assert db.children_of(drop) == []
    assert len(db.children_of(keep)) == 1


def test_a_name_collision_renames_rather_than_drops(two_jobs):
    """Two properties really can both have a 'Unit 2'.

    UNIQUE (parent_canon, name) means one of them has to give. Renaming
    keeps the row and its folder/card; dropping it would be the silent
    loss this test exists to prevent, and letting the write fail would
    abort the merge halfway through.
    """
    keep, drop = two_jobs
    db.set_child(keep, "Unit 2", folder_path=r"X:\keep\Unit 2")
    db.set_child(drop, "Unit 2", folder_path=r"X:\drop\Unit 2")

    res = db.merge_jobs(keep, [drop])

    assert res["children_moved"] == 1
    kids = {c["name"]: c for c in db.children_of(keep)}
    assert set(kids) == {"Unit 2", "Unit 2 (2)"}
    # The survivor's own row keeps its folder; the incoming one keeps its
    # own too — neither is overwritten by the other.
    assert kids["Unit 2"]["folder_path"].endswith(r"keep\unit 2")
    assert kids["Unit 2 (2)"]["folder_path"].endswith(r"drop\unit 2")


def test_a_childless_merge_reports_nothing(two_jobs):
    keep, drop = two_jobs
    res = db.merge_jobs(keep, [drop])
    assert "children_moved" not in res


# ── the Supabase half, held by reading the source ──────────────────────

_SB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "ems_db_supabase.py")


def test_supabase_reparents_before_deleting_the_job():
    """Ordering IS the fix on the cascading backend.

    Re-parenting after the delete would be a no-op against rows the
    cascade had already removed — and it would look perfectly correct in
    review, which is exactly why this is pinned.
    """
    src = io.open(_SB, encoding="utf-8").read()
    reparent = src.index("moved_kids += _reparent_children(")
    delete = src.index('_sb.rest("DELETE", "jobs"')
    assert reparent < delete, (
        "_reparent_children must run BEFORE the jobs row is deleted — "
        "ON DELETE CASCADE takes job_children with it")


def test_supabase_dedupes_child_names_too():
    """Both backends share one collision rule, or they drift apart."""
    src = io.open(_SB, encoding="utf-8").read()
    assert re.search(r"dedupe_child_name\(", src), (
        "the cascading backend must rename colliding children as well")
