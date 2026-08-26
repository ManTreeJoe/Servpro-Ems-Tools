from pathlib import Path

import global_hotkey
import settings_web


def test_supported_shortcuts_are_safe_combinations():
    assert global_hotkey.normalize(" Ctrl + Alt + Space ") == "ctrl+alt+space"
    assert "ctrl+alt+space" in global_hotkey.SHORTCUTS
    assert all(mods and key for mods, key in global_hotkey.SHORTCUTS.values())


def test_settings_can_save_the_toggle_and_shortcut(tmp_path, monkeypatch):
    state = {}
    monkeypatch.setattr(settings_web.config, "load_base", lambda: dict(state))
    monkeypatch.setattr(settings_web.config, "save", lambda cfg: state.update(cfg))
    monkeypatch.setattr(settings_web, "_invalidate", lambda reason: {})
    result = settings_web.Api().save({
        "global_hotkey_enabled": True,
        "global_hotkey": "ctrl+alt+h",
    })
    assert result["ok"]
    assert state["global_hotkey_enabled"] is True
    assert state["global_hotkey"] == "ctrl+alt+h"


def test_home_starts_and_stops_hotkey_service():
    source = Path(__file__).resolve().parents[1].joinpath("home_web.py").read_text(encoding="utf-8")
    assert "global_hotkey.Manager(api.focus_window)" in source
    assert "api._hotkey.stop()" in source


def test_focus_targets_this_process_not_a_shared_window_title():
    source = Path(__file__).resolve().parents[1].joinpath("home_web.py").read_text(encoding="utf-8")
    body = source[source.index("    def focus_window(self):"):source.index("    def hotkey_status(self):")]
    assert "os.getpid()" in body
    assert "EnumWindows" in body
    assert 'FindWindowW(None, "Linguar Hub")' not in body


def test_settings_explains_and_labels_the_shortcut():
    html = Path(__file__).resolve().parents[1].joinpath(
        "settings_web_assets", "index.html").read_text(encoding="utf-8")
    assert "Ctrl + Alt + Space" in html
    assert "Works while Linguar Hub is open" in html
    assert "hotkey_status" in html
