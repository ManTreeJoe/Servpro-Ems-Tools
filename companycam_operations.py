"""Local import receipts, not a retry queue. Reuse workspace account scoping.

An interrupted import is never replayed: downloads/tag writes may have happened.
"""
import json
import uuid
from datetime import datetime, timezone

import job_workspace_cache as cache

_OWNER = uuid.uuid4().hex


def _table(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS companycam_operations '
                 '(operation_id TEXT PRIMARY KEY, scope TEXT, client TEXT, card TEXT, '
                 'project TEXT, owner TEXT, state TEXT, updated TEXT, payload TEXT)')
    conn.execute('CREATE INDEX IF NOT EXISTS companycam_operation_card '
                 'ON companycam_operations(scope,card,updated)')


def start(operation_id, client, card, project):
    identity = (cache.scope(), client, card, project)
    with cache.connect() as conn:
        _table(conn)
        conn.execute('BEGIN IMMEDIATE')
        old = conn.execute('SELECT scope,client,card,project FROM companycam_operations '
                           'WHERE operation_id=?', (operation_id,)).fetchone()
        if old:
            if old != identity:
                raise ValueError('Import ID belongs to a different job or account.')
            return False
        boundary = 'scope=? AND card=?' if card else 'scope=? AND client=? AND card=?'
        boundary_args = (identity[0], card) if card else identity[:3]
        active = conn.execute('SELECT operation_id FROM companycam_operations WHERE '
                              + boundary + " AND project=? AND owner=? AND state='running'",
                              (*boundary_args, project, _OWNER)).fetchone()
        if active:
            raise ValueError('An import is already running for this card. Reopen the pull to check its status.')
        conn.execute('INSERT INTO companycam_operations VALUES (?,?,?,?,?,?,?,?,?)',
                     (operation_id, *identity, _OWNER, 'running',
                      datetime.now(timezone.utc).isoformat(), '{}'))
    return True


def save(operation_id, payload, *, finished=False):
    state = ('complete' if payload.get('ok') else 'failed') if finished else 'running'
    with cache.connect() as conn:
        _table(conn)
        conn.execute('UPDATE companycam_operations SET state=?,updated=?,payload=? '
                     'WHERE operation_id=? AND owner=?',
                     (state, datetime.now(timezone.utc).isoformat(), json.dumps(payload),
                      operation_id, _OWNER))


def record_photo(operation_id, photo):
    """Checkpoint one photo; a crash leaves pending/downloading, never fake success."""
    with cache.connect() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS companycam_photo_receipts '
                     '(operation_id TEXT, photo_id TEXT, payload TEXT, PRIMARY KEY(operation_id,photo_id))')
        owner = conn.execute('SELECT owner FROM companycam_operations WHERE operation_id=?', (operation_id,)).fetchone()
        if not owner or owner[0] != _OWNER:
            raise ValueError('Import receipt belongs to another process.')
        conn.execute('INSERT OR REPLACE INTO companycam_photo_receipts VALUES (?,?,?)',
                     (operation_id, str(photo['photo_id']), json.dumps(photo)))


def photo_receipts(operation_id):
    with cache.connect() as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='companycam_photo_receipts'").fetchone():
            return []
        return [json.loads(row[0]) for row in conn.execute('SELECT payload FROM companycam_photo_receipts WHERE operation_id=?', (operation_id,))]


def status(client, card, operation_id=''):
    with cache.connect() as conn:
        _table(conn)
        query = 'SELECT operation_id,owner,state,updated,payload FROM companycam_operations WHERE scope=? AND card=?'
        args = [cache.scope(), card]
        if not card:
            query += ' AND client=?'
            args.append(client)
        if operation_id:
            query += ' AND operation_id=?'
            args.append(operation_id)
        row = conn.execute(query + ' ORDER BY updated DESC LIMIT 1', args).fetchone()
    if not row:
        return {'ok': True, 'found': False}
    state = 'interrupted' if row[2] == 'running' and row[1] != _OWNER else row[2]
    return {'ok': True, 'found': True, 'operation_id': row[0], 'state': state,
            'updated': row[3], 'result': json.loads(row[4]), 'photos': photo_receipts(row[0])}
