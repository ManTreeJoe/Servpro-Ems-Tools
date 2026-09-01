from pathlib import Path

import snapshot_web


def test_candidate_queue_uses_short_cache(monkeypatch):
    import trello_client
    calls = []
    monkeypatch.setattr(trello_client, "list_boards", lambda **_k: [
        {"id": "board-1", "name": "ESTIMATING"}])

    def call(path, params=None):
        calls.append(path)
        if path.endswith("/lists"):
            return [{"id": "snap", "name": "SNAPSHOT"}]
        return [{"id": "card-1", "name": "Hoffman, Carol",
                 "idList": "snap", "shortUrl": "https://trello.test/c/1"}]

    monkeypatch.setattr(trello_client, "_call", call)
    api = snapshot_web.Api()
    first = api.candidate_jobs()
    second = api.candidate_jobs()
    assert first == second
    assert calls == ["/boards/board-1/lists", "/boards/board-1/cards"]


def test_snapshot_frontend_has_stale_request_and_parallel_loading_guards():
    root = Path(__file__).parents[1]
    js = (root / "snapshot_web_assets" / "app.js").read_text(encoding="utf-8")
    html = (root / "snapshot_web_assets" / "index.html").read_text(encoding="utf-8")
    for marker in ("Promise.allSettled", "openRequest", "requestId !== state.openRequest",
                   "_queueSyncPromise", "setSnapshotFormLoading"):
        assert marker in js
    assert 'id="snapshot-form-loading"' in html
    assert 'id="job-log-sync-state"' in html
