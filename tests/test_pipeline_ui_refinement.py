from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _asset(name):
    return (ROOT / "pipeline_web_assets" / name).read_text(encoding="utf-8")


def test_pipeline_cards_support_keyboard_and_named_actions():
    js = _asset("app.js")
    assert 'role="button" tabindex="0"' in js
    assert 'event.key !== "Enter" && event.key !== " "' in js
    assert 'aria-label="More actions for' in js


def test_pipeline_authors_visible_focus_and_reduced_motion():
    css = _asset("app.css")
    assert ":focus-visible" in css
    assert "prefers-reduced-motion: reduce" in css
    assert "overscroll-behavior: contain" in css
    assert "content-visibility: auto" in css


def test_pipeline_keeps_primary_copy_and_xa_actions_visible():
    js = _asset("app.js")
    footer = js[js.index('<footer class="modal-foot">'):]
    assert "visibleCopyOptions.map" in footer
    assert "data-copy-summary" in footer
    assert "data-stage-xa" in footer


def test_pipeline_status_and_search_are_accessible():
    html = _asset("index.html")
    assert 'aria-label="Search Jobs"' in html
    assert 'aria-live="polite"' in html
    assert 'class="skip-link"' in html
