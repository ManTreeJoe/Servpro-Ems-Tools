"""Remember where the user left off — launcher panel and per-panel tabs.

The requirement has two halves and the second is the tricky one:
  1. reopen the panel/tab you were last on
  2. NEVER switch away from something you already clicked

Half 2 is a race: the restore is driven by data that arrives after the UI
is interactive. These tests cover the Python side of the contract; the
JS guard (state.userNavigated / state.userSwitchedMode) is asserted by
reading the shipped asset, since there's no JS test runner here.
"""
from __future__ import annotations

import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import persistence

_SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(persistence, "_CACHE", None, raising=False)
    yield


@pytest.fixture
def api(monkeypatch):
    """A HomeApi without pywebview/panel construction."""
    import home_web
    a = home_web.HomeApi.__new__(home_web.HomeApi)
    a._failed_subs = {}
    monkeypatch.setattr(home_web.HomeApi, "_is_panel_visible",
                        lambda self, key: True)
    return a


# ── last panel ──────────────────────────────────────────────────────────

def test_no_last_panel_on_a_fresh_install(api):
    assert api.get_last_panel() == ""


def test_last_panel_round_trips(api):
    assert api.set_last_panel("audit")["ok"]
    assert api.get_last_panel() == "audit"


def test_last_panel_rides_in_on_header(api):
    """It must ship inside header(), not as its own call — a second round
    trip is the window where a late restore steals the user's click."""
    api.set_last_panel("snapshot")
    assert api.header()["last_panel"] == "snapshot"


def test_hidden_panel_is_not_restored(api, monkeypatch):
    """Don't strand the user on a panel they've since hidden."""
    import home_web
    api.set_last_panel("kpi")
    monkeypatch.setattr(home_web.HomeApi, "_is_panel_visible",
                        lambda self, key: key != "kpi")
    assert api.get_last_panel() == ""


def test_dead_panel_is_not_restored(api):
    """A panel whose Api failed to import is a ⚠ tab — never reopen it."""
    api.set_last_panel("hygiene")
    api._failed_subs = {"hygiene": "ImportError"}
    assert api.get_last_panel() == ""


def test_blank_key_clears_it(api):
    api.set_last_panel("audit")
    api.set_last_panel("")
    assert api.get_last_panel() == ""


# ── per-panel UI state ──────────────────────────────────────────────────

def test_ui_state_defaults_to_empty(api):
    assert api.get_ui_state("audit") == {}
    assert api.get_ui_state("") == {}


def test_ui_state_round_trips(api):
    assert api.set_ui_state("audit", {"mode": "daily"})["ok"]
    assert api.get_ui_state("audit") == {"mode": "daily"}


def test_ui_state_merges_rather_than_replaces(api):
    """A panel must be able to save one field without clobbering others."""
    api.set_ui_state("audit", {"mode": "daily"})
    api.set_ui_state("audit", {"filter": "flagged"})
    assert api.get_ui_state("audit") == {"mode": "daily", "filter": "flagged"}


def test_ui_state_is_namespaced_per_panel(api):
    api.set_ui_state("audit", {"mode": "daily"})
    api.set_ui_state("snapshot", {"mode": "search"})
    assert api.get_ui_state("audit")["mode"] == "daily"
    assert api.get_ui_state("snapshot")["mode"] == "search"


def test_ui_state_rejects_bad_input(api):
    assert not api.set_ui_state("", {"a": 1})["ok"]
    assert not api.set_ui_state("audit", "notadict")["ok"]


def test_ui_state_stays_local(api):
    """This is per-user preference, not a team fact: it must live in
    state.json and never reach the shared job index."""
    api.set_ui_state("audit", {"mode": "daily"})
    raw = json.loads(open(persistence._STATE_PATH, encoding="utf-8").read())
    assert raw["ui_state"]["audit"]["mode"] == "daily"


# ── the race guard, asserted against the shipped JS ─────────────────────

def _asset(*parts):
    return open(os.path.join(_SCRIPTS, *parts), encoding="utf-8").read()


def test_launcher_restore_yields_to_a_user_click():
    js = _asset("home_web_assets", "app.js")
    assert "state.userNavigated" in js, "no guard flag in the launcher"
    # navigate() must set the flag for real navigations...
    assert re.search(r"if \(!isRestore\) state\.userNavigated = true", js)
    # ...and the restore must bail when it's set.
    assert re.search(r"function restoreLastPanel\(\)\s*\{\s*\n\s*"
                     r"if \(state\.userNavigated\) return", js)


def test_launcher_restore_does_not_persist_itself():
    """Restoring must not re-save; only real navigations write."""
    js = _asset("home_web_assets", "app.js")
    assert re.search(r"if \(!isRestore\) \{\s*\n\s*try \{ pywebview\?\.api\?\."
                     r"set_last_panel", js)


def test_audit_tab_is_resolved_before_the_first_paint():
    """The landing tab used to be chosen at the END of boot: cached
    daily-run rows were rendered, THEN a trailing switchMode("search")
    ran — so every launch flashed the daily board and jumped to Search.
    The tab must now be applied before the data load that paints."""
    js = _asset("audit_web_assets", "app.js")
    chrome = js.index("if (!state.userSwitchedMode) applyModeChrome(landing)")
    paint = js.index("const cached = await pywebview.api.last_audit()")
    assert chrome < paint, "tab must be set before the first render"


def test_audit_boot_restore_does_not_persist_the_mode():
    """That trailing switchMode("search") passed no isRestore flag, so it
    SAVED mode='search' on every boot and silently overwrote whichever tab
    the user had actually left open. Boot is not a user choice."""
    js = _asset("audit_web_assets", "app.js")
    # Boot applies chrome only (never the persisting switchMode path)…
    assert "applyModeChrome(landing)" in js
    # …and the one switchMode boot may call is marked as a restore.
    assert "await switchMode(state.mode, true)" in js
    # Scoped to the boot tail: switchMode("search") elsewhere is fine, since
    # those are user actions (Audit One, deep-link) that legitimately land
    # the user on Search and should be remembered.
    start = js.index("const _focus = window.emsDeepLinkFocus")
    end = js.index("\n});", start)          # close of the pywebviewready handler
    # Strip // comments — the block documents the old bug by name, and a
    # comment describing it must not read as the bug still being there.
    boot_tail = "\n".join(
        re.sub(r"//.*$", "", ln) for ln in js[start:end].splitlines())
    assert 'switchMode("search")' not in boot_tail, (
        "a bare switchMode('search') at boot re-persists the tab")


def test_audit_switch_mode_sets_the_guard():
    js = _asset("audit_web_assets", "app.js")
    assert re.search(r"if \(!isRestore\) \{\s*\n\s*state\.userSwitchedMode = true",
                     js)


def test_audit_restore_ignores_an_unknown_mode():
    js = _asset("audit_web_assets", "app.js")
    assert '["search", "daily", "starred"].includes(st.mode)' in js


def test_apply_mode_chrome_does_not_load_data():
    """The split exists so boot can set the tab WITHOUT re-running
    switchMode's fetches — otherwise the daily board loads twice."""
    js = _asset("audit_web_assets", "app.js")
    m = re.search(r"function applyModeChrome\(mode\)\s*\{(.*?)\n\}", js, re.S)
    assert m, "applyModeChrome missing"
    assert "pywebview.api" not in m.group(1)
