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
    assert "scroll-snap-type: x proximity" in board
    assert "flex: 0 0 clamp(" in section
    assert "height: 100%" in section


def test_apa_board_loads_grab_to_pan_helper():
    root = Path(__file__).parents[1]
    html = (root / "apa_web_assets" / "index.html").read_text(encoding="utf-8")
    helper = (root / "web_shared" / "h_scroll.js").read_text(encoding="utf-8")

    assert '../web_shared/h_scroll.js?v=20260827a' in html
    assert 'el.scrollLeft = scrollLeft - walk' in helper
    assert 'cursor: grabbing' in helper


def test_grab_to_pan_does_not_steal_apa_card_dragging():
    helper = (
        Path(__file__).parents[1] / "web_shared" / "h_scroll.js"
    ).read_text(encoding="utf-8")

    assert r'[draggable=\"true\"]' in helper
    assert '.item' in helper
