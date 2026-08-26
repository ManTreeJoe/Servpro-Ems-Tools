import supabase_client


def test_final_browser_redirect_fragment_is_accepted(monkeypatch):
    stored = {}
    monkeypatch.setattr(supabase_client, "_store_session",
                        lambda payload: stored.update(payload) or payload)
    monkeypatch.setattr(supabase_client, "current_user",
                        lambda: {"email": "nathan@example.com"})
    result = supabase_client.verify_magic_link(
        "http://localhost:3000/#access_token=abc123&refresh_token=ref456"
        "&expires_in=3600&token_type=bearer")
    assert result["email"] == "nathan@example.com"
    assert stored["access_token"] == "abc123"
    assert stored["refresh_token"] == "ref456"


def test_original_token_hash_link_still_verifies(monkeypatch):
    calls = []
    monkeypatch.setattr(supabase_client, "_raw",
                        lambda method, path, body=None, **kw:
                        calls.append(body) or {"access_token": "a", "refresh_token": "r"})
    monkeypatch.setattr(supabase_client, "_store_session", lambda payload: payload)
    monkeypatch.setattr(supabase_client, "current_user", lambda: {"id": "u"})
    result = supabase_client.verify_magic_link(
        "https://example.supabase.co/auth/v1/verify?token_hash=hash123&type=magiclink")
    assert result == {"id": "u"}
    assert calls[0] == {"type": "magiclink", "token_hash": "hash123"}
