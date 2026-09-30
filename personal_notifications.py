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


def call(action, **data):
    if not (sb.current_user() or {}).get('id'):
        return {'ok': False, 'error': 'Sign in to OneLoss to use your personal inbox.'}
    try:
        with sb.interactive_requests(seconds=8):
            return sb.rpc('oneloss_notifications', {'p_action': action, 'p_data': data})
    except Exception:
        # Do not expose credentials/provider URLs in UI error messages.
        return {'ok': False, 'error': 'OneLoss notifications could not connect. Your changes were not confirmed; refresh and retry.'}


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
