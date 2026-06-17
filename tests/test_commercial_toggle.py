"""CommercialToggle is the per-job 'Comm.' checkbox + cascade. Locked in
here because it used to live as ~100 lines of copy-pasted code in three
panels — each with subtle drift. The tests pin its behavior so future
edits don't reintroduce the divergence."""
import tkinter as tk

import pytest

import persistence
from job_widgets import CommercialToggle


@pytest.fixture(autouse=True)
def _isolate_persistence(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(persistence, "_STATE_PATH", str(state_path))
    monkeypatch.setattr(persistence, "_CACHE", None, raising=False)
    monkeypatch.setattr(persistence, "_CACHE_MTIME", None, raising=False)
    yield


def test_persist_mode_loads_initial_state(tk_root):
    persistence.set_commercial("Acme Corp", True)
    ct = CommercialToggle(tk_root, "Acme Corp", persist=True)
    assert ct.var.get() is True


def test_persist_false_ignores_sticky_state(tk_root):
    persistence.set_commercial("Acme Corp", True)
    ct = CommercialToggle(tk_root, "Acme Corp", persist=False)
    # persist=False = always start unchecked (Daily Photos session-only mode)
    assert ct.var.get() is False


def test_register_appends_cascade_target(tk_root):
    ct = CommercialToggle(tk_root, "Acme Corp", persist=False)
    var = tk.BooleanVar(master=tk_root, value=False)
    fired = []
    ct.register(var, lambda: fired.append("hit"))
    assert len(ct.toggles) == 1


def test_master_click_cascades_to_registered_items(tk_root):
    ct = CommercialToggle(tk_root, "Acme Corp", persist=False)
    v1 = tk.BooleanVar(master=tk_root, value=False)
    v2 = tk.BooleanVar(master=tk_root, value=False)
    fired = []
    ct.register(v1, lambda: fired.append(1))
    ct.register(v2, lambda: fired.append(2))
    # Simulate user clicking the master Checkbutton.
    ct.var.set(True)
    ct._on_toggle()
    assert v1.get() is True
    assert v2.get() is True
    assert fired == [1, 2]


def test_master_click_persists_when_persist_true(tk_root):
    ct = CommercialToggle(tk_root, "Acme Corp", persist=True)
    ct.var.set(True)
    ct._on_toggle()
    assert persistence.is_commercial("Acme Corp") is True


def test_master_click_does_not_persist_when_persist_false(tk_root):
    ct = CommercialToggle(tk_root, "Acme Corp", persist=False)
    ct.var.set(True)
    ct._on_toggle()
    assert persistence.is_commercial("Acme Corp") is False


def test_auto_apply_if_sticky_fires_for_loaded_true(tk_root):
    """Regression: when the master loaded True from sticky persistence,
    the cascade did NOT fire on init — items rendered red instead of
    struck-through. auto_apply_if_sticky() fixes that."""
    persistence.set_commercial("Acme Corp", True)
    ct = CommercialToggle(tk_root, "Acme Corp", persist=True)
    v = tk.BooleanVar(master=tk_root, value=False)
    fired = []
    ct.register(v, lambda: fired.append("hit"))
    ct.auto_apply_if_sticky()
    assert v.get() is True
    assert fired == ["hit"]


def test_auto_apply_if_sticky_noop_when_loaded_false(tk_root):
    ct = CommercialToggle(tk_root, "Acme Corp", persist=True)
    v = tk.BooleanVar(master=tk_root, value=False)
    fired = []
    ct.register(v, lambda: fired.append("hit"))
    ct.auto_apply_if_sticky()
    # Loaded False → no cascade
    assert v.get() is False
    assert fired == []


def test_auto_apply_skips_already_resolved_items(tk_root):
    """If a per-item var is already True (already resolved from prior
    session), the cascade should NOT re-call its toggle_fn."""
    persistence.set_commercial("Acme Corp", True)
    ct = CommercialToggle(tk_root, "Acme Corp", persist=True)
    v = tk.BooleanVar(master=tk_root, value=True)  # already resolved
    fired = []
    ct.register(v, lambda: fired.append("hit"))
    ct.auto_apply_if_sticky()
    assert fired == []
