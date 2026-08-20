"""Undo for the operations that rewrite job identity.

A merge moves aliases, links and children onto a survivor and deletes the
loser. Before this there was no way back, and the damage is the quiet
kind — nothing errors, the panel repaints, and the wrong answer looks
exactly like the right one until someone goes looking weeks later.

The test that matters is the round trip: capture, merge, restore, and
find the job whole again. Anything less is a file nobody can act on.
"""
import io
import json
import os

import pytest

import job_undo
import ems_db_sqlite as sdb


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Temp database + temp undo directory."""
    import paths
    monkeypatch.setattr(paths, "data", lambda name="": str(tmp_path / name))
    sdb.reset_db_path(str(tmp_path / "t.db"))
    # Names chosen so the two keys genuinely differ. `canon_key` strips at
    # " - ", so "Greystar - Avana Springs" and "Greystar" are ONE key —
    # picking those merged a job into itself and merge_jobs rightly did
    # nothing, which looked like a broken undo.
    sdb.upsert_job(display_name="Avana Springs Greystar")
    sdb.upsert_job(display_name="Greystar Property Group")
    keep = sdb.canon_key("Avana Springs Greystar")
    drop = sdb.canon_key("Greystar Property Group")
    assert keep != drop
    sdb.set_link(drop, sdb.LINK_TRELLO, "card585")
    sdb.set_link(drop, sdb.LINK_FOLDER, r"X:\IE_Public\2026 Jobs\Greystar")
    sdb.set_child(drop, "Unit 585-G", folder_path=r"X:\a\585G",
                  trello_card="c585", companycam="cc585")
    sdb.add_alias(drop, "Greystar Property")
    return keep, drop


def test_capture_records_what_the_job_is(wired, tmp_path):
    keep, drop = wired
    res = job_undo.capture([drop], op="merge", note="folding greystar")

    assert res["ok"] is True
    assert res["counts"]["jobs"] == 1
    assert res["counts"]["children"] == 1
    assert res["counts"]["links"] >= 2
    rec = json.load(io.open(res["path"], encoding="utf-8"))
    assert rec["op"] == "merge" and rec["note"] == "folding greystar"
    assert rec["jobs"][0]["canon_key"] == drop
    assert rec["jobs"][0]["children"][0]["name"] == "Unit 585-G"


def test_the_round_trip(wired):
    """Capture, destroy, restore — the only test that proves the point."""
    keep, drop = wired
    rec = job_undo.capture([drop], op="merge")

    sdb.merge_jobs(keep, [drop])
    assert sdb.get_job(drop) is None          # really gone

    out = job_undo.restore(rec["id"], dry_run=False)

    assert out["ok"] is True, out.get("errors")
    back = sdb.get_job(drop)
    assert back is not None
    assert back["display_name"] == "Greystar Property Group"
    kids = sdb.children_of(drop)
    assert [c["name"] for c in kids] == ["Unit 585-G"]
    # The child's own links are the expensive part — a restore that
    # returns a bare row has not undone anything worth undoing.
    assert kids[0]["trello_card"] == "c585"
    assert kids[0]["companycam"] == "cc585"
    types = {l["link_type"] for l in sdb.get_links(drop)}
    assert sdb.LINK_TRELLO in types and sdb.LINK_FOLDER in types


def test_restore_is_dry_run_by_default(wired):
    """Every repair path in this codebase defaults to dry-run.

    The one that didn't is how nine canon keys were re-written before
    anyone had read the plan.
    """
    keep, drop = wired
    rec = job_undo.capture([drop], op="merge")
    sdb.merge_jobs(keep, [drop])

    out = job_undo.restore(rec["id"])          # no dry_run= passed

    assert out["dry_run"] is True
    assert out["would"]["children"] == 1
    assert sdb.get_job(drop) is None           # nothing was written


def test_capture_failure_does_not_raise(wired, monkeypatch):
    """A broken undo must not take the operation down with it.

    It downgrades the safety net; it does not break the tool. The caller
    is told so it can decide.
    """
    import ems_db
    monkeypatch.setattr(ems_db, "backend_name",
                        lambda: (_ for _ in ()).throw(RuntimeError("nope")))
    res = job_undo.capture(["whatever"], op="merge")
    assert res["ok"] is False and "error" in res


def test_bulk_capture_falls_back_off_the_shared_backend(wired):
    """The bulk path is a Supabase optimisation, not a second behaviour.

    `_capture_key` costs four network calls PER KEY. A 163-key backfill
    meant ~650 round trips, ran for five minutes and was killed halfway
    through the writes it existed to protect. The bulk path pulls whole
    tables once instead — but only where that's cheap, so anywhere else
    it must return None and let the per-key loop run.
    """
    assert job_undo._capture_bulk(["a", "b"]) is None


def test_capture_is_whole_however_it_was_gathered(wired):
    """Bulk or per-key, the record has to have the same shape — a restore
    reads one format."""
    keep, drop = wired
    rec = job_undo.capture([drop], op="merge")
    got = json.load(io.open(rec["path"], encoding="utf-8"))["jobs"][0]
    assert set(got) == {"canon_key", "job", "aliases", "links", "children"}


def test_records_are_listed_newest_first_and_pruned(wired, monkeypatch):
    keep, drop = wired
    monkeypatch.setattr(job_undo, "KEEP", 3)
    for i in range(5):
        monkeypatch.setattr(job_undo, "_stamp", lambda i=i: f"2026081{i}-000000")
        job_undo.capture([drop], op="merge", note=f"n{i}")
    recs = job_undo.list_records()
    assert len(recs) == 3
    assert [r["note"] for r in recs] == ["n4", "n3", "n2"]
