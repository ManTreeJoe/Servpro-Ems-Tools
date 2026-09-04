"""Resolving a job's PICS folder when the pin ISN'T the job root.

Pinning a subfolder is how an unknown job gets attached by hand. Blindly
appending EMS\\PICS to a path that already ends in one produced
`…\\EMS\\PICS\\EMS\\PICS`, which was returned without checking it exists
— so every photo read as missing and a pull would have filed them into a
folder nobody would ever open.
"""

import os

import pytest

import companycam_web_api as cwa
import persistence


class _Api(cwa.CompanyCamApi):
    pass


@pytest.fixture
def job(tmp_path, monkeypatch):
    """A job folder with the standard EMS\\PICS scaffolding."""
    root = tmp_path / "2026 Jobs" / "Smith John"
    (root / "EMS" / "PICS" / "Initial").mkdir(parents=True)
    (root / "EMS" / "DOCS").mkdir(parents=True)
    monkeypatch.setattr(cwa, "persistence", persistence)
    return root


def _resolve(monkeypatch, pinned):
    monkeypatch.setattr(persistence, "get_folder_path", lambda c: str(pinned))
    return _Api()._cc_pics_dir("Smith, John")


def test_the_job_root_resolves_to_ems_pics(job, monkeypatch):
    got = _resolve(monkeypatch, job)
    assert got == str(job / "EMS" / "PICS")


def test_pinning_the_pics_folder_itself_returns_it(job, monkeypatch):
    pics = job / "EMS" / "PICS"
    assert _resolve(monkeypatch, pics) == str(pics)


def test_pinning_a_folder_inside_pics_walks_back_to_the_pics_root(
        job, monkeypatch):
    # Deeper is wrong: pulls organise into <stage>\<tech date>\<room>
    # BELOW the PICS root, so starting inside one nests a second layout.
    pics = job / "EMS" / "PICS"
    assert _resolve(monkeypatch, pics / "Initial") == str(pics)


def test_pinning_the_ems_folder_finds_pics_under_it(job, monkeypatch):
    assert _resolve(monkeypatch, job / "EMS") == str(job / "EMS" / "PICS")


def test_a_flat_pics_layout_is_honoured(tmp_path, monkeypatch):
    root = tmp_path / "Flat Job"
    (root / "PICS").mkdir(parents=True)
    monkeypatch.setattr(cwa, "persistence", persistence)
    monkeypatch.setattr(persistence, "get_folder_path", lambda c: str(root))
    assert _Api()._cc_pics_dir("Flat, Job") == str(root / "PICS")


def test_a_job_with_no_pics_yet_gets_the_intended_path(tmp_path, monkeypatch):
    # A first pull legitimately creates it, so this must not refuse.
    root = tmp_path / "Brand New"
    root.mkdir(parents=True)
    monkeypatch.setattr(cwa, "persistence", persistence)
    monkeypatch.setattr(persistence, "get_folder_path", lambda c: str(root))
    assert _Api()._cc_pics_dir("Brand, New") == str(root / "EMS" / "PICS")


def test_never_returns_a_doubled_pics_path(job, monkeypatch):
    # The actual bug: the returned path must never contain PICS twice.
    for pinned in (job, job / "EMS", job / "EMS" / "PICS",
                   job / "EMS" / "PICS" / "Initial"):
        got = _resolve(monkeypatch, pinned).upper()
        assert got.count(os.sep + "PICS") == 1, got


def test_an_unresolvable_job_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(cwa, "persistence", persistence)
    monkeypatch.setattr(persistence, "get_folder_path", lambda c: "")
    monkeypatch.setattr(cwa.audit_logic, "try_resolve_folder_by_terms",
                        lambda *a, **k: ("", "", ""))
    assert _Api()._cc_pics_dir("Nobody, Here") == ""


def test_unique_nested_jobs_candidate_is_auto_pinned_for_companycam(
        tmp_path, monkeypatch):
    job = tmp_path / "2026 Jobs" / "PCM" / "Kellogg Terrace - Cruz Sarah"
    pics = job / "EMS" / "PICS"
    pics.mkdir(parents=True)
    monkeypatch.setattr(cwa, "persistence", persistence)
    monkeypatch.setattr(persistence, "get_folder_path", lambda _client: "")
    monkeypatch.setattr(cwa.audit_logic, "try_resolve_folder_by_terms",
                        lambda *a, **k: ("", "", ""))
    pinned = []
    monkeypatch.setattr(persistence, "set_folder_path",
                        lambda client, path: pinned.append((client, path)))

    class NestedApi(_Api):
        def list_folder_candidates(self, _client, _scope):
            return {"ok": True, "candidates": [
                {"path": str(job), "name": job.name, "score": 5},
                {"path": str(job.parent), "name": "PCM", "score": 1},
            ]}

    client = "PCM - Kellogg Terrace - (Cruz, Sarah) 8/28"
    assert NestedApi()._cc_pics_dir(client) == str(pics)
    assert pinned == [(client, str(job))]


def test_ambiguous_nested_candidates_are_never_auto_pinned(
        tmp_path, monkeypatch):
    first = tmp_path / "Kellogg Terrace A"
    second = tmp_path / "Kellogg Terrace B"
    first.mkdir(); second.mkdir()
    monkeypatch.setattr(cwa, "persistence", persistence)
    monkeypatch.setattr(persistence, "get_folder_path", lambda _client: "")
    monkeypatch.setattr(cwa.audit_logic, "try_resolve_folder_by_terms",
                        lambda *a, **k: ("", "", ""))
    pinned = []
    monkeypatch.setattr(persistence, "set_folder_path",
                        lambda *args: pinned.append(args))

    class AmbiguousApi(_Api):
        def list_folder_candidates(self, _client, _scope):
            return {"ok": True, "candidates": [
                {"path": str(first), "name": first.name, "score": 4},
                {"path": str(second), "name": second.name, "score": 4},
            ]}

    assert AmbiguousApi()._cc_pics_dir("PCM - Kellogg Terrace") == ""
    assert pinned == []
