"""Unit tests for missing_items_tracker.

Covers capture / list / resolve / ignore / unignore for missing items
and the docusign-resend SLA escalation logic. Trello/post_comment paths
are monkey-patched out so tests don't reach the network."""
from __future__ import annotations

import datetime as _dt
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import persistence


@pytest.fixture(autouse=True)
def _isolate_persistence(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(persistence, "_STATE_PATH", str(state_path))
    monkeypatch.setattr(persistence, "_CACHE", None, raising=False)
    monkeypatch.setattr(persistence, "_CACHE_MTIME", None, raising=False)
    # Stub trello_client.post_comment so capture() doesn't reach the
    # network. Track calls so tests can assert against them.
    import trello_client as tc
    calls: list[tuple] = []
    monkeypatch.setattr(tc, "post_comment",
                         lambda cid, text: calls.append((cid, text)))
    yield calls


import missing_items_tracker as mit


# ── capture_missing_items ─────────────────────────────────────────────

def test_capture_creates_one_row_per_item():
    ids = mit.capture_missing_items(
        "Doe, John", card_id="abc", missing=["atp", "cif", "scope"])
    assert len(ids) == 3
    rows = mit.list_open_items()
    assert len(rows) == 3
    labels = {r["item_label"] for r in rows}
    assert labels == {"ATP form", "CIF form", "Scope"}


def test_capture_idempotent_on_same_card_and_item():
    """Re-capturing the same (client, card, item) updates snapshot_at
    rather than creating a duplicate row."""
    ids_first = mit.capture_missing_items(
        "Doe, John", card_id="abc", missing=["atp"])
    ids_second = mit.capture_missing_items(
        "Doe, John", card_id="abc", missing=["atp"])
    assert ids_first == ids_second
    assert len(mit.list_open_items()) == 1


def test_capture_passes_through_unknown_item_label():
    """Audit-style labels we haven't pre-canonicalized stay as-is."""
    mit.capture_missing_items(
        "Doe, John", card_id="abc",
        missing=["Some Custom Item"])
    row = mit.list_open_items()[0]
    assert row["item_label"] == "Some Custom Item"


def test_capture_posts_trello_comment_with_mention(_isolate_persistence):
    """Trello comment is posted exactly once on first capture and
    embeds the tech @mention + every newly-tracked item."""
    calls = _isolate_persistence
    mit.capture_missing_items(
        "Doe, John", card_id="abc",
        missing=["atp", "cif"], tech_initials="FB")
    assert len(calls) == 1
    cid, msg = calls[0]
    assert cid == "abc"
    assert "@FB" in msg
    assert "ATP form" in msg and "CIF form" in msg


def test_capture_does_not_repost_on_idempotent_recapture(
        _isolate_persistence):
    """Re-capture within the cooldown window is a no-op for Trello —
    one comment per request day, not per call."""
    calls = _isolate_persistence
    mit.capture_missing_items(
        "Doe, John", card_id="abc", missing=["atp"], tech_initials="FB")
    mit.capture_missing_items(
        "Doe, John", card_id="abc", missing=["atp"], tech_initials="FB")
    assert len(calls) == 1


# ── Repeat-request escalation ──────────────────────────────────────────

def _force_old_comment(monkeypatch, hours_back):
    """Backdate the most recent Trello comment timestamp on EVERY open
    missing_items row so the next capture call counts as a new request
    day. Used to simulate a day-later run without time.sleep."""
    import persistence
    data = persistence.get("missing_items") or {}
    past = (_dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None) - _dt.timedelta(hours=hours_back)).replace(
        microsecond=0).isoformat()
    for rec in data.values():
        if isinstance(rec, dict) and rec.get("status") == "open":
            rec["trello_comment_posted_at"] = past
    persistence.set_value("missing_items", data)


def test_repeat_request_increments_count_and_posts_escalation(
        _isolate_persistence, monkeypatch):
    """A second capture call after the cooldown window posts an
    escalation comment that @-tags Zac + Sam and counts as the 2nd
    request."""
    calls = _isolate_persistence
    ids = mit.capture_missing_items(
        "Doe, John", card_id="abc", missing=["atp"], tech_initials="FB")
    assert len(calls) == 1
    _force_old_comment(monkeypatch, hours_back=24)
    mit.capture_missing_items(
        "Doe, John", card_id="abc", missing=["atp"], tech_initials="FB")
    assert len(calls) == 2
    _, repeat_msg = calls[1]
    assert "2nd" in repeat_msg.lower()
    assert "@zac" in repeat_msg.lower()
    assert "@sam" in repeat_msg.lower()
    assert "@fb" in repeat_msg.lower()       # tech still mentioned

    row = mit.list_open_items()[0]
    assert row["request_count"] == 2


def test_third_request_uses_3rd_ordinal(_isolate_persistence, monkeypatch):
    mit.capture_missing_items(
        "Doe, John", card_id="abc", missing=["atp"], tech_initials="FB")
    _force_old_comment(monkeypatch, hours_back=24)
    mit.capture_missing_items(
        "Doe, John", card_id="abc", missing=["atp"], tech_initials="FB")
    _force_old_comment(monkeypatch, hours_back=24)
    mit.capture_missing_items(
        "Doe, John", card_id="abc", missing=["atp"], tech_initials="FB")
    calls = _isolate_persistence
    assert "3rd" in calls[-1][1].lower()
    assert mit.list_open_items()[0]["request_count"] == 3


def test_recapture_within_cooldown_does_not_escalate(
        _isolate_persistence, monkeypatch):
    """Capturing twice in quick succession (same calendar day) must
    NOT bump request_count or post the escalation note."""
    calls = _isolate_persistence
    mit.capture_missing_items(
        "Doe, John", card_id="abc", missing=["atp"], tech_initials="FB")
    # No timestamp backdating — second call sits inside cooldown
    mit.capture_missing_items(
        "Doe, John", card_id="abc", missing=["atp"], tech_initials="FB")
    assert len(calls) == 1
    assert mit.list_open_items()[0]["request_count"] == 1


def test_capture_skips_trello_when_no_card_id(_isolate_persistence):
    calls = _isolate_persistence
    mit.capture_missing_items(
        "Doe, John", missing=["atp"], tech_initials="FB")
    assert calls == []


def test_capture_skips_trello_when_post_comment_false(
        _isolate_persistence):
    calls = _isolate_persistence
    mit.capture_missing_items(
        "Doe, John", card_id="abc", missing=["atp"],
        post_comment=False)
    assert calls == []


# ── list_open_items ─────────────────────────────────────────────────────

def test_list_open_items_excludes_resolved_and_ignored_by_default():
    ids = mit.capture_missing_items(
        "Doe, John", card_id="abc",
        missing=["atp", "cif", "scope"])
    mit.mark_resolved(ids[0])
    mit.mark_ignored(ids[1], reason="client out of country")
    assert {r["item_label"] for r in mit.list_open_items()} == {"Scope"}


def test_list_open_items_include_flags():
    ids = mit.capture_missing_items(
        "Doe, John", card_id="abc", missing=["atp", "cif"])
    mit.mark_resolved(ids[0])
    assert len(mit.list_open_items(include_resolved=True)) == 2
    mit.mark_ignored(ids[1], reason="x")
    assert len(mit.list_open_items(include_ignored=True)) == 1
    assert len(mit.list_open_items(include_ignored=True,
                                     include_resolved=True)) == 2


def test_age_days_computed_from_snapshot_at(monkeypatch):
    """Age should track snapshot_at, not capture time."""
    past = (_dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None) - _dt.timedelta(days=4)).replace(
        microsecond=0).isoformat()
    mit.capture_missing_items(
        "Doe, John", card_id="abc", missing=["atp"],
        snapshot_at=past)
    row = mit.list_open_items()[0]
    assert row["age_days"] == 4


# ── mark_ignored / unignore ────────────────────────────────────────────

def test_mark_ignored_records_reason():
    ids = mit.capture_missing_items(
        "Doe, John", card_id="abc", missing=["atp"])
    mit.mark_ignored(ids[0], reason="long-term commercial — closing 2027")
    rec = mit.list_open_items(include_ignored=True)[0]
    assert rec["status"] == "ignored"
    assert "closing 2027" in rec["ignore_reason"]


def test_unignore_restores_to_open():
    ids = mit.capture_missing_items(
        "Doe, John", card_id="abc", missing=["atp"])
    mit.mark_ignored(ids[0], reason="x")
    mit.unignore(ids[0])
    rec = mit.list_open_items()[0]
    assert rec["status"] == "open"
    assert rec["ignore_reason"] == ""


# ── Docusign resend SLA ───────────────────────────────────────────────

def test_record_docusign_resend_creates_row(_isolate_persistence):
    calls = _isolate_persistence
    rid = mit.record_docusign_resend("Doe, John", card_id="abc")
    assert rid is not None
    rows = mit.list_docusign_resends()
    assert len(rows) == 1
    assert rows[0]["client"] == "Doe, John"
    assert rows[0]["status"] == "pending"
    # Trello comment posted on the card
    assert any(c[0] == "abc" for c in calls)


def test_record_docusign_resend_restarts_timer_on_same_card():
    rid_first = mit.record_docusign_resend(
        "Doe, John", card_id="abc", post_comment=False)
    rid_second = mit.record_docusign_resend(
        "Doe, John", card_id="abc", post_comment=False)
    assert rid_first == rid_second
    assert len(mit.list_docusign_resends()) == 1


def test_needs_physical_signature_threshold(_isolate_persistence):
    """A resend 6 days old should appear; a 2-day-old one should not."""
    # Force resend timestamps directly via persistence.
    old = (_dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None) - _dt.timedelta(days=6)).replace(
        microsecond=0).isoformat()
    new = (_dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None) - _dt.timedelta(days=2)).replace(
        microsecond=0).isoformat()
    persistence.set_value("docusign_resends", {
        "old": {"id": "old", "client": "Old Job", "card_id": "card_old",
                "resent_at": old, "status": "pending",
                "escalation_posted_at": None},
        "new": {"id": "new", "client": "New Job", "card_id": "card_new",
                "resent_at": new, "status": "pending",
                "escalation_posted_at": None},
    })
    rows = mit.needs_physical_signature(threshold_days=5)
    assert {r["client"] for r in rows} == {"Old Job"}


def test_needs_physical_signature_posts_escalation_once(
        _isolate_persistence):
    """First call past threshold posts the escalation; subsequent calls
    don't repost."""
    calls = _isolate_persistence
    old = (_dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None) - _dt.timedelta(days=7)).replace(
        microsecond=0).isoformat()
    persistence.set_value("docusign_resends", {
        "old": {"id": "old", "client": "Old Job", "card_id": "card_old",
                "resent_at": old, "status": "pending",
                "escalation_posted_at": None},
    })
    mit.needs_physical_signature(threshold_days=5)
    posts_before = len(calls)
    mit.needs_physical_signature(threshold_days=5)
    posts_after = len(calls)
    assert posts_after == posts_before    # idempotent


def test_mark_docusign_signed_clears_from_active_list():
    rid = mit.record_docusign_resend(
        "Doe, John", card_id="abc", post_comment=False)
    mit.mark_docusign_signed(rid)
    assert mit.list_docusign_resends() == []


def test_mark_physical_signature_done_clears_from_active_list():
    rid = mit.record_docusign_resend(
        "Doe, John", card_id="abc", post_comment=False)
    mit.mark_physical_signature_done(rid, note="front desk visited")
    assert mit.list_docusign_resends() == []
    rows = mit.list_docusign_resends(include_resolved=True)
    assert rows[0]["status"] == "physical_signature_done"
    assert rows[0]["physical_signature_note"] == "front desk visited"
