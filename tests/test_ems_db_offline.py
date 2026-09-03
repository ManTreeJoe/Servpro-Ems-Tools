"""Offline fallback for the Supabase backend.

The risky part isn't the happy path, it's the judgement calls: WHICH
failures mean "unreachable", which calls may be replayed later, and what
happens to a write that can't be queued. Those are what's tested here.

Nothing in this file touches the network — `ems_db_supabase` is replaced
with a stub that raises whatever the test wants.
"""
import inspect
import json

import pytest

import ems_db_offline as off
import ems_db_sqlite
import ems_db_supabase


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Point the queue at tmp_path and give each test a clean DB."""
    monkeypatch.setattr(off, "QUEUE_PATH", str(tmp_path / "queue.jsonl"))
    monkeypatch.setattr(off, "FALLBACK_ENABLED", True)
    monkeypatch.setattr(off, "_degraded", False)
    monkeypatch.setattr(off, "_retry_after", 0.0)
    monkeypatch.setattr(off, "_failure_count", 0)
    monkeypatch.setattr(off, "_schema_fallbacks", set())
    ems_db_sqlite.reset_db_path(str(tmp_path / "jobs.db"))
    return tmp_path


def _unreachable(*_a, **_k):
    raise supa_error(0, "unreachable: [Errno 11001] getaddrinfo failed")


def supa_error(status, body):
    import supabase_client
    return supabase_client.SupabaseError(status, body, "http://x")


# ── classification completeness ────────────────────────────────────────

def test_every_backend_function_is_classified():
    """The whole design rests on knowing which calls mutate. An
    unclassified function falls through to "pass straight through", which
    for a WRITE means it is neither applied locally nor queued — the write
    just vanishes when offline. Fail loudly instead."""
    public = {n for n, v in vars(ems_db_sqlite).items()
              if not n.startswith("_") and inspect.isfunction(v)
              and v.__module__ == "ems_db_sqlite"}
    missing = public - (off._READS | off._WRITES)
    assert not missing, (
        f"unclassified ems_db_sqlite function(s): {sorted(missing)} — add "
        f"each to ems_db_offline._READS or ._WRITES")


def test_reads_and_writes_do_not_overlap():
    assert not (off._READS & off._WRITES)


def test_no_queue_is_a_subset_of_writes():
    assert off._NO_QUEUE <= off._WRITES


# ── what counts as "unreachable" ───────────────────────────────────────

def test_transport_failure_is_unreachable():
    assert off._is_unreachable(supa_error(0, "unreachable: DNS"))
    assert off._is_unreachable(TimeoutError("timed out"))
    assert off._is_unreachable(ConnectionResetError("reset"))


@pytest.mark.parametrize("status", [401, 403, 404, 409, 500, 503])
def test_a_server_that_answered_is_not_unreachable(status):
    """A 403 is row-level security refusing the row. Falling back to the
    local mirror would serve rows the database just denied, which is worse
    than an error — it is a silent permission bypass."""
    assert not off._is_unreachable(supa_error(status, "no"))


def test_permission_error_propagates_and_does_not_fall_back(sandbox,
                                                             monkeypatch):
    def denied(*_a, **_k):
        raise supa_error(403, "row-level security")
    monkeypatch.setattr(ems_db_supabase, "get_job", denied)
    with pytest.raises(Exception) as ex:
        off.get_job("anything")
    assert "403" in str(ex.value)
    assert off.queued() == []


# ── reads ──────────────────────────────────────────────────────────────

def test_read_falls_back_to_the_local_mirror(sandbox, monkeypatch):
    key = ems_db_sqlite.upsert_job(display_name="Offline Test Client")
    monkeypatch.setattr(ems_db_supabase, "get_job", _unreachable)
    got = off.get_job(key)
    assert got and got["display_name"] == "Offline Test Client"
    assert off.status()["degraded"] is True


def test_degraded_cooldown_skips_repeated_remote_calls(sandbox, monkeypatch):
    key = ems_db_sqlite.upsert_job(display_name="Cached Client")
    calls = []
    def down(*_a, **_k):
        calls.append("remote")
        return _unreachable()
    monkeypatch.setattr(ems_db_supabase, "get_job", down)
    assert off.get_job(key)
    assert off.get_job(key)
    assert calls == ["remote"]


def test_fallback_can_be_disabled(sandbox, monkeypatch):
    """Conformance runs with it off: answering from SQLite during a real
    outage would let the suite report both backends as identical when it
    never reached one of them."""
    monkeypatch.setattr(off, "FALLBACK_ENABLED", False)
    monkeypatch.setattr(ems_db_supabase, "get_job", _unreachable)
    with pytest.raises(Exception):
        off.get_job("x")


# ── writes ─────────────────────────────────────────────────────────────

def test_write_is_applied_locally_and_queued(sandbox, monkeypatch):
    monkeypatch.setattr(ems_db_supabase, "upsert_job", _unreachable)
    key = off.upsert_job(display_name="Queued Client")

    assert ems_db_sqlite.get_job(key) is not None      # usable right now
    q = off.queued()
    assert len(q) == 1
    assert q[0]["fn"] == "upsert_job"
    assert q[0]["kwargs"]["display_name"] == "Queued Client"


def test_bulk_operations_refuse_rather_than_queue(sandbox, monkeypatch):
    monkeypatch.setattr(ems_db_supabase, "sync_from_trello", _unreachable)
    with pytest.raises(off.OfflineRefused):
        off.sync_from_trello([])
    assert off.queued() == []


def test_missing_optional_job_log_table_falls_back_locally(sandbox,
                                                            monkeypatch):
    key = ems_db_sqlite.upsert_job(display_name="Local Job Log")
    missing = supa_error(404, '{"code":"PGRST205","message":"Could not find '
                         'the table public.crm_job_log_entries"}')
    monkeypatch.setattr(ems_db_supabase, "list_job_log_entries",
                        lambda *_a, **_k: (_ for _ in ()).throw(missing))
    assert off.list_job_log_entries(key) == []
    assert off.status()["schema_fallbacks"] == ["job_log"]


def test_other_404_still_propagates(sandbox, monkeypatch):
    monkeypatch.setattr(ems_db_supabase, "get_job",
                        lambda *_a, **_k: (_ for _ in ()).throw(
                            supa_error(404, '{"code":"PGRST205","message":"missing jobs"}')))
    with pytest.raises(Exception):
        off.get_job("x")


def test_delete_refuses_offline_instead_of_replaying_later(sandbox,
                                                            monkeypatch):
    key = ems_db_sqlite.upsert_job(display_name="Do Not Replay")
    monkeypatch.setattr(ems_db_supabase, "delete_job", _unreachable)
    with pytest.raises(off.OfflineRefused):
        off.delete_job(key)
    assert ems_db_sqlite.get_job(key) is not None
    assert off.queued() == []


def test_unqueueable_write_is_not_applied_locally(sandbox, monkeypatch):
    """A write we cannot replay must not be applied locally either. Doing
    half of it leaves this machine permanently out of step with the shared
    database, with nothing left to say so."""
    monkeypatch.setattr(ems_db_supabase, "set_link", _unreachable)
    unserializable = {"handle": object()}
    with pytest.raises(off.OfflineRefused):
        off.set_link("k", "folder", "C:/x", metadata=unserializable)
    assert off.queued() == []


# ── replay ─────────────────────────────────────────────────────────────

def test_queue_replays_in_order_on_reconnect(sandbox, monkeypatch):
    monkeypatch.setattr(ems_db_supabase, "upsert_job", _unreachable)
    off.upsert_job(display_name="First")
    off.upsert_job(display_name="Second")
    assert len(off.queued()) == 2

    seen = []
    monkeypatch.setattr(ems_db_supabase, "upsert_job",
                        lambda **kw: seen.append(kw["display_name"]))
    res = off.flush_queue()
    assert res["sent"] == 2 and res["pending"] == 0
    assert seen == ["First", "Second"]
    assert off.queued() == []


def test_replay_stops_at_the_first_failure(sandbox, monkeypatch):
    """Draining past a failure reorders the writes — a remove_link landing
    before the set_link it was meant to undo leaves the shared database in
    a state nobody asked for."""
    monkeypatch.setattr(ems_db_supabase, "upsert_job", _unreachable)
    for name in ("A", "B", "C"):
        off.upsert_job(display_name=name)

    seen = []

    def flaky(**kw):
        if kw["display_name"] == "B":
            raise supa_error(0, "unreachable: still down")
        seen.append(kw["display_name"])
    monkeypatch.setattr(ems_db_supabase, "upsert_job", flaky)

    res = off.flush_queue()
    assert res["sent"] == 1
    assert seen == ["A"]
    assert [e["kwargs"]["display_name"] for e in off.queued()] == ["B", "C"]


def test_successful_call_clears_degraded_and_drains(sandbox, monkeypatch):
    monkeypatch.setattr(ems_db_supabase, "upsert_job", _unreachable)
    off.upsert_job(display_name="Pending One")
    assert off.status()["degraded"] is True

    sent = []
    monkeypatch.setattr(ems_db_supabase, "upsert_job",
                        lambda **kw: sent.append(kw["display_name"]))
    monkeypatch.setattr(ems_db_supabase, "get_job", lambda k: {"canon_key": k})
    monkeypatch.setattr(off, "_retry_after", 0.0)

    off.get_job("anything")            # first call that reaches the server
    assert off.status()["degraded"] is False
    assert sent == ["Pending One"]
    assert off.queued() == []


def test_torn_queue_line_is_skipped_not_fatal(sandbox):
    with open(off.QUEUE_PATH, "w", encoding="utf-8") as f:
        f.write(json.dumps({"fn": "upsert_job", "args": [], "kwargs": {}})
                + "\n")
        f.write('{"fn": "upsert_job", "args": [], "kwa')   # power loss
    assert len(off.queued()) == 1
