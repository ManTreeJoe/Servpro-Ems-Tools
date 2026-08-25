"""The close-out queue stays synchronized with Trello's Snapshot lane."""

from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_snapshot_queue_auto_refreshes_from_trello():
    js = (ROOT / "snapshot_web_assets" / "app.js").read_text(encoding="utf-8")

    assert "setInterval(() => syncSnapshotQueue(), 60_000)" in js
    assert 'window.addEventListener("focus", () => syncSnapshotQueue())' in js
    assert "state.candidates = await pywebview.api.candidate_jobs()" in js


def test_snapshot_queue_explains_shared_trello_workflow():
    html = (ROOT / "snapshot_web_assets" / "index.html").read_text(encoding="utf-8")

    assert "Live Trello Snapshot lane" in html
    assert "Anyone can move a card into Snapshot in Trello" in html
    assert 'id="queue-synced"' in html


def test_snapshot_form_has_visible_comments_button():
    html = (ROOT / "snapshot_web_assets" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "snapshot_web_assets" / "app.js").read_text(encoding="utf-8")

    assert 'id="snapshot-comments-btn"' in html
    assert "function toggleSnapshotComments" in js
    assert "AuditDetail.syncCommentsDrawer" in js
    assert "AuditDetail.toggleCommentsDrawer" in js
    assert "refreshSnapshotCommentsButton()" in js
