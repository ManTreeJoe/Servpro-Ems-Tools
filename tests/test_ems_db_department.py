"""ems_db department column — which franchise owns a job.

Department is derived from the job's FOLDER ROOT, never from its Trello
board: IE currently runs recon for both franchises, so an OC-owned job
legitimately sits on an IE board. The column exists to stop IE and OC data
cross-wiring in the shared job index, not to hide jobs from either side.

  - department_for_path maps folder roots to departments (and only folders)
  - a folder pin stamps the department automatically
  - a stamped department is never silently reassigned
  - same customer name in both franchises does NOT resolve to one job
  - merge_jobs refuses to fold jobs owned by different franchises
  - unknown (NULL) department stays permissive everywhere
  - backfill_departments is idempotent and reports real conflicts
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import ems_db

IE_ROOT = r"X:\IE_Public"
OC_ROOT = r"C:\Servpro-OC"


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Fresh DB + a two-department config for every test."""
    cfg = {
        "multi_department_enabled": True,
        "active_department": "IE",
        "audit_base": IE_ROOT,
        "trello_workspace_id": "ie-ws",
        "runs_dir": IE_ROOT + r"\Runs",
        "departments": {
            "IE": {"label": "Inland Empire", "audit_base": IE_ROOT,
                   "trello_workspace_id": "ie-ws", "runs_dir": IE_ROOT + r"\Runs"},
            "OC": {"label": "Orange County", "audit_base": OC_ROOT,
                   "trello_workspace_id": "oc-ws", "runs_dir": OC_ROOT + r"\Runs"},
        },
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(config, "_USER_CFG", str(cfg_path))
    monkeypatch.setattr(config, "_CACHE", None)
    monkeypatch.setattr(config, "_CACHE_MTIME", None)
    ems_db.reset_db_path(str(tmp_path / "jobs.db"))
    ems_db.invalidate_department_cache()
    yield


def _ie(sub="Smith, Robert"):
    return os.path.join(IE_ROOT, "2026 Jobs", sub)


def _oc(sub="Smith, Robert"):
    return os.path.join(OC_ROOT, "2026 OC Jobs", sub)


# ── derivation ──────────────────────────────────────────────────────────

def test_department_for_path_matches_configured_roots():
    assert ems_db.department_for_path(_ie()) == "IE"
    assert ems_db.department_for_path(_oc()) == "OC"


def test_department_for_path_is_case_and_separator_insensitive():
    assert ems_db.department_for_path("x:/ie_public/2026 jobs/x") == "IE"


def test_department_for_path_unknown_root_is_none():
    assert ems_db.department_for_path(r"D:\Somewhere\Else") is None
    assert ems_db.department_for_path("") is None


def test_root_itself_matches_but_a_sibling_prefix_does_not():
    assert ems_db.department_for_path(IE_ROOT) == "IE"
    # "X:\IE_Public_OLD" must not match the "X:\IE_Public" root.
    assert ems_db.department_for_path(r"X:\IE_Public_OLD\job") is None


# ── stamping ────────────────────────────────────────────────────────────

def test_folder_pin_stamps_the_department():
    key = ems_db.upsert_job(display_name="Smith, Robert")
    assert ems_db.get_job(key)["department"] is None
    ems_db.set_link(key, ems_db.LINK_FOLDER, _ie())
    assert ems_db.get_job(key)["department"] == "IE"


def test_trello_card_never_implies_a_department():
    """IE runs OC's recon, so an OC job appears on IE boards. A card link
    must not stamp — or infer — anything."""
    key = ems_db.upsert_job(display_name="Kim, Michael")
    ems_db.set_link(key, ems_db.LINK_TRELLO, "abc123")
    assert ems_db.get_job(key)["department"] is None


def test_established_department_is_not_reassigned_by_another_folder():
    key = ems_db.upsert_job(display_name="Smith, Robert", department="OC")
    ems_db.set_link(key, ems_db.LINK_FOLDER, _ie())
    assert ems_db.get_job(key)["department"] == "OC"


def test_upsert_blank_department_does_not_clear_an_existing_one():
    key = ems_db.upsert_job(display_name="Smith, Robert", department="OC")
    ems_db.upsert_job(display_name="Smith, Robert", carrier="AAA")
    assert ems_db.get_job(key)["department"] == "OC"


def test_set_department_fills_null_but_needs_overwrite_to_correct():
    key = ems_db.upsert_job(display_name="Smith, Robert")
    assert ems_db.set_department(key, "IE") is True
    assert ems_db.set_department(key, "OC") is False
    assert ems_db.get_job(key)["department"] == "IE"
    assert ems_db.set_department(key, "OC", overwrite=True) is True
    assert ems_db.get_job(key)["department"] == "OC"


# ── the cross-wiring guard ──────────────────────────────────────────────

def test_same_name_in_both_franchises_does_not_resolve_to_one_job():
    """The disaster case: OC pins 'Smith, Robert', then IE pins its own."""
    oc = ems_db.resolve_and_link("Smith, Robert", folder_path=_oc(),
                                 create=True, source="test")
    assert oc["department"] == "OC"
    with pytest.raises(ems_db.DepartmentConflict):
        ems_db.resolve_and_link("Smith, Robert", folder_path=_ie(),
                                create=True, source="test")
    # The OC job is untouched — no IE folder attached to it.
    folders = [l["link_value"] for l in
               ems_db.get_links(oc["canon_key"], ems_db.LINK_FOLDER)]
    assert all("ie_public" not in f.lower() for f in folders)


def test_conflict_can_be_opted_out_of():
    ems_db.resolve_and_link("Smith, Robert", folder_path=_oc(),
                            create=True, source="test")
    job = ems_db.resolve_and_link("Smith, Robert", folder_path=_ie(),
                                  create=True, source="test",
                                  strict_department=False)
    assert job is not None


def test_unknown_department_job_still_accepts_a_folder():
    """NULL department is permissive — pre-backfill jobs keep working."""
    key = ems_db.upsert_job(display_name="Jones, Pat")
    job = ems_db.resolve_and_link("Jones, Pat", folder_path=_ie(),
                                  source="test")
    assert job["canon_key"] == key
    assert job["department"] == "IE"


def test_same_department_resolution_is_unaffected():
    ems_db.resolve_and_link("Smith, Robert", folder_path=_ie(),
                            create=True, source="test")
    again = ems_db.resolve_and_link("smith, robert", folder_path=_ie(),
                                    source="test")
    assert again is not None and again["department"] == "IE"


def test_trello_only_resolution_crosses_departments_freely():
    """IE doing OC's recon must still resolve the OC job by its card."""
    oc = ems_db.resolve_and_link("Kim, Michael", folder_path=_oc(),
                                 trello_card="card1", create=True,
                                 source="test")
    found = ems_db.resolve_and_link("Kim, Michael", trello_card="card1",
                                    source="test")
    assert found["canon_key"] == oc["canon_key"]
    assert found["department"] == "OC"


def test_merge_refuses_to_fold_across_departments():
    ie = ems_db.upsert_job(display_name="Smith, Robert - AAA",
                           department="IE")
    oc = ems_db.upsert_job(display_name="Smith Robert", department="OC")
    res = ems_db.merge_jobs(ie, [oc])
    assert res["merged"] == 0
    assert res["skipped_department_conflict"] == [oc]
    assert ems_db.get_job(oc) is not None


def test_merge_still_works_within_one_department():
    ie = ems_db.upsert_job(display_name="Smith, Robert - AAA",
                           department="IE")
    dup = ems_db.upsert_job(display_name="Smith Robert", department="IE")
    assert ems_db.merge_jobs(ie, [dup])["merged"] == 1
    assert ems_db.get_job(dup) is None


def test_merge_folds_an_unknown_department_job():
    ie = ems_db.upsert_job(display_name="Smith, Robert - AAA",
                           department="IE")
    dup = ems_db.upsert_job(display_name="Smith Robert")
    assert ems_db.merge_jobs(ie, [dup])["merged"] == 1


# ── scoped lookup (opt-in) ──────────────────────────────────────────────

def test_find_job_by_name_is_unscoped_by_default():
    ems_db.upsert_job(display_name="Smith, Robert", department="OC")
    assert ems_db.find_job_by_name("Smith, Robert") is not None


def test_find_job_by_name_scoped_rejects_the_other_franchise():
    ems_db.upsert_job(display_name="Smith, Robert", department="OC")
    assert ems_db.find_job_by_name("Smith, Robert", department="IE") is None
    assert ems_db.find_job_by_name("Smith, Robert", department="OC") is not None


def test_scoped_lookup_still_finds_unknown_department_jobs():
    ems_db.upsert_job(display_name="Jones, Pat")
    assert ems_db.find_job_by_name("Jones, Pat", department="IE") is not None


# ── backfill ────────────────────────────────────────────────────────────

def test_backfill_stamps_from_folders_and_is_idempotent():
    a = ems_db.upsert_job(display_name="A Job")
    b = ems_db.upsert_job(display_name="B Job")
    c = ems_db.upsert_job(display_name="C Job")  # no folder at all
    ems_db.set_link(a, ems_db.LINK_FOLDER, _ie("A Job"))
    ems_db.set_link(b, ems_db.LINK_FOLDER, _oc("B Job"))
    # Clear what set_link already stamped so the backfill has work to do.
    for k in (a, b):
        ems_db.set_department(k, "", overwrite=True)
    with ems_db._LOCK, ems_db._connect() as conn:
        conn.execute("UPDATE jobs SET department=NULL")
        conn.commit()

    res = ems_db.backfill_departments()
    assert res["stamped"] == 2 and res["unknown"] == 1
    assert res["conflicts"] == []
    assert ems_db.get_job(a)["department"] == "IE"
    assert ems_db.get_job(b)["department"] == "OC"
    assert ems_db.get_job(c)["department"] is None

    second = ems_db.backfill_departments()
    assert second["stamped"] == 0 and second["already"] == 2


def test_backfill_reports_a_job_whose_folders_span_both():
    k = ems_db.upsert_job(display_name="Split Job")
    ems_db.set_link(k, ems_db.LINK_FOLDER, _ie("Split"))
    ems_db.set_link(k, ems_db.LINK_FOLDER, _oc("Split"))
    with ems_db._LOCK, ems_db._connect() as conn:
        conn.execute("UPDATE jobs SET department=NULL")
        conn.commit()
    res = ems_db.backfill_departments()
    assert res["stamped"] == 0
    assert len(res["conflicts"]) == 1
    assert res["conflicts"][0]["departments"] == ["IE", "OC"]
    # ...and it stays unstamped rather than being guessed at.
    assert ems_db.get_job(k)["department"] is None


def test_find_department_conflicts_flags_a_wrong_stored_value():
    k = ems_db.upsert_job(display_name="Mislabeled", department="OC")
    ems_db.set_link(k, ems_db.LINK_FOLDER, _ie("Mislabeled"))
    conflicts = ems_db.find_department_conflicts()
    assert len(conflicts) == 1
    assert conflicts[0]["stored"] == "OC"
    assert conflicts[0]["folder_departments"] == ["IE"]


def test_count_by_department():
    ems_db.upsert_job(display_name="One", department="IE")
    ems_db.upsert_job(display_name="Two", department="IE")
    ems_db.upsert_job(display_name="Three", department="OC")
    ems_db.upsert_job(display_name="Four")
    counts = ems_db.count_by_department()
    assert counts == {"IE": 2, "OC": 1, "unknown": 1}


# ── single-department installs must be unaffected ───────────────────────

def test_single_department_install_stamps_nothing(tmp_path, monkeypatch):
    cfg_path = tmp_path / "single.json"
    cfg_path.write_text(json.dumps({"audit_base": IE_ROOT}), encoding="utf-8")
    monkeypatch.setattr(config, "_USER_CFG", str(cfg_path))
    monkeypatch.setattr(config, "_CACHE", None)
    monkeypatch.setattr(config, "_CACHE_MTIME", None)
    ems_db.invalidate_department_cache()

    assert ems_db.department_for_path(_ie()) is None
    key = ems_db.upsert_job(display_name="Smith, Robert")
    ems_db.set_link(key, ems_db.LINK_FOLDER, _ie())
    assert ems_db.get_job(key)["department"] is None
    # ...and no guard can fire, so resolution behaves exactly as before.
    assert ems_db.resolve_and_link("Smith, Robert", folder_path=_oc(),
                                   source="test")["canon_key"] == key
