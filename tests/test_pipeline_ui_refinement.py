from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _asset(name):
    return (ROOT / "pipeline_web_assets" / name).read_text(encoding="utf-8")


def test_pipeline_cards_support_keyboard_and_named_actions():
    js = _asset("app.js")
    assert 'role="button" tabindex="0"' in js
    assert 'event.key !== "Enter" && event.key !== " "' in js
    assert 'aria-label="More actions for' in js


def test_card_role_does_not_suppress_its_own_click():
    js = _asset("app.js")
    assert "control && control !== cardEl" in js
    assert "onAuditCard(cardEl);" in js


def test_card_open_is_not_swallowed_by_horizontal_grab_scroll():
    js = _asset("app.js")
    assert 'draggable="false" data-no-drag' in js
    assert "openedOnPointerUp = true" in js
    assert "Open on pointerup" in js


def test_workspace_deep_load_survives_fast_lookup_failure():
    js = _asset("app.js")
    start = js.index("async function onAuditCard")
    end = js.index("function instantWorkspaceData", start)
    block = js[start:end]
    assert "const fullOutcome = await fullPromise" in block
    assert "workspace could not render" in block
    fast_failure = block[block.index("if (!fast?.ok)"):block.index("} else if", block.index("if (!fast?.ok)"))]
    assert "return;" not in fast_failure


def test_pipeline_comment_and_icon_controls_are_named():
    js = _asset("app.js")
    assert 'aria-label="Job comment"' in js
    assert 'aria-label="Close Stage for XA"' in js
    assert 'aria-label="Reset ${escapeAttr(s.label)} to default"' in js


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
def test_jobs_board_zoom_is_visible_persistent_and_board_scoped():
    html = _asset("index.html")
    js = _asset("app.js")
    css = _asset("app.css")
    for marker in ("board-zoom-out", "board-zoom-reset", "board-zoom-in"):
        assert marker in html
    for marker in ('PanelState.get("boardZoom", 1)',
                   "PanelState.set({ boardZoom: next })",
                   "function onBoardZoomShortcut", "Math.max(0.7",
                   "Math.min(1.4"):
        assert marker in js
    assert "zoom: var(--board-zoom, 1)" in css


def test_apa_vertical_wheel_stays_in_the_column():
    apa_html = (ROOT / "apa_web_assets" / "index.html").read_text(encoding="utf-8")
    assert '<main class="board" id="board" data-hdrag-nowheel>' in apa_html


def test_job_shelf_separates_star_shortcuts_from_held_cards():
    html = _asset("index.html")
    js = _asset("app.js")
    css = _asset("app.css")
    assert 'id="job-shelf"' in html and 'id="job-shelf-drop-hint"' in html
    for marker in ('mode = "starred"', 'item.mode === "held"',
                   'addToJobShelf(live ? shelfEntryFromCard(live)',
                   '}, "held")', 'data-act="star"',
                   'mode-${escapeAttr(item.mode || "starred")}'):
        assert marker in js
    assert ".job-shelf.drop-ready" in css
    assert ".shelf-card.mode-held" in css
