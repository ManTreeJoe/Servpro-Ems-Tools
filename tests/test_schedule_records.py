from copy import deepcopy

import pytest

from schedule_records import save_command, visit_payload


@pytest.fixture
def visit():
    return {'id': '11111111-1111-4111-8111-111111111111',
            'job_id': '22222222-2222-4222-8222-222222222222',
            'queue': 'scheduled', 'group': 'Work To Be Performed',
            'date': '2026-10-05', 'activities': [
                {'label': 'Demo', 'people': ['Sam']},
                {'label': 'Monitor', 'people': ['Alex']}],
            'equipment': 'Two air movers'}


def test_untimed_multiple_activities_are_independent(visit):
    result = visit_payload(visit)
    assert result['arrival'] == ''
    assert result['activities'] == visit['activities']
    result['activities'][0]['people'].append('Jordan')
    assert visit['activities'][0]['people'] == ['Sam']


@pytest.mark.parametrize('queue,group', [
    ('tbs', 'TBS Mitigation'), ('pending', 'Pending Testing/Clearance/Abatement'),
    ('hold', 'On Hold')])
def test_waiting_work_is_undated(visit, queue, group):
    visit.update(queue=queue, group=group, date=None)
    assert visit_payload(visit)['date'] is None
    visit['date'] = '2026-10-05'
    with pytest.raises(ValueError):
        visit_payload(visit)


@pytest.mark.parametrize('field,value', [
    ('date', '10/05/26'), ('date', '2026-02-30'), ('date', None),
    ('job_id', 'sample-1'), ('queue', 'unknown'), ('queue', []),
    ('group', 'On Hold'), ('activities', []), ('status', 'deleted'),
    ('notes', 'x' * 4001), ('arrival', 930)])
def test_invalid_fields_fail_closed(visit, field, value):
    visit[field] = value
    with pytest.raises(ValueError):
        visit_payload(visit)


@pytest.mark.parametrize('field', ['title', 'address', 'claim', 'phone', 'carrier',
                                   'created_by', 'revision', 'since', 'position'])
def test_job_facts_and_server_fields_are_not_writable(visit, field):
    visit[field] = 'forged'
    with pytest.raises(ValueError):
        visit_payload(visit)


def test_duplicate_activity_and_people_rejected(visit):
    duplicate = deepcopy(visit['activities'][0])
    visit['activities'].append(duplicate)
    with pytest.raises(ValueError):
        visit_payload(visit)
    visit['activities'].pop()
    visit['activities'][0]['people'].append('sam')
    with pytest.raises(ValueError):
        visit_payload(visit)


@pytest.mark.parametrize('revision', [-1, True, '2', 1.5, None])
def test_revision_is_explicit(visit, revision):
    with pytest.raises(ValueError):
        save_command(visit, department='IE', expected_revision=revision,
                     operation_id='33333333-3333-4333-8333-333333333333')


def test_retry_command_is_stable_without_external_side_effects(visit):
    args = dict(department='IE', expected_revision=2,
                operation_id='33333333-3333-4333-8333-333333333333')
    assert save_command(visit, **args) == save_command(visit, **args)


def test_cancellation_keeps_record_identity_and_details(visit):
    visit['status'] = 'canceled'
    result = visit_payload(visit)
    assert result['id'] == visit['id']
    assert result['equipment'] == 'Two air movers'
    assert result['date'] == '2026-10-05'
