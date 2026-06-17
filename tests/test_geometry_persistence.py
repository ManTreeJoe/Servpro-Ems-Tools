"""Window geometry persistence on ToolPanel.

Embedded mode must NOT write — `self.geometry()` returns the launcher's
geometry there, and writing it would clobber the saved standalone size.
The bug fixed when ToolPanel.save_geometry() was introduced.
"""
import sys
import types
import pytest

import tool_panel


class _FakePersistence:
    """Stand-in for the persistence module so the test doesn't touch state.json."""
    def __init__(self):
        self.store = {}

    def get_geometry(self, key):
        return self.store.get(key)

    def set_geometry(self, key, geo):
        if geo:
            self.store[key] = geo


@pytest.fixture
def fake_persistence(monkeypatch):
    fake = _FakePersistence()
    mod = types.ModuleType("persistence")
    mod.get_geometry = fake.get_geometry
    mod.set_geometry = fake.set_geometry
    monkeypatch.setitem(sys.modules, "persistence", mod)
    return fake


class _StubPanel:
    """Minimal stand-in — exercises the methods without spinning up Tk."""
    TOOL_GEOMETRY_KEY = "stub_tool"
    DEFAULT_GEOMETRY  = "500x500"

    def __init__(self, embedded):
        self._embedded = embedded
        self._geo_calls = []

    def geometry(self, geo=None):
        if geo is None:
            return "999x888+10+20"
        self._geo_calls.append(geo)

    save_geometry    = tool_panel.ToolPanel.save_geometry
    restore_geometry = tool_panel.ToolPanel.restore_geometry


def test_embedded_save_is_a_noop(fake_persistence):
    panel = _StubPanel(embedded=True)
    panel.save_geometry()
    assert fake_persistence.store == {}


def test_standalone_save_writes_geometry(fake_persistence):
    panel = _StubPanel(embedded=False)
    panel.save_geometry()
    assert fake_persistence.store == {"stub_tool": "999x888+10+20"}


def test_save_with_no_key_is_a_noop(fake_persistence):
    panel = _StubPanel(embedded=False)
    panel.TOOL_GEOMETRY_KEY = None
    panel.save_geometry()
    assert fake_persistence.store == {}


def test_embedded_restore_is_a_noop(fake_persistence):
    fake_persistence.store["stub_tool"] = "777x666"
    panel = _StubPanel(embedded=True)
    panel.restore_geometry()
    # Embedded restore must NOT call self.geometry(...) — that would resize
    # the launcher window every time the embedded panel constructed.
    assert panel._geo_calls == []


def test_standalone_restore_uses_saved_geometry(fake_persistence):
    fake_persistence.store["stub_tool"] = "777x666+5+5"
    panel = _StubPanel(embedded=False)
    panel.restore_geometry()
    assert panel._geo_calls == ["777x666+5+5"]


def test_standalone_restore_falls_back_to_default(fake_persistence):
    panel = _StubPanel(embedded=False)
    panel.restore_geometry()
    assert panel._geo_calls == ["500x500"]
