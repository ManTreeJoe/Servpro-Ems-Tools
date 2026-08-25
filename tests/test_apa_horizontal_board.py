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
