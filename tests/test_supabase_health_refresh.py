from pathlib import Path

import web_health


ROOT = Path(__file__).resolve().parents[1]


def test_grant_cache_can_be_invalidated():
    web_health._grant_cache = {"checked": True, "signed_in": False}
    web_health._grant_at = 123.0
    web_health.invalidate_grant_cache()
    assert web_health._grant_cache == {}
    assert web_health._grant_at == 0.0


def test_signin_refreshes_top_level_health_banner():
    html = (ROOT / "settings_web_assets" / "index.html").read_text(encoding="utf-8")
    banner = (ROOT / "web_shared" / "health_banner.js").read_text(encoding="utf-8")
    assert 'type: "health-refresh"' in html
    assert 'ev.data.type === "health-refresh"' in banner
    assert "api.health_state(force === true)" in banner
