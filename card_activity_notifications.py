"""Confirmed desktop Trello edits use the same durable member-notification queue.

Placement events are emitted transactionally by the shared DB. Comments already
have their own saved-action delivery. This does not observe edits made in Trello.
"""
import re
import uuid


def describe(path, method, fields):
    if method.upper() not in ('POST', 'PUT', 'DELETE'):
        return None
    match = re.fullmatch(r'/cards/([a-f0-9]{24})(/.*)?', path)
    if not match:
        return None
    card, tail = match.group(1), match.group(2) or ''
    if tail.startswith('/actions/comments'):
        return None
    if not tail and set(fields) & {'idBoard', 'idList', 'closed', 'pos'}:
        return None  # Shared placement trigger owns moves/archive/order.
    if 'checkItem' in tail or 'checklist' in tail.lower():
        message = 'Updated a checklist on this card'
    elif 'label' in tail.lower() or 'idLabels' in fields:
        message = 'Updated card labels'
    elif 'member' in tail.lower() or 'idMembers' in fields:
        message = 'Updated card members'
    elif 'attachment' in tail.lower():
        message = 'Updated card attachments'
    elif 'desc' in fields:
        message = 'Updated card information'
    else:
        message = 'Updated this card'
    return card, message


def record(path, method, fields):
    event = describe(path, method, fields)
    if not event:
        return
    try:
        import personal_notifications as pn
        if not (pn.sb.current_user() or {}).get('id'):
            return
        warning = pn.enqueue(event[0], 'activity:' + str(uuid.uuid4()), event[1])
        if warning:
            import ems_log
            ems_log.warn('notifications', warning)
    except Exception:
        # A confirmed provider edit must never be retried because an alert failed.
        import ems_log
        ems_log.warn('notifications', 'Card edit saved; activity notification could not be queued.')
