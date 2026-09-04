from pathlib import Path

import companycam_api
import settings_web
import user_connections


ROOT = Path(__file__).resolve().parents[1]


def _access(**overrides):
    base = {"signed_in": True, "email": "sam@servpro.test",
            "display_name": "Samantha Test", "is_admin": False}
    base.update(overrides)
    return base


def test_companycam_is_org_managed_but_attributed_to_signed_in_user(monkeypatch):
    monkeypatch.setattr(user_connections, "_franchise", lambda: "IE")
    cards = user_connections.statuses(
        access=_access(), cfg={"companycam_api_token": "office-key"})
    cc = next(card for card in cards if card["provider"] == "companycam")
    assert cc["state"] == "connected"
    assert cc["scope"] == "organization"
    assert cc["identity"] == "sam@servpro.test"
    assert "IE manages" in cc["detail"]


def test_companycam_connection_requires_linguar_identity(monkeypatch):
    monkeypatch.setattr(user_connections, "_franchise", lambda: "OC")
    cards = user_connections.statuses(
        access=_access(signed_in=False, email="", display_name=""),
        cfg={"companycam_api_token": "office-key"})
    cc = next(card for card in cards if card["provider"] == "companycam")
    assert cc["state"] == "sign_in_required"
    assert cc["action"] == "sign_in"


def test_regular_user_is_not_asked_for_companycam_api_token(monkeypatch):
    monkeypatch.setattr(user_connections, "_franchise", lambda: "IE")
    cards = user_connections.statuses(access=_access(), cfg={})
    cc = next(card for card in cards if card["provider"] == "companycam")
    assert cc["state"] == "admin_required"
    assert cc["action"] == "open_companycam"
    assert cc["action_label"] == "Sign in to CompanyCam"
    assert "should not paste personal API tokens" in cc["detail"]


def test_companycam_write_header_uses_signed_in_email():
    headers = user_connections.companycam_actor_headers(
        "POST", access=_access(email="SAM@SERVPRO.TEST"))
    assert headers == {"X_COMPANYCAM_USER": "sam@servpro.test"}
    assert user_connections.companycam_actor_headers(
        "GET", access=_access()) == {}


def test_companycam_http_layer_merges_actor_header(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self): return b'{}'

    monkeypatch.setattr(companycam_api, "_token", lambda: "office-key")
    monkeypatch.setattr(
        user_connections, "companycam_actor_headers",
        lambda method: {"X_COMPANYCAM_USER": "sam@servpro.test"})
    monkeypatch.setattr(companycam_api.urllib.request, "urlopen",
                        lambda req, timeout=20: captured.setdefault("req", req) or Response())
    # Avoid the truthy Request object returned by setdefault above.
    def open_request(req, timeout=20):
        captured["req"] = req
        return Response()
    monkeypatch.setattr(companycam_api.urllib.request, "urlopen", open_request)
    companycam_api._call("/projects", method="POST", data={"name": "Test"})
    request_headers = {key.lower(): value for key, value in captured["req"].header_items()}
    assert request_headers["x_companycam_user"] == "sam@servpro.test"


def test_settings_exposes_normal_connection_cards(monkeypatch):
    monkeypatch.setattr(user_connections, "statuses", lambda: [{
        "provider": "companycam", "state": "connected"}])
    assert settings_web.Api().user_connections()["connections"][0]["provider"] == "companycam"


def test_settings_page_renders_my_connections():
    html = (ROOT / "settings_web_assets" / "index.html").read_text(encoding="utf-8")
    for marker in ('id="my-connections"', "renderConnections",
                   "open_user_connection", "connection-state"):
        assert marker in html
    assert "!f.managed_connection" in html
