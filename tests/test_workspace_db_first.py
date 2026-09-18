import pytest
import job_workspace_cache as cache
import pipeline_web


@pytest.fixture
def cached(tmp_path, monkeypatch):
    import paths
    monkeypatch.setattr(paths, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(cache, 'scope', lambda: 'user1:IE')
    payload = {'ok': True, 'client': 'Customer', 'card_id': 'card1',
               'info_sections': [{'name': 'Customer', 'fields': [{'id': 'phone', 'value': '555'}]}],
               'comments': [{'id': 'a1', 'text': 'Stored activity'}]}
    cache.save('card1', 'EMS', 'Customer', payload)
    return payload


def test_fast_open_reads_sqlite_before_any_shared_db_or_trello(cached, monkeypatch):
    monkeypatch.setattr(pipeline_web.ems_db, 'find_job_by_name',
                        lambda *a, **k: pytest.fail('fast open waited for the shared database'))
    result = pipeline_web.Api().job_card_workspace_fast('Customer', 'card1', 'EMS')
    assert result['info_sections'] == cached['info_sections']
    assert result['comments'] == cached['comments']
    assert result['source'] == 'local_db'


def test_cache_never_crosses_user_franchise_card_or_division(cached, monkeypatch):
    assert cache.load('card1', 'EMS')
    assert not cache.load('other-card', 'EMS')
    assert not cache.load('card1', 'Contents')
    assert not cache.load('', 'EMS')
    monkeypatch.setattr(cache, 'scope', lambda: 'user2:IE')
    assert not cache.load('card1', 'EMS')
    monkeypatch.setattr(cache, 'scope', lambda: 'user1:OC')
    assert not cache.load('card1', 'EMS')


def test_mutation_invalidates_persistent_projection(cached):
    pipeline_web.Api()._invalidate_workspace(client='Customer', card_id='card1')
    assert not cache.load('card1', 'EMS')


def test_late_background_read_cannot_restore_pre_edit_data(cached):
    version = cache.generation()
    cache.load('card1', 'EMS')
    assert cache.generation() == version  # Reads do not invalidate one another.
    cache.invalidate(card='card1')
    cache.save('card1', 'EMS', 'Customer', cached, expected_generation=version)
    assert not cache.load('card1', 'EMS')
    cache.save('card1', 'EMS', 'Customer', cached, expected_generation=cache.generation())
    assert cache.load('card1', 'EMS')


def test_memory_cache_key_changes_after_edit_or_user_switch(cached, monkeypatch):
    api = pipeline_web.Api()
    before = api._workspace_cache_key('Customer', 'card1', 'EMS')
    cache.invalidate(card='card1')
    assert api._workspace_cache_key('Customer', 'card1', 'EMS') != before
    before = api._workspace_cache_key('Customer', 'card1', 'EMS')
    api._crm_workspace_cache['customer'] = (0, {'previous_user': True})
    monkeypatch.setattr(cache, 'scope', lambda: 'user2:IE')
    assert api._workspace_cache_key('Customer', 'card1', 'EMS') != before
    assert not api._crm_workspace_cache


def test_job_info_save_invalidates_read_projection(cached, monkeypatch):
    import job_settings
    import job_settings_api
    monkeypatch.setattr(job_settings_api, '_resolve', lambda *_: 'customer')
    monkeypatch.setattr(job_settings, 'save', lambda *a, **kw: {'ok': True})
    result = pipeline_web.Api().job_settings_save('Customer', {'phone': '999'})
    assert result['ok']
    assert not cache.load('card1', 'EMS')


def test_ordinary_workspace_refresh_does_not_scan_folders(monkeypatch):
    import types
    import trello_client as tc
    api = pipeline_web.Api()
    monkeypatch.setattr(cache, 'scope', lambda: 'no-scan-test')
    monkeypatch.setattr(api, 'audit_card', lambda *a: pytest.fail('ordinary card open ran a folder audit'))
    monkeypatch.setattr(api, '_document_signature_workspace', lambda *a: pytest.fail('ordinary card open walked document folders'))
    monkeypatch.setattr(api, '_old_ems_jobs', lambda *a: [])
    monkeypatch.setattr(api, '_audit_api', lambda: types.SimpleNamespace(
        crm_job_workspace=lambda *a: {'ok': True, 'job_log': []},
        crm_division_trello_cards=lambda *a: {'ok': True, 'cards': []}))
    monkeypatch.setattr(pipeline_web.pipeline_store, 'list_checklists', lambda *a: [])
    monkeypatch.setattr(pipeline_web.pipeline_store, 'list_activity', lambda *a: [])
    monkeypatch.setattr(tc, 'get_card', lambda *a: {'name': 'Test', 'desc': ''})
    monkeypatch.setattr(tc, 'get_member_me', lambda: {})
    result = api.job_card_workspace('Test', 'no-scan-card', 'EMS')
    assert result['ok']
    assert result['audit']['audit_pending']


def test_cold_open_includes_comments_and_checklists_already_in_db(monkeypatch):
    import trello_client as tc
    monkeypatch.setattr(cache, 'scope', lambda: 'cold-stored-activity')
    monkeypatch.setattr(tc, 'get_card', lambda *a: pytest.fail('cold open called Trello'))
    monkeypatch.setattr(pipeline_web.pipeline_store, 'list_activity', lambda *a: [
        {'action_type':'comment', 'body':'Already saved', 'activity_key':'saved1', 'source':'linguar'}])
    monkeypatch.setattr(pipeline_web.pipeline_store, 'list_checklists', lambda *a: [{'id':'check1','name':'Saved checklist','items':[]}])
    result = pipeline_web.Api().job_card_workspace_fast('Test', 'cold-card', 'EMS')
    assert result['comments'][0]['text'] == 'Already saved'
    assert result['checklists'][0]['id'] == 'check1'


def test_provider_failure_preserves_saved_card_material(monkeypatch, cached):
    import types
    import trello_client as tc
    previous = {**cached, 'audit': {'ok': True, 'found': True},
                'checklists': [{'id': 'list1', 'items': []}],
                'attachments': [{'name': 'Saved file', 'url': 'https://example.test/file'}]}
    cache.save('card1', 'EMS', 'Customer', previous)
    api = pipeline_web.Api()
    monkeypatch.setattr(api, '_old_ems_jobs', lambda *a: [])
    monkeypatch.setattr(api, '_audit_api', lambda: types.SimpleNamespace(
        crm_job_workspace=lambda *a: {'ok': True},
        crm_division_trello_cards=lambda *a: {'ok': True, 'cards': []}))
    monkeypatch.setattr(pipeline_web.pipeline_store, 'list_activity', lambda *a: [])
    monkeypatch.setattr(pipeline_web.pipeline_store, 'list_checklists', lambda *a: [])
    monkeypatch.setattr(tc, 'get_card', lambda *a: (_ for _ in ()).throw(ConnectionError('Offline')))
    monkeypatch.setattr(tc, 'get_member_me', lambda: {})
    result = api.job_card_workspace('Customer', 'card1', 'EMS')
    assert result['audit']['trello_error'] == 'Offline'
    for key in ('comments', 'checklists', 'attachments', 'info_sections'):
        assert result[key] == previous[key], key
