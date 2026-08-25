from __future__ import annotations

import snapshot_revisions as sr


def test_snapshot_revisions_are_append_only(monkeypatch):
    events = []
    monkeypatch.setattr(sr.ems_db, "find_job_by_name",
                        lambda client: {"canon_key": "smith-jane"})
    monkeypatch.setattr(sr.ems_db, "list_events",
                        lambda key, event_type, limit=100: list(reversed(events)))
    monkeypatch.setattr(sr.ems_db, "log_event",
                        lambda key, event_type, payload=None: events.append(
                            {"event_at": payload["created_at"], "payload": payload}))
    first = sr.save_revision("Jane Smith", {"insured": "Jane Smith", "logs": []})
    second = sr.save_revision("Jane Smith", {"insured": "Jane Smith", "cause": "Pipe"})
    assert first["revision"] == 1
    assert second["revision"] == 2
    assert len(events) == 2
    assert events[0]["payload"]["snapshot_id"] != events[1]["payload"]["snapshot_id"]


def test_rendered_text_keeps_structured_rows_searchable():
    text = sr.render_text({"insured": "Jane Smith", "carrier": "Mercury",
                           "logs": [{"date": "8/25", "activity": "Demo",
                                     "techs": "ME"}]})
    assert "Insured: Jane Smith" in text
    assert "Log: 8/25 | Demo | ME" in text


def test_snapshot_ui_exposes_history_and_removes_duplicate_mark_step():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    html = (root / "snapshot_web_assets" / "index.html").read_text(encoding="utf-8")
    js = (root / "snapshot_web_assets" / "app.js").read_text(encoding="utf-8")
    assert 'id="snapshot-history-btn"' in html
    assert "openSnapshotHistory" in js
    assert 'id="mark-drafted-btn"' not in html
