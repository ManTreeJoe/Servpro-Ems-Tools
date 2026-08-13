"""Bulk Trello sync on the Supabase backend.

It was unsupported because the per-card form is three round trips times
every open card — thousands of requests — so after the cutover the shared
index quietly stopped learning anything from Trello: no new jobs, no
carriers, no claim numbers.

What matters here is that batching didn't cost the SQLite semantics
conformance compares against.
"""
import json

import pytest

import ems_db_supabase as sup


@pytest.fixture
def sync(monkeypatch):
    """Stub the Trello walk and capture every request the sync makes."""
    calls = []
    existing = {}

    def _fake_rows(table, **params):
        if table == "jobs":
            return list(existing.values())
        return []

    def _fake_rest(method, table, body=None, **kw):
        calls.append({"method": method, "table": table,
                      "n": len(body) if isinstance(body, list) else 1,
                      "body": body, "prefer": kw.get("prefer", "")})
        return body

    monkeypatch.setattr(sup, "_rows", _fake_rows)
    monkeypatch.setattr(sup._sb, "rest", _fake_rest)
    monkeypatch.setattr(sup, "log_event", lambda *a, **k: None)

    records = {"boards": 2, "records": []}

    import trello_job_sync as walk
    monkeypatch.setattr(walk, "collect", lambda **kw: records)

    def _run(recs, prior=None):
        records["records"] = recs
        existing.clear()
        existing.update(prior or {})
        calls.clear()
        return sup.sync_from_trello(), calls

    return _run


def _rec(key, name, **kw):
    base = {"canon_key": key, "display_name": name, "claim_number": "",
            "carrier": "", "status": "active", "board": "WIP",
            "lane": "Initial", "card_id": "card-" + key}
    base.update(kw)
    return base


def test_nothing_found_writes_nothing(sync):
    res, calls = sync([])
    assert res["cards"] == 0
    assert calls == []


def test_a_new_card_becomes_a_job_an_alias_and_a_link(sync):
    res, calls = sync([_rec("smith john", "Smith, John - AAA", carrier="AAA")])
    tables = [c["table"] for c in calls]
    assert "jobs" in tables and "job_aliases" in tables and "job_links" in tables
    assert res["jobs_upserted"] == 1
    assert res["links_added"] == 1
    job = [c for c in calls if c["table"] == "jobs"][0]["body"][0]
    assert job["carrier"] == "AAA"
    assert job["display_name"] == "Smith, John - AAA"


def test_the_whole_workspace_is_a_handful_of_requests(sync):
    """The point of the exercise. Per-card writing was what made this
    unusable against a hosted database."""
    recs = [_rec(f"job{i}", f"Job {i}") for i in range(300)]
    res, calls = sync(recs)
    assert res["cards"] == 300
    # 300 cards, chunked — nowhere near 300 requests, let alone 900.
    assert len(calls) < 15, f"{len(calls)} requests for 300 cards"


def test_a_blank_from_trello_never_clears_a_stored_value(sync):
    """The partial-update rule. A card with no carrier must not erase a
    carrier somebody typed in."""
    prior = {"smith john": {"canon_key": "smith john",
                            "display_name": "Smith, John",
                            "carrier": "Mercury", "claim_number": "C-1",
                            "status": "active", "first_seen_at": "2026-01-01",
                            "department": "IE"}}
    _res, calls = sync([_rec("smith john", "Smith, John")], prior)
    job = [c for c in calls if c["table"] == "jobs"][0]["body"][0]
    assert job["carrier"] == "Mercury"
    assert job["claim_number"] == "C-1"


def test_first_seen_survives_and_last_seen_moves(sync):
    prior = {"a b": {"canon_key": "a b", "display_name": "A B",
                     "first_seen_at": "2026-01-01", "department": None}}
    _res, calls = sync([_rec("a b", "A B")], prior)
    job = [c for c in calls if c["table"] == "jobs"][0]["body"][0]
    assert job["first_seen_at"] == "2026-01-01"
    assert job["last_seen_at"] != "2026-01-01"


def test_department_is_not_wiped(sync):
    """ems_db has no department column on the Trello side; blanking it
    here would silently unassign every job on a sync."""
    prior = {"a b": {"canon_key": "a b", "display_name": "A B",
                     "department": "OC", "first_seen_at": "2026-01-01"}}
    _res, calls = sync([_rec("a b", "A B")], prior)
    job = [c for c in calls if c["table"] == "jobs"][0]["body"][0]
    assert job["department"] == "OC"


def test_a_material_rename_keeps_the_old_name_as_an_alias(sync):
    prior = {"a b": {"canon_key": "a b", "display_name": "Old Name",
                     "first_seen_at": "2026-01-01", "department": None}}
    _res, calls = sync([_rec("a b", "Totally Different Name")], prior)
    aliases = [c for c in calls if c["table"] == "job_aliases"][0]["body"]
    sources = {a["source"] for a in aliases}
    assert "rename" in sources, "the previous name must survive as an alias"


def test_upserts_use_merge_duplicates(sync):
    """Re-running a sync must update rows, not fail on the primary key."""
    _res, calls = sync([_rec("a b", "A B")])
    for c in calls:
        if c["table"] in ("jobs", "job_links"):
            assert "merge-duplicates" in c["prefer"]


def test_the_same_alias_is_not_written_twice(sync):
    recs = [_rec("a b", "A B"), _rec("a b", "A B", card_id="card-2")]
    _res, calls = sync(recs)
    aliases = [c for c in calls if c["table"] == "job_aliases"][0]["body"]
    sigs = [(a["canon_key"], a["alias_canon"]) for a in aliases]
    assert len(sigs) == len(set(sigs))


def test_several_cards_for_one_client_all_get_links(sync):
    """A client with two cards must stay reachable from both."""
    recs = [_rec("a b", "A B", card_id="card-1"),
            _rec("a b", "A B", card_id="card-2")]
    res, calls = sync(recs)
    links = [c for c in calls if c["table"] == "job_links"][0]["body"]
    assert {l["value"] for l in links} == {"card-1", "card-2"}
    assert res["jobs_upserted"] == 1     # ...but one job row


def test_metadata_carries_board_and_lane(sync):
    _res, calls = sync([_rec("a b", "A B", board="WIP", lane="Demo")])
    job = [c for c in calls if c["table"] == "jobs"][0]["body"][0]
    md = json.loads(job["metadata_json"])
    assert md == {"board": "WIP", "lane": "Demo"}
