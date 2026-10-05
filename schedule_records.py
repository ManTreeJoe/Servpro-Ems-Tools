"""Draft schedule contract: validation only, no storage or external side effects.

Job facts are deliberately excluded. This contract must also be enforced by the
future server migration; Python validation is not an authorization boundary.
"""
from datetime import date
from uuid import UUID

GROUPS = {
    'scheduled': ('Monitor', 'Work To Be Performed'),
    'tbs': ('TBS New Loss /Reinspection', 'TBS Mitigation', 'TBS Contents'),
    'pending': ('Pending Testing/Clearance/Abatement',
                'Pending Approvals – Insurance/Self Pay',
                'Pending Approvals – Property Management'),
    'hold': ('On Hold',),
}
FIELDS = frozenset({'id', 'job_id', 'queue', 'group', 'date', 'arrival',
                    'activities', 'equipment', 'access', 'notes', 'status'})


def identifier(value):
    if not isinstance(value, str):
        raise ValueError('Expected a UUID string')
    return str(UUID(value))


def text(value, limit, *, required=False):
    if not isinstance(value, str):
        raise ValueError('Expected text')
    value = value.strip()
    if len(value) > limit or (required and not value) or '\x00' in value:
        raise ValueError('Text is empty, too long or contains an invalid character')
    return value


def day(value):
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError('Expected an ISO calendar date')
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError('Expected an ISO calendar date')
    return value


def visit_payload(record):
    """Return a detached allowlisted payload; never copy customer/claim facts."""
    if not isinstance(record, dict) or set(record) - FIELDS:
        raise ValueError('Unknown schedule fields; job facts cannot be saved here')
    queue = record.get('queue')
    if not isinstance(queue, str) or queue not in GROUPS:
        raise ValueError('Unknown waiting queue')
    group = record.get('group')
    if group not in GROUPS[queue]:
        raise ValueError('Run group does not belong to the selected queue')
    status = record.get('status', 'active')
    if status not in ('active', 'completed', 'canceled'):
        raise ValueError('Unknown visit status')
    visit_date = record.get('date')
    if queue == 'scheduled':
        visit_date = day(visit_date)
    elif visit_date is not None:
        raise ValueError('Waiting work must not have a scheduled date')
    activities = record.get('activities')
    if not isinstance(activities, list) or not 1 <= len(activities) <= 30:
        raise ValueError('Choose between one and thirty activities')
    cleaned, labels = [], set()
    for activity in activities:
        if not isinstance(activity, dict) or set(activity) != {'label', 'people'}:
            raise ValueError('An activity requires a label and people')
        label = text(activity['label'], 120, required=True)
        if label.casefold() in labels:
            raise ValueError('Duplicate activity')
        labels.add(label.casefold())
        people = activity['people']
        if not isinstance(people, list) or len(people) > 30:
            raise ValueError('Invalid activity crew')
        crew = [text(person, 120, required=True) for person in people]
        if len({person.casefold() for person in crew}) != len(crew):
            raise ValueError('Duplicate person on the same activity')
        cleaned.append({'label': label, 'people': crew})
    return {
        'id': identifier(record.get('id')), 'job_id': identifier(record.get('job_id')),
        'queue': queue, 'group': group, 'date': visit_date, 'status': status,
        'arrival': text(record.get('arrival', ''), 120), 'activities': cleaned,
        **{key: text(record.get(key, ''), 4000) for key in ('equipment', 'access', 'notes')},
    }


def save_command(record, *, department, expected_revision, operation_id):
    """Stable operation ID must be reused for a retry of the identical command.

    Reordering is a separate server operation, not an arbitrary client position.
    Server supplies entered-at dates, actors, revisions and timestamps.
    """
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError('A nonnegative integer revision is required')
    return {
        'contract_version': 1,
        'department': text(department, 80, required=True),
        'expected_revision': expected_revision,
        'operation_id': identifier(operation_id),
        'visit': visit_payload(record),
    }
