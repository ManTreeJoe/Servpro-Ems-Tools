from pathlib import Path

import supabase_client


ROOT = Path(__file__).resolve().parents[1]


def test_connection_status_uses_rls_backed_status_table(monkeypatch):
    captured = {}
    monkeypatch.setattr(supabase_client, "rest", lambda method, table, **kwargs:
                        captured.update(method=method, table=table, kwargs=kwargs) or
                        [{"provider": "companycam", "status": "connected"}])
    result = supabase_client.external_connection_status("companycam", "ie")
    assert result["status"] == "connected"
    assert captured["method"] == "GET"
    assert captured["table"] == "external_connection_status"
    assert captured["kwargs"]["params"]["department"] == "eq.IE"


def test_oauth_tokens_are_encrypted_and_never_returned_to_client_source():
    callback = (ROOT / "supabase/functions/companycam-oauth-callback/index.ts").read_text(encoding="utf-8")
    shared = (ROOT / "supabase/functions/_shared/companycam-oauth.ts").read_text(encoding="utf-8")
    assert "encryptSecret" in callback
    assert "AES-GCM" in shared
    assert "OAUTH_TOKEN_ENCRYPTION_KEY" in shared


def test_gateway_prefers_personal_connection_and_can_refresh_it():
    gateway = (ROOT / "supabase/functions/companycam-gateway/index.ts").read_text(encoding="utf-8")
    assert "personalCredential" in gateway
    assert "grant_type: \"refresh_token\"" in gateway
    assert "personal || Deno.env.get" in gateway


def test_schema_has_rls_and_no_client_grant_on_credentials():
    sql = (ROOT / "supabase/migrations/20260904153439_companycam_user_oauth.sql").read_text(encoding="utf-8")
    assert "external_oauth_credentials enable row level security" in sql
    assert "revoke all on table public.external_oauth_credentials from public, anon, authenticated" in sql
    assert "Users read their own external connection status" in sql
    assert "(select auth.uid()) = user_id" in sql


def test_settings_waits_for_browser_callback_without_page_reload():
    html = (ROOT / "settings_web_assets/index.html").read_text(encoding="utf-8")
    assert "waitForCompanyCamConnection" in html
    assert 'card.provider === "companycam" && card.state === "connected"' in html
