"""Small, JSON-safe appearance projection shared by the web shells.

The desktop widgets already use :mod:`theme`; web panels need the same saved
choice without importing the heavier Tk/font setup.  This module deliberately
returns presentation data only and never exposes the rest of config.json.
"""
from __future__ import annotations


VALID_APPEARANCES = {"system", "light", "dark"}


def _windows_mode() -> str:
    """Return the current Windows app theme, defaulting safely to dark."""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if int(value) == 1 else "dark"
    except Exception:
        return "dark"


def preferences() -> dict:
    """Return only the current user's safe visual preferences."""
    try:
        import config

        cfg = config.load() or {}
    except Exception:
        cfg = {}
    selected = str(cfg.get("appearance") or "system").strip().lower()
    if selected not in VALID_APPEARANCES:
        selected = "system"
    system = _windows_mode()
    return {
        "selected": selected,
        "system": system,
        "effective": system if selected == "system" else selected,
        "density": str(cfg.get("ui_density") or "comfortable"),
        "reduce_motion": bool(cfg.get("reduce_motion", False)),
    }
