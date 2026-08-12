"""Per-department UI state.

Saved panel state is mostly about jobs — selected row, search term,
filter, active tab. A single shared key meant switching IE→OC restored
IE's selection onto OC's board. These pin the scoping and, just as
importantly, that the upgrade doesn't throw away state saved before it.
"""
import pytest

import home_web


@pytest.fixture
def api(monkeypatch):
    """HomeApi with an in-memory persistence store, no window."""
    store = {}

    def _get(key, default=None):
        return store.get(key, default)

    def _set_value(key, val):
        store[key] = val

    monkeypatch.setattr(home_web.persistence, "get", _get)
    monkeypatch.setattr(home_web.persistence, "set_value", _set_value)
    a = home_web.HomeApi.__new__(home_web.HomeApi)   # skip __init__ / sub-Apis
    return a, store


def _dept(monkeypatch, name):
    import config
    monkeypatch.setattr(config, "active_department", lambda: name)


def test_state_is_scoped_to_the_department(api, monkeypatch):
    a, store = api
    _dept(monkeypatch, "IE")
    a.set_ui_state("audit", {"tab": "daily", "selected": "smith, john"})
    _dept(monkeypatch, "OC")
    assert a.get_ui_state("audit") == {}          # OC starts clean
    a.set_ui_state("audit", {"tab": "search"})
    _dept(monkeypatch, "IE")
    # IE is untouched by anything OC did.
    assert a.get_ui_state("audit") == {"tab": "daily", "selected": "smith, john"}


def test_each_department_comes_back_to_its_own_place(api, monkeypatch):
    a, _ = api
    _dept(monkeypatch, "IE")
    a.set_ui_state("hygiene", {"scroll": 120})
    _dept(monkeypatch, "OC")
    a.set_ui_state("hygiene", {"scroll": 940})
    _dept(monkeypatch, "IE")
    assert a.get_ui_state("hygiene")["scroll"] == 120
    _dept(monkeypatch, "OC")
    assert a.get_ui_state("hygiene")["scroll"] == 940


def test_panels_stay_separate_within_a_department(api, monkeypatch):
    a, _ = api
    _dept(monkeypatch, "IE")
    a.set_ui_state("audit", {"tab": "daily"})
    a.set_ui_state("snapshot", {"tab": "recent"})
    assert a.get_ui_state("audit") == {"tab": "daily"}
    assert a.get_ui_state("snapshot") == {"tab": "recent"}


def test_legacy_unscoped_state_is_still_read(api, monkeypatch):
    """State saved before scoping must not vanish on upgrade."""
    a, store = api
    store["ui_state"] = {"audit": {"tab": "daily", "scroll": 40}}
    _dept(monkeypatch, "IE")
    assert a.get_ui_state("audit") == {"tab": "daily", "scroll": 40}


def test_first_write_after_upgrade_keeps_the_other_legacy_fields(api, monkeypatch):
    """Patching one field must not drop the rest of the legacy entry."""
    a, store = api
    store["ui_state"] = {"audit": {"tab": "daily", "scroll": 40}}
    _dept(monkeypatch, "IE")
    a.set_ui_state("audit", {"tab": "search"})
    assert a.get_ui_state("audit") == {"tab": "search", "scroll": 40}


def test_writing_scoped_leaves_the_legacy_entry_alone(api, monkeypatch):
    """The other department can still claim the legacy state."""
    a, store = api
    store["ui_state"] = {"audit": {"tab": "daily"}}
    _dept(monkeypatch, "IE")
    a.set_ui_state("audit", {"tab": "search"})
    assert store["ui_state"]["audit"] == {"tab": "daily"}
    assert store["ui_state"]["IE:audit"] == {"tab": "search"}


def test_no_department_falls_back_to_the_bare_key(api, monkeypatch):
    """A single-franchise install has no dept — don't invent a prefix."""
    a, store = api
    _dept(monkeypatch, "")
    a.set_ui_state("audit", {"tab": "daily"})
    assert "audit" in store["ui_state"]
    assert a.get_ui_state("audit") == {"tab": "daily"}


def test_unreadable_department_does_not_break_the_store(api, monkeypatch):
    """config blowing up must not cost the user their panel state."""
    a, _ = api
    import config

    def _boom():
        raise RuntimeError("config unavailable")

    monkeypatch.setattr(config, "active_department", _boom)
    assert a.set_ui_state("audit", {"tab": "daily"})["ok"] is True
    assert a.get_ui_state("audit") == {"tab": "daily"}


def test_bad_input_is_rejected(api, monkeypatch):
    a, _ = api
    _dept(monkeypatch, "IE")
    assert a.set_ui_state("", {"tab": "x"})["ok"] is False
    assert a.set_ui_state("audit", "nope")["ok"] is False
