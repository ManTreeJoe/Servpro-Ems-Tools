from unittest.mock import patch

import settings_web


def _api():
    return settings_web.Api.__new__(settings_web.Api)


def test_only_exact_initial_admin_email_gets_bootstrap_access():
    with patch("supabase_client.rpc", side_effect=RuntimeError("migration pending")), \
         patch("supabase_client.current_user", return_value={
             "email": "nathan@servpro10100.com"}):
        assert settings_web._is_admin() is True
    with patch("supabase_client.rpc", side_effect=RuntimeError("migration pending")), \
         patch("supabase_client.current_user", return_value={
             "email": "nathan@another-company.com"}):
        assert settings_web._is_admin() is False


def test_bootstrap_owner_remains_admin_when_seed_row_is_missing():
    with patch("supabase_client.rpc", return_value={"is_admin": False}), \
         patch("supabase_client.current_user", return_value={
             "email": "nathan@servpro10100.com"}):
        assert settings_web._is_admin() is True


def test_settings_access_does_not_overwrite_bootstrap_owner():
    with patch("supabase_client.rpc", return_value={"is_admin": False,
                                                     "departments": ["IE"]}), \
         patch("supabase_client.current_user", return_value={
             "email": "nathan@servpro10100.com"}):
        result = _api().settings_access()
    assert result["is_admin"] is True
    assert result["departments"] == ["IE"]


def test_regular_user_cannot_write_admin_settings():
    with patch.object(settings_web, "_is_admin", return_value=False), \
         patch.object(settings_web, "_admin_enforcement_active",
                      return_value=True):
        result = _api().save({"trello_workspace_id": "different"})
    assert result["ok"] is False
    assert "Administrator" in result["error"]


def test_admin_can_assign_only_configured_franchises():
    departments = [{"key": "IE"}, {"key": "OC"}]
    with patch.object(settings_web, "_is_admin", return_value=True), \
         patch.object(settings_web.config, "list_departments",
                      return_value=departments), \
         patch("supabase_client.rpc", return_value=["IE"]) as rpc:
        result = _api().admin_set_user_franchises(
            "00000000-0000-0000-0000-000000000001",
            ["IE", "not-configured"])
    assert result["ok"] is True
    rpc.assert_called_once_with("admin_set_user_departments", {
        "p_user_id": "00000000-0000-0000-0000-000000000001",
        "p_departments": ["IE"],
    })
