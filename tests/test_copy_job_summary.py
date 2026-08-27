from pathlib import Path

import audit_web


ROOT = Path(__file__).resolve().parents[1]


def test_job_summary_data_is_local_and_structured(monkeypatch):
    import ems_db
    monkeypatch.setattr(ems_db, "find_job_by_name", lambda name: {
        "canon_key": "smith-jane", "display_name": "Jane Smith",
        "carrier": "Mercury", "claim_number": "ABC123",
        "address": "123 Main St", "email": "jane@example.com",
        "adjuster_name": "Alex", "adjuster_email": "alex@example.com"})
    monkeypatch.setattr(ems_db, "get_links", lambda key: [
        {"link_type": "companycam", "link_value": "https://companycam.test/job"}])
    result = audit_web.Api().job_summary_data("Jane Smith", "card123")
    assert result["ok"] is True
    assert result["claim_number"] == "ABC123"
    assert result["trello"] == "https://trello.com/c/card123"


def test_summary_preview_keeps_individual_copy_actions():
    js = (ROOT / "web_shared" / "audit_detail.js").read_text(encoding="utf-8")
    assert "openCopyJobSummaryModal" in js
    for action in ("copy-client", "copy-phone", "copy-claim", "copy-email", "copy-address",
                   "copy-path", "copy-job-summary"):
        assert f'data-action="{action}"' in js
    assert 'class="copy-action-menu"' in js
    assert "📋 Copy…" in js


def test_copy_data_uses_saved_job_info_customer_name(monkeypatch):
    import ems_db
    monkeypatch.setattr(ems_db, "find_job_by_name", lambda _name: {
        "display_name": "Wrong Audit Name",
        "metadata": {"settings": {"customer_name": "Correct Customer",
                                     "address": "42 Correct Ave"}},
        "claim_number": "JOB-123", "email": "saved@example.com",
    })
    result = audit_web.Api().job_info_copy_data("Wrong Audit Name")
    assert result["ok"] is True
    assert result["name"] == "Correct Customer"
    assert result["address"] == "42 Correct Ave"
    assert result["claim_number"] == "JOB-123"


def test_copy_name_button_loads_job_info_instead_of_row_name():
    js = (ROOT / "web_shared" / "audit_detail.js").read_text(encoding="utf-8")
    block = js[js.index('action === "copy-client"'):]
    block = block[:block.index('action === "copy-path"')]
    assert "job_info_copy_data" in block
    assert "_firstLast(row.client)" not in block
