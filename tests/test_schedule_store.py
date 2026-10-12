import base64
import json
from unittest.mock import Mock

import pytest
import schedule_store as store

USER = '10000000-0000-4000-8000-000000000001'


def test_schedule_uses_same_stored_facts_as_job_card():
    job = store.ScheduleStore.job({'job_id': 'job', 'display_name': 'Job title',
        'metadata_json': json.dumps({'settings': {'customer_name': 'Actual customer',
            'address': 'Saved address', 'email': 'customer@example.com',
            'scope_initial': 'Protect floors'}})})
    assert job['contact'] == 'Actual customer'
    assert job['address'] == 'Saved address'
    assert job['email'] == 'customer@example.com'
    assert any(f['value'] == 'Protect floors' for s in job['info_sections'] for f in s['fields'])


@pytest.fixture
def bound(monkeypatch):
    monkeypatch.setattr(store.sb, 'creds', lambda: ('https://example.supabase.co', 'public'))
    monkeypatch.setattr(store.sb, 'current_user', lambda: {'id': USER})
    monkeypatch.setattr(store.config, 'active_department', lambda: 'IE')
    payload = base64.urlsafe_b64encode(json.dumps({'sub': USER}).encode()).decode().rstrip('=')
    monkeypatch.setattr(store.sb, 'access_token', lambda: 'header.' + payload + '.signature')
    return store.ScheduleStore()


def test_wrong_context_rejected_before_write(bound):
    with pytest.raises(ValueError, match='changed'):
        store.ScheduleStore('another office')


def test_changed_account_stops_network(bound, monkeypatch):
    bound.opener = Mock()
    monkeypatch.setattr(store.sb, 'current_user', lambda: {'id': 'different'})
    with pytest.raises(ValueError, match='changed'):
        bound.request('schedule_visits')
    bound.opener.open.assert_not_called()


def test_search_cannot_inject_filter(bound):
    bound.request = Mock(return_value=[])
    bound.search('Jones),department.eq.OTHER,(a')
    params = bound.request.call_args.kwargs['params']
    assert params['department'] == 'eq.IE'
    assert params['or'].count('(') == 1
    assert params['or'].count(',') == 1


def test_search_lists_populated_job_before_empty_legacy_record(bound):
    bound.request = Mock(return_value=[
        {'job_id': 'legacy', 'display_name': 'Carenza Nicholas'},
        {'job_id': 'real', 'display_name': 'Carenza, Nicholas - Mercury', 'address': '3412 Cameo Dr'}])
    assert [j['job_id'] for j in bound.search('Carenza')] == ['real', 'legacy']


def test_load_maps_job_facts_and_pages(bound):
    payload = {'id': 'visit', 'job_id': 'job', 'arrival': '', 'activities': []}
    bound.request = Mock(return_value=[{'payload': payload, 'job_id': 'job',
        'revision': 2, 'queue_entered_at': '2026-10-05T12:00:00Z',
        'jobs': {'job_id': 'job', 'display_name': 'Real job', 'carrier': 'AAA'}}])
    row = bound.load()[0]
    assert row['title'] == 'Real job'
    assert row['insurance'] == 'AAA'
    assert row['revision'] == 2
    assert row['since'] == '2026-10-05'


def test_wrong_office_save_rejected(bound):
    bound.request = Mock()
    with pytest.raises(ValueError, match='Office changed'):
        bound.save({'department': 'OTHER'})
    bound.request.assert_not_called()


def test_job_detail_is_office_scoped_and_rejects_missing_job(bound):
    bound.request = Mock(return_value=[])
    with pytest.raises(ValueError, match='no longer available'):
        bound.job_detail('20000000-0000-4000-8000-000000000001')
    assert bound.request.call_args.kwargs['params']['department'] == 'eq.IE'


def test_job_detail_returns_exact_jobs_links(bound):
    jid = '20000000-0000-4000-8000-000000000001'
    bound.request = Mock(return_value=[{'job_id': jid, 'canon_key': 'exact', 'display_name': 'One job'}])
    bound.trello_links = Mock(return_value={'exact': ['a'*24], 'other': ['b'*24]})
    assert bound.job_detail(jid)['trello_cards'] == ['a'*24]


def test_conflict_is_safe_message():
    result = store.failure(store.sb.SupabaseError(409, '{"code":"40001","message":"private data"}'))
    assert result['conflict']
    assert 'private data' not in result['error']


def test_unique_conflict_does_not_claim_one_visit_per_job():
    result = store.failure(store.sb.SupabaseError(409, '{"code":"23505","message":"private data"}'))
    assert result['conflict']
    assert 'imported source already exists' in result['error']
    assert 'active visit' not in result['error']


def test_repair_name_keeps_site_and_unit_qualifiers():
    from tools.repair_schedule_links import name_key
    assert name_key('Rose, Jasmin - Self Pay') == name_key('Jasmin Rose')
    assert name_key('PCM (Belcourt - Unit 3) 9/10/26') != name_key('PCM (Belcourt)')
    assert name_key('Lilia Robles - (3rd Floor)') != name_key('Lilia Robles')
