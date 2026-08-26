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


def test_snapshot_ui_uses_one_plain_snapshot_toggle():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    js = (root / "snapshot_web_assets" / "app.js").read_text(encoding="utf-8")
    assert "data-snapshot-toggle" in js
    assert "<span>Snapshot</span>" in js
    assert "set_snapshot" in js
    assert "snapshot_return_destinations" in js
    assert "pickSnapshotDestination" in js


def test_closeout_destination_lists_only_estimating_and_service_call(monkeypatch):
    api = snapshot_web.Api()
    import trello_client as tc
    monkeypatch.setattr(tc, "get_card_lite", lambda *a, **k: {
        "id": "c1", "idBoard": "b1", "idList": "snap"})
    monkeypatch.setattr(tc, "_call", lambda *a, **k: [
        {"id": "est", "name": "Ready for Estimating"},
        {"id": "svc", "name": "Service Calls"},
        {"id": "paid", "name": "Paid"},
    ])
    result = api.snapshot_return_destinations("c1")
    assert result == {"ok": True, "destinations": [
        {"id": "est", "name": "Ready for Estimating"},
        {"id": "svc", "name": "Service Calls"},
    ]}


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
