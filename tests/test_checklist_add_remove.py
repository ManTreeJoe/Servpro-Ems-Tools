"""Adding and removing Trello checklist items from the panel.

A job needing a step the card template didn't cover meant opening Trello
to add it — the round trip the panel exists to avoid. Delete already
existed (CLOSE OUT's right-click); add did not.
"""
import pytest

import trello_client as tc


@pytest.fixture
def calls(monkeypatch):
    """Record _call instead of hitting Trello."""
    seen = []

    def _fake(path, *, method="GET", params=None, data=None, **kw):
        seen.append({"path": path, "method": method, "data": data or {}})
        return {"id": "item9", "name": (data or {}).get("name", ""),
                "state": "incomplete"}

    monkeypatch.setattr(tc, "_call", _fake)
    return seen


def test_add_posts_to_the_checklist(calls):
    item = tc.add_check_item("cl1", "Order dumpster")
    assert item["id"] == "item9"
    assert calls[0]["path"] == "/checklists/cl1/checkItems"
    assert calls[0]["method"] == "POST"
    assert calls[0]["data"]["name"] == "Order dumpster"


def test_add_defaults_to_the_bottom():
    """New steps belong at the end; inserting at the top would reorder a
    checklist other people read top-down."""
    import inspect
    assert inspect.signature(tc.add_check_item).parameters["pos"].default \
        == "bottom"


def test_add_trims_whitespace(calls):
    tc.add_check_item("cl1", "  Padded  ")
    assert calls[0]["data"]["name"] == "Padded"


@pytest.mark.parametrize("name", ["", "   ", None])
def test_add_refuses_an_empty_name(calls, name):
    """An empty item is invisible on the card — don't create it."""
    assert tc.add_check_item("cl1", name) is None
    assert calls == []


def test_add_refuses_without_a_checklist(calls):
    assert tc.add_check_item("", "Something") is None
    assert calls == []


def test_add_returns_none_on_failure(monkeypatch):
    """Callers render the returned item, so a failure must not look like
    success with a blank row."""
    def _boom(*a, **kw):
        raise RuntimeError("Trello 429")

    monkeypatch.setattr(tc, "_call", _boom)
    assert tc.add_check_item("cl1", "Order dumpster") is None


# ── the panel API ─────────────────────────────────────────────────────

@pytest.fixture
def api(monkeypatch):
    import audit_web
    a = audit_web.Api.__new__(audit_web.Api)
    return a


def test_api_add_requires_both_arguments(api):
    assert api.add_checklist_item("", "x")["ok"] is False
    assert api.add_checklist_item("cl1", "")["ok"] is False


def test_api_add_returns_the_new_item(api, monkeypatch):
    monkeypatch.setattr(tc, "add_check_item",
                        lambda cid, nm, **kw: {"id": "i1", "name": nm,
                                               "state": "incomplete"})
    res = api.add_checklist_item("cl1", "Order dumpster")
    assert res["ok"] is True
    assert res["item"] == {"id": "i1", "name": "Order dumpster",
                           "complete": False}


def test_api_add_reports_a_rejection(api, monkeypatch):
    monkeypatch.setattr(tc, "add_check_item", lambda cid, nm, **kw: None)
    res = api.add_checklist_item("cl1", "Order dumpster")
    assert res["ok"] is False and res["error"]


def test_invalidate_clears_both_caches(api):
    """Add/remove must be visible at once; the checklist payload is
    cached 45s and the enrichment 60s, so a reload without this redraws
    the old list and reads as a failed change."""
    api._all_cl_cache = {"card1": (0, {"x": 1})}
    api._card_enrich_cache = {"card1": (0, {"y": 2})}
    assert api.invalidate_checklist_cache()["ok"] is True
    assert api._all_cl_cache == {}
    assert api._card_enrich_cache == {}


def test_invalidate_is_safe_with_no_caches_yet(api):
    assert api.invalidate_checklist_cache()["ok"] is True
