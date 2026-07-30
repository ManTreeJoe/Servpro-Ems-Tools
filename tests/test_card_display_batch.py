"""Batched pinned-card name lookup must equal the per-row lookup.

`_shape_job` resolved the display name with its own find_job_by_name +
get_link per row — ~600 queries on a 300-row audit. Free against local
SQLite, fatal against a hosted database. `card_display_names_for` does the
same work in two queries; these tests pin the equivalence so the fast path
can't silently drift from the slow one.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ems_db


@pytest.fixture(autouse=True)
def _db(tmp_path):
    ems_db.reset_db_path(str(tmp_path / "jobs.db"))
    ems_db.invalidate_department_cache()
    yield


def _per_row(name):
    """The original implementation, kept here as the oracle."""
    j = ems_db.find_job_by_name(name)
    if (j and j.get("display_name")
            and ems_db.get_link(j.get("canon_key") or "", ems_db.LINK_TRELLO)):
        return j["display_name"]
    return ""


def _assert_matches(names):
    batch = ems_db.card_display_names_for(names)
    for n in names:
        assert batch.get(n, "") == _per_row(n), f"mismatch for {n!r}"


def test_pinned_job_returns_card_name():
    ems_db.upsert_job(display_name="Sanchez, Anthony - Farmers")
    ems_db.set_link("sanchez, anthony", ems_db.LINK_TRELLO, "card1")
    assert ems_db.card_display_names_for(["Sanchez, Anthony"]) == {
        "Sanchez, Anthony": "Sanchez, Anthony - Farmers"}
    _assert_matches(["Sanchez, Anthony"])


def test_unpinned_job_is_absent():
    """No Trello card = keep the run-doc spelling."""
    ems_db.upsert_job(display_name="Nopin, Job")
    assert ems_db.card_display_names_for(["Nopin, Job"]) == {}
    _assert_matches(["Nopin, Job"])


def test_alias_spelling_resolves():
    ems_db.upsert_job(display_name="Sanchez, Anthony - Farmers")
    ems_db.add_alias("sanchez, anthony", "tony sanchez")
    ems_db.set_link("sanchez, anthony", ems_db.LINK_TRELLO, "card1")
    got = ems_db.card_display_names_for(["tony sanchez"])
    assert got == {"tony sanchez": "Sanchez, Anthony - Farmers"}
    _assert_matches(["tony sanchez"])


def test_direct_canon_wins_over_alias():
    """A name that is both a real job and someone else's alias resolves to
    the real job — same precedence as find_job_by_name."""
    ems_db.upsert_job(display_name="Smith, Robert")
    ems_db.set_link("smith, robert", ems_db.LINK_TRELLO, "card_real")
    ems_db.upsert_job(display_name="Other Job")
    ems_db.add_alias("other job", "Smith, Robert")
    ems_db.set_link("other job", ems_db.LINK_TRELLO, "card_other")
    assert ems_db.card_display_names_for(
        ["Smith, Robert"])["Smith, Robert"] == "Smith, Robert"
    _assert_matches(["Smith, Robert"])


def test_uncarded_direct_job_does_not_fall_through_to_an_alias():
    """Caught on live data, not by the earlier tests.

    'Gabriel Ramirez' was BOTH a real job row with no Trello card AND an
    alias of the carded 'Ramirez, Gabriella - Farmers'. find_job_by_name
    stops at the direct hit and returns no display name; a naive batch
    treats "rejected for having no card" as "no match" and falls through
    to the alias — relabelling the row with a DIFFERENT customer's name.
    """
    ems_db.upsert_job(display_name="Gabriel Ramirez")          # no card
    ems_db.upsert_job(display_name="Ramirez, Gabriella - Farmers")
    ems_db.add_alias("ramirez, gabriella", "Gabriel Ramirez")
    ems_db.set_link("ramirez, gabriella", ems_db.LINK_TRELLO, "card1")

    assert ems_db.card_display_names_for(["Gabriel Ramirez"]) == {}
    _assert_matches(["Gabriel Ramirez"])


def test_unknown_names_and_blanks_are_safe():
    assert ems_db.card_display_names_for([]) == {}
    assert ems_db.card_display_names_for(["", None]) == {}
    assert ems_db.card_display_names_for(["Never Seen"]) == {}
    _assert_matches(["Never Seen"])


def test_duplicate_names_in_one_batch():
    ems_db.upsert_job(display_name="Dup, Job - AAA")
    ems_db.set_link("dup, job", ems_db.LINK_TRELLO, "card1")
    got = ems_db.card_display_names_for(["Dup, Job", "Dup, Job"])
    assert got == {"Dup, Job": "Dup, Job - AAA"}


def test_differently_spelled_inputs_both_map():
    """Two run-doc spellings of one job must BOTH appear in the map — the
    result is keyed by the caller's input, not the canon key."""
    ems_db.upsert_job(display_name="Sanchez, Anthony - Farmers")
    ems_db.add_alias("sanchez, anthony", "tony sanchez")
    ems_db.set_link("sanchez, anthony", ems_db.LINK_TRELLO, "card1")
    got = ems_db.card_display_names_for(["Sanchez, Anthony", "tony sanchez"])
    assert got == {"Sanchez, Anthony": "Sanchez, Anthony - Farmers",
                   "tony sanchez": "Sanchez, Anthony - Farmers"}


def test_realistic_batch_matches_per_row_everywhere():
    """Mixed population: pinned, unpinned, aliased, unknown."""
    names = []
    for i in range(40):
        dn = f"Client{i:02d}, Test - AAA"
        ems_db.upsert_job(display_name=dn)
        key = ems_db.canon_key(dn)
        if i % 2 == 0:
            ems_db.set_link(key, ems_db.LINK_TRELLO, f"card{i}")
        if i % 5 == 0:
            ems_db.add_alias(key, f"alt spelling {i}")
            names.append(f"alt spelling {i}")
        names.append(dn)
    names += ["Ghost Job", ""]
    _assert_matches(names)


def test_batch_issues_a_constant_number_of_queries(monkeypatch):
    """The whole point: query count must not grow with row count."""
    for i in range(50):
        dn = f"Row{i:02d}, Job"
        ems_db.upsert_job(display_name=dn)
        ems_db.set_link(ems_db.canon_key(dn), ems_db.LINK_TRELLO, f"c{i}")
    names = [f"Row{i:02d}, Job" for i in range(50)]

    # Patch the SQLite backend directly, not the ems_db façade: the façade
    # delegates via module __getattr__, so an attribute set on it would
    # shadow the name without the backend's own internals ever seeing it.
    import ems_db_sqlite

    real_connect = ems_db_sqlite._connect
    calls = {"n": 0}

    def counting_connect(*a, **k):
        calls["n"] += 1
        return real_connect(*a, **k)

    monkeypatch.setattr(ems_db_sqlite, "_connect", counting_connect)
    ems_db.card_display_names_for(names)
    assert calls["n"] == 1, (
        f"expected one connection for 50 rows, got {calls['n']}")
