"""Private, local draft recovery. Never a submitted comment or Job Log record."""
import json
from datetime import datetime, timezone

import job_workspace_cache as cache


def _scope():
    import supabase_client
    if not (supabase_client.current_user() or {}).get('id'):
        raise ValueError('Sign in to save private drafts on this PC.')
    return cache.scope()


def exchange(card, division, kind, entry_id='', *, payload=None, version=None, scope=None):
    current_scope = _scope()
    if scope is not None and scope != current_scope:
        raise ValueError('Account or franchise changed. This draft was not written.')
    if not card or kind not in ('comment', 'job-log') or division.upper() not in ('EMS', 'CONTENTS', 'RECON'):
        raise ValueError('An exact card and division are required for draft recovery.')
    key = (current_scope, str(card), division.upper(), kind, str(entry_id))
    encoded = json.dumps(payload)
    if len(encoded.encode('utf-8')) > 256_000:
        raise ValueError('Draft is too large to save locally.')
    with cache.connect() as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS private_job_drafts '
                           '(scope TEXT, card TEXT, division TEXT, kind TEXT, entry_id TEXT, '
                           'version INTEGER, payload TEXT, updated TEXT, '
                           'PRIMARY KEY(scope,card,division,kind,entry_id))')
        connection.execute('BEGIN IMMEDIATE')
        row = connection.execute('SELECT version,payload,updated FROM private_job_drafts '
                                 'WHERE scope=? AND card=? AND division=? AND kind=? AND entry_id=?', key).fetchone()
        actual = row[0] if row else 0
        if version is not None:
            if int(version) != actual:
                raise ValueError('This draft changed in another window. Reopen it before editing again.')
            stamp = datetime.now(timezone.utc).isoformat()
            connection.execute('INSERT OR REPLACE INTO private_job_drafts VALUES (?,?,?,?,?,?,?,?)',
                               (*key, actual + 1, encoded, stamp))
            row = (actual + 1, encoded, stamp)
    return {'ok': True, 'scope': current_scope, 'version': row[0] if row else 0,
            'payload': json.loads(row[1]) if row else None, 'updated': row[2] if row else ''}
