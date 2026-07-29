"""Snapshot tech roster Api — add/remove/list techs on the canonical
store (persistence.user_techs) that feeds audit_logic.TECH_PATTERN.

The snapshot recognizes techs in Trello comments via TECH_PATTERN, so a
tech added through the snapshot's "Manage techs" modal must land in that
store and rebuild the live regex — not the disconnected settings
tech_roster.json. These tests pin that wiring."""
import audit_logic
import persistence
import snapshot_web


def _isolate(monkeypatch):
    """Clean, in-memory persistence so the test can't touch the real
    state.json."""
    monkeypatch.setattr(persistence, "_CACHE", {}, raising=False)
    monkeypatch.setattr(persistence, "_CACHE_MTIME", None, raising=False)
    monkeypatch.setattr(persistence, "_save",
                         lambda state: persistence.__dict__.update(
                             _CACHE=state, _CACHE_MTIME=None))
    monkeypatch.setattr(persistence, "_load", lambda: persistence._CACHE)


def _api():
    return snapshot_web.Api()


def test_list_seeds_builtins_as_removable(monkeypatch):
    _isolate(monkeypatch)
    audit_logic.rebuild_tech_pattern()
    out = _api().snapshot_techs()
    assert out["ok"]
    # Opening the roster seeds the former built-ins into the editable store.
    assert "Fernando" in out["all"]
    assert "FB" in out["all"]              # initials offered too
    # Every tech — including the former built-ins — is now in the removable
    # `user` list. None are locked.
    names = {u["name"] for u in out["user"]}
    assert "Fernando" in names
    # Fernando's initials (FB) ride along on its row.
    assert any(u["name"] == "Fernando" and u["initials"] == "FB"
               for u in out["user"])


def test_builtin_tech_can_be_removed(monkeypatch):
    _isolate(monkeypatch)
    api = _api()
    api.snapshot_techs()                  # seed
    # A formerly-locked built-in ("Pablo") is now removable and the removal
    # actually drops it from recognition.
    r = api.remove_snapshot_tech("Pablo")
    try:
        assert r["ok"]
        assert all(u["name"] != "Pablo" for u in r["user"])
        audit_logic.rebuild_tech_pattern()
        assert not audit_logic.TECH_PATTERN.search("Demo - Pablo")
    finally:
        persistence.set_user_techs([], {})
        persistence.__dict__["_CACHE"].pop("user_techs_seeded", None)
        audit_logic.rebuild_tech_pattern()


def test_add_tech_recognized_in_comments(monkeypatch):
    _isolate(monkeypatch)
    api = _api()
    # Baseline: Uli isn't recognized.
    audit_logic.rebuild_tech_pattern()
    assert not audit_logic.TECH_PATTERN.search("Monitor - Uli")

    res = api.add_snapshot_tech("Uli", "UL")
    try:
        assert res["ok"] and res["added"] == "Uli"
        # Now recognized in comment text everywhere.
        assert audit_logic.TECH_PATTERN.search("Monitor - Uli")
        # Shows in the autocomplete + user list.
        assert "Uli" in res["all"]
        assert any(u["name"] == "Uli" and u["initials"] == "UL"
                   for u in res["user"])
    finally:
        persistence.set_user_techs([], {})
        audit_logic.rebuild_tech_pattern()


def test_add_rejects_blank_and_bad_initials(monkeypatch):
    _isolate(monkeypatch)
    api = _api()
    assert not api.add_snapshot_tech("", "")["ok"]
    assert not api.add_snapshot_tech("Uli", "U2")["ok"]


def test_add_duplicate_is_refused(monkeypatch):
    _isolate(monkeypatch)
    api = _api()
    api.snapshot_techs()                  # seed so Fernando is on the list
    # Adding a name already present is refused as a duplicate (not "locked").
    r = api.add_snapshot_tech("Fernando", "")
    assert not r["ok"]
    assert "already" in r["error"].lower()


def test_remove_tech(monkeypatch):
    _isolate(monkeypatch)
    api = _api()
    api.add_snapshot_tech("Uli", "UL")
    try:
        r = api.remove_snapshot_tech("Uli")
        assert r["ok"]
        assert all(u["name"] != "Uli" for u in r["user"])
        audit_logic.rebuild_tech_pattern()
        assert not audit_logic.TECH_PATTERN.search("Monitor - Uli")
    finally:
        persistence.set_user_techs([], {})
        audit_logic.rebuild_tech_pattern()
