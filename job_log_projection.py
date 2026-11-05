"""Durable, scoped read copies of loaded Job Logs, independent of UI eviction.

Shared Job Log writes still use their existing authorization/backend. These
records retain successfully read entries, not an alternative writable job DB.
Absence in a response is never a deletion; only an acknowledged delete is.
"""
import json
import sqlite3
import threading
import time
from datetime import datetime, timezone


def _table(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS loaded_job_logs '
                 '(scope TEXT, card TEXT, division TEXT, payload TEXT, '
                 'PRIMARY KEY(scope,card,division))')


def _key(entry):
    if entry.get('entry_id'):
        return str(entry['entry_id'])
    if entry.get('source') and entry.get('source_id'):
        return str(entry['source']) + ':' + str(entry['source_id'])
    return ''


def _source_key(entry):
    if entry.get('source') == 'trello' and entry.get('source_id'):
        return json.dumps([entry.get('placement_card_id') or '', entry['source_id']])
    return ''


def _is_dismissed(state, entry, card):
    sources = state.get('dismissed_sources', [])
    if _source_key(entry) in sources:
        return True
    # Older primary-card imports had no placement. A later import may fill
    # that field without changing the source interpretation being suppressed.
    owner = str(entry.get('placement_card_id') or '')
    if entry.get('source') != 'trello' or not entry.get('source_id'):
        return False
    if owner == card:
        return json.dumps(['', entry['source_id']]) in sources
    if not owner and state.get('include_legacy') is True:
        return json.dumps([card, entry['source_id']]) in sources
    return False


def _stamp(entry):
    try:
        value = datetime.fromisoformat(str(entry.get('updated_at') or '').replace('Z', '+00:00'))
        return value.replace(tzinfo=value.tzinfo or timezone.utc).timestamp()
    except (ValueError, TypeError):
        return 0


def _read(conn, scope, card, division):
    _table(conn)
    row = conn.execute('SELECT payload FROM loaded_job_logs WHERE scope=? AND card=? AND division=?',
                       (scope, card, (division or 'EMS').upper())).fetchone()
    return json.loads(row[0]) if row else None


def _write(conn, scope, card, division, state):
    conn.execute('INSERT OR REPLACE INTO loaded_job_logs VALUES (?,?,?,?)',
                 (scope, card, (division or 'EMS').upper(), json.dumps(state)))


def _view(state, card=''):
    if state is None:
        return {}
    opened = str(card or '').strip().casefold()
    include_legacy = state.get('include_legacy', True)
    visible = {}
    deleted = set(state.get('deleted', []))
    for row in state.get('entries', {}).values():
        owner = str(row.get('placement_card_id') or '').strip().casefold()
        if owner and owner != opened:
            continue
        if not owner and not include_legacy:
            continue
        source = _source_key(row)
        if _key(row) in deleted or _is_dismissed(state, row, card):
            deleted.add(_key(row))
            continue
        identity = source or _key(row)
        if identity not in visible or _stamp(row) > _stamp(visible[identity]):
            visible[identity] = row
    entries = sorted(visible.values(), key=lambda row: (
        row.get('work_date') or '', row.get('created_at') or '', _key(row)))
    return {'job_log': entries, 'job_log_saved_at': state.get('saved_at', ''),
            'job_log_deleted_ids': sorted(deleted),
            'job_log_deleted_sources': list(state.get('dismissed_sources', [])),
            'job_log_source': 'local_db',
            'job_log_dismissal_pending': bool(state.get('dismissal_pending'))}


def merge(conn, scope, card, division, crm):
    """Called inside the workspace cache's generation-checked transaction."""
    if not card:
        return {}
    state = _read(conn, scope, card, division)
    if not crm.get('ok') or crm.get('job_log_error') or 'job_log' not in crm:
        return _view(state, card)
    state = state or {'entries': {}, 'deleted': [], 'job_id': crm.get('job_id', '')}
    if crm.get('canon_key'):
        state['canon_key'] = crm['canon_key']
    for key in crm.get('job_log_deleted_ids') or []:
        if not isinstance(key, str) or not key:
            continue
        state['entries'].pop(key, None)
        if key not in state['deleted']:
            state['deleted'].append(key)
    log_scope = crm.get('job_log_scope') or {}
    if log_scope:
        state['include_legacy'] = bool(log_scope.get('include_legacy'))
    for entry in crm.get('job_log') or []:
        key = _key(entry)
        if key and _is_dismissed(state, entry, card):
            if key not in state['deleted']:
                state['deleted'].append(key)
            state['entries'].pop(key, None)
            continue
        if not key or key in state['deleted']:
            continue
        prior = state['entries'].get(key)
        if prior and _stamp(prior) > _stamp(entry):
            continue
        state['entries'][key] = dict(entry)
    state['saved_at'] = datetime.now(timezone.utc).isoformat()
    _write(conn, scope, card, division, state)
    return _view(state, card)


def load(card, division, *, scope_id=None):
    if not card:
        return {}
    import job_workspace_cache as cache
    try:
        with cache.connect() as conn:
            result = _view(_read(conn, scope_id or cache.scope(), card, division), card)
        if result.get('job_log_dismissal_pending'):
            request_dismissal_sync()
        return result
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return {}


def refresh_saved(card, division):
    import job_workspace_cache as cache
    import ems_db
    scope_id = cache.scope()
    try:
        with cache.connect() as conn:
            state = _read(conn, scope_id, card, division)
        canon = (state or {}).get('canon_key')
        if not canon:
            return {'ok':False, 'error':'The saved log has no verified job identity. Existing rows were kept.'}
        rows = ems_db.list_job_log_entries(canon)
        if cache.scope() != scope_id:
            return {'ok':False, 'error':'Account or office changed. Reopen the job.'}
        with cache.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            crm = merge(conn, scope_id, card, division, {'ok':True, 'canon_key':canon,
                'job_log':rows, 'job_log_deleted_ids':getattr(rows,'deleted_ids',[])})
        return {'ok':True, 'crm':crm}
    except Exception as ex:
        return {'ok':False, 'error':f'Saved log refresh failed ({type(ex).__name__}). Existing rows were kept.'}


def _dismissal_table(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS job_log_dismissal_outbox '
                 '(scope TEXT, card TEXT, division TEXT, source TEXT, payload TEXT, '
                 'PRIMARY KEY(scope,card,division,source))')


def dismiss(card, division, entry_id, *, scope_id):
    """Commit an exact-source suppression and delivery intent atomically, offline."""
    return remove(card, division, entry_id, scope_id=scope_id, imported_only=True)


def remove(card, division, entry_id, *, scope_id, imported_only=False):
    """Commit deletion against the exact displayed record before network work.

    Imported source aliases share a suppression; manual entries use their stable
    application ID. Never resolve a displayed record through a customer name.
    """
    import job_workspace_cache as cache
    try:
        with cache.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            state = _read(conn, scope_id, card, division)
            view = _view(state, card)
            if entry_id and entry_id in view.get('job_log_deleted_ids', []):
                return {'ok': True, 'dismissed': True, 'deleted': True,
                        'already_dismissed': True, 'deleted_ids': view['job_log_deleted_ids'],
                        'deleted_sources': view['job_log_deleted_sources'],
                        'deleted_trello': False, 'deleted_comment_id': '',
                        'pending_sync': bool(state.get('dismissal_pending')),
                        'entries': view['job_log']}
            row = (state or {}).get('entries', {}).get(entry_id)
            owner = str((row or {}).get('placement_card_id') or '').strip()
            legacy_on_primary = not owner and (state or {}).get('include_legacy', True) is True
            if not row or (imported_only and not _source_key(row)) or not (owner == card or legacy_on_primary):
                return {'ok':False, 'error':'This imported entry is not saved for this card. Refresh the Job Log first.'}
            canon = state.get('canon_key')
            if not canon:
                saved = conn.execute('SELECT payload FROM workspaces WHERE scope=? AND card=? AND division=?',
                                     (scope_id,card,division.upper())).fetchone()
                canon = (json.loads(saved[0]).get('crm') or {}).get('canon_key') if saved else None
            if canon:
                state['canon_key'] = canon
            # Legacy projections can outlive the temporary workspace containing
            # their job identity. Exact card/source is enough to suppress locally;
            # missing identity is resolved from the card link during delivery.
            source = _source_key(row)
            ids = [entry_id] if not source else [key for key, entry in state['entries'].items() if _source_key(entry) == source]
            state.setdefault('dismissed_sources', [])
            if source and source not in state['dismissed_sources']:
                state['dismissed_sources'].append(source)
            for key in ids:
                state['entries'].pop(key)
                if key not in state['deleted']:
                    state['deleted'].append(key)
            state['dismissal_pending'] = True
            _dismissal_table(conn)
            # Replay is idempotent: the same source tombstone may be delivered twice.
            conn.execute('INSERT OR REPLACE INTO job_log_dismissal_outbox VALUES (?,?,?,?,?)',
                         (scope_id,card,division.upper(),source or 'entry:'+entry_id,json.dumps({
                             'canon_key':canon,'entry':row,'deleted_ids':ids})))
            _write(conn,scope_id,card,division,state)
            conn.execute('INSERT INTO generations VALUES (?,1) ON CONFLICT(scope) DO UPDATE SET version=version+1',(scope_id,))
            result = {'ok':True,'dismissed':True,'deleted':True,'deleted_ids':ids,
                      'deleted_sources':list(state.get('dismissed_sources', [])),
                      'deleted_trello':False,'deleted_comment_id':'','pending_sync':True,
                      'entries':_view(state,card)['job_log']}
        request_dismissal_sync()
        return result
    except (OSError, sqlite3.Error, ValueError, TypeError) as ex:
        return {'ok':False,'error':f'Could not save dismissal locally ({type(ex).__name__}). Entry kept.'}


_dismissal_lock = threading.Lock()
_dismissal_retry_at = 0.0


def sync_dismissals():
    """One bounded background pass; never runs network work in the click handler."""
    import job_workspace_cache as cache
    import ems_db_supabase as db
    import supabase_client as sb
    scope_id = cache.scope()
    with cache.connect() as conn:
        _dismissal_table(conn)
        pending = conn.execute('SELECT card,division,source,payload FROM job_log_dismissal_outbox WHERE scope=? LIMIT 20',
                               (scope_id,)).fetchall()
    for card, division, source, raw in pending:
        if cache.scope() != scope_id:
            return
        intent = json.loads(raw)
        entry = intent['entry']
        with sb.interactive_requests():
            canon = intent.get('canon_key')
            if not canon:
                links = db._rows('job_links', link_type='eq.trello_card',
                                 link_value=f'eq.{card}', select='canon_key')
                identities = {link.get('canon_key') for link in links if link.get('canon_key')}
                if len(identities) != 1:
                    raise ValueError('Exact card identity is missing or ambiguous; dismissal remains pending')
                canon = identities.pop()
            # Both native and event-backed readers apply these tombstones.
            import job_workflow
            for removed_id in intent.get('deleted_ids', [entry['entry_id']]):
                job_workflow.cancel_job_log_delivery(canon, removed_id)
            db.log_event(canon,'crm_job_log_revision',payload={
                'entry_id':entry['entry_id'],'before':entry,
                'after':{**entry,'deleted':True,'dismissed_interpretation':True,
                         'updated_at':datetime.now(timezone.utc).isoformat()}})
        with cache.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('DELETE FROM job_log_dismissal_outbox WHERE scope=? AND card=? AND division=? AND source=? AND payload=?',
                         (scope_id,card,division,source,raw))
            state = _read(conn,scope_id,card,division)
            if state:
                state['canon_key'] = canon
                state['dismissal_pending'] = bool(conn.execute(
                    'SELECT 1 FROM job_log_dismissal_outbox WHERE scope=? AND card=? AND division=?',
                    (scope_id,card,division)).fetchone())
                _write(conn,scope_id,card,division,state)


def request_dismissal_sync():
    global _dismissal_retry_at
    if time.monotonic() < _dismissal_retry_at or not _dismissal_lock.acquire(False):
        return
    _dismissal_retry_at = time.monotonic() + 30
    def run():
        try:
            sync_dismissals()
        except Exception:
            pass  # Durable intent stays pending; next load retries after backoff.
        finally:
            _dismissal_lock.release()
    threading.Thread(target=run,daemon=True,name='job-log-dismissal-sync').start()


def restore(conn, scope, card, division, crm):
    """Adopt a pre-upgrade workspace once; never replay it over newer entries."""
    state = _read(conn, scope, card, division)
    if state and state.get('dismissal_pending'):
        request_dismissal_sync()
    return (_view(state, card) if state is not None
            else merge(conn, scope, card, division, crm))


def refresh(card, division, crm, *, scope_id, expected_generation):
    """A shared log read may succeed even while the unrelated Trello read fails."""
    import job_workspace_cache as cache
    try:
        with cache.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT version FROM generations WHERE scope=?', (scope_id,)).fetchone()
            if expected_generation == (row[0] if row else 0):
                merge(conn, scope_id, card, division, crm)
    except (OSError, sqlite3.Error, ValueError, TypeError):
        pass


def record_change(card, result, *, scope_id, division='EMS', deleted_id=''):
    """Patch acknowledged edits/imports/deletes, never infer missing rows.

    Exact entry IDs also update other already-loaded views of that shared log.
    No lookup or reuse by customer name is permitted.
    """
    if not result.get('ok'):
        return
    import job_workspace_cache as cache
    try:
        with cache.connect() as conn:
            _table(conn)
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('INSERT INTO generations VALUES (?,1) ON CONFLICT(scope) DO UPDATE SET version=version+1',
                         (scope_id,))
            rows = conn.execute('SELECT card,division,payload FROM loaded_job_logs WHERE scope=?',
                                (scope_id,)).fetchall()
            if card and not any(row[0] == card for row in rows):
                rows.append((card, division or 'EMS', json.dumps({'entries': {}, 'deleted': []})))
            entries = list(result.get('entries') or [])
            explicit = result.get('entry') or {}
            if explicit:
                entries = [r for r in entries if _key(r) != _key(explicit)] + [explicit]
            changed_keys = {_key(r) for r in entries if _key(r)}
            deleted_ids = set(result.get('deleted_ids') or ([deleted_id] if deleted_id else [])) if result.get('deleted') else set()
            changed_keys.update(deleted_ids)
            for saved_card, division, raw in rows:
                state = json.loads(raw)
                same_card = bool(card and saved_card == card)
                if not same_card and not changed_keys.intersection(state['entries']):
                    continue
                for entry in entries:
                    key = _key(entry)
                    if not key or key in state['deleted']:
                        continue
                    if not same_card and key not in state['entries']:
                        continue
                    prior = state['entries'].get(key)
                    if key == _key(explicit) or not prior or _stamp(entry) >= _stamp(prior):
                        state['entries'][key] = dict(entry)
                for removed_id in deleted_ids:
                    state['entries'].pop(removed_id, None)
                    if removed_id not in state['deleted']:
                        state['deleted'].append(removed_id)
                state['saved_at'] = datetime.now(timezone.utc).isoformat()
                _write(conn, scope_id, saved_card, division, state)
    except (OSError, sqlite3.Error, ValueError, TypeError):
        pass  # The shared write succeeded even if its local read copy failed.
