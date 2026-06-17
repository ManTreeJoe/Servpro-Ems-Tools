"""Unit tests for trello_autotick — covers event-to-item mapping,
idempotency (already-complete items aren't re-ticked), and the
no-checklist-on-card silent-skip path."""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                 "..")))

import pytest
import trello_autotick as at


class FakeTC:
    """In-process Trello stub. Captures ticks against a deterministic
    fake card so we can assert on (card_id, item_id, state) without
    touching the real Trello API."""

    def __init__(self, card):
        self._card = card
        self.calls: list[tuple[str, str, str]] = []

    def get_card(self, card_id, **_):
        if card_id == self._card.get("id"):
            return self._card
        return None

    def set_check_item_state(self, card_id, item_id, state):
        self.calls.append((card_id, item_id, state))
        # Mutate the fake card so a second autotick() call sees the
        # already-complete state.
        for cl in (self._card.get("checklists") or []):
            for it in (cl.get("checkItems") or []):
                if it.get("id") == item_id:
                    it["state"] = state
                    return True
        return False


@pytest.fixture
def fake_tc(monkeypatch):
    card = {
        "id": "card-abc",
        "name": "Smith, John",
        "checklists": [
            {
                "name": "INITIAL - ADMIN",
                "checkItems": [
                    {"id": "i1", "name": "INITIAL PAPERWORK",
                     "state": "incomplete"},
                    {"id": "i2",
                     "name": "INITIAL PHOTOS/PHOTO REPORT",
                     "state": "incomplete"},
                    {"id": "i3", "name": "INITIAL UPLOAD",
                     "state": "incomplete"},
                    {"id": "i4", "name": "PHYSICAL SKETCH",
                     "state": "incomplete"},
                ],
            },
            {
                "name": "INITIAL",
                "checkItems": [
                    {"id": "j1", "name": "INITIAL PAPERWORK",
                     "state": "incomplete"},
                    {"id": "j2", "name": "INITIAL PHOTOS",
                     "state": "incomplete"},
                    {"id": "j3", "name": "PRELIMINARY SKETCH",
                     "state": "incomplete"},
                    {"id": "j4", "name": "PRELIMINARY SCOPE",
                     "state": "incomplete"},
                ],
            },
        ],
    }
    fake = FakeTC(card)
    monkeypatch.setitem(sys.modules, "trello_client", fake)
    return fake


def test_sp_photos_initial_ticks_both_checklists(fake_tc):
    """SP photo import covers Initial photos on EITHER checklist."""
    ticked = at.autotick("card-abc", events=("sp_photos_initial",))
    names = {nm for _, nm in ticked}
    assert "INITIAL PHOTOS/PHOTO REPORT" in names  # ADMIN checklist
    assert "INITIAL PHOTOS" in names                # INITIAL checklist
    # Should NOT touch unrelated items.
    assert "INITIAL PAPERWORK" not in names
    assert "INITIAL UPLOAD" not in names


def test_docusketch_ticks_sketch_only(fake_tc):
    """Docusketch import ticks PHYSICAL SKETCH / PRELIMINARY SKETCH only."""
    ticked = at.autotick("card-abc", events=("docusketch_imported",))
    names = {nm for _, nm in ticked}
    assert "PHYSICAL SKETCH" in names
    assert "PRELIMINARY SKETCH" in names
    assert "PRELIMINARY SCOPE" not in names


def test_scope_ticks_preliminary_scope_only(fake_tc):
    ticked = at.autotick("card-abc", events=("scope_saved",))
    names = {nm for _, nm in ticked}
    assert names == {"PRELIMINARY SCOPE"}


def test_idempotent_no_second_tick(fake_tc):
    """Running autotick twice doesn't double-call Trello — already-
    complete items short-circuit."""
    at.autotick("card-abc", events=("scope_saved",))
    calls_after_first = len(fake_tc.calls)
    at.autotick("card-abc", events=("scope_saved",))
    assert len(fake_tc.calls) == calls_after_first


def test_unknown_event_no_op(fake_tc):
    ticked = at.autotick("card-abc", events=("never_heard_of_this",))
    assert ticked == []
    assert fake_tc.calls == []


def test_no_card_id_no_op():
    """Empty card_id short-circuits before any Trello call."""
    assert at.autotick("", events=("scope_saved",)) == []


def test_no_checklist_silent_skip(monkeypatch):
    """Card that doesn't have either tracked checklist returns [] silently."""
    card = {"id": "card-xyz", "checklists": []}
    fake = FakeTC(card)
    monkeypatch.setitem(sys.modules, "trello_client", fake)
    ticked = at.autotick("card-xyz", events=("scope_saved",))
    assert ticked == []
    assert fake.calls == []


def test_multiple_events_union(fake_tc):
    """Multiple events combine targets — sp_photos + docusketch ticks
    photos AND sketch items in one pass."""
    ticked = at.autotick("card-abc",
                          events=("sp_photos_initial",
                                   "docusketch_imported"))
    names = {nm for _, nm in ticked}
    assert "INITIAL PHOTOS" in names
    assert "PHYSICAL SKETCH" in names


def test_autotick_summary_empty():
    assert at.autotick_summary([]) == ""


def test_autotick_summary_single():
    out = at.autotick_summary([("INITIAL - ADMIN", "PHYSICAL SKETCH")])
    assert "PHYSICAL SKETCH" in out
    assert "INITIAL - ADMIN" in out


def test_autotick_summary_multiple():
    out = at.autotick_summary([
        ("INITIAL - ADMIN", "PHYSICAL SKETCH"),
        ("INITIAL", "PRELIMINARY SKETCH"),
    ])
    assert "2 checklist items" in out
