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

import paths as _paths
import ems_db_sqlite
import ems_db_supabase

# Set False to make a transport failure raise instead of falling back.
# The conformance suite does this: silently answering from SQLite would
# let it report "identical on every scenario" during a total outage.
FALLBACK_ENABLED = True

QUEUE_PATH = _paths.data("ems_db_queue.jsonl")

_LOCK = threading.RLock()
_last_error = ""
_degraded = False

# ── which calls change data ────────────────────────────────────────────
# `tests/test_ems_db_offline.py` asserts these two sets together cover
# every public function of ems_db_sqlite, so adding a backend function
# without classifying it fails the suite instead of silently defaulting
# to "read" and being served stale from the cache.

_WRITES = frozenset({
    "add_alias", "backfill_departments", "backfill_stage_entered_dates",
    "import_db", "lifecycle_delete", "lifecycle_mark_actions_synced",
    "lifecycle_purge_where", "lifecycle_set_stage_entered",
    "lifecycle_upsert", "log_event", "merge_jobs", "prune_dead_folder_links",
    "remove_child", "remove_link", "reset_db_path", "resolve_and_link",
    "set_child", "set_department", "set_link", "sync_from_trello",
    "upsert_job",
})

_READS = frozenset({
    "all_aliases", "all_children",
    "card_display_names_for", "carriers_for", "children_of",
    "count_by_department",
    "department_of_job", "export_db", "find_child_by_card",
    "find_child_by_folder", "find_dead_folder_links",
    "find_department_conflicts", "find_job_by_link", "find_job_by_name",
    "find_jobs_by_status", "find_property_of", "find_units_of",
    "get_aliases", "get_job", "get_link", "get_links", "group_by_property",
    "iter_jobs", "job_identity", "lifecycle_counts_by_stage",
    "lifecycle_get", "lifecycle_list", "lifecycle_needs_action_enrichment",
    "list_transitions", "name_history",
})

# Writes that must never be replayed later. Each is either a bulk rewrite
# whose inputs go stale (sync_from_trello, the backfills), destructive and
# order-sensitive (merge_jobs, the purges), or local-only plumbing
# (reset_db_path, import_db). Offline, these raise rather than pretend.
_NO_QUEUE = frozenset({
    "backfill_departments", "backfill_stage_entered_dates", "import_db",
    "lifecycle_purge_where", "merge_jobs", "prune_dead_folder_links",
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


# ── replay queue ───────────────────────────────────────────────────────

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
    with _LOCK:
        os.makedirs(os.path.dirname(QUEUE_PATH), exist_ok=True)
        with open(QUEUE_PATH, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    return True


def queued() -> list:
    """Pending calls, oldest first."""
    with _LOCK:
        if not os.path.exists(QUEUE_PATH):
            return []
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
        return out


def _write_queue(entries):
    with _LOCK:
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
    pending = queued()
    if not pending:
        return {"sent": 0, "pending": 0, "error": ""}
    sent, err = 0, ""
    for i, entry in enumerate(pending):
        fn = getattr(ems_db_supabase, entry.get("fn", ""), None)
        if fn is None:
            # The function was renamed or removed since it was queued.
            # Dropping it silently would lose a write, so stop and report.
            err = f"unknown queued call {entry.get('fn')!r}"
            pending = pending[i:]
            break
        try:
            fn(*entry.get("args", []), **entry.get("kwargs", {}))
            sent += 1
        except Exception as ex:
            err = f"{type(ex).__name__}: {ex}"
            pending = pending[i:]
            break
    else:
        pending = []
    _write_queue(pending)
    return {"sent": sent, "pending": len(pending), "error": err}


def status() -> dict:
    """For Settings: are we degraded, and how much is waiting?"""
    return {"degraded": _degraded, "queued": len(queued()),
            "last_error": _last_error, "queue_path": QUEUE_PATH}


# ── delegation ─────────────────────────────────────────────────────────

def _mark(degraded, error=""):
    global _degraded, _last_error
    _degraded = degraded
    _last_error = error
    if not degraded:
        return
    try:
        import ems_log
        ems_log.warn("ems_db", f"Supabase unreachable, using local cache: "
                               f"{error}")
    except Exception:
        pass


def _call(name, *args, **kwargs):
    remote = getattr(ems_db_supabase, name)
    try:
        out = remote(*args, **kwargs)
    except Exception as ex:
        if not (FALLBACK_ENABLED and _is_unreachable(ex)):
            raise
        _mark(True, str(ex))
        return _fallback(name, ex, *args, **kwargs)

    # Reaching the server clears the degraded flag and is the natural
    # moment to drain anything queued while it was down.
    if _degraded:
        _mark(False)
        try:
            flush_queue()
        except Exception:
            pass
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
    if not _queue_append(name, args, kwargs):
        raise OfflineRefused(
            f"'{name}' could not be saved for replay (its arguments are not "
            f"JSON-serializable), so it was not applied locally either — "
            f"applying it would put this machine out of step with the "
            f"shared database with no way to catch up.")
    return local(*args, **kwargs)


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
