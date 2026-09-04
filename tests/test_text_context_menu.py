from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_every_web_surface_loads_normal_text_context_menu():
    pages = sorted(ROOT.glob("*_web_assets/index.html"))
    assert pages
    missing = [page.name for page in pages
               if "web_shared/text_context_menu.js" not in page.read_text(encoding="utf-8")]
    assert missing == []


def test_text_context_menu_keeps_standard_editing_actions():
    source = (ROOT / "web_shared" / "text_context_menu.js").read_text(encoding="utf-8")
    for action in ('["Cut"', '["Copy"', '["Paste"', '["Select all"'):
        assert action in source
    assert "event.defaultPrevented" in source
    assert "navigator.clipboard" in source
