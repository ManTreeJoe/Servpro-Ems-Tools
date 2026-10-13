from datetime import datetime, timezone, timedelta
import pytest
from operations_attention import evaluate, OperationsAttention

NOW = datetime(2026, 10, 12, 19, tzinfo=timezone.utc)


def check(fields, **kwargs):
    return evaluate({'drafts': {'a': {'fields': fields}}}, [{'card_id': 'a', 'client': 'Example'}],
                    {'ok': True}, now=NOW, **kwargs)


@pytest.mark.parametrize('field,target', [('incoming_loss_at', 30), ('insured_contacted_at', 240),
                                        ('on_site_at', 60), ('field_note_posted_at', 60)])
def test_target_boundaries(field, target):
    assert not check({field: (NOW-timedelta(minutes=target-16)).isoformat()})['items']
    assert check({field: (NOW-timedelta(minutes=target-15)).isoformat()})['items'][0]['severity'] == 'soon'
    assert check({field: (NOW-timedelta(minutes=target)).isoformat()})['items'][0]['severity'] == 'soon'
    assert check({field: (NOW-timedelta(minutes=target+1)).isoformat()})['items'][0]['severity'] == 'late'


@pytest.mark.parametrize('value', ['bad', '2026-10-12T10:00:00', '2027-01-01T00:00:00Z'])
def test_invalid_or_future_times_are_not_overdue(value):
    result = check({'incoming_loss_at': value})
    assert result['invalid_dates'] == 1 and not result['items']


def test_completed_step_not_flagged_and_billing_is_review_only():
    result = check({'incoming_loss_at': '2026-10-12T17:00:00Z', 'insured_contacted_at': NOW.isoformat(),
                    'ems_completed': '2026-10-11'})
    assert len(result['items']) == 1
    assert result['items'][0]['category'] == 'Billing'
    assert 'not recorded' in result['items'][0]['detail']
    assert not check({'ems_completed': '2026-10-11', 'ems_billed': '2026-10-12'})['items']


def test_archived_cards_not_flagged():
    result = evaluate({'drafts': {'archived': {'fields': {'ems_ready': '2026-10-01'}}}}, [], {'ok': True}, NOW)
    assert not result['items'] and result['covered_cards'] == 0


def test_unavailable_keeps_schedule_issues(monkeypatch):
    import supabase_client
    monkeypatch.setattr(supabase_client, 'current_user', lambda: None)
    result = OperationsAttention().load([], {'ok': True, 'issues': [{'id': 's'}]})
    assert not result['ok'] and result['items'] == [{'id': 's'}]
