"""Supabase backend — shape and logic, without a live project.

A real conformance run (the same ems_db tests against both backends) needs
an authenticated session, and the OTP code goes to a human's inbox. These
tests cover everything that does NOT need the network:

  * surface parity — the two backends must expose the same functions, or
    `ems_db`'s façade silently AttributeErrors at runtime
  * identity comes from ems_db_common in BOTH backends, never reimplemented
  * request shaping — filters, quoting, and the precedence rules that were
    already got wrong once on live data
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ems_db_common as common
import ems_db_sqlite as sqlite_be
import ems_db_supabase as sup
from supabase_client import SupabaseError


def _public(mod):
    return {n for n in dir(mod)
            if not n.startswith("_") and callable(getattr(mod, n, None))}


# ── surface parity ──────────────────────────────────────────────────────

_STDLIB_LEAKS = {"Iterable", "contextmanager", "datetime", "timedelta",
                 "timezone", "json"}


def test_every_sqlite_function_exists_on_the_supabase_backend():
    """The façade delegates by name — a function missing here is an
    AttributeError in production, not a test failure."""
    missing = []
    for name in sorted(_public(sqlite_be) - _STDLIB_LEAKS):
        try:
            getattr(sup, name)
        except AttributeError:
            missing.append(name)
    assert missing == [], f"not implemented on the Supabase backend: {missing}"


def test_bulk_operations_fail_loudly_rather_than_half_working():
    # sync_from_trello is no longer here: it is implemented in bulk.
    # It was unsupported because the per-card form was thousands of
    # round trips, which left the shared index unable to learn
    # anything from Trello after the cutover.
    for name in ("export_db", "import_db", "backfill_departments"):
        with pytest.raises(NotImplementedError) as ex:
            getattr(sup, name)()
        assert "sqlite" in str(ex.value).lower()


def test_unknown_attribute_still_raises():
    with pytest.raises(AttributeError):
        sup.definitely_not_a_function


# ── identity must be shared, not reimplemented ──────────────────────────

@pytest.mark.parametrize("fn", [
    "canon_key", "detect_property_and_unit", "classify_child",
    "department_for_path", "split_department_path", "rebase_department_path",
    "_norm_link",
])
def test_identity_helpers_are_the_same_object_in_both_backends(fn):
    """Two copies of canon_key would eventually disagree and split one job
    into two — the worst failure mode this codebase has."""
    assert getattr(sup, fn) is getattr(common, fn)
    assert getattr(sqlite_be, fn) is getattr(common, fn)


def test_link_type_constants_match():
    assert sup.LINK_FOLDER == sqlite_be.LINK_FOLDER == "folder_path"
    assert sup.LINK_TRELLO == sqlite_be.LINK_TRELLO == "trello_card"
    assert sup.CHILD_CLAIM == sqlite_be.CHILD_CLAIM == "claim"


# ── request shaping ─────────────────────────────────────────────────────

def test_in_filter_quotes_values():
    """Job names contain commas ('Smith, David') — unquoted they would
    split into two filter values and match the wrong rows."""
    f = sup._in(["smith, david", "jones"])
    assert f == 'in.("smith, david","jones")'


def test_in_filter_escapes_quotes():
    assert '\\"' in sup._in(['he said "hi"'])


class _Fake:
    """Minimal stand-in for supabase_client.rest()."""

    def __init__(self, tables):
        self.tables = tables
        self.calls = []

    def rest(self, method, table, *, params=None, body=None, prefer=None):
        self.calls.append((method, table, dict(params or {}), body))
        if method != "GET":
            return []
        rows = self.tables.get(table, [])
        for k, v in (params or {}).items():
            if k in ("select", "order", "limit"):
                continue
            if isinstance(v, str) and v.startswith("eq."):
                want = v[3:]
                rows = [r for r in rows if str(r.get(k, "")) == want]
            elif isinstance(v, str) and v.startswith("in.("):
                vals = {s.strip('"') for s in v[4:-1].split('","')}
                vals = {s.strip('"') for s in vals}
                rows = [r for r in rows if str(r.get(k, "")) in vals]
            elif v == "is.null":
                rows = [r for r in rows if not r.get(k)]
        if (params or {}).get("limit") == "1":
            rows = rows[:1]
        return rows


@pytest.fixture
def fake(monkeypatch):
    f = _Fake({})
    monkeypatch.setattr(sup._sb, "rest", f.rest)
    return f


def test_find_job_by_name_prefers_the_direct_hit(fake):
    fake.tables = {
        "jobs": [{"canon_key": "smith, robert", "display_name": "Direct"}],
        "job_aliases": [{"alias_canon": "smith, robert",
                         "canon_key": "someone else"}],
    }
    assert sup.find_job_by_name("Smith, Robert")["display_name"] == "Direct"


def test_new_supabase_job_starts_lifecycle_once(fake):
    fake.tables = {"jobs": []}
    sup.upsert_job(display_name="Smith, Robert", status="new_loss")
    posts = [c for c in fake.calls if c[0] == "POST"]
    assert [c[1] for c in posts] == ["jobs", "job_events"]
    assert posts[1][3]["event_type"] == "job_created"


def test_existing_supabase_job_does_not_repeat_created_event(fake):
    fake.tables = {"jobs": [{"canon_key": "smith, robert",
                              "display_name": "Smith, Robert"}]}
    sup.upsert_job(display_name="Smith, Robert", status="active")
    assert not [c for c in fake.calls
                if c[0] == "POST" and c[1] == "job_events"]


def test_shared_lifecycle_upsert_writes_pipeline_row(fake):
    fake.tables = {"job_lifecycle": []}
    result = sup.lifecycle_upsert({
        "card_id": "card-1", "client_canon": "smith",
        "client_display": "Smith", "board_id": "b1",
        "board_name": "EMS", "list_id": "l1", "list_name": "WIP",
        "current_stage": "mitigation", "last_activity_at": "2026-08-01T12:00:00Z",
        "card_url": "https://trello.com/c/card-1", "owner": "Sam",
    })
    posts = [call for call in fake.calls if call[0] == "POST"]
    assert [call[1] for call in posts] == ["job_lifecycle"]
    assert posts[0][3]["current_stage"] == "mitigation"
    assert result["card_id"] == "card-1"


def test_shared_lifecycle_stage_change_records_transition(fake):
    fake.tables = {"job_lifecycle": [{
        "card_id": "card-1", "current_stage": "initial",
        "stage_entered_at": "2026-08-01T12:00:00",
        "created_at": "2026-07-01T12:00:00", "billed_at": None,
        "paid_at": None, "actions_synced_at": "old",
    }]}
    sup.lifecycle_upsert({
        "card_id": "card-1", "client_canon": "smith",
        "client_display": "Smith", "current_stage": "mitigation",
    })
    posts = [call for call in fake.calls if call[0] == "POST"]
    assert [call[1] for call in posts] == [
        "job_lifecycle", "job_stage_transitions"]
    assert posts[0][3]["actions_synced_at"] is None
    assert posts[1][3]["from_stage"] == "initial"
    assert posts[1][3]["to_stage"] == "mitigation"


def test_shared_lifecycle_list_and_counts(fake):
    fake.tables = {"job_lifecycle": [
        {"card_id": "1", "current_stage": "mitigation",
         "stage_entered_at": "2026-08-01"},
        {"card_id": "2", "current_stage": "closeout",
         "stage_entered_at": "2026-08-02"},
    ]}
    assert [row["card_id"] for row in sup.lifecycle_list()] == ["1", "2"]
    assert sup.lifecycle_counts_by_stage() == {"mitigation": 1, "closeout": 1}


def test_job_log_reads_shared_events_when_optional_tables_are_missing(monkeypatch):
    monkeypatch.setattr(sup, "get_job", lambda _key: {"job_id": "job-1"})
    missing = SupabaseError(404, '{"code":"PGRST205","message":"Could not find the table crm_job_log_entries"}')

    def rows(table, **_params):
        if table == "crm_job_log_entries":
            raise missing
        if table == "job_events":
            return [{"id": 1, "canon_key": "smith", "event_type": "crm_job_log_revision",
                     "event_at": "2026-08-27T10:00:00", "actor": "user@example.com",
                     "payload_json": '{"entry_id":"entry-1","after":{"entry_id":"entry-1","work_date":"2026-08-27","work_type":"Monitor","created_at":"2026-08-27T10:00:00"}}'}]
        return []

    monkeypatch.setattr(sup, "_rows", rows)
    result = sup.list_job_log_entries("smith")
    assert result[0]["entry_id"] == "entry-1"
    assert result[0]["work_type"] == "Monitor"


def test_job_log_writes_shared_event_when_optional_tables_are_missing(monkeypatch):
    monkeypatch.setattr(sup, "get_job", lambda _key: {"job_id": "job-1"})
    missing = SupabaseError(404, '{"code":"PGRST205","message":"Could not find the table crm_job_log_entries"}')
    monkeypatch.setattr(sup._sb, "rest", lambda method, table, **kwargs:
                        (_ for _ in ()).throw(missing) if table == "crm_job_log_entries" else [])
    captured = []
    monkeypatch.setattr(sup, "log_event", lambda key, event_type, payload=None:
                        captured.append((key, event_type, payload)))
    saved = sup.save_job_log_entry("smith", {
        "work_date": "2026-08-27", "work_type": "Monitor",
        "status": "completed", "note": "Dry",
    })
    assert saved["work_type"] == "Monitor"
    assert captured[0][0:2] == ("smith", "crm_job_log_revision")
    assert captured[0][2]["after"]["note"] == "Dry"


def test_find_job_by_name_falls_back_to_alias(fake):
    fake.tables = {
        "jobs": [{"canon_key": "real job", "display_name": "Real"}],
        "job_aliases": [{"alias_canon": "tony sanchez",
                         "canon_key": "real job"}],
    }
    assert sup.find_job_by_name("Tony Sanchez")["display_name"] == "Real"


def test_find_job_by_name_department_filter(fake):
    fake.tables = {"jobs": [{"canon_key": "smith, robert",
                             "display_name": "X", "department": "OC"}]}
    assert sup.find_job_by_name("Smith, Robert", department="IE") is None
    assert sup.find_job_by_name("Smith, Robert", department="OC") is not None


def test_card_display_names_uncarded_direct_job_does_not_use_an_alias(fake):
    """The live bug: 'Gabriel Ramirez' is BOTH an uncarded real job and an
    alias of the carded 'Ramirez, Gabriella'. Falling through relabels the
    row with a DIFFERENT customer's name."""
    fake.tables = {
        "jobs": [
            {"canon_key": "gabriel ramirez", "display_name": "Gabriel Ramirez"},
            {"canon_key": "ramirez, gabriella",
             "display_name": "Ramirez, Gabriella - Farmers"},
        ],
        "job_aliases": [{"alias_canon": "gabriel ramirez",
                         "canon_key": "ramirez, gabriella"}],
        "job_links": [{"canon_key": "ramirez, gabriella",
                       "link_type": "trello_card"}],
    }
    assert sup.card_display_names_for(["Gabriel Ramirez"]) == {}


def test_card_display_names_resolves_a_carded_job(fake):
    fake.tables = {
        "jobs": [{"canon_key": "smith, robert",
                  "display_name": "Smith, Robert - AAA"}],
        "job_links": [{"canon_key": "smith, robert",
                       "link_type": "trello_card"}],
    }
    assert sup.card_display_names_for(["Smith, Robert"]) == {
        "Smith, Robert": "Smith, Robert - AAA"}


def test_card_display_names_is_a_constant_number_of_requests(fake):
    """The whole point — the per-row form cost ~36s on a hosted DB."""
    fake.tables = {"jobs": [], "job_links": [], "job_aliases": []}
    sup.card_display_names_for([f"Client {i}" for i in range(100)])
    gets = [c for c in fake.calls if c[0] == "GET"]
    assert len(gets) <= 3, f"{len(gets)} requests for 100 names"


def test_folder_link_stamps_the_department(fake, monkeypatch):
    monkeypatch.setattr(sup, "department_for_path", lambda p: "IE")
    fake.tables = {"job_links": [], "jobs": []}
    sup.set_link("job1", sup.LINK_FOLDER, r"X:\IE_Public\2026 Jobs\A")
    patches = [c for c in fake.calls if c[0] == "PATCH" and c[1] == "jobs"]
    assert patches, "folder pin must stamp jobs.department"
    # ...and only onto a job that has no owner yet.
    assert patches[0][2].get("department") == "is.null"


def test_trello_link_never_stamps_a_department(fake, monkeypatch):
    """IE runs OC's recon — a board says nothing about ownership."""
    monkeypatch.setattr(sup, "department_for_path", lambda p: "IE")
    fake.tables = {"job_links": [], "jobs": []}
    sup.set_link("job1", sup.LINK_TRELLO, "card1")
    assert not [c for c in fake.calls if c[0] == "PATCH" and c[1] == "jobs"]


def test_shared_folder_migration_previews_then_converts(fake, monkeypatch):
    old = r"C:\Users\Nathan\OneDrive\Jobs\2026\Smith"
    portable = "linguar-folder://IE/2026/Smith"
    fake.tables = {"job_links": [{
        "canon_key": "smith", "link_type": sup.LINK_FOLDER,
        "link_value": old, "added_at": "2026-01-01", "added_by": "Nathan",
        "metadata_json": None,
    }]}
    monkeypatch.setattr(sup, "portable_folder_path",
                        lambda value: portable if value == old else value)
    preview = sup.migrate_folder_links_portable(apply=False)
    assert preview["convertible"] == 1
    assert preview["converted"] == 0
    assert not [c for c in fake.calls if c[0] in ("POST", "DELETE")]

    result = sup.migrate_folder_links_portable(apply=True)
    assert result["converted"] == 1
    writes = [c for c in fake.calls if c[0] in ("POST", "DELETE")]
    assert [c[0] for c in writes] == ["POST", "DELETE"]
    assert writes[0][3]["link_value"] == portable


def test_delete_job_removes_children_then_the_job(fake):
    fake.tables = {
        "jobs": [{"canon_key": "wrong job", "display_name": "Wrong Job"}],
        "job_children": [{"id": 1, "parent_canon": "wrong job"}],
    }
    res = sup.delete_job("wrong job")
    deletes = [(c[1], c[2]) for c in fake.calls if c[0] == "DELETE"]
    assert res == {"deleted": 1, "display_name": "Wrong Job",
                   "children_deleted": 1}
    assert [table for table, _params in deletes] == ["job_children", "jobs"]


def test_resolve_and_link_refuses_a_cross_franchise_match(fake, monkeypatch):
    monkeypatch.setattr(sup, "department_for_path", lambda p: "IE")
    fake.tables = {
        "jobs": [{"canon_key": "smith, robert", "display_name": "S",
                  "department": "OC"}],
        "job_links": [], "job_aliases": [],
    }
    with pytest.raises(sup.DepartmentConflict):
        sup.resolve_and_link("Smith, Robert", folder_path=r"X:\IE_Public\A",
                             create=True)
