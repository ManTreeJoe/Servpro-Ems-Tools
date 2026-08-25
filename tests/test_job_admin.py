"""User-facing merge/delete must preview, guard, preserve, and undo."""
import pathlib

import pytest

import ems_db
import ems_db_sqlite as sdb
import job_undo
from job_admin_api import JobAdminApi


class _Api(JobAdminApi):
    pass


@pytest.fixture
def jobs(tmp_path, monkeypatch):
    import paths
    monkeypatch.setattr(paths, "data", lambda name="": str(tmp_path / name))
    ems_db.use_backend("sqlite")
    sdb.reset_db_path(str(tmp_path / "jobs.db"))
    keep = sdb.upsert_job(display_name="Smith, Jordan - AAA",
                          carrier="AAA")
    drop = sdb.upsert_job(display_name="Jordan Smith",
                          claim_number="CLM-42",
                          address="42 Cedar Street")
    sdb.set_link(drop, sdb.LINK_TRELLO, "card-42")
    sdb.set_child(drop, "2nd Claim")
    return keep, drop


def test_delete_preview_says_what_will_go(jobs):
    _keep, drop = jobs
    p = _Api().job_delete_preview(drop)
    assert p["ok"] and p["job"]["display_name"] == "Jordan Smith"
    assert p["children"] == ["2nd Claim"]
    assert p["links"][0]["type"] == sdb.LINK_TRELLO
    assert p["external_untouched"] is True


def test_delete_requires_the_exact_display_name(jobs):
    _keep, drop = jobs
    res = _Api().job_delete_apply(drop, "Jordan")
    assert res["ok"] is False
    assert sdb.get_job(drop) is not None


def test_delete_records_undo_and_restore_rebuilds_the_job(jobs):
    _keep, drop = jobs
    res = _Api().job_delete_apply(drop, "Jordan Smith")
    assert res["ok"] and res["deleted"] == 1 and res.get("undo_id")
    assert sdb.get_job(drop) is None
    assert job_undo.restore(res["undo_id"], dry_run=False)["ok"]
    assert sdb.get_job(drop)["address"] == "42 Cedar Street"
    assert [c["name"] for c in sdb.children_of(drop)] == ["2nd Claim"]


def test_merge_preview_and_apply_carry_empty_fields(jobs):
    keep, drop = jobs
    api = _Api()
    p = api.job_merge_preview(keep, drop)
    assert p["ok"] and p["carried"] == ["claim_number", "address"]
    assert p["preview"]["totals"]["children"] == 1
    res = api.job_merge_apply(keep, drop, "Jordan Smith")
    assert res["ok"] and res.get("undo_id")
    assert sdb.get_job(drop) is None
    assert sdb.get_job(keep)["claim_number"] == "CLM-42"
    assert [c["name"] for c in sdb.children_of(keep)] == ["2nd Claim"]


def test_merge_refuses_different_departments(jobs):
    keep, drop = jobs
    sdb.upsert_job(display_name="Smith, Jordan - AAA", department="IE")
    sdb.upsert_job(display_name="Jordan Smith", department="OC")
    res = _Api().job_merge_apply(keep, drop, "Jordan Smith")
    assert res["ok"] is False
    assert sdb.get_job(drop) is not None


def test_shared_card_exposes_the_guarded_job_manager():
    js = (pathlib.Path(__file__).parents[1] / "web_shared" /
          "audit_detail.js").read_text(encoding="utf-8")
    assert 'data-action="manage-job"' in js
    for call in ("job_delete_preview", "job_delete_apply",
                 "job_merge_preview", "job_merge_apply"):
        assert f"pywebview.api.{call}" in js
    assert "Type the full job name to confirm" in js
    assert "External jobs were untouched" in js
