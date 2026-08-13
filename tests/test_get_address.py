"""📋 Copy address — the loss address off the pinned Trello card.

Checked against ten live pinned cards: every one keeps it under
CUSTOMER INFORMATION → ADDRESS, so a single lookup is honest here —
unlike the insured's email, which really does appear under four
different headings.
"""
import pytest

import audit_web


@pytest.fixture
def api(monkeypatch):
    a = audit_web.Api.__new__(audit_web.Api)
    import trello_client as tc

    state = {"desc": "", "pin": "card1"}

    monkeypatch.setattr(audit_web.persistence, "get_trello_card_id",
                        lambda c: state["pin"])
    monkeypatch.setattr(tc, "get_card",
                        lambda cid, **kw: {"desc": state["desc"]})
    return a, state


def test_reads_the_address_from_the_card(api):
    a, state = api
    state["desc"] = ("**CUSTOMER INFORMATION**\n"
                     "CUSTOMER NAME: Jane Doe\n"
                     "ADDRESS: 123 Main St, Riverside CA 92503\n")
    res = a.get_address("Doe, Jane")
    assert res["ok"] is True
    assert res["address"] == "123 Main St, Riverside CA 92503"


def test_accepts_street_as_a_second_spelling(api):
    a, state = api
    state["desc"] = "**CUSTOMER INFORMATION**\nSTREET: 9 Elm Ave\n"
    assert a.get_address("x")["address"] == "9 Elm Ave"


def test_no_address_on_the_card_is_reported_not_blank(api):
    """A blank copy would look like it worked and paste nothing."""
    a, state = api
    state["desc"] = "**CUSTOMER INFORMATION**\nCUSTOMER NAME: Jane Doe\n"
    res = a.get_address("Doe, Jane")
    assert res["ok"] is False and res["error"]


def test_unpinned_job_says_so(api):
    a, state = api
    state["pin"] = ""
    res = a.get_address("Doe, Jane")
    assert res["ok"] is False
    assert "pinned" in res["error"].lower()


def test_no_client_is_rejected(api):
    a, _ = api
    assert a.get_address("")["ok"] is False


def test_a_trello_failure_is_reported_not_raised(api, monkeypatch):
    """Copying an address must never take the panel down."""
    a, state = api
    import trello_client as tc

    def _boom(cid, **kw):
        raise RuntimeError("Trello 429")

    monkeypatch.setattr(tc, "get_card", _boom)
    res = a.get_address("Doe, Jane")
    assert res["ok"] is False and "429" in res["error"]


def test_whitespace_is_trimmed(api):
    a, state = api
    state["desc"] = "**CUSTOMER INFORMATION**\nADDRESS:    77 Oak Rd   \n"
    assert a.get_address("x")["address"] == "77 Oak Rd"
