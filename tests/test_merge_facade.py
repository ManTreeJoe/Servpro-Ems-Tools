"""Preview and undo belong at the façade, not at each call site.

`merge_jobs` folds jobs together and deletes rows — the most destructive
thing the index can do — and it had neither a preview nor a way back.
Both now live in `ems_db` itself, so the six callers that route through
the façade get them without being touched. (`migrate_canon_carrier_keys`
imports `ems_db_sqlite` directly and bypasses this; it is a one-off
script, and new repair scripts should import `ems_db`.)

The preview exists to be READ before someone commits: "3 children" and
"Unit 585-G, Unit 561-I, Unit 880-A" are very different things to see in
a confirmation dialog, so children come back by name.
"""
import pytest

import ems_db
import ems_db_sqlite as sdb
import job_undo


@pytest.fixture
def wired(tmp_path, monkeypatch):
    import paths
    monkeypatch.setattr(paths, "data", lambda name="": str(tmp_path / name))
    sdb.reset_db_path(str(tmp_path / "t.db"))
    sdb.upsert_job(display_name="Avana Springs Greystar")
    sdb.upsert_job(display_name="Greystar Property Group")
    keep = sdb.canon_key("Avana Springs Greystar")
    drop = sdb.canon_key("Greystar Property Group")
    sdb.set_link(drop, sdb.LINK_TRELLO, "card585")
    sdb.set_child(drop, "Unit 585-G")
    sdb.set_child(drop, "Unit 561-I")
    sdb.add_alias(drop, "Greystar Props")
    return keep, drop


def test_preview_names_the_children(wired):
    keep, drop = wired
    pv = ems_db.merge_preview(keep, [drop])

    assert pv["into"]["exists"] is True
    assert pv["totals"] == {"jobs": 1, "aliases": 1, "links": 1, "children": 2}
    assert sorted(pv["from"][0]["children"]) == ["Unit 561-I", "Unit 585-G"]
    assert pv["from"][0]["link_types"] == [sdb.LINK_TRELLO]


def test_preview_changes_nothing(wired):
    keep, drop = wired
    ems_db.merge_preview(keep, [drop])
    assert sdb.get_job(drop) is not None
    assert len(sdb.children_of(drop)) == 2


def test_preview_reports_a_job_that_is_not_there(wired):
    keep, _ = wired
    pv = ems_db.merge_preview(keep, ["no such job"])
    assert pv["missing"] == ["no such job"]
    assert pv["totals"]["jobs"] == 0


def test_preview_does_not_promise_a_fold_the_merge_will_refuse(wired):
    """Cross-department merges are refused, so the preview must say so
    rather than counting rows that will never move."""
    keep, drop = wired
    sdb.upsert_job(display_name="Avana Springs Greystar", department="IE")
    sdb.upsert_job(display_name="Greystar Property Group", department="OC")

    pv = ems_db.merge_preview(keep, [drop])

    assert pv["department_conflicts"] == [drop]
    assert pv["totals"]["children"] == 0


def test_merge_through_the_facade_records_an_undo(wired):
    keep, drop = wired
    res = ems_db.merge_jobs(keep, [drop])

    assert res["merged"] == 1
    assert res.get("undo_id"), "every façade merge must leave a way back"
    rec = job_undo.load(res["undo_id"])
    captured = {j["canon_key"] for j in rec["jobs"]}
    # The SURVIVOR is captured too: a merge changes it as well, so a
    # record of only the loser describes half the change.
    assert captured == {keep, drop}


def test_the_undo_actually_reverses_a_facade_merge(wired):
    keep, drop = wired
    res = ems_db.merge_jobs(keep, [drop])
    assert sdb.get_job(drop) is None

    job_undo.restore(res["undo_id"], dry_run=False)

    assert sdb.get_job(drop) is not None
    assert sorted(c["name"] for c in sdb.children_of(drop)) == [
        "Unit 561-I", "Unit 585-G"]


def test_a_broken_undo_does_not_block_the_merge(wired, monkeypatch):
    """Downgrading the safety net beats refusing to work.

    The absent undo_id is how the caller can tell it happened.
    """
    keep, drop = wired
    monkeypatch.setattr(job_undo, "capture",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    res = ems_db.merge_jobs(keep, [drop])
    assert res["merged"] == 1
    assert "undo_id" not in res
