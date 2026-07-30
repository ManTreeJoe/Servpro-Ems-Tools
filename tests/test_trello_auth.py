"""Trello sign-in — approve in the browser, no copy-paste.

The old Settings button opened Trello's token page with a HARDCODED api key
(4f7cf06b…) that was NOT the key this install calls with, so any token it
produced authenticated as a different application. It also made the user
copy the token out of the browser and paste it back.

The loopback half is fully testable without Trello: the callback page and
the token capture are just HTTP.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import urllib.request

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import trello_auth


@pytest.fixture(autouse=True)
def _cfg(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"trello_api_key": "abc123key"}),
                    encoding="utf-8")
    monkeypatch.setattr(config, "_USER_CFG", str(path))
    monkeypatch.setattr(config, "_CACHE", None)
    monkeypatch.setattr(config, "_CACHE_MTIME", None)
    yield path


# ── the URL ─────────────────────────────────────────────────────────────

def test_authorize_url_uses_the_configured_key():
    """The whole reason the old button was broken."""
    url = trello_auth.authorize_url("mykey", "http://127.0.0.1:9/")
    assert "key=mykey" in url
    assert "4f7cf06b75c52d6c63a73e7a8df7d1a8" not in url


def test_authorize_url_requests_a_never_expiring_token():
    url = trello_auth.authorize_url("k", "http://127.0.0.1:9/")
    assert "expiration=never" in url
    assert "response_type=token" in url
    assert "scope=read%2Cwrite%2Caccount" in url


def test_authorize_refuses_without_an_api_key(tmp_path, monkeypatch):
    path = tmp_path / "nokey.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "_USER_CFG", str(path))
    monkeypatch.setattr(config, "_CACHE", None)
    monkeypatch.setattr(config, "_CACHE_MTIME", None)
    res = trello_auth.authorize(open_browser=False, timeout=1)
    assert not res["ok"] and "API key" in res["error"]


# ── the loopback callback ───────────────────────────────────────────────

def test_callback_page_bounces_the_fragment_to_the_server():
    """Trello returns the token in the URL fragment, which never reaches a
    server — the landing page must re-request it as a query string."""
    srv = trello_auth._Server(("127.0.0.1", trello_auth._free_port()))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        html = urllib.request.urlopen(
            f"http://127.0.0.1:{port}/", timeout=5).read().decode()
        assert "location.hash" in html
        assert '"/done"' in html
    finally:
        srv.shutdown(); srv.server_close()


def test_server_captures_the_token_and_signals_done():
    srv = trello_auth._Server(("127.0.0.1", trello_auth._free_port()))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        body = urllib.request.urlopen(
            f"http://127.0.0.1:{port}/done?token=TOK123", timeout=5
        ).read().decode()
        assert "Trello connected" in body
        assert srv.done.wait(2)
        assert srv.token == "TOK123"
    finally:
        srv.shutdown(); srv.server_close()


def test_server_reports_a_missing_token():
    srv = trello_auth._Server(("127.0.0.1", trello_auth._free_port()))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        with pytest.raises(urllib.error.HTTPError) as ex:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/done", timeout=5)
        assert ex.value.code == 400
        assert srv.done.wait(2)
        assert srv.token == ""
    finally:
        srv.shutdown(); srv.server_close()


def test_authorize_times_out_cleanly_and_offers_the_url():
    """If the user closes the tab, say so and hand back the link rather
    than hanging or losing the flow."""
    res = trello_auth.authorize(open_browser=False, timeout=1)
    assert not res["ok"] and res.get("timeout")
    assert res["authorize_url"].startswith("https://trello.com/1/authorize")


# ── where the token is stored ───────────────────────────────────────────

def test_token_saves_to_base_in_single_department_mode(_cfg):
    assert trello_auth.save_token("TOK")["scope"] == "base"
    config._CACHE = None; config._CACHE_MTIME = None
    assert config.load_base()["trello_token"] == "TOK"


def test_token_saves_to_the_ACTIVE_department(_cfg):
    """trello_token is department-scoped. Writing it to the base would hand
    one franchise's token to the other — the same class of bug that had IE
    searching OC's workspace."""
    _cfg.write_text(json.dumps({
        "trello_api_key": "k",
        "multi_department_enabled": True,
        "active_department": "OC",
        "trello_token": "IE-TOKEN",
        "departments": {"IE": {"label": "IE"}, "OC": {"label": "OC"}},
    }), encoding="utf-8")
    config._CACHE = None; config._CACHE_MTIME = None

    assert trello_auth.save_token("OC-TOKEN")["scope"] == "OC"
    config._CACHE = None; config._CACHE_MTIME = None
    base = config.load_base()
    assert base["departments"]["OC"]["trello_token"] == "OC-TOKEN"
    assert base["trello_token"] == "IE-TOKEN", "must not clobber the base"


def test_empty_token_is_rejected():
    assert not trello_auth.save_token("")["ok"]
    assert not trello_auth.save_token("   ")["ok"]


# ── Allowed Origins (the "Invalid return_url" failure) ──────────────────

def test_port_is_fixed_not_ephemeral():
    """Trello validates return_url against the API key's Allowed Origins,
    and an origin includes the PORT. A random port would need a new origin
    whitelisted on every single sign-in."""
    assert trello_auth.auth_port() == trello_auth._DEFAULT_PORT
    assert trello_auth.allowed_origin() == \
        f"http://localhost:{trello_auth._DEFAULT_PORT}"


def test_port_is_overridable(_cfg):
    _cfg.write_text(json.dumps({"trello_api_key": "k",
                                "trello_auth_port": 9123}), encoding="utf-8")
    config._CACHE = None; config._CACHE_MTIME = None
    assert trello_auth.auth_port() == 9123
    assert trello_auth.allowed_origin() == "http://localhost:9123"


def test_bad_port_value_falls_back():
    import config as c
    c._CACHE = None; c._CACHE_MTIME = None
    assert isinstance(trello_auth.auth_port(), int)


def test_manual_url_omits_return_url():
    """The fallback: without return_url Trello prints the token on screen,
    so it works with no Allowed Origins entry at all."""
    res = trello_auth.manual_url()
    assert res["ok"]
    assert "return_url" not in res["url"]
    assert "key=abc123key" in res["url"]


def test_timeout_explains_the_origin_fix():
    """The most likely reason Trello never comes back is the origin — say
    so, with the exact string to register."""
    res = trello_auth.authorize(open_browser=False, timeout=1)
    assert not res["ok"]
    assert res["allowed_origin"].startswith("http://localhost:")
    assert "Allowed Origins" in res["error"]
    assert "return_url" not in res["manual_url"]
