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
