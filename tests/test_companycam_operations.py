import pytest
import companycam_operations as operations


@pytest.fixture(autouse=True)
def local_receipts(monkeypatch, tmp_path):
    import paths
    monkeypatch.setattr(paths, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(operations.cache, 'scope', lambda: 'test-account')


def test_receipt_survives_process_restart_without_replay(monkeypatch):
    assert operations.start('op', 'Customer', 'card', 'project')
    operations.save('op', {'ok': True, 'pulled': 3, 'pics': 'fixture'}, finished=True)
    monkeypatch.setattr(operations, '_OWNER', 'another-process')
    receipt = operations.status('Customer', 'card')
    assert receipt['state'] == 'complete'
    assert receipt['result']['pulled'] == 3
    assert not operations.start('op', 'Customer', 'card', 'project')


def test_running_receipt_is_interrupted_after_restart(monkeypatch):
    operations.start('op', 'Customer', 'card', 'project')
    monkeypatch.setattr(operations, '_OWNER', 'another-process')
    assert operations.status('Customer', 'card')['state'] == 'interrupted'


def test_unaccounted_selected_photo_cannot_be_reported_complete(monkeypatch):
    from companycam_web_api import CompanyCamApi
    import web_helpers
    api = CompanyCamApi()
    monkeypatch.setattr(web_helpers, 'run_bg', lambda fn: fn())
    monkeypatch.setattr(api, '_cc_emit', lambda *a: None)
    monkeypatch.setattr(api, 'companycam_pull_assigned', lambda *a, **kw: {'ok':True, 'pulled':0})
    api.companycam_pull_assigned_bg('Customer', [{'photo_ids':['missing']}], '', 'card', 'project', 'op')
    receipt = operations.status('Customer', 'card')
    assert receipt['state'] == 'failed'
    assert receipt['photos'][0]['state'] == 'pending'
    assert 'no confirmed outcome' in receipt['result']['error']


def test_per_photo_receipt_keeps_destination_across_restart(monkeypatch):
    operations.start('op', 'Customer', 'card', 'project')
    operations.record_photo('op', {'photo_id':'photo', 'state':'downloaded', 'destination':'C:/fixture/photo.jpg'})
    monkeypatch.setattr(operations, '_OWNER', 'restart')
    receipt = operations.status('Customer', 'card')
    assert receipt['photos'][0]['destination'] == 'C:/fixture/photo.jpg'
    assert not operations.status('Customer', 'other-card')['found']


def test_scope_and_card_boundaries(monkeypatch):
    operations.start('op', 'Customer', 'ems', 'project')
    assert not operations.status('Customer', 'contents')['found']
    monkeypatch.setattr(operations.cache, 'scope', lambda: 'other-account')
    assert not operations.status('Customer', 'ems')['found']
    with pytest.raises(ValueError):
        operations.start('op', 'Customer', 'ems', 'project')


def test_duplicate_running_request_is_not_started():
    assert operations.start('op', 'Customer', 'card', 'project')
    assert not operations.start('op', 'Customer', 'card', 'project')
    with pytest.raises(ValueError, match='already running'):
        operations.start('other-op', 'Customer', 'card', 'project')


def test_card_rename_does_not_lose_receipt_or_allow_duplicate():
    operations.start('op', 'Old display name', 'card', 'project')
    assert operations.status('New display name', 'card')['found']
    with pytest.raises(ValueError, match='already running'):
        operations.start('other-op', 'New display name', 'card', 'project')


def test_worker_saves_completion_before_event_and_deduplicates(monkeypatch):
    from companycam_web_api import CompanyCamApi
    import web_helpers
    api = CompanyCamApi()
    calls = []
    monkeypatch.setattr(web_helpers, 'run_bg', lambda fn: fn())
    def completed(*a, **kw):
        calls.append(a)
        kw['photo_result_cb']({'photo_id':'p1', 'state':'downloaded', 'destination':'fixture.jpg'})
        return {'ok': True, 'pulled': 1}
    monkeypatch.setattr(api, 'companycam_pull_assigned', completed)
    def emit(event, payload):
        if event == 'companycam:pull-done':
            assert operations.status('Customer', 'card', 'op')['state'] == 'complete'
            assert payload['operation_id'] == 'op'
    monkeypatch.setattr(api, '_cc_emit', emit)
    args = ('Customer', [{'photo_ids': ['p1']}], '', 'card', 'project', 'op')
    assert api.companycam_pull_assigned_bg(*args)['ok']
    assert api.companycam_pull_assigned_bg(*args)['existing']
    assert len(calls) == 1


def test_worker_exception_is_saved_without_retry(monkeypatch):
    from companycam_web_api import CompanyCamApi
    import web_helpers
    api = CompanyCamApi()
    monkeypatch.setattr(web_helpers, 'run_bg', lambda fn: fn())
    monkeypatch.setattr(api, '_cc_emit', lambda *a: None)
    def fail(*a, **kw):
        raise TimeoutError('fixture timeout')
    monkeypatch.setattr(api, 'companycam_pull_assigned', fail)
    api.companycam_pull_assigned_bg('Customer', [{'photo_ids':['p']}], '', 'card', 'project', 'op')
    receipt = operations.status('Customer', 'card')
    assert receipt['state'] == 'failed'
    assert 'TimeoutError' in receipt['result']['error']


def test_tracking_failure_does_not_start_download(monkeypatch):
    from companycam_web_api import CompanyCamApi
    import web_helpers
    api = CompanyCamApi()
    def fail(*a, **kw):
        raise OSError('disk unavailable')
    monkeypatch.setattr(operations, 'start', fail)
    monkeypatch.setattr(web_helpers, 'run_bg', lambda fn: pytest.fail('Worker must not start without receipt'))
    result = api.companycam_pull_assigned_bg('Customer', [{'photo_ids':['p']}], '', 'card', 'project', 'op')
    assert not result['ok']


def test_photo_plan_failure_releases_running_operation(monkeypatch):
    from companycam_web_api import CompanyCamApi
    import web_helpers
    api = CompanyCamApi()
    def fail(*a, **kw):
        raise OSError('disk unavailable')
    monkeypatch.setattr(operations, 'record_photo', fail)
    monkeypatch.setattr(web_helpers, 'run_bg', lambda fn: pytest.fail('Worker must not start'))
    result = api.companycam_pull_assigned_bg('Customer', [{'photo_ids':['p']}], '', 'card', 'project', 'op')
    assert not result['ok']
    assert operations.status('Customer', 'card', 'op')['state'] == 'failed'
    assert operations.start('next-op', 'Customer', 'card', 'project')


def test_completion_receipt_failure_does_not_repeat_download(monkeypatch):
    from companycam_web_api import CompanyCamApi
    import web_helpers
    api = CompanyCamApi()
    monkeypatch.setattr(web_helpers, 'run_bg', lambda fn: fn())
    calls, events = [], []
    def completed(*a, **kw):
        calls.append(a)
        kw['photo_result_cb']({'photo_id':'p', 'state':'downloaded', 'destination':'fixture.jpg'})
        return {'ok':True, 'pulled':2}
    monkeypatch.setattr(api, 'companycam_pull_assigned', completed)
    monkeypatch.setattr(api, '_cc_emit', lambda event, result: events.append(result))
    def fail(*a, **kw):
        raise OSError('disk unavailable')
    monkeypatch.setattr(operations, 'save', fail)
    api.companycam_pull_assigned_bg('Customer', [{'photo_ids':['p']}], '', 'card', 'project', 'op')
    assert len(calls) == 1
    assert events[-1]['ok'] and events[-1]['pulled'] == 2
    assert events[-1]['receipt_error']
