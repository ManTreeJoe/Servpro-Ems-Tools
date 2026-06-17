"""Audit-key separator hygiene.

The audit/cache keys join (run_date, client, issue) with `::` and are
later parsed via `key.split('::', 1)` and `key.endswith(suffix)`. A
literal `::` inside any part would fork the parse — date_part could
shift to the wrong segment, suffix matches could collide. These tests
pin the escape so future issue text containing `::` (no current data
does, but rare admin notes might) round-trips correctly."""
import pytest

import persistence


@pytest.fixture(autouse=True)
def _isolate_persistence(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(persistence, "_STATE_PATH", str(state_path))
    monkeypatch.setattr(persistence, "_CACHE", None, raising=False)
    monkeypatch.setattr(persistence, "_CACHE_MTIME", None, raising=False)
    yield


def test_set_and_is_resolved_round_trip_with_double_colon_in_issue():
    """`Note: priority::high` would, without escaping, produce a key
    ending in `Note: priority::high` — the trailing `::high` then
    looks like a second separator and `clear_old_resolved` could
    misparse it."""
    persistence.set_resolved("05-04-2026", "Smith",
                              "Note: priority::high", True)
    assert persistence.is_resolved(
        "05-04-2026", "Smith", "Note: priority::high")
    assert not persistence.is_resolved(
        "05-04-2026", "Smith", "Note: priority")
    assert not persistence.is_resolved(
        "05-04-2026", "Smith", "high")


def test_double_colon_in_client_does_not_collide_with_date_split():
    """If a client name like `Smith::Sons` were keyed naively, the
    first split-on-`::` would put `Smith` in the date slot and
    `Sons` in the client slot — wrecking clear_old_resolved's
    date-cutoff filter. Escaping makes the split unambiguous."""
    persistence.set_resolved("05-04-2026", "Smith::Sons", "issue A", True)
    assert persistence.is_resolved("05-04-2026", "Smith::Sons", "issue A")
    # Different client (just `Smith`) must NOT be confused with this one.
    assert not persistence.is_resolved("05-04-2026", "Smith", "issue A")


def test_last_resolved_within_handles_double_colon_issue():
    """Carry-forward lookup uses `key.endswith(suffix)`. The suffix is
    built from the same escape so a `::` issue still matches its
    stored row.

    Uses a date relative to today (not a fixed one) so the record stays
    inside the `days` window no matter when the suite runs — a hardcoded
    past date silently ages out of the window and the test rots."""
    from datetime import date
    today = date.today().strftime("%m-%d-%Y")
    persistence.set_resolved(today, "Smith", "Note: priority::high", True)
    found = persistence.last_resolved_within(
        "Smith", "Note: priority::high", days=30)
    assert found == today


def test_audit_cache_key_round_trip_with_double_colon_in_client():
    """The audit_cache key uses the same separator. A `::`-bearing
    client must not map to the same bucket as a different client
    that happens to share a substring."""
    persistence.set_audit_cache_entry(
        "05-04-2026", "Smith::Sons", None, "C:\\foo", 1234.0,
        {"flagged": False, "marker": "A"})
    persistence.set_audit_cache_entry(
        "05-04-2026", "Smith", None, "C:\\bar", 5678.0,
        {"flagged": False, "marker": "B"})
    a = persistence.get_audit_cache_entry("05-04-2026", "Smith::Sons", None)
    b = persistence.get_audit_cache_entry("05-04-2026", "Smith", None)
    assert a and a["result"]["marker"] == "A"
    assert b and b["result"]["marker"] == "B"
