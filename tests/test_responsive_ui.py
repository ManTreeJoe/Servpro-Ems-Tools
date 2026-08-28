from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANELS = tuple(sorted(
    path.relative_to(ROOT).as_posix()
    for path in ROOT.glob("*_web_assets/index.html")
))


def test_primary_workspaces_load_the_shared_responsive_layer():
    assert len(PANELS) >= 20
    for rel in PANELS:
        html = (ROOT / rel).read_text(encoding="utf-8")
        assert "web_shared/responsive.css" in html, rel
        assert 'name="viewport"' in html, rel
        assert 'name="theme-color"' in html, rel
        assert "responsive-ui" in html, rel


def test_responsive_layer_covers_layout_focus_touch_and_motion():
    css = (ROOT / "web_shared" / "responsive.css").read_text(encoding="utf-8")
    for marker in ("clamp(", "focus-visible", "touch-action: manipulation",
                   "overscroll-behavior: contain", "prefers-reduced-motion",
                   "max-width: 680px", "grid-template-columns: 1fr"):
        assert marker in css
