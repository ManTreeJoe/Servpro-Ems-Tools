from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_shared_add_update_offers_approved_types_and_primary_action():
    js = (ROOT / "web_shared" / "audit_detail.js").read_text(encoding="utf-8")
    assert 'data-action="add-update"' in js
    assert "function openAddUpdateModal" in js
    for value in ("general", "job_log", "activity", "call", "note"):
        assert f'["{value}"' in js


def test_existing_update_shortcuts_use_shared_entry():
    js = (ROOT / "web_shared" / "audit_detail.js").read_text(encoding="utf-8")
    for value in ("job_log", "activity", "call", "general", "note"):
        assert f'openAddUpdateModal(row, ctx, "{value}")' in js
