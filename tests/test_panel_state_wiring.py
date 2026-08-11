"""Panels remember where you were.

HomeApi has had `get_ui_state` / `set_ui_state` — a per-panel merge-patch
store — for a while, but only the audit panel ever called it, and only
for its active tab. Panels live in iframes and are destroyed on
navigate, so every filter, search box and tab reset on the way back in.

`web_shared/panel_state.js` is the shared front end. These tests pin the
wiring, which is the part that rots: a panel that loads the script but
never calls it, or calls it without loading the script, both look fine
until someone tries to use the panel.
"""
import os
import re

import pytest

_SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Panels wired so far. Adding a panel here without wiring it fails.
WIRED = ["audit", "hygiene", "pipeline"]


def _read(*parts):
    with open(os.path.join(_SCRIPTS, *parts), encoding="utf-8") as f:
        return f.read()


def _panel_js(panel):
    """The panel's script, whether it lives in app.js or inline."""
    app = os.path.join(_SCRIPTS, f"{panel}_web_assets", "app.js")
    if os.path.isfile(app):
        return _read(f"{panel}_web_assets", "app.js")
    return _read(f"{panel}_web_assets", "index.html")


# ── the shared module ──────────────────────────────────────────────────
def test_panel_state_exports_the_documented_surface():
    js = _read("web_shared", "panel_state.js")
    for fn in ("init", "get", "set", "all", "flush",
               "bindScroll", "restoreScroll"):
        assert re.search(rf"\b{fn}\b", js), f"PanelState.{fn} missing"
    assert "window.PanelState" in js


def test_writes_are_debounced():
    """set_ui_state lands in state.json and a save there costs ~23ms.
    An undebounced scroll handler would write on every frame."""
    js = _read("web_shared", "panel_state.js")
    assert "setTimeout(flush" in js
    assert "FLUSH_MS" in js


def test_pending_writes_are_flushed_on_teardown():
    """Navigating away destroys the iframe mid-debounce. Without a flush
    the last thing you changed is exactly the thing that never persists."""
    js = _read("web_shared", "panel_state.js")
    for ev in ("visibilitychange", "pagehide", "beforeunload"):
        assert ev in js, f"no flush on {ev}"


def test_missing_store_is_not_fatal():
    """Standalone windows have no HomeApi. The panel must still open."""
    js = _read("web_shared", "panel_state.js")
    assert "catch" in js
    assert "api.get_ui_state" in js


# ── per-panel wiring ───────────────────────────────────────────────────
@pytest.mark.parametrize("panel", WIRED)
def test_panel_loads_the_script(panel):
    html = _read(f"{panel}_web_assets", "index.html")
    assert "panel_state.js" in html, \
        f"{panel}/index.html does not load panel_state.js"


@pytest.mark.parametrize("panel", WIRED)
def test_script_loads_after_the_iframe_shim(panel):
    """PanelState calls through window.pywebview.api, which the shim
    installs. Loading it first would give it no API to talk to."""
    html = _read(f"{panel}_web_assets", "index.html")
    assert html.index("iframe_shim.js") < html.index("panel_state.js"), \
        f"{panel}: panel_state.js must come after iframe_shim.js"


@pytest.mark.parametrize("panel", WIRED)
def test_panel_initialises_with_its_own_key(panel):
    js = _panel_js(panel)
    assert re.search(rf'PanelState\.init\(\s*["\']{panel}["\']', js), \
        f"{panel} never calls PanelState.init(\"{panel}\")"


@pytest.mark.parametrize("panel", WIRED)
def test_panel_saves_something(panel):
    js = _panel_js(panel)
    assert "PanelState.set(" in js, f"{panel} restores but never saves"


@pytest.mark.parametrize("panel", WIRED)
def test_panel_restores_something(panel):
    js = _panel_js(panel)
    assert "PanelState.get(" in js, f"{panel} saves but never restores"


def test_cache_bust_bumped_where_the_script_is_loaded():
    """web_shared edits only reach the screen if every index.html that
    loads them bumps ?v= — the recurring trap."""
    for panel in WIRED:
        html = _read(f"{panel}_web_assets", "index.html")
        m = re.search(r"panel_state\.js\?v=([0-9a-z]+)", html)
        assert m, f"{panel}: panel_state.js loaded without a ?v="


# ── the store itself still behaves ─────────────────────────────────────
def test_set_ui_state_merges_rather_than_replaces():
    """A panel saves one field at a time; a replacing store would make
    each save wipe the others."""
    import home_web
    src = __import__("inspect").getsource(home_web.HomeApi.set_ui_state)
    assert "cur.update(patch)" in src
