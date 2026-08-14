"""Audit search has to reach Trello, not just what we've already filed.

The three original sources — today's run-doc, pinned cards, year folders
— all assume the job is already somewhere we keep things. Work is STARTED
on Trello today (the New Loss button isn't in use yet), so a brand-new
job has a card and nothing else: not on the run-doc, not pinned, no
folder. It was invisible to the search that exists to find it.

The ranking question that matters: a job with a folder AND a card must
still audit the FOLDER. Grouping keeps the folder path regardless of
which source won, so scoring a card highly changes the order between
different jobs and never which folder gets audited — the tests below
pin that.
"""
import pytest

import audit_web


@pytest.fixture
def api(monkeypatch):
    a = audit_web.Api.__new__(audit_web.Api)
    hits = []

    monkeypatch.setattr(audit_web.Api, "search_trello",
                        lambda self, q, boards=None: list(hits))
    # Silence the three local sources so each test controls its own input.
    monkeypatch.setattr(audit_web, "_find_run_doc_for_date", lambda d: "")
    monkeypatch.setattr(audit_web.persistence, "_load", lambda: {})
    monkeypatch.setattr(audit_web.Api, "list_folder_candidates",
                        lambda self, t, s="": {"candidates": []})
    return a, hits


def _card(name, board="WORK IN PROGRESS", lane=""):
    return {"card_id": "c1", "name": name, "board": board, "lane": lane}


def test_a_job_that_exists_only_on_trello_is_found(api):
    """The whole point: no run-doc entry, no pin, no folder."""
    a, hits = api
    hits.append(_card("Knudsen, Seth"))
    res = a.list_audit_candidates("knudsen")
    assert res["ok"] is True
    names = [c["name"] for c in res["candidates"]]
    assert "Knudsen, Seth" in names


def test_the_trello_hit_says_where_it_came_from(api):
    a, hits = api
    hits.append(_card("Knudsen, Seth", board="WORK IN PROGRESS", lane="Demo"))
    c = a.list_audit_candidates("knudsen")["candidates"][0]
    assert "trello" in (c.get("sources") or [c.get("source")])
    assert "WORK IN PROGRESS" in c["detail"]
    assert "Demo" in c["detail"]


def test_a_trello_only_hit_carries_no_folder_path(api):
    """It has no folder here — saying otherwise would send an import to a
    path that doesn't exist."""
    a, hits = api
    hits.append(_card("Knudsen, Seth"))
    assert a.list_audit_candidates("knudsen")["candidates"][0]["path"] == ""


def test_a_folder_hit_keeps_its_path_when_a_card_matches_too(api, monkeypatch):
    """The ranking risk, pinned down: a highly-scored card must not cost
    the job its folder."""
    a, hits = api
    hits.append(_card("Knudsen, Seth"))
    monkeypatch.setattr(
        audit_web.Api, "list_folder_candidates",
        lambda self, t, s="": {"candidates": [
            {"name": "Knudsen, Seth", "path": r"X:\2026 Jobs\Knudsen, Seth",
             "score": 40, "year_folder": "2026 Jobs"}]})
    cands = a.list_audit_candidates("knudsen")["candidates"]
    assert len(cands) == 1, "one job, not two rows"
    assert cands[0]["path"] == r"X:\2026 Jobs\Knudsen, Seth"


def test_an_exact_card_beats_a_loose_folder_match(api, monkeypatch):
    """Work starts on the board, so an exact card name should not sit
    under something that merely shares a token."""
    a, hits = api
    hits.append(_card("Knudsen, Seth"))
    monkeypatch.setattr(
        audit_web.Api, "list_folder_candidates",
        lambda self, t, s="": {"candidates": [
            {"name": "Knudsen Property Mgmt", "path": r"X:\other",
             "score": 8, "year_folder": "2026 Jobs"}]})
    cands = a.list_audit_candidates("Knudsen, Seth")["candidates"]
    assert cands[0]["name"] == "Knudsen, Seth"


def test_a_dead_trello_call_never_breaks_the_search(api, monkeypatch):
    """The local sources still answer when Trello is down or rate-limited."""
    monkeypatch.setattr(
        audit_web.Api, "search_trello",
        lambda self, q, boards=None: (_ for _ in ()).throw(RuntimeError("429")))
    monkeypatch.setattr(
        audit_web.Api, "list_folder_candidates",
        lambda self, t, s="": {"candidates": [
            {"name": "Knudsen, Seth", "path": r"X:\k", "score": 40}]})
    a, _ = api
    res = a.list_audit_candidates("knudsen")
    assert res["ok"] is True
    assert res["candidates"][0]["name"] == "Knudsen, Seth"


def test_unrelated_cards_are_not_dragged_in(api):
    """Trello's search is loose; an unrelated name must not become a
    candidate to audit."""
    a, hits = api
    hits.append(_card("Completely Different Person"))
    assert a.list_audit_candidates("knudsen")["candidates"] == []


def test_a_nameless_card_is_skipped(api):
    a, hits = api
    hits.extend([_card(""), _card("   ")])
    assert a.list_audit_candidates("knudsen")["candidates"] == []


def test_the_search_is_capped(api):
    """Trello can return a lot for a common surname."""
    a, hits = api
    hits.extend(_card(f"Smith, Person {i}") for i in range(40))
    assert len(a.list_audit_candidates("smith")["candidates"]) <= 12
