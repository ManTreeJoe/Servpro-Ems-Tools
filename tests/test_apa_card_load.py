"""APA's card lookup must not drag the whole card across.

`suggest_apa_routing` reads four fields — name, desc, idBoard, idList —
but called `get_card`, which returns everything in one request:
`actions_limit` defaults to 50, plus every checklist, attachment and
member. On these boards the comments are pasted email threads, so that is
a lot of bytes for a description.

Measured on 12 live cards: 754ms / 76.8KB the old way against 253ms /
1.6KB with a plain field fetch — 48x the payload for the same four
fields. The remaining ~230ms is the round trip to Trello, so the fetch is
now close to the floor for a single card.
"""
import inspect

import pytest

import apa_web
import trello_client as tc


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def _fake(path, *, method="GET", params=None, data=None, **kw):
        seen.append({"path": path, "params": dict(params or {})})
        return {"id": "c1", "name": "Doe, Jane", "idBoard": "b1",
                "idList": "l1",
                "desc": ("**CUSTOMER INFORMATION**\nCUSTOMER NAME: Jane Doe\n"
                         "**INSURANCE INFORMATION**\n"
                         "INSURANCE COMPANY: ACE\nCLAIM NUMBER: 12345\n")}

    monkeypatch.setattr(tc, "_call", _fake)
    return seen


# ── the lean fetch ───────────────────────────────────────────────────
def test_get_card_lite_asks_for_fields_only(calls):
    tc.get_card_lite("c1")
    p = calls[0]["params"]
    assert p["fields"] == "name,desc,idBoard,idList"
    for heavy in ("checklists", "attachments", "members", "actions",
                  "actions_limit"):
        assert heavy not in p, f"{heavy} is exactly what made this slow"


def test_get_card_lite_returns_what_the_caller_needs(calls):
    card = tc.get_card_lite("c1")
    assert card["name"] and card["desc"] and card["idBoard"] and card["idList"]


def test_get_card_lite_refuses_a_blank_id(calls):
    assert tc.get_card_lite("") is None
    assert calls == []


def test_get_card_still_returns_the_whole_card(calls):
    """The lean call is an addition, not a replacement — rendering a card
    still needs its contents."""
    tc.get_card("c1")
    p = calls[0]["params"]
    assert p["checklists"] == "all" and p["attachments"] == "true"


# ── APA uses it ──────────────────────────────────────────────────────
def test_apa_routing_does_not_fetch_the_heavy_payload(calls):
    api = apa_web.Api.__new__(apa_web.Api)
    api.suggest_apa_routing("c1", lane_hint="Initial Uploads")
    card_calls = [c for c in calls if c["path"] == "/cards/c1"]
    assert card_calls, "it still has to read the card"
    for c in card_calls:
        assert "actions_limit" not in c["params"], (
            "APA is pulling 50 activity actions to read a description")
        assert "checklists" not in c["params"]


def test_apa_routing_still_parses_the_desc(calls):
    api = apa_web.Api.__new__(apa_web.Api)
    res = api.suggest_apa_routing("c1", lane_hint="Initial Uploads")
    assert res["ok"] is True
    assert res["claim"] == "12345"
    assert res["name"] == "Jane Doe", "insured comes from CUSTOMER INFORMATION"


def test_apa_folds_ace_to_aaa(calls):
    """Same call the new-loss intake makes — the carrier goes straight
    into the APA title, so one carrier must not appear under two names."""
    api = apa_web.Api.__new__(apa_web.Api)
    res = api.suggest_apa_routing("c1", lane_hint="Initial Uploads")
    assert res["carrier"] == "AAA"
    assert res["base_text"] == "Jane Doe - AAA"


def test_an_unknown_carrier_is_left_alone(calls, monkeypatch):
    def _fake(path, *, method="GET", params=None, data=None, **kw):
        return {"id": "c1", "name": "Doe, Jane", "idBoard": "b1", "idList": "l1",
                "desc": ("**INSURANCE INFORMATION**\n"
                         "INSURANCE COMPANY: Bilbrey Mutual\n")}

    monkeypatch.setattr(tc, "_call", _fake)
    api = apa_web.Api.__new__(apa_web.Api)
    assert api.suggest_apa_routing("c1")["carrier"] == "Bilbrey Mutual"


def test_a_card_fetch_failure_still_returns_a_suggestion(monkeypatch):
    """The lane-driven routing is computed before the network call for
    exactly this reason — a dead fetch must not strand the user."""
    def _boom(*a, **k):
        raise RuntimeError("rate limited")

    monkeypatch.setattr(tc, "_call", _boom)
    api = apa_web.Api.__new__(apa_web.Api)
    res = api.suggest_apa_routing("c1", lane_hint="Initial Uploads",
                                  name_hint="Doe, Jane")
    assert res["ok"] is True
    assert res["name"] == "Doe, Jane"


def test_apa_asks_for_the_card_once(calls):
    """A second fetch would put the whole saving back."""
    api = apa_web.Api.__new__(apa_web.Api)
    api.suggest_apa_routing("c1", lane_hint="Initial Uploads")
    assert len([c for c in calls if c["path"] == "/cards/c1"]) == 1


def test_the_heavy_fetch_is_not_reintroduced():
    """Guards the regression directly: the reviewer of a future change
    sees why this call is deliberately the lean one."""
    src = inspect.getsource(apa_web.Api.suggest_apa_routing)
    assert "get_card_lite" in src
    assert "tc.get_card(" not in src
