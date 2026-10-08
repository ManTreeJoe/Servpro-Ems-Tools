from copy import deepcopy

import pytest
import loss_label_sync as sync


@pytest.fixture
def world(monkeypatch):
    water = {'id': 'water', 'name': 'WATER'}
    fire = {'id': 'fire', 'name': 'FIRE'}
    bio = {'id': 'bio', 'name': 'OTHER - BIO'}
    carrier = {'id': 'aaa', 'name': 'AAA'}
    billing = {'id': 'bill', 'name': 'READY TO BILL'}
    w = {'job': {'metadata': {'settings': {'carrier': 'AAA'}}},
         'card': {'id': 'card1', 'idBoard': 'board1', 'labels': [water, carrier, billing]},
         'labels': [water, fire, bio, carrier, billing], 'writes': [], 'fail': '', 'reads': 0}

    def record(key):
        assert key == 'job1'
        return deepcopy(w['job'])

    def persist(key, child, values, meta):
        assert key == 'job1' and not child and not values
        w['job']['metadata'] = deepcopy(meta)

    def read(cid, **kwargs):
        assert cid == 'card1'
        w['reads'] += 1
        if w['fail'] == 'read':
            raise OSError('offline')
        return deepcopy(w['card'])

    def call(path, method='GET', **kwargs):
        if method == 'GET':
            assert path == '/boards/board1/labels'
            return deepcopy(w['labels'])
        assert sync.state(w['job'], 'card1')['status'] == 'pending'
        w['writes'].append((method, path, kwargs.get('data')))
        if w['fail'] == 'before':
            raise OSError('offline')
        if method == 'POST':
            label_id = kwargs['data']['value']
            if not any(l['id'] == label_id for l in w['card']['labels']):
                w['card']['labels'].append(next(l for l in w['labels'] if l['id'] == label_id))
        else:
            label_id = path.rsplit('/', 1)[-1]
            w['card']['labels'] = [l for l in w['card']['labels'] if l['id'] != label_id]
        if w['fail'] == 'after':
            raise OSError('response lost after acceptance')
        if w['fail'] == 'race':
            w['card']['labels'].append({'id': 'storm', 'name': 'STORM'})
        return {}

    monkeypatch.setattr(sync.js, '_record', record)
    monkeypatch.setattr(sync.js, '_persist', persist)
    monkeypatch.setattr(sync.tc, 'get_card_lite', read)
    monkeypatch.setattr(sync.tc, '_call', call)
    return w


def edit(w):
    return sync.context(w['job'], 'card1')['context']


def test_two_way_and_non_loss_labels_untouched(world):
    result = sync.save('job1', 'card1', 'Fire, Bio', edit(world))
    assert result['ok'] and not result['pending_push']
    assert {l['id'] for l in world['card']['labels']} == {'fire', 'bio', 'aaa', 'bill'}
    assert world['job']['metadata']['settings'] == {'carrier': 'AAA'}
    assert sync.projected(world['job'], world['card']) == 'Fire, Bio'
    world['card']['labels'] = [{'id': 'water', 'name': 'WATER'}]
    assert sync.context(world['job'], 'card1')['value'] == 'Water'
    world['card']['labels'] = []
    assert sync.context(world['job'], 'card1')['value'] == ''


def test_clear_removes_only_loss_labels(world):
    assert sync.save('job1', 'card1', '', edit(world))['ok']
    assert {l['id'] for l in world['card']['labels']} == {'aaa', 'bill'}
    assert sync.projected(world['job'], world['card']) == ''


@pytest.mark.parametrize('change', ['labels', 'board'])
def test_stale_editor_rejects_without_writes(world, change):
    expected = edit(world)
    if change == 'labels':
        world['card']['labels'].append({'id': 'bio', 'name': 'OTHER - BIO'})
    else:
        world['card']['idBoard'] = 'other-board'
    result = sync.save('job1', 'card1', 'Fire', expected)
    assert not result['ok'] and result['loss_label_conflict']
    assert not world['writes']


def test_missing_mapping_fails_before_removals(world):
    result = sync.save('job1', 'card1', 'Cleaning', edit(world))
    assert not result['ok'] and 'no matching label' in result['error']
    assert not world['writes']


@pytest.mark.parametrize('failure', ['before', 'after'])
def test_pending_survives_reopen_and_retry_is_idempotent(world, failure):
    expected = edit(world)
    world['fail'] = failure
    result = sync.save('job1', 'card1', 'Fire', expected)
    assert result['ok'] and result['loss_labels_pending']
    assert sync.state(world['job'], 'card1')['status'] == 'pending'
    world['fail'] = ''
    loaded = sync.context(world['job'], 'card1')
    assert loaded['pending'] and loaded['value'] == 'Fire'
    result = sync.save('job1', 'card1', loaded['value'], loaded['context'])
    assert result['ok'] and not result['pending_push']
    assert [l['id'] for l in world['card']['labels']].count('fire') == 1


def test_retry_does_not_undo_external_change(world):
    expected = edit(world)
    world['fail'] = 'after'
    result = sync.save('job1', 'card1', 'Fire', expected)
    world['fail'] = ''
    world['card']['labels'].append({'id': 'bio', 'name': 'OTHER - BIO'})
    writes = len(world['writes'])
    retry = sync.save('job1', 'card1', 'Fire', result['loss_label_context'])
    assert not retry['ok'] and len(world['writes']) == writes
    loaded = sync.context(world['job'], 'card1')
    assert not loaded['pending'] and loaded['notice']
    assert loaded['value'] == 'Water, Fire, Bio'


def test_mid_save_change_is_detected(world):
    expected = edit(world)
    world['fail'] = 'race'
    result = sync.save('job1', 'card1', 'Fire', expected)
    assert not result['ok'] and result['loss_label_conflict']
    assert len(world['writes']) == 1
    assert sync.state(world['job'], 'card1')['status'] == 'conflict'


def test_other_card_state_not_applied(world):
    assert sync.save('job1', 'card1', 'Fire', edit(world))['ok']
    other = {'id': 'card2', 'labels': [{'id': 'bio', 'name': 'OTHER - BIO'}]}
    assert sync.projected(world['job'], other) == 'Bio'


def test_local_stale_editor_detected(world):
    expected = edit(world)
    assert sync.save('job1', 'card1', 'Fire', expected)['ok']
    assert not sync.save('job1', 'card1', 'Bio', expected)['ok']


def test_unverified_request_rejected(world):
    assert not sync.save('job1', 'card1', 'Fire', None)['ok']
    assert not world['writes']


def test_persistence_failure_is_not_reported_as_saved(world, monkeypatch):
    expected = edit(world)
    def fail(*args):
        raise OSError('database unavailable')
    monkeypatch.setattr(sync.js, '_persist', fail)
    result = sync.save('job1', 'card1', 'Fire', expected)
    assert not result['ok'] and not world['writes']


def test_api_load_and_save_use_exact_card_context(world, monkeypatch):
    from job_settings_api import JobSettingsApi
    import job_saved_data
    import job_workspace_cache
    import job_search
    monkeypatch.setattr(job_saved_data, 'resolve', lambda client, cid: ({'canon_key': 'job1'}, None))
    monkeypatch.setattr(sync.js, 'load', lambda *a, **kw: {'ok': True, 'values': {}})
    monkeypatch.setattr(job_workspace_cache, 'invalidate', lambda **kw: None)
    monkeypatch.setattr(job_search, 'invalidate_cache', lambda: None)
    regular_saves = []
    def save(*a, **kw):
        regular_saves.append(a[1])
        return {'ok': True, 'pending_push': False}
    monkeypatch.setattr(sync.js, 'save', save)
    api = JobSettingsApi()
    loaded = api.job_settings_load('Anything', '', 'card1')
    assert loaded['values']['loss_categories'] == 'Water'
    result = api.job_settings_save('Anything', {'loss_categories': 'Bio', 'phone': '555'},
                                   '', '', 'card1', loaded['loss_label_context'])
    assert result['ok'] and not result['pending_push']
    assert regular_saves == [{'phone': '555'}]
    assert sync.projected(world['job'], world['card']) == 'Bio'


def test_pending_is_durable_in_existing_job_metadata(tmp_path, monkeypatch):
    import ems_db
    import ems_db_sqlite as db
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path / 'labels.db'))
    db._init_schema()
    monkeypatch.setattr(ems_db, 'get_job', db.get_job)
    monkeypatch.setattr(ems_db, 'upsert_job', db.upsert_job)
    key = db.upsert_job(display_name='Loss label fixture')
    card = {'id': 'fixture-card', 'idBoard': 'fixture-board', 'labels': []}
    monkeypatch.setattr(sync.tc, 'get_card_lite', lambda *a, **kw: deepcopy(card))
    def call(path, method='GET', **kw):
        if method == 'GET':
            return [{'id': 'bio', 'name': 'OTHER - BIO'}]
        raise OSError('offline')
    monkeypatch.setattr(sync.tc, '_call', call)
    expected = sync.context(db.get_job(key), 'fixture-card')['context']
    result = sync.save(key, 'fixture-card', 'Bio', expected)
    assert result['ok'] and result['loss_labels_pending']
    reopened = sync.context(db.get_job(key), 'fixture-card')
    assert reopened['pending'] and reopened['value'] == 'Bio'
