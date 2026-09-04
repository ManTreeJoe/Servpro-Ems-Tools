from pathlib import Path

import companycam_web_api


ROOT = Path(__file__).parents[1]


def _shared_detail_source() -> str:
    return (ROOT / "web_shared" / "audit_detail.js").read_text(encoding="utf-8")


def _snapshot_source() -> str:
    return (ROOT / "snapshot_web_assets" / "app.js").read_text(encoding="utf-8")


def test_companycam_watcher_is_armed_before_background_pull_starts():
    """A fast background job may emit done before the start call resolves.

    The watcher therefore has to exist before companycam_pull_assigned_bg is
    called.  Otherwise the completion event is lost and the progress bar runs
    forever.
    """
    js = _shared_detail_source()
    click = js[js.index('overlay.querySelector("#ccm-pull")'):
               js.index("// ── Background CompanyCam pull", js.index(
                   'overlay.querySelector("#ccm-pull")'))]
    assert click.index("watchCcPull(") < click.index(
        "companycam_pull_assigned_bg(")


def test_companycam_failed_start_disposes_the_armed_watcher():
    """A failed worker start must not poison all later pulls for that job."""
    js = _shared_detail_source()
    click = js[js.index('overlay.querySelector("#ccm-pull")'):
               js.index("// ── Background CompanyCam pull", js.index(
                   'overlay.querySelector("#ccm-pull")'))]
    assert "stopWatching" in click
    assert click.count("stopWatching()") >= 2


def test_snapshot_prefill_always_releases_its_loading_state():
    """Rendering a malformed/partial prefill must not strand aria-busy."""
    js = _snapshot_source()
    block = js[js.index("async function startNew"):
               js.index("function setSnapshotFormLoading")]
    assert "finally" in block
    assert "setSnapshotFormLoading(false)" in block[block.index("finally"):]


def test_snapshot_audit_reports_rejection_instead_of_staying_running():
    js = _snapshot_source()
    block = js[js.index("async function runSnapshotAudit"):
               js.index("\nfunction ", js.index("async function runSnapshotAudit") + 20)]
    assert "catch" in block
    assert "Audit failed:" in block


def test_companycam_background_progress_happens_during_real_pull(monkeypatch):
    """Progress must wrap the download, not run to the end before it starts."""
    events = []
    api = companycam_web_api.CompanyCamApi()
    monkeypatch.setattr(api, "_cc_emit",
                        lambda event, payload: events.append((event, payload)))

    def pull(_client, groups, _tech, _card_id, progress_cb=None):
        assert progress_cb is not None
        progress_cb(1, len(groups), "Demo", 0, 2)
        events.append(("download", {}))
        progress_cb(1, len(groups), "Demo", 2, 2)
        return {"ok": True, "pulled": 2}

    monkeypatch.setattr(api, "companycam_pull_assigned", pull)
    import web_helpers
    monkeypatch.setattr(web_helpers, "run_bg", lambda fn: fn())

    result = api.companycam_pull_assigned_bg(
        "Hoffman, Carol", [{"stage": "Demo", "photo_ids": ["1", "2"]}])

    assert result["ok"]
    assert [event for event, _ in events] == [
        "companycam:pull-progress", "download",
        "companycam:pull-progress", "companycam:pull-done"]
    assert events[0][1]["done"] == 0
    assert events[2][1]["done"] == 2
