"""Loaded Job Logs outlive the disposable workspace/read cache."""
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

import job_workspace_cache as cache
import pipeline_web


@pytest.fixture
def stored_log(tmp_path, monkeypatch):
    import paths
    import job_saved_data
    monkeypatch.setattr(paths, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(cache, 'scope', lambda: 'service:user:IE')
    monkeypatch.setattr(job_saved_data, 'resolve', lambda *a: ({}, {}))
    monkeypatch.setattr(job_saved_data, 'destination', lambda *a: '')
    monkeypatch.setattr(pipeline_web.pipeline_store, 'list_activity', lambda *a: [])
    monkeypatch.setattr(pipeline_web.pipeline_store, 'list_checklists', lambda *a: [])
    rows = [dict(entry_id='log1', work_date='2026-09-18', work_type='Monitor',
                 note='Saved reading', updated_at='2026-09-18T10:00:00+00:00')]
    cache.save('card1', 'EMS', 'Customer', payload(rows))
    return rows


def payload(rows, **crm):
    return dict(ok=True, client='Customer', card_id='card1',
                audit={'ok': True}, crm=dict(ok=True, canon_key='customer',
                job_log=rows, **crm))


def fast():
    return pipeline_web.Api().job_card_workspace_fast('Customer', 'card1', 'EMS')['crm']['job_log']


def test_logs_survive_unrelated_edit_and_new_api_instance(stored_log):
    pipeline_web.Api()._invalidate_workspace(client='Customer', card_id='card1')
    assert fast() == stored_log


def test_saved_log_reopens_without_waiting_for_any_shared_read(stored_log, monkeypatch):
    import job_saved_data
    cache.invalidate(card='card1')
    monkeypatch.setattr(job_saved_data, 'resolve', lambda *a: pytest.fail('Waited for shared identity'))
    monkeypatch.setattr(job_saved_data, 'destination', lambda *a: pytest.fail('Waited for shared folder'))
    monkeypatch.setattr(pipeline_web.pipeline_store, 'list_activity', lambda *a: pytest.fail('Waited for shared activity'))
    monkeypatch.setattr(pipeline_web.pipeline_store, 'list_checklists', lambda *a: pytest.fail('Waited for shared checklists'))
    assert fast() == stored_log


def test_logs_survive_workspace_eviction(stored_log):
    for index in range(205):
        cache.save(f'other{index}', 'EMS', 'Other', payload([]))
    assert fast() == stored_log


def test_partial_and_failed_refresh_never_erase_saved_logs(stored_log):
    second = dict(entry_id='log2', work_date='2026-09-19', work_type='Demo')
    cache.save('card1', 'EMS', 'Customer', payload([second]))
    assert {r['entry_id'] for r in fast()} == {'log1', 'log2'}
    cache.save('card1', 'EMS', 'Customer', payload([], job_log_error='Offline'))
    assert {r['entry_id'] for r in fast()} == {'log1', 'log2'}


def test_new_revision_replaces_only_its_entry_and_old_revision_cannot_undo_it(stored_log):
    changed = {**stored_log[0], 'note': 'Corrected reading', 'updated_at': '2026-09-18T12:00:00Z'}
    cache.save('card1', 'EMS', 'Customer', payload([changed]))
    cache.save('card1', 'EMS', 'Customer', payload(stored_log))
    assert fast() == [changed]


def test_successful_edit_is_immediately_available_after_invalidation(stored_log, monkeypatch):
    changed = {**stored_log[0], 'note': 'Confirmed edit'}
    api = pipeline_web.Api()
    monkeypatch.setattr(api, '_audit_api', lambda: SimpleNamespace(
        save_crm_job_log=lambda *a: {'ok': True, 'entry': changed, 'entries': [changed]}))
    assert api.save_job_log_update('Customer', changed, 'card1')['ok']
    assert fast() == [changed]


def test_confirmed_delete_is_not_resurrected_by_late_refresh(stored_log, monkeypatch):
    api = pipeline_web.Api()
    monkeypatch.setattr(api, '_audit_api', lambda: SimpleNamespace(
        delete_crm_job_log=lambda *a: {'ok': True, 'deleted': True, 'entries': []}))
    assert api.delete_job_log_update('Customer', 'log1', 'card1')['ok']
    cache.save('card1', 'EMS', 'Customer', payload(stored_log))
    assert fast() == []


def test_persisted_logs_stay_scoped(stored_log, monkeypatch):
    cache.invalidate(card='card1')
    monkeypatch.setattr(cache, 'scope', lambda: 'service:other-user:IE')
    assert fast() == []
    monkeypatch.setattr(cache, 'scope', lambda: 'service:user:OC')
    assert fast() == []


def test_projection_survives_a_real_process_restart(stored_log):
    import paths
    cache.invalidate(card='card1')
    script = ('import paths, job_log_projection, json; '
              f'paths.DATA_DIR={str(paths.DATA_DIR)!r}; '
              'print(json.dumps(job_log_projection.load("card1", "EMS", scope_id="service:user:IE")))')
    result = subprocess.run([sys.executable, '-c', script], text=True, capture_output=True, check=True)
    assert json.loads(result.stdout)['job_log'] == stored_log


def test_existing_1821_workspace_is_adopted_before_invalidation(stored_log):
    with cache.connect() as conn:
        conn.execute('DELETE FROM loaded_job_logs')
    assert cache.load('card1', 'EMS')['crm']['job_log'] == stored_log
    cache.invalidate(card='card1')
    assert fast() == stored_log


def test_late_pre_edit_read_cannot_restore_old_log(stored_log, monkeypatch):
    version = cache.generation()
    changed = {**stored_log[0], 'note': 'Confirmed edit'}
    api = pipeline_web.Api()
    monkeypatch.setattr(api, '_audit_api', lambda: SimpleNamespace(
        save_crm_job_log=lambda *a: {'ok': True, 'entry': changed, 'entries': [changed]}))
    api.save_job_log_update('Customer', changed, 'card1')
    cache.save('card1', 'EMS', 'Customer', payload(stored_log), expected_generation=version)
    assert fast() == [changed]


def test_failed_delete_preserves_entries(stored_log, monkeypatch):
    api = pipeline_web.Api()
    import job_log_projection
    monkeypatch.setattr(job_log_projection, 'remove', lambda *a, **kw:
        {'ok': False, 'error': 'Not permitted'})
    assert not api.delete_job_log_update('Customer', 'log1', 'card1')['ok']
    assert fast() == stored_log


def test_partial_import_keeps_older_entries(stored_log, monkeypatch):
    second = dict(entry_id='log2', work_date='2026-09-19', work_type='Demo')
    api = pipeline_web.Api()
    monkeypatch.setattr(api, '_audit_api', lambda: SimpleNamespace(
        import_crm_job_log_from_trello=lambda *a: {'ok': True, 'entries': [second]}))
    api.import_job_log_from_trello('Customer', 'card1')
    assert {r['entry_id'] for r in fast()} == {'log1', 'log2'}


def test_log_refresh_can_persist_without_successful_trello_refresh(stored_log):
    import job_log_projection
    second = dict(entry_id='log2', work_date='2026-09-19', work_type='Demo')
    job_log_projection.refresh('card1', 'EMS', payload([second])['crm'],
        scope_id=cache.scope(), expected_generation=cache.generation())
    cache.invalidate(card='card1')
    assert {r['entry_id'] for r in fast()} == {'log1', 'log2'}


def test_card_and_division_isolation(stored_log):
    import job_log_projection
    assert not job_log_projection.load('different-card', 'EMS')
    assert not job_log_projection.load('card1', 'Contents')
    assert not job_log_projection.load('', 'EMS')


def test_projection_hides_another_placements_log_and_legacy_on_auxiliary(tmp_path, monkeypatch):
    import paths
    import job_log_projection
    monkeypatch.setattr(paths, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(cache, 'scope', lambda: 'service:user:IE')
    rows = [
        dict(entry_id='legacy', work_date='2026-09-18', work_type='Old'),
        dict(entry_id='wip', work_date='2026-09-19', work_type='Monitor',
             placement_card_id='wip-card'),
        dict(entry_id='estimate', work_date='2026-09-20', work_type='Estimate',
             placement_card_id='estimating-card'),
    ]
    with cache.connect() as conn:
        job_log_projection.merge(conn, cache.scope(), 'estimating-card', 'EMS', {
            'ok': True, 'job_log': rows,
            'job_log_scope': {'placement_card_id': 'estimating-card',
                              'include_legacy': False},
        })
    visible = job_log_projection.load('estimating-card', 'EMS')['job_log']
    assert [row['entry_id'] for row in visible] == ['estimate']


def test_save_before_full_hydration_creates_a_persistent_contents_copy(stored_log, monkeypatch):
    import job_log_projection
    entry = dict(entry_id='contents-log', work_date='2026-09-18', work_type='Pack out')
    api = pipeline_web.Api()
    monkeypatch.setattr(api, '_audit_api', lambda: SimpleNamespace(
        save_crm_job_log=lambda *a: {'ok': True, 'entry': entry, 'entries': [entry]}))
    api.save_job_log_update('Contents job', entry, 'contents-card', 'Contents')
    assert job_log_projection.load('contents-card', 'Contents')['job_log'] == [entry]
    assert not job_log_projection.load('contents-card', 'EMS')
