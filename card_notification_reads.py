"""Acknowledge only notifications for the card the user actually opened."""
import re
import time


def _unread_inbox(call):
    """Retry only the read-only lookup, never a notification mutation."""
    result = call('inbox', unread=True, filter='all')
    if (result.get('ok') or result.get('error_code') in ('auth', 'permission')
            or 'sign in' in (result.get('error') or '').lower()):
        return result
    time.sleep(0.25)
    return call('inbox', unread=True, filter='all')


def mark_opened(card_id):
    if not re.fullmatch(r'[0-9a-f]{24}', card_id or ''):
        return {'ok': False, 'error': 'An exact card is required.'}
    import trello_client as tc
    from personal_notifications import call
    confirmed, errors = [], []
    try:
        # Snapshot first: new arrivals during acknowledgement remain unread.
        rows = tc._call('/members/me/notifications', params={
            'read_filter': 'unread', 'limit': '1000', 'fields': 'id,data'}) or []
        for row in rows:
            if ((row.get('data') or {}).get('card') or {}).get('id') == card_id:
                if tc.mark_notification_read(row['id']):
                    confirmed.append(row['id'])
                else:
                    errors.append('Trello read status was not confirmed.')
        if len(rows) == 1000:
            errors.append('Older Trello notifications may still be unread.')
    except Exception:
        errors.append('Trello read status could not connect.')
    inbox = _unread_inbox(call)
    if inbox.get('ok'):
        for row in inbox.get('items') or []:
            if row.get('card_id') == card_id and not row.get('read_at'):
                if call('read', id=row['id'], read=True).get('ok'):
                    confirmed.append(row['id'])
                else:
                    errors.append('OneLoss read status was not confirmed.')
        if len(inbox.get('items') or []) >= 100:
            errors.append('Older OneLoss notifications may still be unread.')
    else:
        if inbox.get('error_code') == 'auth' or 'sign in' in (inbox.get('error') or '').lower():
            errors.append('Sign in to OneLoss to confirm its notification read status.')
        elif inbox.get('error_code') in ('permission', 'timeout', 'connection', 'server', 'unknown'):
            errors.append({
                'permission': 'Your account could not access OneLoss notifications. Ask an administrator to check your access.',
                'timeout': 'Checking OneLoss notifications timed out. Reopen the card to retry.',
                'connection': 'OneLoss notifications could not connect. Check your connection and reopen the card.',
                'server': 'OneLoss notifications are temporarily unavailable. Try again shortly.',
                'unknown': 'OneLoss read status could not be confirmed. Reopen the card to retry.',
            }[inbox['error_code']])
        else:
            errors.append('OneLoss read status could not connect. Reopen the card to retry.')
    return {'ok': not errors, 'marked': confirmed, 'error': ' '.join(dict.fromkeys(errors))}
