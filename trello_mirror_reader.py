"""Read the authorized server projection; never write or widen its scope.

None means unavailable/incomplete: callers retain their existing provider path.
Only Jobs' board/card reads use this module; provider timeline consumers still
use Trello because the server currently mirrors comments, not every action type.
"""
from datetime import datetime, timezone
import logging
import threading
import time
from concurrent.futures import Future
from copy import deepcopy

import config
import supabase_client as sb
import job_workspace_cache as cache

_FAILURES = {}
_FAILURE_LOCK = threading.Lock()
_INFLIGHT = {}
_INFLIGHT_LOCK = threading.Lock()


def _shared_read(scope, department, workspace, card_id):
    """Coalesce only overlapping identical reads; never cache across edits."""
    key = (scope, department, workspace, card_id)
    with _INFLIGHT_LOCK:
        future = _INFLIGHT.get(key)
        leader = future is None
        if leader:
            future = Future()
            _INFLIGHT[key] = future
    if leader:
        try:
            future.set_result(sb.rpc('hub_trello_read', {
                'p_department': department, 'p_workspace': workspace,
                'p_card_id': card_id,
            }))
        except Exception as ex:
            future.set_exception(ex)
        finally:
            with _INFLIGHT_LOCK:
                _INFLIGHT.pop(key, None)
    # Consumers shape/mutate payloads independently. The caller rechecks
    # authorization scope and the write barrier after receiving its copy.
    return deepcopy(future.result())


def _read_allowed(key):
    with _FAILURE_LOCK:
        return time.monotonic() >= _FAILURES.get(key, (0, 0))[0]


def _record_failure(key):
    with _FAILURE_LOCK:
        count = min(_FAILURES.get(key, (0, 0))[1] + 1, 4)
        _FAILURES[key] = (time.monotonic() + min(15 * 2 ** (count - 1), 120), count)
        # Metadata only, scoped; bound memory across account/workspace changes.
        if len(_FAILURES) > 64:
            oldest = min(_FAILURES, key=lambda k: _FAILURES[k][0])
            if oldest != key:
                _FAILURES.pop(oldest, None)


def _timestamp(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError):
        return 0


def mark_write():
    """Persist BEFORE a provider mutation, including uncertain write outcomes.

The server supplies a conservative snapshot lower bound (completion minus the
worker's maximum lease). A pre-edit snapshot cannot roll back a recent edit.
"""
    with cache.connect() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS mirror_write_barriers '
                     '(scope TEXT PRIMARY KEY, changed_at REAL NOT NULL)')
        conn.execute('INSERT INTO mirror_write_barriers VALUES (?,?) '
                     'ON CONFLICT(scope) DO UPDATE SET changed_at=max(changed_at,excluded.changed_at)',
                     (cache.scope(), datetime.now(timezone.utc).timestamp()))


def _barrier():
    with cache.connect() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS mirror_write_barriers '
                     '(scope TEXT PRIMARY KEY, changed_at REAL NOT NULL)')
        row = conn.execute('SELECT changed_at FROM mirror_write_barriers WHERE scope=?', (cache.scope(),)).fetchone()
        return row[0] if row else 0


def _read(card_id=None):
    failure_key = None
    try:
        if not sb.current_user():
            return None
        cfg = config.load()
        if cfg.get('trello_server_reads_enabled', True) is False:
            return None
        department = str(config.active_department() or config.base_department() or '').strip().upper()
        workspace = str(cfg.get('trello_workspace_id') or '').strip()
        if not department or not workspace:
            return None
        scope = cache.scope()
        failure_key = (scope, department, workspace)
        if not _read_allowed(failure_key):
            return None
        barrier = _barrier()
        result = _shared_read(scope, department, workspace, card_id)
        if scope != cache.scope() or not isinstance(result, dict):
            return None
        with _FAILURE_LOCK:
            _FAILURES.pop(failure_key, None)
        return result, max(barrier, _barrier())  # An edit may have occurred during the RPC.
    except Exception as ex:
        if failure_key:
            _record_failure(failure_key)
        # Older installs/schema, access denial, or outage: no empty-success.
        logging.getLogger(__name__).warning(
            'Server Trello projection unavailable; retry backoff active (type=%s, status=%s)',
            type(ex).__name__, getattr(ex, 'status', None))
        return None


def boards():
    read = _read()
    if not read:
        return None
    result, barrier = read
    rows = result.get('boards')
    if not isinstance(rows, list) or not rows:
        return None
    if any(not row.get('ready') or _timestamp(row.get('safe_after')) <= barrier for row in rows):
        return None
    return rows


def card(card_id):
    if not card_id:
        return None
    read = _read(card_id)
    if not read:
        return None
    result, barrier = read
    value = result.get('card')
    if (result.get('ready') is not True or not isinstance(value, dict)
            or value.get('id') != card_id or _timestamp(result.get('safe_after')) <= barrier
            or not all(isinstance(value.get(key), list) for key in ('actions','checklists','attachments'))):
        return None
    return {**value, '_hub_source': 'server_mirror', '_hub_saved_at': result.get('saved_at')}


def get_card(card_id):
    import trello_client as tc
    saved = card(card_id)
    if saved is not None:
        return tc.order_checklists(saved)
    value = dict(tc.get_card(card_id) or {})
    comments = tc.get_all_comments(card_id)
    value['actions'] = [a for a in value.get('actions', [])
                        if a.get('type') != 'commentCard'] + comments
    value['_comments_complete'] = True
    return value
