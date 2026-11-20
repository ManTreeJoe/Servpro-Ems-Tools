from pathlib import Path

import settings_web
import supabase_client


ROOT = Path(__file__).resolve().parents[1]


def test_password_login_exchanges_credentials_without_storing_password(monkeypatch):
    calls = []
    stored = {}
    monkeypatch.setattr(supabase_client, "_raw",
                        lambda method, path, params=None, body=None, **kw:
                        calls.append((method, path, params, body)) or {
                            "access_token": "access", "refresh_token": "refresh",
                            "user": {"id": "u1", "email": "person@example.com"}})
    monkeypatch.setattr(supabase_client, "_store_session",
                        lambda payload: stored.update(payload) or payload)
    monkeypatch.setattr(supabase_client, "current_user",
                        lambda: {"id": "u1", "email": "person@example.com"})
    result = supabase_client.sign_in_with_password("person@example.com", "secret")
    assert result["email"] == "person@example.com"
    assert calls == [("POST", "/auth/v1/token", {"grant_type": "password"},
                      {"email": "person@example.com", "password": "secret"})]
    assert "password" not in stored


def test_employee_password_controls_are_inert_and_microsoft_is_primary():
    html = (ROOT / "settings_web_assets" / "index.html").read_text(encoding="utf-8")
    assert 'id="sb-password"' in html
    assert 'id="sb-password-signin"' in html
    assert 'hidden inert aria-hidden="true"' in html
    assert 'id="sb-microsoft-signin"' in html
    assert "supabase_sign_in_password" in html


def test_sign_in_controls_bind_before_unrelated_settings_loads():
    """A failed franchise/property request must not leave visible auth inert."""
    html = (ROOT / "settings_web_assets" / "index.html").read_text(encoding="utf-8")
    start = html.index('window.addEventListener("pywebviewready"')
    first_await = html.index("await ", start)
    assert html.index("bindSupabaseControls();", start) < first_await
    assert 'getElementById("sb-password-signin")?.addEventListener' in html


def test_auth_status_renders_before_unrelated_async_setup():
    html = (ROOT / "settings_web_assets" / "index.html").read_text(encoding="utf-8")
    start = html.index('window.addEventListener("pywebviewready"')
    auth = html.index("await refreshSupabase();", start)
    assert auth < html.index("await pywebview.api.settings_access()", start)
    assert auth < html.index("await renderFirstRunWizard();", start)


def test_setup_signin_button_opens_modal_directly():
    html = (ROOT / "settings_web_assets" / "index.html").read_text(encoding="utf-8")
    start = html.index("function wireSetupGuide()")
    handler = html.index('data-setup="signin"', start)
    end = html.index("data-scope-tab-jump", handler)
    block = html[handler:end]
    assert 'getElementById("account-sync")' in block
    assert 'getElementById("sb-open-signin")' in block
    assert "openSupabaseSignIn();" not in block
    assert 'addEventListener("click", openSupabaseSignIn)' in html


def test_failed_signin_can_be_retried_without_refresh_hiding_modal():
    html = (ROOT / "settings_web_assets" / "index.html").read_text(encoding="utf-8")
    assert 'class="signin-modal"' in html
    assert 'role="dialog"' in html
    start = html.index("async function sbPasswordSignIn()")
    end = html.index("async function sbVerify()", start)
    block = html[start:end]
    assert "finally {" in block
    assert 'button.disabled = false;' in block
    assert 'document.getElementById("sb-password").select();' in block
    assert block.count("await refreshSupabase();") == 1


def test_employee_password_bridge_directs_to_microsoft():
    assert settings_web.Api().supabase_sign_in_password("person@example.com", "") == {
        "ok": False, "error": "Use Sign in with Microsoft. Administrator recovery is separate."}
