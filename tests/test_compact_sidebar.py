from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_sidebar_collapses_to_icon_rail_on_narrow_windows():
    css = (ROOT / "home_web_assets" / "app.css").read_text(encoding="utf-8")
    assert "@media (max-width: 900px)" in css
    compact = css[css.index("@media (max-width: 900px)") :]
    assert "grid-template-columns: 64px" in compact
    assert ".sb-name { display: none; }" in compact
    assert ".sb-icon { font-size: 19px; }" in compact


def test_sidebar_icons_keep_names_and_keyboard_navigation():
    js = (ROOT / "home_web_assets" / "app.js").read_text(encoding="utf-8")
    assert 'title="${esc(it.name)}"' in js
    assert 'aria-label="Open ${esc(it.name)}"' in js
    assert 'role="button" tabindex="0"' in js
    assert 'event.key !== "Enter" && event.key !== " "' in js
