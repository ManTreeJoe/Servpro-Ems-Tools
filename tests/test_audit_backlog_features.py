"""Regression tests for the three audit-panel features that read from
the audit backlog / resolved-issues store:

1. Repeat-offender badge — driven by `audit_export.get_audit_count_index()`
2. Carry-forward pre-check — driven by `persistence.last_resolved_within()`
3. Stale-flagged-jobs banner — driven by `audit_export.get_stale_flagged_jobs()`

Each helper is a pure data lookup; the rendering layer is exercised
manually. These tests pin the lookup contracts so the UI can rely on
them without re-checking edge cases (date parsing, missing fields,
unit-aware keying)."""

import json
import os
from datetime import datetime, timedelta

import pytest

import audit_export
import persistence


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Point both modules at temp data files so tests don't see the
    user's real backlog / state."""
    backlog = tmp_path / "audit_backlog.json"
    state   = tmp_path / "state.json"
    monkeypatch.setattr(audit_export, "_BACKLOG_FILE", str(backlog))
    monkeypatch.setattr(persistence,    "_STATE_PATH", str(state))
    monkeypatch.setattr(persistence, "_CACHE", None, raising=False)
    monkeypatch.setattr(persistence, "_CACHE_MTIME", None, raising=False)
    yield


def _write_backlog(jobs):
    with open(audit_export._BACKLOG_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_updated": datetime.today().isoformat(),
                   "jobs": jobs}, f)


# ── get_audit_count_index ─────────────────────────────────────────────────

def test_audit_count_index_basic():
    _write_backlog([
        {"client": "Antonio Garcia", "folder": "Garcia Antonio",
         "status": "FLAG", "audit_count": 32},
        {"client": "Bridgette Miles", "folder": "Miles Bridgette",
         "status": "FLAG", "audit_count": 151},
    ])
    idx = audit_export.get_audit_count_index()
    assert idx[("Garcia Antonio", "")] == 32
    assert idx[("Miles Bridgette", "")] == 151


def test_audit_count_index_unit_keyed():
    """Multi-unit properties stay separate in the index — Unit 168 and
    Unit 182 of the same Keystone folder don't collapse counts."""
    _write_backlog([
        {"client": "Keystone", "folder": "KEYSTONE",
         "unit": "168", "status": "FLAG", "audit_count": 5},
        {"client": "Keystone", "folder": "KEYSTONE",
         "unit": "182", "status": "FLAG", "audit_count": 12},
    ])
    idx = audit_export.get_audit_count_index()
    assert idx[("KEYSTONE", "168")] == 5
    assert idx[("KEYSTONE", "182")] == 12


def test_audit_count_index_missing_folder_skipped():
    """Entries with no folder name (rare legacy data) shouldn't crash
    the index build, just get skipped."""
    _write_backlog([
        {"client": "Foo", "folder": "", "status": "OK", "audit_count": 3},
        {"client": "Bar", "folder": "Bar Folder", "status": "OK",
         "audit_count": 7},
    ])
    idx = audit_export.get_audit_count_index()
    assert idx == {("Bar Folder", ""): 7}


def test_audit_count_index_picks_max_on_collision():
    """If legacy data has two entries for the same (folder, unit) key
    (because old data lacks unit info), keep the higher count rather
    than letting dict order silently win."""
    _write_backlog([
        {"client": "John Camp", "folder": "Camp John",
         "status": "FLAG", "audit_count": 156},
        {"client": "Camp John", "folder": "Camp John",
         "status": "FLAG", "audit_count": 1},
    ])
    idx = audit_export.get_audit_count_index()
    assert idx[("Camp John", "")] == 156


def test_audit_count_index_empty_when_no_backlog(tmp_path):
    """Missing backlog file should return {} not crash."""
    audit_export._BACKLOG_FILE = str(tmp_path / "nope.json")
    assert audit_export.get_audit_count_index() == {}


# ── get_stale_flagged_jobs ────────────────────────────────────────────────

def test_stale_jobs_returns_only_flagged_past_cutoff():
    now    = datetime.today()
    recent = (now - timedelta(days=2)).isoformat()
    stale  = (now - timedelta(days=10)).isoformat()
    _write_backlog([
        {"client": "Recent FLAG", "folder": "A", "status": "FLAG",
         "last_audited": recent},
        {"client": "Stale FLAG",  "folder": "B", "status": "FLAG",
         "last_audited": stale},
        {"client": "Stale OK",    "folder": "C", "status": "OK",
         "last_audited": stale},
    ])
    out = audit_export.get_stale_flagged_jobs(days=7)
    names = {j["client"] for j in out}
    assert names == {"Stale FLAG"}


def test_stale_jobs_sorts_newest_first():
    now = datetime.today()
    _write_backlog([
        {"client": "Older",  "folder": "A", "status": "FLAG",
         "last_audited": (now - timedelta(days=20)).isoformat()},
        {"client": "Newer",  "folder": "B", "status": "FLAG",
         "last_audited": (now - timedelta(days=10)).isoformat()},
    ])
    out = audit_export.get_stale_flagged_jobs(days=7)
    assert [j["client"] for j in out] == ["Newer", "Older"]


def test_stale_jobs_empty_when_no_backlog(tmp_path):
    audit_export._BACKLOG_FILE = str(tmp_path / "nope.json")
    assert audit_export.get_stale_flagged_jobs(days=7) == []


# ── persistence.last_resolved_within ──────────────────────────────────────

def test_last_resolved_within_finds_recent():
    today = datetime.today()
    yest  = (today - timedelta(days=1)).strftime("%m-%d-%Y")
    persistence.set_resolved(yest, "Smith John", "Auth to Perform", True)
    out = persistence.last_resolved_within("Smith John", "Auth to Perform",
                                           days=7)
    assert out == yest


def test_last_resolved_within_picks_most_recent():
    """When multiple prior dates resolved the same item, the most
    recent date wins — the user wants 'last marked done' not 'first
    marked done'."""
    today = datetime.today()
    older = (today - timedelta(days=5)).strftime("%m-%d-%Y")
    newer = (today - timedelta(days=2)).strftime("%m-%d-%Y")
    persistence.set_resolved(older, "Smith John", "Scope", True)
    persistence.set_resolved(newer, "Smith John", "Scope", True)
    out = persistence.last_resolved_within("Smith John", "Scope", days=7)
    assert out == newer


def test_last_resolved_within_respects_cutoff():
    today = datetime.today()
    too_old = (today - timedelta(days=15)).strftime("%m-%d-%Y")
    persistence.set_resolved(too_old, "Smith John", "Scope", True)
    assert persistence.last_resolved_within("Smith John", "Scope",
                                             days=7) is None


def test_last_resolved_within_other_client_doesnt_leak():
    """A resolved entry for client A must not surface for client B."""
    today = datetime.today()
    yest  = (today - timedelta(days=1)).strftime("%m-%d-%Y")
    persistence.set_resolved(yest, "Smith John", "Scope", True)
    assert persistence.last_resolved_within("Doe Jane", "Scope",
                                             days=7) is None


def test_last_resolved_within_unset_returns_none():
    """Items the user never marked resolved should report None."""
    assert persistence.last_resolved_within("Anyone", "Anything",
                                             days=7) is None


def test_last_resolved_within_skips_unset_value():
    """If the user UN-resolved a prior entry (set_resolved(..., False)),
    the key is removed from the dict — last_resolved_within should NOT
    return a date for it. The semantic is 'currently marked done'."""
    today = datetime.today()
    yest  = (today - timedelta(days=1)).strftime("%m-%d-%Y")
    persistence.set_resolved(yest, "Smith John", "Scope", True)
    persistence.set_resolved(yest, "Smith John", "Scope", False)
    assert persistence.last_resolved_within("Smith John", "Scope",
                                             days=7) is None
