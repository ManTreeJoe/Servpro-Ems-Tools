from pathlib import Path

import pipeline_web
import settings_web
import supabase_client


ROOT = Path(__file__).resolve().parents[1]


def test_current_user_exposes_display_name(tmp_path, monkeypatch):
    session = tmp_path / "session.json"
    monkeypatch.setattr(supabase_client, "_SESSION_PATH", str(session))
    supabase_client._write_session({"user": {
        "id": "u1", "email": "sam@example.com",
        "user_metadata": {"display_name": "Samantha Rivera"},
    }})
    assert supabase_client.current_user() == {
        "id": "u1", "email": "sam@example.com",
        "display_name": "Samantha Rivera",
    }
    assert supabase_client.actor_name() == "Samantha Rivera"


def test_updating_display_name_saves_auth_metadata(tmp_path, monkeypatch):
    session = tmp_path / "session.json"
    monkeypatch.setattr(supabase_client, "_SESSION_PATH", str(session))
    supabase_client._write_session({"access_token": "token", "user": {
        "id": "u1", "email": "sam@example.com", "user_metadata": {},
    }})
    monkeypatch.setattr(supabase_client, "access_token", lambda: "token")
    calls = []
    monkeypatch.setattr(supabase_client, "_raw", lambda method, path, **kw:
                        calls.append((method, path, kw["body"])) or {
                            "id": "u1", "email": "sam@example.com",
                            "user_metadata": {"display_name": "Samantha Rivera"},
                        })
    user = supabase_client.update_display_name("  Samantha   Rivera ")
    assert user["display_name"] == "Samantha Rivera"
    assert calls == [("PUT", "/auth/v1/user",
                      {"data": {"display_name": "Samantha Rivera"}})]


def test_pipeline_comment_uses_name_not_email(monkeypatch):
    monkeypatch.setattr(supabase_client, "current_user", lambda: {
        "id": "u1", "email": "sam@example.com",
        "display_name": "Samantha Rivera"})
    monkeypatch.setattr(pipeline_web.pipeline_store, "add_activity",
                        lambda *_a, **_k: {"activity_key": "a1",
                                          "happened_at": "now"})
    monkeypatch.setattr("trello_client.post_comment", lambda *_a: True)
    result = pipeline_web.Api().post_job_comment("Job", "card", "Update")
    assert result["ok"]
    assert result["comment"]["actor"] == "Samantha Rivera"


def test_signed_in_user_must_add_name_before_commenting(monkeypatch):
    monkeypatch.setattr(supabase_client, "current_user", lambda: {
        "id": "u1", "email": "sam@example.com", "display_name": ""})
    result = pipeline_web.Api().post_job_comment("Job", "card", "Update")
    assert result == {"ok": False,
                      "error": "Add your name in My Settings before commenting."}


def test_my_settings_has_required_name_control():
    html = (ROOT / "settings_web_assets" / "index.html").read_text(
        encoding="utf-8")
    for marker in ("sb-profile-name", "sb-display-name",
                   "sb-save-display-name", "save_my_display_name",
                   "Required before you can add comments"):
        assert marker in html


def test_settings_api_saves_current_users_name(monkeypatch):
    monkeypatch.setattr(supabase_client, "update_display_name", lambda name: {
        "id": "u1", "email": "sam@example.com", "display_name": name})
    result = settings_web.Api().save_my_display_name("Samantha Rivera")
    assert result["ok"]
    assert "Samantha Rivera" in result["message"]
