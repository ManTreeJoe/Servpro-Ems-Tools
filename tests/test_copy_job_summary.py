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
    for action in ("copy-client", "copy-claim", "copy-email", "copy-address",
                   "copy-path", "copy-job-summary"):
        assert f'data-action="{action}"' in js
