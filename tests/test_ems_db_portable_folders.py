"""Folder links must survive an export/import onto a DIFFERENT machine.

IE's root is a server share (X:\\IE_Public — identical everywhere), but OC's
is a OneDrive-synced SharePoint library in a separate M365 tenant:

    C:\\Users\\<user>\\Servpro12342\\Servpro-OC - OC-Onedrive
        -> https://servpro12342.sharepoint.com/sites/Servpro-OC2/...

The local path therefore contains the syncing user's own profile and is
different on every machine. Folder links travel as department + relative
path and get rebased against the importer's configured root.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import ems_db
import ems_db_common as common

IE_ROOT = r"X:\IE_Public"
OC_ROOT_A = r"C:\Users\alice\Servpro12342\Servpro-OC - OC-Onedrive"
OC_ROOT_B = r"D:\Sync\bob\Servpro-OC - OC-Onedrive"


def _configure(tmp_path, monkeypatch, oc_root):
    cfg = {
        "multi_department_enabled": True,
        "active_department": "IE",
        "audit_base": IE_ROOT,
        "trello_workspace_id": "ie-ws",
        "runs_dir": IE_ROOT + r"\Runs",
        "departments": {
            "IE": {"label": "Inland Empire", "audit_base": IE_ROOT,
                   "trello_workspace_id": "ie-ws",
                   "runs_dir": IE_ROOT + r"\Runs"},
            "OC": {"label": "Orange County", "audit_base": oc_root,
                   "trello_workspace_id": "oc-ws",
                   "runs_dir": oc_root + r"\Runs"},
        },
    }
    p = tmp_path / f"config_{abs(hash(oc_root))}.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(config, "_USER_CFG", str(p))
    monkeypatch.setattr(config, "_CACHE", None)
    monkeypatch.setattr(config, "_CACHE_MTIME", None)
    ems_db.invalidate_department_cache()


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    ems_db.reset_db_path(str(tmp_path / "jobs.db"))
    _configure(tmp_path, monkeypatch, OC_ROOT_A)
    yield


def test_split_and_rebase_round_trip():
    p = os.path.join(OC_ROOT_A, "2026 OC Jobs", "Garvin Ruth")
    dept, rel = ems_db.split_department_path(p)
    assert dept == "OC"
    assert rel == os.path.join("2026 OC Jobs", "Garvin Ruth")
    assert os.path.normcase(ems_db.rebase_department_path(dept, rel)) == \
        os.path.normcase(p)


def test_everyday_folder_value_rebases_between_windows_users(tmp_path,
                                                              monkeypatch):
    alice = os.path.join(OC_ROOT_A, "2026 OC Jobs", "Garvin Ruth")
    stored = common.portable_folder_path(alice)
    assert stored.startswith("linguar-folder://OC/")
    assert "alice" not in stored.lower()

    _configure(tmp_path, monkeypatch, OC_ROOT_B)
    bob = common.resolve_portable_folder_path(stored)
    assert os.path.normcase(bob) == os.path.normcase(os.path.join(
        OC_ROOT_B, "2026 OC Jobs", "Garvin Ruth"))


def test_legacy_absolute_folder_is_still_readable():
    old = os.path.join(OC_ROOT_A, "2026 OC Jobs", "Legacy")
    assert common.resolve_portable_folder_path(old) == old


def test_split_returns_none_outside_every_root():
    assert ems_db.split_department_path(r"D:\Elsewhere\Job") == (None, None)


def test_rebase_unknown_department_is_none():
    assert ems_db.rebase_department_path("XX", "some\\job") is None


def test_export_carries_department_and_relative(tmp_path):
    ems_db.upsert_job(display_name="Garvin, Ruth - AAA")
    ems_db.set_link("garvin, ruth", ems_db.LINK_FOLDER,
                    os.path.join(OC_ROOT_A, "2026 OC Jobs", "Garvin Ruth"))
    out = tmp_path / "export.json"
    ems_db.export_db(str(out), include_folders=True)
    payload = json.loads(out.read_text(encoding="utf-8"))
    folder = [l for l in payload["jobs"][0]["links"]
              if l["type"] == ems_db.LINK_FOLDER][0]
    assert folder["department"] == "OC"
    assert "garvin ruth" in folder["relative"].lower()
    assert "alice" not in folder["relative"].lower()   # no user profile


def test_import_rebases_onto_a_different_sync_root(tmp_path, monkeypatch):
    """The real scenario: Alice exports, Bob imports, Bob's OneDrive syncs
    the same SharePoint library to a different local path."""
    ems_db.upsert_job(display_name="Garvin, Ruth - AAA")
    ems_db.set_link("garvin, ruth", ems_db.LINK_FOLDER,
                    os.path.join(OC_ROOT_A, "2026 OC Jobs", "Garvin Ruth"))
    out = tmp_path / "export.json"
    ems_db.export_db(str(out), include_folders=True)

    # Bob: same departments, different OC sync root, empty DB.
    ems_db.reset_db_path(str(tmp_path / "bob.db"))
    _configure(tmp_path, monkeypatch, OC_ROOT_B)

    res = ems_db.import_db(str(out), mode="upsert")
    assert res["folders_rebased"] == 1
    got = ems_db.get_link("garvin, ruth", ems_db.LINK_FOLDER)
    assert got.startswith(os.path.normcase(os.path.normpath(OC_ROOT_B)))
    assert "alice" not in got
    assert got.endswith(os.path.normcase(os.path.join("2026 oc jobs",
                                                      "garvin ruth")))


def test_server_share_department_is_unchanged_by_rebasing(tmp_path,
                                                          monkeypatch):
    """IE's X:\\ root is identical on every machine — same path out."""
    ems_db.upsert_job(display_name="Smith, David - Mercury")
    original = os.path.join(IE_ROOT, "2026 Jobs", "Smith David")
    ems_db.set_link("smith, david", ems_db.LINK_FOLDER, original)
    out = tmp_path / "export.json"
    ems_db.export_db(str(out), include_folders=True)

    ems_db.reset_db_path(str(tmp_path / "other.db"))
    _configure(tmp_path, monkeypatch, OC_ROOT_B)
    ems_db.import_db(str(out), mode="upsert")
    assert ems_db.get_link("smith, david", ems_db.LINK_FOLDER) == \
        os.path.normcase(os.path.normpath(original))


def test_import_falls_back_when_department_not_configured(tmp_path,
                                                          monkeypatch):
    """A single-department machine importing a two-department export keeps
    the absolute path rather than dropping the link."""
    ems_db.upsert_job(display_name="Garvin, Ruth - AAA")
    abs_path = os.path.join(OC_ROOT_A, "2026 OC Jobs", "Garvin Ruth")
    ems_db.set_link("garvin, ruth", ems_db.LINK_FOLDER, abs_path)
    out = tmp_path / "export.json"
    ems_db.export_db(str(out), include_folders=True)

    solo = tmp_path / "solo.json"
    solo.write_text(json.dumps({"audit_base": IE_ROOT}), encoding="utf-8")
    monkeypatch.setattr(config, "_USER_CFG", str(solo))
    monkeypatch.setattr(config, "_CACHE", None)
    monkeypatch.setattr(config, "_CACHE_MTIME", None)
    ems_db.invalidate_department_cache()
    ems_db.reset_db_path(str(tmp_path / "solo.db"))

    res = ems_db.import_db(str(out), mode="upsert")
    assert res["folders_rebased"] == 0
    assert ems_db.get_link("garvin, ruth", ems_db.LINK_FOLDER) == \
        os.path.normcase(os.path.normpath(abs_path))


def test_legacy_export_without_department_still_imports(tmp_path):
    """Files written before the portable form have no department key."""
    payload = {
        "schema_version": 2,
        "jobs": [{
            "canon_key": "legacy job",
            "display_name": "Legacy Job",
            "aliases": [],
            "links": [{"type": ems_db.LINK_FOLDER,
                       "value": r"X:\IE_Public\2026 Jobs\Legacy"}],
        }],
    }
    f = tmp_path / "legacy.json"
    f.write_text(json.dumps(payload), encoding="utf-8")
    res = ems_db.import_db(str(f), mode="upsert")
    assert res["folders_rebased"] == 0
    assert ems_db.get_link("legacy job", ems_db.LINK_FOLDER)


def test_exclude_folders_still_omits_them_entirely(tmp_path):
    ems_db.upsert_job(display_name="Garvin, Ruth - AAA")
    ems_db.set_link("garvin, ruth", ems_db.LINK_FOLDER,
                    os.path.join(OC_ROOT_A, "2026 OC Jobs", "Garvin Ruth"))
    out = tmp_path / "nofolders.json"
    ems_db.export_db(str(out), include_folders=False)
    payload = json.loads(out.read_text(encoding="utf-8"))
    types = {l["type"] for j in payload["jobs"] for l in j["links"]}
    assert ems_db.LINK_FOLDER not in types
