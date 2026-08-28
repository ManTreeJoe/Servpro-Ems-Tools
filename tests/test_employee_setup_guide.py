from unittest.mock import patch

import home_web
import settings_web


def test_employee_setup_includes_comment_display_name():
    api = settings_web.Api.__new__(settings_web.Api)
    with patch.object(settings_web.config, "load", return_value={}), \
         patch.object(settings_web.config, "active_department", return_value="IE"), \
         patch("supabase_client.current_user", return_value=None):
        result = api.employee_setup_status()
    assert [step["key"] for step in result["steps"]] == [
        "signin", "profile_name", "franchise", "trello", "folders"
    ]
    assert result["all_done"] is False


def test_franchise_check_failure_does_not_make_signed_in_user_look_signed_out():
    api = settings_web.Api.__new__(settings_web.Api)
    with patch.object(settings_web.config, "load", return_value={}), \
         patch.object(settings_web.config, "active_department", return_value="IE"), \
         patch("supabase_client.current_user", return_value={
             "id": "user-1", "email": "employee@example.test",
             "display_name": "Samantha Test"}), \
         patch("supabase_client.rpc", side_effect=RuntimeError("temporary outage")):
        result = api.employee_setup_status()
    steps = {step["key"]: step for step in result["steps"]}
    assert steps["signin"]["done"] is True
    assert steps["signin"]["detail"] == "employee@example.test"
    assert steps["profile_name"]["done"] is True
    assert steps["profile_name"]["detail"] == "Samantha Test"
    assert steps["franchise"]["done"] is False
    assert "Could not check franchise access" in steps["franchise"]["detail"]


def test_regular_user_sees_only_assigned_franchises():
    api = home_web.HomeApi.__new__(home_web.HomeApi)
    departments = [{"key": "IE", "label": "IE"},
                   {"key": "OC", "label": "OC"}]
    with patch("config.is_multi_dept", return_value=True), \
         patch("config.list_departments", return_value=departments), \
         patch("config.active_department", return_value="IE"), \
         patch("supabase_client.is_configured", return_value=True), \
         patch("supabase_client.is_signed_in", return_value=True), \
         patch("supabase_client.rpc", return_value={
             "is_admin": False, "departments": ["OC"]}):
        result = api.department_state()
    assert [d["key"] for d in result["departments"]] == ["OC"]


def test_admin_keeps_every_configured_franchise():
    api = home_web.HomeApi.__new__(home_web.HomeApi)
    departments = [{"key": "IE"}, {"key": "OC"}]
    with patch("config.is_multi_dept", return_value=True), \
         patch("config.list_departments", return_value=departments), \
         patch("config.active_department", return_value="IE"), \
         patch("supabase_client.is_configured", return_value=True), \
         patch("supabase_client.is_signed_in", return_value=True), \
         patch("supabase_client.rpc", return_value={"is_admin": True}):
        result = api.department_state()
    assert result["departments"] == departments


def test_token_page_uses_the_configured_app_authorization_url():
    api = settings_web.Api.__new__(settings_web.Api)
    with patch("trello_auth.manual_url", return_value={
        "ok": True, "url": "https://trello.com/1/authorize?key=public"}):
        result = api.my_trello_token_page()
    assert result["ok"] is True
    assert result["url"].startswith("https://trello.com/1/authorize?")
