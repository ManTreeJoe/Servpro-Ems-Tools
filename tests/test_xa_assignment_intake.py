from email.message import EmailMessage
from pathlib import Path

import xa_assignment_intake as intake


def _message(*, xa="XA-100", claim="CL-200", address="10 Test Way"):
    msg = EmailMessage()
    msg["From"] = "assignments@xactware.com"
    msg["To"] = "intake@example.test"
    msg["Subject"] = "New assignment"
    msg["Message-ID"] = f"<{xa}@example.test>"
    msg.set_content(
        "Insured Name: Test Customer\n"
        f"Location of Property: {address}\n"
        f"Claim Number: {claim}\n"
        f"XA ID: {xa}\n"
        "Date of Loss: 9/20/2026\n"
        "Assignment Received by XactAnalysis: 9/21/2026 8:01 AM\n"
        "Loss Details: Synthetic fixture only\n")
    msg.add_attachment(b"fixture", maintype="application", subtype="pdf",
                       filename="assignment.pdf")
    return msg


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(intake, "_ROOT", tmp_path)
    monkeypatch.setattr(intake, "_MESSAGES", tmp_path / "messages")
    monkeypatch.setattr(intake, "_INDEX", tmp_path / "drafts.json")


def test_eml_becomes_review_draft_and_preserves_original(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path / "store")
    source = tmp_path / "assignment.eml"
    source.write_bytes(_message().as_bytes())

    result = intake.ingest_eml(source)

    assert result["ok"] and result["created"]
    draft = result["draft"]
    assert draft["status"] == "needs_review"
    assert draft["fields"]["insured_name"] == "Test Customer"
    assert draft["fields"]["date_received"] == "9/21/2026"
    assert draft["source"]["attachment_names"] == ["assignment.pdf"]
    assert (intake._MESSAGES / f'{draft["id"]}.eml').read_bytes() == source.read_bytes()
    assert "stored_message" not in draft["source"]


def test_same_message_is_idempotent(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path / "store")
    source = tmp_path / "assignment.eml"
    source.write_bytes(_message().as_bytes())
    first = intake.ingest_eml(source)
    second = intake.ingest_eml(source)
    assert first["draft"]["id"] == second["draft"]["id"]
    assert not second["created"]
    assert len(intake.list_drafts()) == 1


def test_related_assignment_is_warning_not_automatic_merge(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path / "store")
    one = tmp_path / "one.eml"
    two = tmp_path / "two.eml"
    one.write_bytes(_message(xa="XA-1").as_bytes())
    two.write_bytes(_message(xa="XA-2").as_bytes())
    intake.ingest_eml(one)
    result = intake.ingest_eml(two)
    assert result["draft"]["match"]["candidates"][0]["relation"] == "same_claim_and_property"
    assert result["draft"]["status"] == "needs_review"


def test_approval_records_result_and_removes_from_pending(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path / "store")
    source = tmp_path / "assignment.eml"
    source.write_bytes(_message().as_bytes())
    draft_id = intake.ingest_eml(source)["draft"]["id"]
    result = intake.mark_approved(draft_id, card_id="card-1", card_url="https://example.test/card")
    assert result["ok"]
    assert result["draft"]["status"] == "approved"
    assert intake.list_drafts() == []
    assert len(intake.list_drafts(include_completed=True)) == 1


def test_xa_html_style_separate_label_and_value_lines(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path / "store")
    msg = EmailMessage()
    msg["From"] = "assignments@xactware.com"
    msg["To"] = "intake@example.test"
    msg["Subject"] = "New assignment"
    msg.set_content(
        "Insured Name\nTest Customer\n"
        "Location of Property\n10 Test Way\n"
        "Claim Number\nCL-200\n"
        "XA ID\nXA-100\n"
        "Date of Loss\n9/20/2026\n"
        "Assignment Received by XactAnalysis\n9/21/2026 8:01 AM\n")
    source = tmp_path / "table-layout.eml"
    source.write_bytes(msg.as_bytes())
    fields = intake.ingest_eml(source)["draft"]["fields"]
    assert fields["insured_name"] == "Test Customer"
    assert fields["claim_number"] == "CL-200"
    assert fields["date_received"] == "9/21/2026"
