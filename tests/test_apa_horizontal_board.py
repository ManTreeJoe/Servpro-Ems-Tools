"""APA lanes remain on one horizontal, Trello-style rail."""

from pathlib import Path


def test_apa_board_scrolls_horizontally_without_wrapping():
    css = (Path(__file__).parents[1] / "apa_web_assets" / "app.css").read_text(
        encoding="utf-8"
    )

    board = css.split(".board {", 1)[1].split("}", 1)[0]
    section = css.split(".section {", 1)[1].split("}", 1)[0]

    assert "overflow-x: auto" in board
    assert "overflow-y: hidden" in board
    assert "flex-wrap: nowrap" in board
    assert "scroll-snap-type: none" in board
    assert "flex: 0 0 clamp(" in section
    assert "height: 100%" in section


def test_apa_board_loads_grab_to_pan_helper():
    root = Path(__file__).parents[1]
    html = (root / "apa_web_assets" / "index.html").read_text(encoding="utf-8")
    helper = (root / "web_shared" / "h_scroll.js").read_text(encoding="utf-8")

    assert '../web_shared/h_scroll.js?v=20260901a' in html
    assert 'el.scrollLeft = clamp(scrollLeft - walk)' in helper
    assert 'const horizontal = absX > 0' in helper
    assert 'requestAnimationFrame(paintDrag)' in helper
    assert 'cursor: grabbing' in helper


def test_grab_to_pan_does_not_steal_apa_card_dragging():
    helper = (
        Path(__file__).parents[1] / "web_shared" / "h_scroll.js"
    ).read_text(encoding="utf-8")

    assert r'[draggable=\"true\"]' in helper
    assert '.item' in helper


def test_apa_toolbar_uses_short_labels_without_squashing_buttons():
    root = Path(__file__).parents[1]
    html = (root / "apa_web_assets" / "index.html").read_text(encoding="utf-8")
    css = (root / "apa_web_assets" / "app.css").read_text(encoding="utf-8")

    for label in (">Sync Lanes<", ">Teams<", ">EOD<", ">Paste<", ">Refresh<"):
        assert label in html
    for verbose in ("Refresh lanes from Trello", "Send Teams (all)",
                    "Send EOD email", "Bulk paste"):
        assert f">{verbose}<" not in html
    assert ".topbar-actions .btn" in css
    toolbar_button_rule = css.split(".topbar-actions .btn", 1)[1].split("}", 1)[0]
    assert "white-space: nowrap" in toolbar_button_rule
    assert "flex: 0 0 auto" in toolbar_button_rule
