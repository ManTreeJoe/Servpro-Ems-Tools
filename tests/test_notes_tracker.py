"""Tracked to-do notes — add / filter / done / delete."""
import persistence
import notes_tracker as nt


def _iso(monkeypatch):
    state = {}
    monkeypatch.setattr(persistence, "_load", lambda: state)
    monkeypatch.setattr(persistence, "_save", lambda s: state.update(s))
    return state


def test_add_and_filter_by_job(monkeypatch):
    _iso(monkeypatch)
    nt.add("Chase scope", job="Mims, Stewart")
    nt.add("Order air movers")                       # untied
    nt.add("Call adjuster", job="Doe, Jane")
    # All open.
    assert len(nt.list_notes()) == 3
    # By job (case-insensitive).
    assert [n["text"] for n in nt.list_notes(job="mims, stewart")] == ["Chase scope"]
    # Untied only.
    assert [n["text"] for n in nt.list_notes(job="__untied__")] == ["Order air movers"]


def test_done_hides_and_moves(monkeypatch):
    _iso(monkeypatch)
    a = nt.add("todo A")["note"]
    nt.add("todo B")
    nt.set_done(a["id"], True)
    # Default excludes done.
    assert [n["text"] for n in nt.list_notes()] == ["todo B"]
    # include_done shows both, open before done.
    both = nt.list_notes(include_done=True)
    assert [n["text"] for n in both] == ["todo B", "todo A"]
    assert both[-1]["done"] and both[-1]["done_at"]
    # Reopen.
    nt.set_done(a["id"], False)
    assert nt.open_count() == 2


def test_update_and_delete(monkeypatch):
    _iso(monkeypatch)
    n = nt.add("typo")["note"]
    nt.update(n["id"], "fixed text")
    assert nt.list_notes()[0]["text"] == "fixed text"
    assert nt.update(n["id"], "  ")["ok"] is False        # empty rejected
    nt.delete(n["id"])
    assert nt.list_notes() == []
    assert nt.delete(999)["ok"] is False


def test_empty_note_rejected(monkeypatch):
    _iso(monkeypatch)
    assert nt.add("   ")["ok"] is False
    assert nt.list_notes() == []
