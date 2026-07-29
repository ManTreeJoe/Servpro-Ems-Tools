"""Request-items: compose message, post to Trello, track for follow-up."""
import persistence
import trello_client
import request_items as ri


def test_compose_message():
    m = ri.compose("Mims, Stewart", ["atp", "scope", "docusketch"],
                   other="", handle="fernandob")
    assert m["trello"].startswith("@fernandob 📨 For **Mims, Stewart**")
    assert "ATP, Scope, Docusketch scan" in m["trello"]
    assert m["teams"] == "Hey — for Mims, Stewart, can you get me: ATP, Scope, Docusketch scan? Thanks!"
    # Handle gets an @ if missing; empty items → generic phrase.
    assert ri.compose("J", [], handle="@x")["trello"].startswith("@x 📨")
    assert "outstanding items" in ri.compose("J", [])["trello"]
    # 'Other' free text appended.
    assert "photos of the roof" in ri.compose(
        "J", ["cos"], other="photos of the roof")["teams"]


def test_send_posts_tracks_and_remembers_handle(monkeypatch):
    posted = {}
    monkeypatch.setattr(trello_client, "post_comment",
                        lambda cid, txt: posted.update(card=cid, text=txt))
    state = {}
    monkeypatch.setattr(persistence, "_load", lambda: state)
    monkeypatch.setattr(persistence, "_save", lambda s: state.update(s))

    res = ri.send("cardA", "mims stewart", ["atp", "cos"],
                  other="", handle="fernandob", client="Mims, Stewart")
    assert res["ok"] and res["posted"] is True
    assert posted["card"] == "cardA" and "ATP, COS" in posted["text"]
    assert res["teams"].startswith("Hey — for Mims, Stewart")
    # Tracked.
    req = ri.get_request("mims stewart")
    assert req["items"] == ["atp", "cos"] and req["requested_at"]
    # Handle remembered for the dropdown.
    assert "fernandob" in ri.recent_handles()


def test_send_survives_trello_failure(monkeypatch):
    def _boom(cid, txt):
        raise RuntimeError("trello down")
    monkeypatch.setattr(trello_client, "post_comment", _boom)
    state = {}
    monkeypatch.setattr(persistence, "_load", lambda: state)
    monkeypatch.setattr(persistence, "_save", lambda s: state.update(s))
    res = ri.send("cardA", "x", ["scope"], handle="h")
    assert res["ok"] and res["posted"] is False       # recorded anyway
    assert ri.get_request("x")["posted"] is False


def test_clear_request(monkeypatch):
    state = {"item_requests": {"x": {"items": ["scope"]}}}
    monkeypatch.setattr(persistence, "_load", lambda: state)
    monkeypatch.setattr(persistence, "_save", lambda s: state.update(s))
    ri.clear_request("x")
    assert ri.get_request("x") is None
