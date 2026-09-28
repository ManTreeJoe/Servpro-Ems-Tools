"""Scope- and exact-card-keyed local read projection, never a writable comment authority."""
import json
import sqlite3
from datetime import datetime, timezone
from concurrent.futures import Future
import threading
import job_workspace_cache as cache

_lock = threading.Lock()
_pending = {}


def _table(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS comment_snapshots '
                 '(scope TEXT, card TEXT, payload TEXT, updated TEXT, PRIMARY KEY(scope,card))')


def load(card):
    if not card:
        return {'ok': True, 'cached': False}
    try:
        scope = cache.scope()
        with cache.connect() as conn:
            _table(conn)
            row = conn.execute('SELECT payload,updated FROM comment_snapshots WHERE scope=? AND card=?',
                               (scope, card)).fetchone()
            if row:
                return {'ok': True, 'cached': True, 'comments': json.loads(row[0]),
                        'saved_at': row[1], 'source': 'local_db', 'refresh_pending': True}
            # Adopt an already loaded full workspace without invoking its remote loader.
            row = conn.execute('SELECT payload,updated FROM workspaces WHERE scope=? AND card=? '
                               'ORDER BY updated DESC LIMIT 1', (scope, card)).fetchone()
            if row:
                value = json.loads(row[0])
                if isinstance(value.get('comments'), list) and (value['comments'] or not value.get('deferred_loading')):
                    return {'ok': True, 'cached': True, 'comments': value['comments'],
                            'saved_at': row[1], 'source': 'local_db', 'refresh_pending': True}
    except (OSError, sqlite3.Error, ValueError, TypeError):
        pass
    return {'ok': True, 'cached': False}


def save(card, result, scope, generation):
    if not card or not result.get('ok') or not isinstance(result.get('comments'), list):
        return
    try:
        with cache.connect() as conn:
            _table(conn)
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT version FROM generations WHERE scope=?', (scope,)).fetchone()
            if scope != cache.scope() or (row[0] if row else 0) != generation:
                return  # Edit/account change happened while the network was pending.
            conn.execute('INSERT OR REPLACE INTO comment_snapshots VALUES(?,?,?,?)',
                         (scope, card, json.dumps(result['comments']), datetime.now(timezone.utc).isoformat()))
    except (OSError, sqlite3.Error, ValueError, TypeError):
        pass


def refresh(card, fetch):
    scope = cache.scope()
    generation = cache.generation(scope)
    key = (scope, card, generation)
    with _lock:
        task = _pending.get(key)
        owner = task is None
        if owner:
            task = _pending[key] = Future()
    if not owner:
        return task.result()
    try:
        result = fetch()
        if scope != cache.scope() or cache.generation(scope) != generation:
            result = {'ok': False, 'error': 'Job changed during refresh. Your current view was preserved.'}
        else:
            save(card, result, scope, generation)
        task.set_result(result)
        return result
    except Exception as ex:
        task.set_exception(ex)
        raise
    finally:
        with _lock:
            _pending.pop(key, None)
