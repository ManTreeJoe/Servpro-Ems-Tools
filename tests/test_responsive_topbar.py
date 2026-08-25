from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_shared_topbar_compacts_and_wraps_at_narrow_widths():
    css = (ROOT / "web_shared" / "theme.css").read_text(encoding="utf-8")
    assert "@media (max-width: 1180px)" in css
    assert "@media (max-width: 860px)" in css
    compact = css[css.index("@media (max-width: 1180px)"):]
    assert ".topbar .btn" in compact
    assert "flex-wrap: wrap" in compact
    assert ".topbar .search" in compact
