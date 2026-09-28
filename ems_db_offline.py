"""Keep working when Supabase can't be reached.

Wraps `ems_db_supabase`. While the network is fine this is a pass-through
and costs one `try`. When a call fails for TRANSPORT reasons it falls back
to the local SQLite mirror, so the tools keep answering instead of raising
into the UI:

    read  -> serve from ems_db_sqlite (a full mirror; migrate_to_supabase
             put it there, and every online write keeps it current)
    write -> apply to ems_db_sqlite AND record it, to be replayed against
             Supabase on the next successful call

What counts as "can't be reached" is deliberately narrow: only
`SupabaseError` with `status == 0` (the sentinel `_raw` raises for
URLError/DNS/TLS) and raw socket timeouts. A 401, a 403 from row-level
security, or a 409 is a real answer from a reachable server — falling back
on those would paper over a genuine permission or data bug and, worse,
would let a user act on rows the database had just refused them.

Ordering, not merging
---------------------
The queue is a strict FIFO replayed in the order the calls happened. It
does not attempt three-way merge: if someone else changed the same job
while you were offline, your queued write wins when it replays. That
matches how the app already behaves online (`upsert_job` is last-write-
wins) and is the honest behaviour for an office of a few people editing
mostly-disjoint jobs. Anything cleverer needs per-field timestamps, which
the schema does not carry.

Bulk and admin operations are NOT queued — see `_NO_QUEUE`. Replaying a
`sync_from_trello` or a `merge_jobs` hours later, against data that has
since moved, does more damage than refusing it. Offline, those raise.
"""
import json
import os
import threading
import time
from contextlib import contextmanager

import paths as _paths
import ems_db_sqlite
import ems_db_supabase

# Set False to make a transport failure raise instead of falling back.
# The conformance suite does this: silently answering from SQLite would
# let it report "identical on every scenario" during a total outage.
FALLBACK_ENABLED = True

QUEUE_PATH = _paths.data("ems_db_queue.jsonl")

_LOCK = threading.RLock()
_FLUSH_LOCK = threading.Lock()
_SCHEDULE_LOCK = threading.Lock()
_worker = None
_queue_retry_after = 0.0
_queue_failures = 0
_queue_error = ""
_queue_guard_depth = threading.local()
_last_error = ""
_degraded = False
_schema_fallbacks = set()
_retry_after = 0.0
_failure_count = 0
_RETRY_DELAYS_S = (5.0, 15.0, 30.0, 60.0, 120.0)

# ── which calls change data ────────────────────────────────────────────
# `tests/test_ems_db_offline.py` asserts these two sets together cover
# every public function of ems_db_sqlite, so adding a backend function
# without classifying it fails the suite instead of silently defaulting
# to "read" and being served stale from the cache.

_WRITES = frozenset({
    "add_alias", "backfill_departments", "backfill_stage_entered_dates",
    "import_db", "lifecycle_delete", "lifecycle_mark_actions_synced",
    "lifecycle_purge_where", "lifecycle_set_stage_entered",
    "delete_job", "lifecycle_upsert", "log_event", "merge_jobs", "prune_dead_folder_links",
    "relate_jobs", "remove_job_relationship",
    "remove_child", "remove_link", "reset_db_path", "resolve_and_link",
    "set_child", "set_department", "set_link", "sync_from_trello",
    "set_master_job_state", "set_work_environment_state", "upsert_job",
    "save_job_log_entry", "delete_job_log_entry", "delete_job_log_entries",
})

_READS = frozenset({
    "all_aliases", "all_children",
    "card_display_names_for", "carriers_for", "children_of",
    "count_by_department",
    "department_of_job", "export_db", "find_child_by_card",
    "find_child_by_folder", "find_dead_folder_links",
    "find_department_conflicts", "find_job_by_link", "find_job_by_name",
    "find_jobs_by_status", "find_property_of", "find_units_of",
    "get_aliases", "get_job", "get_job_by_id", "get_link", "get_links",
    "get_job_relationships", "get_master_job", "get_work_environment_states",
    "list_job_log_entries", "job_log_history",
    "group_by_property",
    "iter_jobs", "job_identity", "lifecycle_counts_by_stage",
    "lifecycle_get", "lifecycle_list", "lifecycle_needs_action_enrichment",
    "list_events", "list_transitions", "name_history",
})

# Writes that must never be replayed later. Each is either a bulk rewrite
# whose inputs go stale (sync_from_trello, the backfills), destructive and
# order-sensitive (merge_jobs, the purges), or local-only plumbing
# (reset_db_path, import_db). Offline, these raise rather than pretend.
_NO_QUEUE = frozenset({
    "backfill_departments", "backfill_stage_entered_dates", "import_db",
    "delete_job", "delete_job_log_entry", "delete_job_log_entries", "lifecycle_purge_where", "merge_jobs", "prune_dead_folder_links",
    "reset_db_path", "sync_from_trello",
})


class OfflineRefused(RuntimeError):
    """A bulk or destructive operation was attempted while offline."""


def _is_unreachable(ex):
    """True only for transport failures — never for a server that answered.

    `supabase_client._raw` turns URLError into SupabaseError(status=0), so
    status is the signal. A timeout can also surface as a bare OSError
    before urllib wraps it, hence the second arm.
    """
    if isinstance(ex, (TimeoutError, ConnectionError)):
        return True
    return getattr(ex, "status", None) == 0


def _is_missing_feature_schema(name, ex):
    """The optional Job Log may run locally until migration 010 lands.

    This is intentionally narrower than `_is_unreachable`: a generic 404,
    permission failure, or missing core table must still surface loudly.
    """
    if name not in {"list_job_log_entries", "save_job_log_entry", "delete_job_log_entry",
                    "job_log_history"}:
        return False
    body = str(getattr(ex, "body", "") or ex)
    return (getattr(ex, "status", None) == 404 and "PGRST205" in body
            and ("crm_job_log_entries" in body
                 or "crm_job_log_revisions" in body))


# ── replay queue ───────────────────────────────────────────────────────

@contextmanager
def _file_guard(suffix, blocking=True):
    """Coordinate installed/dev processes sharing the same queue file."""
    os.makedirs(os.path.dirname(QUEUE_PATH), exist_ok=True)
    with open(QUEUE_PATH + suffix, "a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        acquired = False
        try:
            if os.name == "nt":
                import msvcrt
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
                    acquired = True
                except OSError:
                    if blocking:
                        raise
            else:
                import fcntl
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
                    acquired = True
                except BlockingIOError:
                    pass
            yield acquired
        finally:
            if acquired:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)


@contextmanager
def _queue_guard():
    with _LOCK:
        if getattr(_queue_guard_depth, "active", False):
            yield
        else:
            with _file_guard(".lock"):
                _queue_guard_depth.active = True
                try:
                    yield
                finally:
                    _queue_guard_depth.active = False

def _queue_append(fn, args, kwargs):
    """Record a call for replay. Returns False if it can't be serialized,
    which the caller must treat as a failure to queue rather than a
    success — a write we cannot replay is a write that would silently
    diverge from the shared database."""
    try:
        entry = json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "fn": fn, "args": list(args), "kwargs": kwargs})
    except (TypeError, ValueError):
        return False
    with _queue_guard():
        os.makedirs(os.path.dirname(QUEUE_PATH), exist_ok=True)
        with open(QUEUE_PATH, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    return True


def queued() -> list:
    """Pending calls, oldest first."""
    with _queue_guard():
        if not os.path.exists(QUEUE_PATH):
            return ems_db_sqlite._outbox_entries()
        out = []
        with open(QUEUE_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue      # a torn final line, not worth failing on
        return out + ems_db_sqlite._outbox_entries()


def _write_queue(entries):
    if any('_outbox_id' in entry for entry in entries):
        raise RuntimeError('SQLite pending changes cannot be rewritten as a legacy JSON queue.')
    with _queue_guard():
        if not entries:
            if os.path.exists(QUEUE_PATH):
                os.remove(QUEUE_PATH)
            return
        tmp = QUEUE_PATH + ".tmp"
        os.makedirs(os.path.dirname(QUEUE_PATH), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
        os.replace(tmp, QUEUE_PATH)


def flush_queue() -> dict:
    """Replay pending calls against Supabase, oldest first.

    Stops at the FIRST failure and keeps that entry plus everything after
    it. Draining past a failure would reorder the writes — a `remove_link`
    landing before the `set_link` it was meant to undo leaves the shared
    database in a state the user never asked for.
    """
    if not _FLUSH_LOCK.acquire(blocking=False):
        return {"sent": 0, "pending": len(queued()), "error": "", "busy": True}
    try:
        with _file_guard(".replay.lock", blocking=False) as acquired:
            if not acquired:
                return {"sent": 0, "pending": len(queued()), "error": "", "busy": True}
            return _flush_queue_batch()
    finally:
        _FLUSH_LOCK.release()


def _flush_queue_batch():
    global _queue_retry_after, _queue_failures, _queue_error
    sent, err = 0, ""
    try:
        # Bound this pass to the starting batch. New edits remain for the next
        # pass, and every acknowledged entry is checkpointed immediately.
        for entry in queued():
            try:
                if entry.get('_scope') and entry['_scope'] != _outbox_scope():
                    raise RuntimeError('Pending change belongs to another account or franchise. Switch back to sync it.')
                fn = getattr(ems_db_supabase, entry.get("fn", ""), None)
                if fn is None:
                    raise RuntimeError(f"unknown queued call {entry.get('fn')!r}")
                fn(*entry.get("args", []), **entry.get("kwargs", {}))
                with _queue_guard():
                    current = queued()
                    if not current or current[0] != entry:
                        raise RuntimeError("Queue changed during replay; retained pending changes")
                    if '_outbox_id' in entry:
                        ems_db_sqlite._outbox_ack(entry['_outbox_id'])
                    else:
                        _write_queue([row for row in current[1:] if '_outbox_id' not in row])
                sent += 1
            except Exception as ex:
                err = f"{type(ex).__name__}: {ex}"
                if _is_unreachable(ex):
                    _mark(True, str(ex))
                elif getattr(ex, 'status', None) in (400, 401, 403, 404, 409, 422):
                    # A permission/validation response proves reachability.
                    # Keep the failed write, but do not call this an outage.
                    _mark(False)
                break
        _queue_error = err
        if err:
            delay = _RETRY_DELAYS_S[min(_queue_failures, len(_RETRY_DELAYS_S) - 1)]
            _queue_failures += 1
            _queue_retry_after = time.monotonic() + delay
        else:
            _queue_failures = 0
            _queue_retry_after = 0.0
            if sent:
                _mark(False)
        return {"sent": sent, "pending": len(queued()), "error": err}
    except Exception as ex:
        _queue_error = f"{type(ex).__name__}: {ex}"
        _queue_retry_after = time.monotonic() + 30
        raise


def request_queue_sync():
    """Schedule one paced replay without blocking a card or health refresh."""
    global _worker
    if not FALLBACK_ENABLED:
        return
    with _SCHEDULE_LOCK:
        if _worker is not None and _worker.is_alive():
            return
        if time.monotonic() < max(_queue_retry_after, _retry_after) or not queued():
            return
        _worker = threading.Thread(target=flush_queue, name="hub-queue-sync", daemon=True)
        _worker.start()


def status() -> dict:
    """For Settings: are we degraded, and how much is waiting?"""
    return {"degraded": _degraded, "queued": len(queued()),
            "last_error": _queue_error or _last_error, "queue_path": QUEUE_PATH,
            "schema_fallbacks": sorted(_schema_fallbacks)}


# ── delegation ─────────────────────────────────────────────────────────

def _mark(degraded, error=""):
    global _degraded, _last_error, _retry_after, _failure_count
    was_degraded = _degraded
    previous_error = _last_error
    _degraded = degraded
    _last_error = error
    if not degraded:
        _failure_count = 0
        _retry_after = 0.0
        return
    delay = _RETRY_DELAYS_S[min(_failure_count, len(_RETRY_DELAYS_S) - 1)]
    _failure_count += 1
    _retry_after = time.monotonic() + delay
    if was_degraded and previous_error == error:
        return
    try:
        import ems_log
        ems_log.warn("ems_db", f"Supabase unreachable, using local cache: "
                               f"{error}")
    except Exception:
        pass


def _call(name, *args, **kwargs):
    if name == 'save_job_log_entry':
        entry = args[1] if len(args) > 1 else kwargs.get('entry')
        if isinstance(entry, dict) and not entry.get('entry_id') and not entry.get('source_id'):
            # Reserve identity BEFORE the first network attempt. The server
            # may commit and lose its response; fallback and replay must
            # address that same entry, including a subsequent local delete.
            import uuid
            entry = {**entry, 'entry_id': str(uuid.uuid4())}
            if len(args) > 1:
                args = (args[0], entry, *args[2:])
            else:
                kwargs = {**kwargs, 'entry': entry}
    remote = getattr(ems_db_supabase, name)
    if (FALLBACK_ENABLED and _degraded
            and time.monotonic() < _retry_after):
        return _fallback(name, _last_error or "shared database unavailable",
                         *args, **kwargs)
    try:
        out = remote(*args, **kwargs)
    except Exception as ex:
        if FALLBACK_ENABLED and _is_missing_feature_schema(name, ex):
            _schema_fallbacks.add("job_log")
            return _fallback(name, ex, *args, **kwargs)
        if not (FALLBACK_ENABLED and _is_unreachable(ex)):
            raise
        _mark(True, str(ex))
        return _fallback(name, ex, *args, **kwargs)

    # Also recover a queue left by a previous process or a partial failed
    # replay. Do not make the current card wait for all queued writes.
    if _degraded:
        _mark(False)
    request_queue_sync()
    return out


def _fallback(name, ex, *args, **kwargs):
    if name in _NO_QUEUE:
        raise OfflineRefused(
            f"'{name}' needs the shared database and it is unreachable "
            f"({ex}). It is not queued because replaying it later, against "
            f"data that has since moved, could undo someone else's work.")
    local = getattr(ems_db_sqlite, name)
    if name not in _WRITES:
        return local(*args, **kwargs)
    entry = {'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'fn': name,
             'args': list(args), 'kwargs': kwargs, '_scope': _outbox_scope()}
    try:
        with _queue_guard():
            return ems_db_sqlite._with_outbox(entry, lambda: local(*args, **kwargs))
    except (TypeError, ValueError) as error:
        raise OfflineRefused(f"'{name}' could not be saved for replay; no local change was committed: {error}") from error


def _outbox_scope():
    import job_workspace_cache
    return job_workspace_cache.scope()


_WRAPPED = {}


def __getattr__(name):
    if name.startswith("__") and name.endswith("__"):
        raise AttributeError(name)
    cached = _WRAPPED.get(name)
    if cached is not None:
        return cached
    attr = getattr(ems_db_supabase, name)
    if not callable(attr) or name not in (_READS | _WRITES):
        # Constants, and anything the classification doesn't cover, pass
        # straight through — wrapping a non-call would break `DB_PATH`.
        return attr

    def _wrapped(*args, **kwargs):
        return _call(name, *args, **kwargs)
    _wrapped.__name__ = name
    _wrapped.__doc__ = getattr(attr, "__doc__", "")
    # Memoized: every `ems_db.get_job(...)` reaches this module through two
    # `__getattr__` hops, so building a fresh closure per call would put an
    # allocation in front of every one of the ~2000 lookups an audit render
    # makes. The wrapper closes over `name` only, never over a backend
    # reference, so caching it can't pin a stale module after a switch.
    _WRAPPED[name] = _wrapped
    return _wrapped


def __dir__():
    return sorted(set(globals()) | set(dir(ems_db_supabase)))
