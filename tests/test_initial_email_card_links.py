"""The initial email fills its links from the card's LINKS section.

The office was pasting the DocuSketch section in by hand on every job
that had one, while the link sat on the Trello card the whole time. Of 25
live pinned cards, 21 carry a DocuSketch link and all 25 carry an initial
video link — so this is the common case, not an edge one.
"""
import pytest

import audit_web


DESC = """**CUSTOMER INFORMATION**
CUSTOMER NAME: Jane Doe

**LINKS**
INITIAL VIDEO LINK: https://companycam.com/v/abc
POST VIDEO LINK: https://companycam.com/v/zzz
DOCUSKETCH LINK: https://app.docusketch.com/player/q7LhKw3S
"""


@pytest.fixture
def draft(monkeypatch):
    """Call initial_email_draft with the card + comments stubbed."""
    import trello_client as tc
    import initial_notes_parser as inp

    state = {"desc": DESC, "notes": {}}

    a = audit_web.Api.__new__(audit_web.Api)
    monkeypatch.setattr(audit_web.persistence, "get_trello_card_id",
                        lambda c: "card1")
    monkeypatch.setattr(tc, "get_all_comments", lambda cid: [])
    monkeypatch.setattr(tc, "get_card", lambda cid, **kw: {"desc": state["desc"]})
    monkeypatch.setattr(inp, "best_initial_block", lambda blocks: state["notes"])
    monkeypatch.setattr(a, "_supervisor_for", lambda c, f: "Mark Escobar")

    def _run():
        return a.initial_email_draft("Doe, Jane")

    return _run, state


def test_docusketch_link_comes_off_the_card(draft):
    run, _ = draft
    res = run()
    assert res["ok"] is True
    assert res["docusketch_url"] == "https://app.docusketch.com/player/q7LhKw3S"
    assert "browser to view the DocuSketch:" in res["text"]
    assert "https://app.docusketch.com/player/q7LhKw3S" in res["text"]


def test_initial_video_link_becomes_the_walkthrough(draft):
    run, _ = draft
    assert "https://companycam.com/v/abc" in run()["text"]


def test_the_post_video_link_is_not_used_as_the_walkthrough(draft):
    """POST VIDEO LINK is a different visit — sending it as the initial
    walkthrough shows an adjuster the wrong footage."""
    run, _ = draft
    assert "https://companycam.com/v/zzz" not in run()["text"]


def test_notes_beat_the_card_for_the_walkthrough(draft):
    """A tech who wrote the link into THIS visit's notes is more specific
    than a card field that may predate it."""
    run, state = draft
    state["notes"] = {"Video Taken": "https://companycam.com/v/from-notes"}
    txt = run()["text"]
    assert "https://companycam.com/v/from-notes" in txt
    assert "https://companycam.com/v/abc" not in txt


def test_a_card_with_no_links_section_still_drafts(draft):
    run, state = draft
    state["desc"] = "**CUSTOMER INFORMATION**\nCUSTOMER NAME: Jane Doe\n"
    res = run()
    assert res["ok"] is True
    assert res["docusketch_url"] == ""
    assert "DocuSketch" not in res["text"]


def test_an_unreadable_card_does_not_break_the_draft(draft, monkeypatch):
    """Links are a convenience; losing them must not cost the email."""
    run, _ = draft
    import trello_client as tc

    def _boom(cid, **kw):
        raise RuntimeError("Trello 429")

    monkeypatch.setattr(tc, "get_card", _boom)
    res = run()
    assert res["ok"] is True
    assert res["docusketch_url"] == ""


def test_the_draft_endpoint_actually_returns(draft):
    """Regression for 49dc7ef: it swapped parse_initial_inspection_notes
    for best_initial_block and left `bool(blocks)` in the return, so
    every call raised NameError and ✉ Initial email did nothing. No test
    called this endpoint, so nothing caught it."""
    run, _ = draft
    res = run()
    assert res["ok"] is True
    assert res["text"]


def test_found_notes_reflects_whether_notes_were_parsed(draft):
    run, state = draft
    state["notes"] = {}
    assert run()["found_notes"] is False
    state["notes"] = {"Time": "11:00AM"}
    assert run()["found_notes"] is True
