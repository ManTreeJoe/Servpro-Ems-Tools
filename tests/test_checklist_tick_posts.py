"""Ticking a checklist item posts the comment that goes with it.

The office used to tick the item on Trello AND press a separate button to
post the comment — two actions for one fact, and the comment was the half
that got forgotten. Now the tick IS the action.

Live items (INITIAL - ADMIN / IN PROGRESS - ADMIN):

    INITIAL PHOTOS/PHOTO REPORT  -> "Initial Photo Report Created and Uploaded to OD."
    INITIAL UPLOAD               -> "Initial Upload submitted To WC."
    ORDER DOCUSKETCH             -> request_docusketch (comment + Hygiene tracking)

"ORDER DOCUSKETCH" is a REQUEST, not a completion — ticking it means the
sketch has been ordered, which is exactly what request_docusketch records.
"""
import pytest

from audit_web import Api


class _Stub(Api):
    """Api with the network ends replaced."""

    def __init__(self):
        self.posted = []
        self.sketched = []
        self._inprog_cl_cache = {}
        self._initial_cl_cache = {}
        self.tick_ok = True

    def post_canned(self, card_id, key):
        self.posted.append((card_id, key))
        return {"ok": True, "text": f"canned:{key}"}

    def request_docusketch(self, client, card_id=""):
        self.sketched.append((client, card_id))
        return {"ok": True, "card_id": card_id}


@pytest.fixture
def api(monkeypatch):
    a = _Stub()

    class _FakeTrello:
        @staticmethod
        def set_check_item_state(card_id, item_id, state):
            return a.tick_ok

    import sys
    monkeypatch.setitem(sys.modules, "trello_client", _FakeTrello)
    return a


# ── the mapping itself ─────────────────────────────────────────────────

@pytest.mark.parametrize("name,want", [
    ("INITIAL PHOTOS/PHOTO REPORT", ("canned", "ipr")),
    ("INITIAL UPLOAD", ("canned", "upload")),
    ("ORDER DOCUSKETCH", ("docusketch", "")),
])
def test_the_mapped_items(name, want):
    assert Api._TICK_POSTS[Api._tick_key(name)] == want


def test_item_names_are_matched_normalized():
    """A live item is literally ' INITIAL PAPERWORK' — leading space and
    all — so exact matching would miss."""
    assert Api._tick_key("  INITIAL PHOTOS/PHOTO REPORT ") == \
        "initial photos/photo report"
    assert Api._TICK_POSTS.get(Api._tick_key(" initial upload"))


@pytest.mark.parametrize("name", ["SPREADSHEET", "PHYSICAL SKETCH",
                                  "FINAL PHOTOS", "DEMO PHOTOS", ""])
def test_unmapped_items_post_nothing(name):
    assert Api._TICK_POSTS.get(Api._tick_key(name)) is None


# ── behaviour ──────────────────────────────────────────────────────────

def test_ticking_posts_the_comment(api):
    r = api.toggle_checklist_item("c1", "i1", True,
                                  item_name="INITIAL UPLOAD")
    assert r["ok"] is True
    assert api.posted == [("c1", "upload")]
    assert r["comment_ok"] is True


def test_unticking_posts_nothing(api):
    """Un-ticking is a correction, not an announcement."""
    api.toggle_checklist_item("c1", "i1", False, item_name="INITIAL UPLOAD")
    assert api.posted == []


def test_an_already_complete_item_does_not_post_again(api):
    """Re-ticking something already ticked must not spam the card."""
    api._initial_cl_cache["c1"] = (0, {"items": [{"id": "i1",
                                                  "complete": True}]})
    api.toggle_checklist_item("c1", "i1", True, item_name="INITIAL UPLOAD")
    assert api.posted == []


def test_an_incomplete_item_in_cache_still_posts(api):
    api._initial_cl_cache["c1"] = (0, {"items": [{"id": "i1",
                                                  "complete": False}]})
    api.toggle_checklist_item("c1", "i1", True, item_name="INITIAL UPLOAD")
    assert api.posted == [("c1", "upload")]


def test_order_docusketch_makes_a_request_not_a_comment(api):
    """It records the pending entry Hygiene watches, which a plain
    comment would not."""
    api.toggle_checklist_item("c1", "i1", True,
                              item_name="ORDER DOCUSKETCH",
                              client="Abbott, Darlene")
    assert api.sketched == [("Abbott, Darlene", "c1")]
    assert api.posted == []


def test_an_unmapped_tick_is_just_a_tick(api):
    r = api.toggle_checklist_item("c1", "i1", True,
                                  item_name="PHYSICAL SKETCH")
    assert r["ok"] is True
    assert api.posted == [] and api.sketched == []
    assert "comment" not in r


def test_a_failed_tick_posts_nothing(api):
    """The comment announces a state change that didn't happen."""
    api.tick_ok = False
    api.toggle_checklist_item("c1", "i1", True, item_name="INITIAL UPLOAD")
    assert api.posted == []


def test_a_failed_comment_does_not_fail_the_tick(api, monkeypatch):
    """The checklist state is the user's action and it succeeded. Failing
    the whole call would make them click it again — and tick it twice."""
    def _boom(card_id, key):
        raise RuntimeError("trello down")

    monkeypatch.setattr(api, "post_canned", _boom)
    r = api.toggle_checklist_item("c1", "i1", True,
                                  item_name="INITIAL UPLOAD")
    assert r["ok"] is True
    assert r["comment_ok"] is False
    assert "trello down" in r["comment_error"]


def test_no_item_name_behaves_as_before(api):
    """Older callers pass no name; they must keep working."""
    r = api.toggle_checklist_item("c1", "i1", True)
    assert r["ok"] is True
    assert api.posted == []


# ── un-ticking takes the comment back ──────────────────────────────────

@pytest.fixture
def api_with_store(api, monkeypatch, tmp_path):
    """`api`, plus an isolated persistence store and a fake delete."""
    import persistence
    store = {}
    monkeypatch.setattr(persistence, "get",
                        lambda k, d=None: store.get(k, d))
    monkeypatch.setattr(persistence, "set_value",
                        lambda k, v: store.__setitem__(k, v))

    deleted = []

    class _FakeTrello:
        @staticmethod
        def set_check_item_state(card_id, item_id, state):
            return api.tick_ok

        @staticmethod
        def delete_comment(action_id):
            deleted.append(action_id)
            return True

    import sys
    monkeypatch.setitem(sys.modules, "trello_client", _FakeTrello)

    def _post_canned(card_id, key):
        api.posted.append((card_id, key))
        return {"ok": True, "text": f"canned:{key}", "action_id": "act-1"}

    monkeypatch.setattr(api, "post_canned", _post_canned)
    return api, store, deleted


def test_unticking_deletes_the_comment_the_tick_posted(api_with_store):
    """The tick announced it; undoing the tick must retract it, or the
    card claims something that is no longer true."""
    api, store, deleted = api_with_store
    api.toggle_checklist_item("c1", "i1", True, item_name="INITIAL UPLOAD")
    assert store["tick_comment_actions"]["c1|i1"] == "act-1"

    r = api.toggle_checklist_item("c1", "i1", False, item_name="INITIAL UPLOAD")

    assert deleted == ["act-1"]
    assert r["comment_deleted"] is True
    assert "c1|i1" not in store["tick_comment_actions"]


def test_unticking_something_we_never_posted_deletes_nothing(api_with_store):
    """Only comments this tick created are ours to remove."""
    api, store, deleted = api_with_store
    api.toggle_checklist_item("c1", "i9", False, item_name="SPREADSHEET")
    assert deleted == []


def test_a_comment_deleted_by_hand_is_not_retried_forever(api_with_store,
                                                          monkeypatch):
    """If it is already gone on Trello, drop the record anyway."""
    api, store, deleted = api_with_store
    api.toggle_checklist_item("c1", "i1", True, item_name="INITIAL UPLOAD")

    import sys
    fake = sys.modules["trello_client"]
    monkeypatch.setattr(fake, "delete_comment", staticmethod(lambda a: False))

    api.toggle_checklist_item("c1", "i1", False, item_name="INITIAL UPLOAD")
    assert "c1|i1" not in store["tick_comment_actions"]


def test_re_ticking_after_an_untick_posts_again(api_with_store):
    """Un-tick cleared the record, so the item is genuinely not-done and
    ticking it announces it once more."""
    api, store, deleted = api_with_store
    api.toggle_checklist_item("c1", "i1", True, item_name="INITIAL UPLOAD")
    api.toggle_checklist_item("c1", "i1", False, item_name="INITIAL UPLOAD")
    api.posted.clear()
    api.toggle_checklist_item("c1", "i1", True, item_name="INITIAL UPLOAD")
    assert api.posted == [("c1", "upload")]
