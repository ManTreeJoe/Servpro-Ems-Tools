from datetime import date
from analytics_model import records, report


def metrics(decisions):
    graph = {'_jobs_by_key': {'job': {
        'canon_key': 'job', 'department': 'IE', 'status': 'active',
        'metadata': {'requirement_overrides': decisions},
    }}}
    rows = records(graph, 'IE')
    return rows, {m['key']: m for m in report(rows, {'status': 'all'}, date(2026, 10, 8))['metrics']}


def test_saved_blocked_followup_is_overdue_and_inspectable():
    rows, m = metrics({'contact': {'state': 'blocked', 'follow_up_at': '10/07/26',
                                  'blocked_reason': 'Awaiting signature', 'assignee': 'Sam',
                                  'actor': 'Nathan', 'at': '2026-10-06T12:00:00Z'}})
    assert m['overdue']['ids'] == ['job']
    assert m['attention']['ids'] == ['job']
    assert rows[0]['requirements'][0]['blocked_reason'] == 'Awaiting signature'
    assert rows[0]['requirements'][0]['actor'] == 'Nathan'
    assert m['paperwork']['value'] is None
    assert m['estimate_new']['value'] is None
    assert m['stale']['value'] is None


def test_completed_decision_does_not_remain_overdue():
    _, m = metrics({'contact': {'state': 'completed', 'due_at': '2026-10-01'}})
    assert m['overdue']['value'] == 0
    assert m['attention']['value'] == 0


def test_future_blocked_work_needs_attention_but_is_not_overdue():
    _, m = metrics({'contact': {'state': 'blocked', 'follow_up_at': '2026-10-10'}})
    assert m['overdue']['value'] == 0
    assert m['attention']['value'] == 1


def test_missing_or_invalid_dates_do_not_claim_due_coverage():
    _, m = metrics({'contact': {'state': 'todo', 'due_at': 'invalid'}})
    assert m['overdue']['value'] is None
    _, m = metrics({})
    assert m['attention']['value'] is None
