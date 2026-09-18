"""Local SQLite read projection of successfully loaded job workspaces.

This is not a second writable job database. Shared records remain authoritative;
the projection lets reopening an exact card avoid waiting for the network.
User, service and franchise boundaries are part of every key.
"""
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone


def scope():
    import config
    import supabase_client as sb
    user = str((sb.current_user() or {}).get('id') or '')
    service = str(config.load().get('supabase_url') or '').rstrip('/')
    department = str(config.active_department() or 'default').upper()
    return hashlib.sha256(json.dumps([service, user, department]).encode()).hexdigest()


@contextmanager
def connect():
    import paths
    path = Path(paths.DATA_DIR)/'job_workspace_cache.sqlite3'
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=2)
    conn.execute('CREATE TABLE IF NOT EXISTS workspaces '
                 '(scope TEXT, card TEXT, division TEXT, client TEXT, updated TEXT, payload TEXT, '
                 'PRIMARY KEY(scope,card,division))')
    conn.execute('CREATE TABLE IF NOT EXISTS generations (scope TEXT PRIMARY KEY, version INTEGER NOT NULL)')
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def generation(scope_id=None):
    try:
        with connect() as conn:
            row = conn.execute('SELECT version FROM generations WHERE scope=?', (scope_id or scope(),)).fetchone()
            return row[0] if row else 0
    except (OSError, sqlite3.Error):
        return -1


def save(card, division, client, payload, *, scope_id=None, expected_generation=None):
    if not card or not payload.get('ok'):
        return
    try:
        with connect() as conn:
            current_scope = scope_id or scope()
            conn.execute('BEGIN IMMEDIATE')
            if expected_generation is not None:
                row = conn.execute('SELECT version FROM generations WHERE scope=?', (current_scope,)).fetchone()
                if expected_generation != (row[0] if row else 0):
                    return  # An edit happened while this background read was running.
            conn.execute('INSERT OR REPLACE INTO workspaces VALUES (?,?,?,?,?,?)',
                (current_scope, card, (division or 'EMS').upper(), client.casefold(),
                 datetime.now(timezone.utc).isoformat(), json.dumps(payload)))
            conn.execute('DELETE FROM workspaces WHERE rowid NOT IN '
                         '(SELECT rowid FROM workspaces ORDER BY updated DESC LIMIT 200)')
    except (OSError, sqlite3.Error, TypeError, ValueError):
        pass  # A cache failure must not fail a successful shared-data read.


def load(card, division):
    if not card:
        return None  # Never reuse by a possibly ambiguous customer name.
    try:
        with connect() as conn:
            row = conn.execute('SELECT payload,updated FROM workspaces '
                               'WHERE scope=? AND card=? AND division=?',
                               (scope(), card, (division or 'EMS').upper())).fetchone()
        if row:
            return {**json.loads(row[0]), 'cached': True, 'saved_at': row[1],
                    'source': 'local_db', 'refresh_pending': True}
    except (OSError, sqlite3.Error, ValueError, TypeError):
        pass
    return None


def invalidate(client='', card=''):
    try:
        with connect() as conn:
            conn.execute('INSERT INTO generations VALUES (?,1) ON CONFLICT(scope) DO UPDATE SET version=version+1', (scope(),))
            if not client and not card:
                conn.execute('DELETE FROM workspaces WHERE scope=?', (scope(),))
            else:
                conn.execute('DELETE FROM workspaces WHERE scope=? AND (client=? OR card=?)',
                             (scope(), client.casefold(), card))
    except (OSError, sqlite3.Error):
        pass
