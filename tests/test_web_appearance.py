import json
import sys
from pathlib import Path
from types import SimpleNamespace

import web_appearance


ROOT = Path(__file__).resolve().parents[1]


def test_preferences_follow_windows_by_default(monkeypatch):
    monkeypatch.setitem(sys.modules, "config", SimpleNamespace(load=lambda: {}))
    monkeypatch.setattr(web_appearance, "_windows_mode", lambda: "light")

    result = web_appearance.preferences()

    assert result["selected"] == "system"
    assert result["system"] == "light"
    assert result["effective"] == "light"


def test_explicit_dark_overrides_light_windows(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "config",
        SimpleNamespace(load=lambda: {
            "appearance": "dark",
            "ui_density": "compact",
            "reduce_motion": True,
        }),
    )
    monkeypatch.setattr(web_appearance, "_windows_mode", lambda: "light")

    result = web_appearance.preferences()

    assert result == {
        "selected": "dark",
        "system": "light",
        "effective": "dark",
        "density": "compact",
        "reduce_motion": True,
    }


def test_every_web_panel_loads_shared_appearance_controller():
    pages = sorted(ROOT.glob("*_web_assets/index.html"))
    assert pages
    missing = [page.parent.name for page in pages
               if "web_shared/appearance.js" not in page.read_text(encoding="utf-8")]
    assert missing == []


def test_new_installs_follow_system_theme():
    shipped = json.loads((ROOT / "_packaging" / "config.json").read_text(encoding="utf-8"))
    assert shipped["appearance"] == "system"


def test_shared_theme_has_real_light_palette():
    css = (ROOT / "web_shared" / "theme.css").read_text(encoding="utf-8")
    assert ':root[data-theme="light"]' in css
    assert "--bg:           #E9ECE6" in css
    assert "color-scheme: light" in css
