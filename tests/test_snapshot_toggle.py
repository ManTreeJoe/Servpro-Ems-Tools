from __future__ import annotations

import snapshot_web


def test_snapshot_toggle_moves_on_and_remembers_previous_lane(monkeypatch):
    api = snapshot_web.Api()
    import trello_client as tc
    import persistence
    saved = {}
    monkeypatch.setattr(tc, "get_card_lite", lambda *a, **k: {
        "id": "c1", "idBoard": "b1", "idList": "working"})
    monkeypatch.setattr(tc, "get_list", lambda list_id: {
        "id": list_id, "idBoard": "b1",
        "name": "SNAPSHOT" if list_id == "snap" else "Working"})
    monkeypatch.setattr(tc, "move_card", lambda card, lane: saved.update(moved=lane) or True)
    monkeypatch.setattr(persistence, "get", lambda key: {})
    monkeypatch.setattr(persistence, "set_value", lambda key, value: saved.update(previous=value))
    result = api.set_snapshot("c1", True, "snap")
    assert result["ok"] and result["snapshot"] is True
    assert saved["moved"] == "snap"
    assert saved["previous"]["c1"] == "working"


def test_snapshot_ui_uses_explicit_post_snapshot_transition():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    js = (root / "snapshot_web_assets" / "app.js").read_text(encoding="utf-8")
    queue = js[js.index("function renderCandidateQueue"):
               js.index("function pickSnapshotDestination")]
    assert "data-snapshot-toggle" not in queue
    assert "Close-out queue" in queue
    assert "snapshot_return_destinations" in js
    assert "pickSnapshotDestination" in js
    assert "move_snapshot_to_lane" in js


def test_snapshot_queue_control_explains_itself_and_does_not_gate_opening():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    js = (root / "snapshot_web_assets" / "app.js").read_text(encoding="utf-8")
    queue = js[js.index("function renderCandidateQueue"):
               js.index("function pickSnapshotDestination")]
    assert "Close-out queue" in queue
    assert '>Open</button>' in queue
    assert '${r.snapshot ? "" : "disabled"}' not in queue
    assert "state.cardId" in js[js.index("async function postToTrello"):]


def test_snapshot_form_has_visible_move_to_lane_action():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    html = (root / "snapshot_web_assets" / "index.html").read_text(encoding="utf-8")
    assert 'id="move-snapshot-btn"' in html
    assert "Move card to" in html


def test_closeout_destination_lists_all_other_non_snapshot_lanes(monkeypatch):
    api = snapshot_web.Api()
    import trello_client as tc
    monkeypatch.setattr(tc, "get_card_lite", lambda *a, **k: {
        "id": "c1", "idBoard": "b1", "idList": "snap"})
    monkeypatch.setattr(tc, "_call", lambda *a, **k: [
        {"id": "est", "name": "Ready for Estimating"},
        {"id": "svc", "name": "Service Calls"},
        {"id": "review", "name": "Estimate Review"},
        {"id": "snap", "name": "Snapshot"},
        {"id": "paid", "name": "Paid"},
    ])
    result = api.snapshot_return_destinations("c1")
    assert result == {"ok": True, "destinations": [
        {"id": "est", "name": "Ready for Estimating"},
        {"id": "svc", "name": "Service Calls"},
        {"id": "review", "name": "Estimate Review"},
        {"id": "paid", "name": "Paid"},
    ]}


def test_explicit_snapshot_transition_moves_to_selected_lane(monkeypatch):
    api = snapshot_web.Api()
    import trello_client as tc
    import persistence
    moved = {}
    monkeypatch.setattr(tc, "get_card_lite", lambda *a, **k: {
        "id": "c1", "idBoard": "b1", "idList": "snap"})
    monkeypatch.setattr(tc, "get_list", lambda list_id: {
        "id": list_id, "idBoard": "b1",
        "name": "Snapshot" if list_id == "snap" else "Estimate Review"})
    monkeypatch.setattr(tc, "move_card",
                        lambda card, lane: moved.update(card=card, lane=lane) or True)
    monkeypatch.setattr(persistence, "get", lambda _key: {"c1": "old"})
    monkeypatch.setattr(persistence, "set_value", lambda *_a, **_k: None)

    result = api.move_snapshot_to_lane("c1", "review")

    assert result == {"ok": True, "lane": "Estimate Review",
                      "list_id": "review"}
    assert moved == {"card": "c1", "lane": "review"}


def test_closeout_moves_to_the_explicit_destination(monkeypatch):
    api = snapshot_web.Api()
    import trello_client as tc
    import persistence
    moved = {}
    monkeypatch.setattr(tc, "get_card_lite", lambda *a, **k: {
        "id": "c1", "idBoard": "b1", "idList": "snap"})
    monkeypatch.setattr(tc, "get_list", lambda list_id: {
        "id": list_id, "idBoard": "b1", "name": "Service Calls"})
    monkeypatch.setattr(tc, "move_card", lambda card, lane: moved.update(lane=lane) or True)
    monkeypatch.setattr(persistence, "get", lambda key: {"c1": "old"})
    monkeypatch.setattr(persistence, "set_value", lambda *a, **k: None)
    result = api.set_snapshot("c1", False, "snap", "service")
    assert result["ok"] and result["lane"] == "Service Calls"
    assert moved["lane"] == "service"
