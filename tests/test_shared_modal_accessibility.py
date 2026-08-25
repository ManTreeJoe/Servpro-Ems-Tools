"""Shared dialogs must be keyboard-safe before panel-specific cleanup."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_shared_modal_has_dialog_name_and_close_label():
    js = (ROOT / "web_shared" / "modal.js").read_text(encoding="utf-8")
    for token in ('role="dialog"', 'aria-modal="true"', 'aria-labelledby=',
                  'aria-label="Close dialog"'):
        assert token in js


def test_shared_modal_traps_focus_closes_on_escape_and_restores_focus():
    js = (ROOT / "web_shared" / "modal.js").read_text(encoding="utf-8")
    assert 'e.key === "Escape"' in js
    assert 'e.key !== "Tab"' in js
    assert "_returnFocus" in js and "returnFocus.focus()" in js
    assert "el.inert = true" in js


def test_shared_modal_contains_scroll_and_has_visible_focus():
    css = (ROOT / "web_shared" / "modal.css").read_text(encoding="utf-8")
    assert "overscroll-behavior: contain" in css
    assert ":focus-visible" in css
    assert "outline: 2px" in css


def test_primary_web_surfaces_do_not_transition_every_property():
    for rel in ("apa_web_assets/app.css", "home_web_assets/app.css",
                "audit_web_assets/app.css", "snapshot_web_assets/index.html"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "transition: all" not in text
