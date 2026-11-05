"""Personal inbox boundary and durable, actor-scoped comment delivery outbox.

Only confirmed comment saves enqueue. Notification failure must never cause a
comment to be reposted. Delivery retries reuse the same server-side event key.
"""
import json
import sqlite3
import threading

import paths
import supabase_client as sb

_FLUSH = threading.Lock()


def _failure(error):
    """Classify failures using local exception types/status, never provider text."""
    status = getattr(error, 'status', None)
    if isinstance(error, sb.NotSignedIn) or status == 401:
        return 'auth', 'Your OneLoss session needs attention. Sign in again to check notifications.'
    if status == 403:
        return 'permission', 'Your account could not access OneLoss notifications. Ask an administrator to check your access.'
    if isinstance(error, TimeoutError) or (status == 0 and str(getattr(error, 'body', '')).startswith('Database action timed out')):
        return 'timeout', 'Checking OneLoss notifications timed out. Refresh and try again.'
    if isinstance(error, ConnectionError) or status == 0:
        return 'connection', 'OneLoss notifications could not connect. Check your connection and try again.'
    if isinstance(status, int) and status >= 500:
        return 'server', 'OneLoss notifications are temporarily unavailable. Try again shortly.'
    return 'unknown', 'OneLoss notifications could not be checked. Refresh and try again.'


def call(action, **data):
    if not (sb.current_user() or {}).get('id'):
        return {'ok': False, 'error_code': 'auth', 'error': 'Sign in to OneLoss to use your personal inbox.'}
    try:
        with sb.interactive_requests(seconds=8):
            return sb.rpc('oneloss_notifications', {'p_action': action, 'p_data': data})
    except Exception as error:
        import app_error_reports
        app_error_reports.capture_failure('notifications', 'personal_' + action, error)
        code, message = _failure(error)
        if action not in ('inbox', 'members'):
            message += ' Your change was not confirmed.'
        return {'ok': False, 'error_code': code, 'error': message}


def clear_unread():
    """Mark accessible personal inbox items read, in bounded batches."""
    actor = (sb.current_user() or {}).get('id')
    if not actor:
        return {'ok': False, 'marked': 0, 'error': 'Sign in to OneLoss to use your personal inbox.'}
    marked, seen = 0, set()
    for _ in range(20):
        if (sb.current_user() or {}).get('id') != actor:
            return {'ok': False, 'marked': marked, 'error': 'Your OneLoss account changed. Refresh and retry.'}
        inbox = call('inbox', filter='all', unread=True)
        if not inbox.get('ok'):
            return {'ok': False, 'marked': marked, 'error': inbox.get('error') or 'OneLoss notifications could not be checked.'}
        rows = inbox.get('items')
        if not isinstance(rows, list):
            return {'ok': False, 'marked': marked, 'error': 'OneLoss inbox response was incomplete. Refresh and retry.'}
        if (sb.current_user() or {}).get('id') != actor:
            return {'ok': False, 'marked': marked, 'error': 'Your OneLoss account changed. Refresh and retry.'}
        if not rows:
            return {'ok': True, 'marked': marked}
        for row in rows:
            if (sb.current_user() or {}).get('id') != actor:
                return {'ok': False, 'marked': marked, 'error': 'Your OneLoss account changed. Refresh and retry.'}
            nid = row.get('id') if isinstance(row, dict) else None
            if not nid or nid in seen:
                return {'ok': False, 'marked': marked, 'error': 'OneLoss read status could not be confirmed. Refresh and retry.'}
            seen.add(nid)
            if not call('read', id=nid, read=True).get('ok'):
                return {'ok': False, 'marked': marked, 'error': 'Some OneLoss notifications could not be marked read. Refresh and retry.'}
            marked += 1
        if len(rows) < 100:
            return {'ok': True, 'marked': marked}
    return {'ok': False, 'marked': marked, 'error': 'More OneLoss notifications may remain. Refresh and retry.'}


def _connect():
    db = sqlite3.connect(paths.data('notification_outbox.db'), timeout=2)
    db.execute('CREATE TABLE IF NOT EXISTS pending (actor TEXT NOT NULL, event_key TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(actor,event_key))')
    return db


def pending_count():
    actor = (sb.current_user() or {}).get('id')
    with _connect() as db:
        return db.execute('SELECT count(*) FROM pending WHERE actor=?', (actor,)).fetchone()[0]


def enqueue(card_id, event_id, body):
    """Returns a separate delivery warning, never a comment-post failure."""
    actor = (sb.current_user() or {}).get('id')
    if not actor:
        return 'Comment saved. Sign in to OneLoss for personal notifications.'
    if not event_id:
        return 'Comment saved, but notifications could not be queued without its saved ID.'
    payload = {'card_id': card_id, 'event_key': f'{card_id}:{event_id}', 'body': body, 'actor_id': actor}
    try:
        with _connect() as db:
            db.execute('INSERT OR IGNORE INTO pending VALUES (?,?,?)',
                       (actor, payload['event_key'], json.dumps(payload)))
        threading.Thread(target=flush, daemon=True, name='personal-notifications').start()
        return ''
    except Exception:
        return 'Comment saved, but personal notifications could not be queued. Do not repost the comment.'


def flush():
    """One bounded batch; no polling loop, no delivery as another login."""
    if not _FLUSH.acquire(blocking=False):
        return
    try:
        actor = (sb.current_user() or {}).get('id')
        if not actor:
            return
        with _connect() as db:
            rows = db.execute('SELECT event_key,payload FROM pending WHERE actor=? LIMIT 20', (actor,)).fetchall()
        for event_key, payload in rows:
            if (sb.current_user() or {}).get('id') != actor:
                break
            result = call('emit', **json.loads(payload))
            if not result or not result.get('ok'):
                continue
            with _connect() as db:
                db.execute('DELETE FROM pending WHERE actor=? AND event_key=?', (actor, event_key))
    finally:
        _FLUSH.release()


def mention_members(card_id):
    result = call('members', card_id=card_id)
    return {'ok': bool(result.get('ok')), 'members': result.get('people', []),
            'error': result.get('error', '')}
