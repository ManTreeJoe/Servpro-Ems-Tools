import base64
import json
from unittest.mock import Mock

import pytest
import schedule_store as store

USER = '10000000-0000-4000-8000-000000000001'


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


def test_conflict_is_safe_message():
    result = store.failure(store.sb.SupabaseError(409, '{"code":"40001","message":"private data"}'))
    assert result['conflict']
    assert 'private data' not in result['error']
