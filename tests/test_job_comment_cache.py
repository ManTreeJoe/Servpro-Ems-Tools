from concurrent.futures import ThreadPoolExecutor
import threading
import pytest
import job_comment_cache as comments
import job_workspace_cache as workspace


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    import paths
    monkeypatch.setattr(paths, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(workspace, 'scope', lambda: 'user-workplace-a')


def test_saved_comments_load_without_provider_and_are_scoped(monkeypatch):
    value = {'ok': True, 'comments': [{'id': 'one', 'text': 'Saved'}]}
    comments.refresh('card', lambda: value)
    assert comments.load('card')['comments'] == value['comments']
    assert not comments.load('other')['cached']
    monkeypatch.setattr(workspace, 'scope', lambda: 'other-user')
    assert not comments.load('card')['cached']


def test_failed_refresh_preserves_saved_comments():
    comments.refresh('card', lambda: {'ok': True, 'comments': [{'id': 'one'}]})
    comments.refresh('card', lambda: {'ok': False, 'comments': []})
    assert comments.load('card')['comments'] == [{'id': 'one'}]


def test_invalidated_pending_read_cannot_restore_deleted_comment():
    def fetch():
        workspace.invalidate(card='card')
        return {'ok': True, 'comments': [{'id': 'deleted'}]}
    assert not comments.refresh('card', fetch)['ok']
    assert not comments.load('card')['cached']


def test_already_loaded_workspace_is_used_without_reloading():
    workspace.save('card', 'CONTENTS', 'Customer', {'ok': True,
        'comments': [{'id': 'saved'}], 'crm': {}})
    assert comments.load('card')['comments'] == [{'id': 'saved'}]


def test_concurrent_refreshes_share_one_fetch():
    started, release = threading.Event(), threading.Event()
    calls = []
    def fetch():
        calls.append(1); started.set()
        assert release.wait(2)
        return {'ok': True, 'comments': []}
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(comments.refresh, 'card', fetch)
        assert started.wait(1)
        second = pool.submit(comments.refresh, 'card', fetch)
        # Hold the first fetch until the second caller enters the pending map.
        import time
        time.sleep(.05)
        release.set()
        assert first.result()['ok'] and second.result()['ok']
    assert len(calls) == 1


def test_missing_table_cache_expires_and_is_scoped(monkeypatch):
    import pipeline_store as store
    monkeypatch.setattr(store, '_MISSING_TABLES', {})
    current = ['first']
    clock = [100.0]
    monkeypatch.setattr(store, '_cache_scope', lambda: current[0])
    monkeypatch.setattr(store.time, 'monotonic', lambda: clock[0])
    calls = []
    def missing(*a, **k):
        calls.append(1)
        raise RuntimeError('PGRST205 could not find the table')
    monkeypatch.setattr(store._sb, 'rest', missing)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            store._rows('crm_pipeline_cards')
    assert len(calls) == 1
    current[0] = 'second'
    with pytest.raises(RuntimeError):
        store._rows('crm_pipeline_cards')
    assert len(calls) == 2
    current[0] = 'first'
    clock[0] = 401.0
    with pytest.raises(RuntimeError):
        store._rows('crm_pipeline_cards')
    assert len(calls) == 3


@pytest.mark.parametrize('error', ['HTTP 503 unavailable', 'read timed out', 'HTTP 401 unauthorized'])
def test_transient_errors_are_not_remembered_as_missing_tables(monkeypatch, error):
    import pipeline_store as store
    monkeypatch.setattr(store, '_MISSING_TABLES', {})
    monkeypatch.setattr(store, '_cache_scope', lambda: 'test')
    calls = []
    def fail(*a, **k):
        calls.append(1)
        raise RuntimeError(error)
    monkeypatch.setattr(store._sb, 'rest', fail)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            store._rows('crm_pipeline_cards')
    assert len(calls) == 2


def test_api_saved_path_never_touches_remote(monkeypatch):
    import pipeline_web
    comments.refresh('card', lambda: {'ok': True, 'comments': [{'id': 'one'}]})
    monkeypatch.setattr(pipeline_web.pipeline_store, 'list_activity', lambda *a: pytest.fail('network read'))
    assert pipeline_web.Api().saved_job_comments('card')['cached']


def test_missing_optional_table_is_not_probed_repeatedly(monkeypatch):
    import pipeline_store as store
    monkeypatch.setattr(store, '_MISSING_TABLES', {}, raising=False)
    monkeypatch.setattr(store, '_cache_scope', lambda: 'test')
    calls = []
    def missing(*a, **k):
        calls.append(1)
        raise RuntimeError('PGRST205 could not find the table')
    monkeypatch.setattr(store._sb, 'rest', missing)
    assert store.list_activity('card') == []
    assert store.list_activity('card') == []
    assert len(calls) == 1
