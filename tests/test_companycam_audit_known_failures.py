"""Confirmed audit gaps. Strict xfails must be removed when repaired.

Run with --runxfail to see the failing acceptance contracts. No live services.
"""
import sys
from types import SimpleNamespace

import pytest
import companycam_api as cc
import companycam_web_api as web


def test_failed_photo_listing_is_not_clean_import(monkeypatch, tmp_path):
    api = web.CompanyCamApi()
    monkeypatch.setattr(api, "_cc_pics_dir", lambda *a: str(tmp_path))
    monkeypatch.setattr(api, "_cc_contents_dir", lambda *a: "")
    monkeypatch.setattr(api, "_cc_docs_dir", lambda *a: "")
    monkeypatch.setattr(cc, "pull_new_photos", lambda *a, **k: {
        "ok": False, "error": "Provider unavailable", "downloaded": 0,
        "skipped": 0, "files": [], "latest": None,
    })
    result = api.companycam_pull_assigned(
        "Audit fixture", [{"photo_ids": ["p1"]}], project_id="fixture-project")
    assert not result["ok"] or result.get("error"), result


def test_failed_duplicate_lookup_never_creates_project(monkeypatch):
    import new_loss_intake as intake
    monkeypatch.setitem(sys.modules, "ems_db", SimpleNamespace(find_job_by_name=lambda *a: None))
    monkeypatch.setattr(cc, "is_configured", lambda: True)
    monkeypatch.setattr(cc, "find_project", lambda *a, **k: {
        "ok": False, "error": "Provider unavailable"})
    created = []
    monkeypatch.setattr(cc, "create_project", lambda *a, **k:
                        created.append(a) or {"ok": True, "project": {"id": "fake"}})
    monkeypatch.setattr(intake, "_pin_companycam", lambda *a, **k: True)
    result = intake.create_companycam_project(
        {"insured_name": "Audit fixture"}, confirm_create=True)
    assert not created, result
