"""Snapshot PDF posting must report Trello's real result, not button success."""
from __future__ import annotations

import persistence
import snapshot_web
import trello_client


def _pdf(tmp_path):
    path = tmp_path / "Snapshot.pdf"
    path.write_bytes(b"%PDF-1.4\n")
    return str(path)


def test_snapshot_post_returns_confirmed_attachment_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "get_trello_card_id", lambda _c: "card-1")
    monkeypatch.setattr(
        trello_client, "attach_file",
        lambda *a, **k: {"id": "att-1", "url": "https://trello/attachment"})
    monkeypatch.setattr(trello_client, "post_comment", lambda *a, **k: {"id": "comment-1"})

    result = snapshot_web.Api().post_snapshot_to_trello(
        "Example Job", _pdf(tmp_path), [])

    assert result["ok"] is True
    assert result["attached"] is True
    assert result["posted"] is True
    assert result["attachment_id"] == "att-1"
    assert result["attachment_url"] == "https://trello/attachment"


def test_snapshot_post_does_not_claim_a_failed_upload_succeeded(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "get_trello_card_id", lambda _c: "card-1")
    monkeypatch.setattr(trello_client, "attach_file", lambda *a, **k: None)
    monkeypatch.setattr(trello_client, "post_comment", lambda *a, **k: {"id": "comment-1"})

    result = snapshot_web.Api().post_snapshot_to_trello(
        "Example Job", _pdf(tmp_path), [])

    assert result["ok"] is False
    assert result["attached"] is False
    assert result["posted"] is True
    assert "did not confirm the PDF attachment" in result["error"]


def test_snapshot_posts_to_the_exact_opened_card_without_a_local_pin(
        tmp_path, monkeypatch):
    """The card chosen in Snapshot wins over fragile name-based pin lookup."""
    monkeypatch.setattr(persistence, "get_trello_card_id", lambda _c: "")
    attached_to = []
    commented_on = []
    monkeypatch.setattr(
        trello_client, "attach_file",
        lambda card_id, *a, **k: attached_to.append(card_id) or
        {"id": "att-1", "url": "https://trello/attachment"})
    monkeypatch.setattr(
        trello_client, "post_comment",
        lambda card_id, *a, **k: commented_on.append(card_id) or
        {"id": "comment-1"})

    result = snapshot_web.Api().post_snapshot_to_trello(
        "Example Job", _pdf(tmp_path), [], "opened-card")

    assert result["ok"] is True
    assert attached_to == ["opened-card"]
    assert commented_on == ["opened-card"]
