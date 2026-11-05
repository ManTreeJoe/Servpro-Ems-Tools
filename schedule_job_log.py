"""Linked-work-item contract and read-only dev preview.

No fallback writes: atomic server persistence is required before enabling save.
The pure transitions are an executable contract, not an authorization boundary.
"""
from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5

import schedule_records as records

PLANNED = frozenset({'queue', 'group', 'date', 'arrival', 'activities', 'notes'})
PERFORMED = frozenset({'date', 'started_at', 'ended_at', 'activities', 'notes',
                       'work_party', 'subcontractor', 'status'})
UNAVAILABLE = 'Linked Schedule / Job Log saving is unavailable until the atomic server integration is installed and verified.'


def revision(value):
    if type(value) is not int or value < 0:
        raise ValueError('Expected a nonnegative revision')
    return value


def planned_fields(value, job_id, visit_id):
    if not isinstance(value, dict) or set(value) != PLANNED:
        raise ValueError('Expected planned fields only')
    visit = records.visit_payload({**deepcopy(value), 'id': visit_id,
                                  'job_id': job_id, 'status': 'active'})
    return {key: visit[key] for key in PLANNED}


def initial_state(job_id, origin, origin_id, planned, department):
    """Explicit creation only; never derive a visit from historical actual work."""
    job_id, origin_id = records.identifier(job_id), records.identifier(origin_id)
    if origin not in ('schedule', 'job_log'):
        raise ValueError('Choose an explicit Schedule or Job Log origin')
    item_id = str(uuid5(NAMESPACE_URL, f'oneloss-work-item:{job_id}:{origin}:{origin_id}'))
    visit_id = origin_id if origin == 'schedule' else str(uuid5(NAMESPACE_URL, item_id + ':visit'))
    log_id = origin_id if origin == 'job_log' else str(uuid5(NAMESPACE_URL, item_id + ':log'))
    return {'contract_version': 1, 'work_item_id': item_id, 'job_id': job_id,
            'visit_id': visit_id, 'log_entry_id': log_id,
            'department': records.text(department, 80, required=True), 'revision': 0,
            'state': 'active', 'planned': planned_fields(planned, job_id, visit_id),
            'performed': {'date': None, 'started_at': None, 'ended_at': None,
                          'activities': [], 'notes': '', 'work_party': '',
                          'subcontractor': '', 'status': 'needs_review'}}


def edit_command(item, values, *, view, expected_revision, operation_id, cancel=False):
    if view not in ('schedule', 'job_log') or type(cancel) is not bool:
        raise ValueError('Invalid linked work command')
    if not isinstance(values, dict) or set(values) - {'planned', 'performed'}:
        raise ValueError('Identity and shared job facts cannot be edited here')
    clean = {}
    if 'planned' in values:
        clean['planned'] = planned_fields(values['planned'], item['job_id'], item['visit_id'])
    if 'performed' in values:
        actual = values['performed']
        if not isinstance(actual, dict) or set(actual) != PERFORMED:
            raise ValueError('Expected performed fields only')
        # Dates/timestamps are explicit actual-work input, never Schedule prefill.
        import datetime
        for key in ('started_at', 'ended_at'):
            if actual[key] is not None:
                if not isinstance(actual[key], str):
                    raise ValueError('Actual timestamps must include a timezone')
                stamp = datetime.datetime.fromisoformat(actual[key].replace('Z', '+00:00'))
                if stamp.utcoffset() is None:
                    raise ValueError('Actual timestamps must include a timezone')
        if actual['started_at'] and actual['ended_at']:
            if datetime.datetime.fromisoformat(actual['ended_at'].replace('Z', '+00:00')) < datetime.datetime.fromisoformat(actual['started_at'].replace('Z', '+00:00')):
                raise ValueError('Actual end precedes start')
        if actual['date'] is not None:
            records.day(actual['date'])
        if actual['status'] not in ('needs_review', 'completed', 'skipped'):
            raise ValueError('Invalid performed status')
        if actual['status'] == 'completed' and actual['date'] is None:
            raise ValueError('Completion requires an explicit performed date')
        if actual['activities']:
            # Reuse Schedule's activity/crew validation without copying planned data.
            planned_fields({**item['planned'], 'activities': actual['activities']}, item['job_id'], item['visit_id'])
        elif actual['activities'] != [] or actual['status'] == 'completed':
            raise ValueError('Completion requires performed activities')
        from job_log_participants import fields
        fields(actual)
        records.text(actual['notes'], 4000)
        clean['performed'] = deepcopy(actual)
    if cancel and 'performed' in clean:
        raise ValueError('Cancellation preserves performed history')
    return {'contract_version': 1, 'work_item_id': records.identifier(item['work_item_id']),
            'department': records.text(item['department'], 80, required=True),
            'expected_revision': revision(expected_revision),
            'operation_id': records.identifier(operation_id), 'view': view,
            'cancel': cancel, 'values': clean}


def transition(item, command):
    """Pure reference transition used by isolated tests; no persistence."""
    if command['work_item_id'] != item['work_item_id'] or command['department'] != item['department']:
        raise ValueError('Work item context changed')
    if command['expected_revision'] != item['revision']:
        raise ValueError('Work item changed elsewhere')
    if item['state'] == 'canceled':
        raise ValueError('Canceled work history cannot be rescheduled implicitly')
    result = deepcopy(item)
    result.update(deepcopy(command['values']))
    result['revision'] += 1
    if command['cancel']:
        result['state'] = 'canceled'
    return result


def view(item, side):
    """Both editors consume the same plan and revision, never a name match."""
    if side not in ('schedule', 'job_log'):
        raise ValueError('Unknown linked work view')
    return {'id': item['visit_id'] if side == 'schedule' else item['log_entry_id'],
            **{key: deepcopy(item[key]) for key in ('work_item_id', 'job_id',
                'department', 'revision', 'state', 'planned', 'performed')}}


def preview(store, visit_id, expected_revision):
    visit_id = records.identifier(visit_id)
    rows = store.request('schedule_visits', params={'id': 'eq.' + visit_id,
        'department': 'eq.' + store.department, 'select': '*', 'limit': 1})
    if not rows or rows[0]['revision'] != revision(expected_revision):
        raise ValueError('Visit changed elsewhere. Reload before opening linked work.')
    row = rows[0]
    if not row.get('job_id') or row['payload'].get('status') != 'active':
        raise ValueError('Choose an active saved visit linked to an exact job')
    job = store.job_detail(row['job_id'])  # Same office/access checks as Schedule.
    store.check()
    planned = {key: row['payload'][key] for key in PLANNED}
    return {'item': initial_state(row['job_id'], 'schedule', visit_id, planned, store.department),
            'job': job, 'save_available': False, 'blocked_reason': UNAVAILABLE,
            'preview_only': True}
