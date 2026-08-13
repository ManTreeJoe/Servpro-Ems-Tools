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
    for name in ("export_db", "import_db",
                 "backfill_departments", "lifecycle_list"):
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
