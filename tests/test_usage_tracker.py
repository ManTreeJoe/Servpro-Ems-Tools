"""Local usage tracker — event log + aggregation."""
import usage_tracker as ut


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(ut, "DB_PATH", str(tmp_path / "usage.db"))
    monkeypatch.setattr(ut, "_INITED", False, raising=False)


def test_record_and_report(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    ut.record([
        {"tool": "audit", "action": "view", "label": ""},
        {"tool": "audit", "action": "click", "label": "Import SP"},
        {"tool": "audit", "action": "click", "label": "Import SP"},
        {"tool": "audit", "action": "click", "label": "Re-audit"},
        {"tool": "snapshot", "action": "click", "label": "Generate"},
    ])
    rep = ut.report(days=30)
    assert rep["ok"] and rep["total"] == 5
    tools = {t["tool"]: t["count"] for t in rep["tools"]}
    assert tools == {"audit": 4, "snapshot": 1}
    # Top button is the twice-clicked "Import SP".
    top = rep["buttons"][0]
    assert top["label"] == "Import SP" and top["count"] == 2
    # 'view' has no label → excluded from the button breakdown.
    assert all(b["label"] for b in rep["buttons"])


def test_bad_events_ignored(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    res = ut.record([{"action": "click"}, {"tool": "x"}, "not a dict", {}])
    assert res["ok"] and res["written"] == 0     # all missing tool+action
    assert ut.record([]) == {"ok": True, "written": 0}


def test_label_capped_and_cleaned(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    ut.record([{"tool": "audit", "action": "click",
                "label": "  📥   Import   from   SharePoint " + "x" * 200}])
    rep = ut.report()
    assert len(rep["buttons"][0]["label"]) <= 80    # capped
    assert "  " not in rep["buttons"][0]["label"]    # whitespace collapsed


def test_reset(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    ut.record_event("audit", "click", "Foo")
    assert ut.report()["total"] == 1
    ut.reset()
    assert ut.report()["total"] == 0
