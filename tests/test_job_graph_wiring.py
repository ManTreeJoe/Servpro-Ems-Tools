"""End-to-end wiring of the job-identity graph: folder pins, Trello pins,
CompanyCam resolution, and the backfill all teach the same graph so tools
stop mismatching a job spelled differently across systems."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import companycam_api as cc
import ems_db
import persistence


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    ems_db.reset_db_path(str(tmp_path / "jobs.db"))
    monkeypatch.setattr(persistence, "_CACHE", {}, raising=False)
    monkeypatch.setattr(persistence, "_CACHE_MTIME", None, raising=False)
    monkeypatch.setattr(persistence, "_save",
                        lambda s: persistence.__dict__.update(
                            _CACHE=s, _CACHE_MTIME=None))
    monkeypatch.setattr(persistence, "_load", lambda: persistence._CACHE)
    yield


def test_folder_pin_aliases_second_spelling():
    folder = r"X:\IE_Public\2026 Jobs\Bromme Ira\EMS"
    persistence.set_folder_path("Bromme Ira", folder)
    persistence.set_folder_path("Ira Bromme", folder)   # same folder, new spelling
    j1 = ems_db.find_job_by_name("Bromme Ira")
    j2 = ems_db.find_job_by_name("Ira Bromme")
    assert j1 and j2 and j1["canon_key"] == j2["canon_key"]


def test_trello_pin_aliases_second_spelling():
    persistence.set_trello_card_ids("Club Pilates", ["AbC12345"])
    persistence.set_trello_card_ids("Pilates Club", ["AbC12345"])
    a = ems_db.find_job_by_name("Club Pilates")
    b = ems_db.find_job_by_name("Pilates Club")
    assert a and b and a["canon_key"] == b["canon_key"]
    # Card stored normalized (lowercased) on the one job.
    assert ems_db.get_link(a["canon_key"], "trello_card") == "abc12345"


def test_backfill_from_existing_pins():
    # Pins already sitting in state, never run through the teaching hooks.
    persistence._CACHE["folder_paths"] = {"smith john": r"X:\J\Smith John"}
    persistence._CACHE["trello_card_ids"] = {"doe jane": ["ZZ99"]}
    res = persistence.backfill_job_graph()
    assert res["folders"] == 1 and res["cards"] == 1
    assert ems_db.find_job_by_name("smith john")
    assert ems_db.get_link(ems_db.canon_key("doe jane"), "trello_card") == "zz99"


def test_job_identity_shows_aliases_and_links():
    folder = r"X:\J\Bromme Ira\EMS"
    persistence.set_folder_path("Bromme Ira", folder)
    persistence.set_folder_path("Ira Bromme", folder)
    ident = ems_db.job_identity("Ira Bromme")
    assert ident
    assert ident["job"]["canon_key"] == ems_db.canon_key("Bromme Ira")
    assert "Ira Bromme" in ident["aliases"]            # list[str]
    assert any(l["link_type"] == "folder_path" for l in ident["links"])


def test_companycam_find_project_id_teaches_then_caches(monkeypatch):
    calls = {"n": 0}

    def _api(name, address_hint=""):
        calls["n"] += 1
        return {"ok": True, "candidates": [],
                "match": {"id": "proj_42", "name": name}}
    monkeypatch.setattr(cc, "find_project", _api)

    pid = cc.find_project_id("Bernardo, Foilan")
    assert pid == "proj_42" and calls["n"] == 1
    # Taught the graph.
    assert ems_db.get_link(ems_db.canon_key("Bernardo, Foilan"),
                           ems_db.LINK_COMPANYCAM) == "proj_42"

    # Second lookup of the same spelling is a cache hit — no API call.
    def _boom(*a, **k):
        raise AssertionError("API should not be called on a cache hit")
    monkeypatch.setattr(cc, "find_project", _boom)
    assert cc.find_project_id("Bernardo, Foilan") == "proj_42"


def test_companycam_ties_to_folder_job(monkeypatch):
    # A job already known by its folder under one spelling…
    folder = r"X:\J\Bernardo Foilan\EMS"
    persistence.set_folder_path("Bernardo, Foilan", folder)
    monkeypatch.setattr(cc, "find_project", lambda name, address_hint="": {
        "ok": True, "candidates": [], "match": {"id": "proj_9", "name": name}})
    # …resolving CompanyCam WITH the folder ties them to the same job.
    cc.find_project_id("Foilan Bernardo", folder_path=folder)
    key = ems_db.canon_key("Bernardo, Foilan")
    assert ems_db.get_link(key, ems_db.LINK_COMPANYCAM) == "proj_9"
    # And "Foilan Bernardo" now resolves to that same job.
    assert ems_db.find_job_by_name("Foilan Bernardo")["canon_key"] == key
