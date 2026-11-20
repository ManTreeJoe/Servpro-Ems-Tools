"""Fake-only setup tests. No provider, profile or shared-drive access."""
from unittest.mock import Mock, call
import pytest
import home_web
import settings_web
import employee_setup as setup


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    import account_access
    import config
    import supabase_client as sb
    import trello_client
    import companycam_api
    import ems_db
    import paths
    cfg = {"supabase_url": "https://demo.invalid", "audit_base": str(tmp_path),
           "runs_dir": str(tmp_path), "trello_api_key": "fake", "trello_token": "fake"}
    access = {"signed_in": True, "identity": {"id": "test-user", "display_name": "Test Employee"},
              "departments": ["TEST"], "error": ""}
    monkeypatch.setattr(config, "load", lambda: cfg.copy())
    monkeypatch.setattr(config, "active_department", lambda: "TEST")
    monkeypatch.setattr(account_access, "current_access", lambda: access.copy())
    monkeypatch.setattr(setup, "_progress_path", lambda: tmp_path / "progress.json")
    monkeypatch.setattr(sb, "current_user", lambda: access["identity"] if access["signed_in"] else None)
    monkeypatch.setattr(sb, "rest", Mock(return_value=[]))
    monkeypatch.setattr(sb, "external_connection_status", Mock(return_value={"status": "connected"}))
    monkeypatch.setattr(trello_client, "_call", Mock(return_value={"id": "fake-trello"}))
    monkeypatch.setattr(companycam_api, "cloud_gateway_available", lambda: True)
    monkeypatch.setattr(companycam_api, "_call", Mock(return_value=[]))
    monkeypatch.setattr(companycam_api, "create_project", Mock(side_effect=AssertionError("No writes")))
    monkeypatch.setattr(ems_db, "backend_name", lambda: "supabase")
    monkeypatch.setattr(paths, "mark_configured", Mock(side_effect=AssertionError("No marker writes")))
    return cfg, access


def shell():
    return home_web.HomeApi.__new__(home_web.HomeApi)


def test_incomplete_setup_first_index(monkeypatch):
    steps = [{"key": "signin", "done": True}, {"key": "name", "done": False}]
    monkeypatch.setattr(settings_web.Api, "employee_setup_status", lambda _: {"all_done": False, "steps": steps})
    result = shell().first_run()
    assert result["show"] is True
    assert result["steps"] == steps
    assert result["first_incomplete"] == 1


def test_all_done_hidden():
    result = shell().first_run()
    assert result["show"] is False
    assert result["first_incomplete"] is None


def test_later_does_not_complete_setup(monkeypatch):
    monkeypatch.setattr(settings_web.Api, "employee_setup_status", lambda _: {"all_done": False, "steps": [{"done": False}]})
    api = shell()
    assert api.dismiss_first_run() == {"ok": True}
    assert api.first_run()["show"] is True
    assert api.first_run()["session_dismissed"] is True
    assert shell().first_run()["session_dismissed"] is False


def test_status_exception_fails_open(monkeypatch):
    monkeypatch.setattr(settings_web.Api, "employee_setup_status", Mock(side_effect=RuntimeError("sensitive value")))
    result = shell().first_run()
    assert result["show"] is True
    assert result["error"]
    assert "sensitive value" not in result["error"]


def test_saved_credentials_are_not_verification(monkeypatch):
    import trello_client
    monkeypatch.setattr(trello_client, "_call", Mock(side_effect=RuntimeError("offline")))
    result = setup.status(None)
    assert not next(s for s in result["steps"] if s["key"] == "trello")["done"]
    assert not result["all_done"]


@pytest.mark.parametrize("response", [None, {}, [], {"fullName": "Only a name"}])
def test_malformed_trello_is_not_verified(monkeypatch, response):
    import trello_client
    monkeypatch.setattr(trello_client, "_call", Mock(return_value=response))
    assert not next(s for s in setup.status(None)["steps"] if s["key"] == "trello")["done"]


def test_provider_and_job_checks_only_read():
    import companycam_api as cc
    import supabase_client as sb
    assert setup.status(None)["all_done"]
    cc._call.assert_called_once_with("/projects", params={"per_page": 1}, method="GET", _max_retries=0)
    cc.create_project.assert_not_called()
    sb.rest.assert_called_once_with("GET", "jobs", params={"select": "canon_key", "limit": "1"})


def test_companycam_saved_connected_but_probe_fails(monkeypatch):
    import companycam_api as cc
    monkeypatch.setattr(cc, "_call", Mock(side_effect=RuntimeError("offline")))
    result = setup.status(None)
    assert not next(s for s in result["steps"] if s["key"] == "companycam")["done"]
    assert setup.action(None, "skip_companycam")["ok"]
    assert setup.status(None)["all_done"]


def test_optional_skip_is_scoped_and_resumes(isolated, monkeypatch):
    cfg, access = isolated
    import companycam_api as cc
    monkeypatch.setattr(cc, "_call", Mock(side_effect=RuntimeError("offline")))
    setup.action(None, "skip_companycam")
    assert setup.status(None)["all_done"]
    cfg["supabase_url"] = "https://other.invalid"
    assert not setup.status(None)["all_done"]
    cfg["supabase_url"] = "https://demo.invalid"
    access["identity"] = {"id": "another-user", "display_name": "Other Employee"}
    assert not setup.status(None)["all_done"]


def test_server_assignment_required_even_for_local_owner(isolated):
    _, access = isolated
    access.update(is_owner=True, is_admin=True, departments=[])
    assert not setup.status(None)["all_done"]
    assert not setup.action(Mock(), "franchise", {"key": "TEST"})["ok"]
    assert not setup.action(Mock(), "folders", {})["ok"]


def test_final_check_read_failure(monkeypatch):
    import supabase_client as sb
    monkeypatch.setattr(sb, "rest", Mock(side_effect=RuntimeError("offline")))
    result = setup.status(None)
    assert result["steps"][-1]["key"] == "live_data"
    assert not result["steps"][-1]["done"]


def test_folder_save_rejects_unreadable_path(monkeypatch):
    monkeypatch.setattr(setup, "_read_folder", lambda _: False)
    api = Mock()
    assert not setup.action(api, "folders", {"job_root": "missing", "runs_dir": "missing"})["ok"]
    api.save_my_franchise_folders.assert_not_called()


def test_folder_save_preserves_other_settings(isolated):
    cfg, _ = isolated
    api = Mock()
    api.save_my_franchise_folders.return_value = {"ok": True}
    assert setup.action(api, "folders", {"job_root": cfg["audit_base"], "runs_dir": cfg["runs_dir"]})["ok"]
    api.save_my_franchise_folders.assert_called_once_with("TEST", cfg["audit_base"], cfg["runs_dir"])
    api.save.assert_not_called()


def test_connect_actions_do_not_invoke_write_test():
    api = Mock()
    setup.action(api, "companycam")
    api.open_user_connection.assert_called_once_with("companycam")
    api.test_user_connection.assert_not_called()


def test_no_secret_fields_or_marker_calls_in_wizard():
    from pathlib import Path
    root = Path(__file__).parents[1]
    js = (root / "home_web_assets/setup_wizard.js").read_text(encoding="utf-8")
    assert "api_key" not in js and "supabase_url" not in js
    assert "settings_save(" not in js and "test_user_connection" not in js
    for name in ("home_web_assets/index.html", "_ems_root_index.html"):
        html = (root / name).read_text(encoding="utf-8")
        assert 'src="setup_wizard.js"' in html
        assert 'id="fr-step-form"' in html
        assert 'id="fr-settings"' not in html


def test_signin_refreshes_shell_only_after_success():
    api = Mock()
    api.supabase_sign_in_microsoft.return_value = {"ok": False, "error": "Denied"}
    assert not setup.action(api, "signin", {})["reload"]
    api.supabase_sign_in_microsoft.return_value = {"ok": True}
    assert setup.action(api, "signin", {})["reload"]
    assert api.supabase_sign_in_microsoft.call_args_list == [call(), call()]
    api.supabase_sign_in_password.assert_not_called()


def test_channel_skip_does_not_cross_profiles(monkeypatch):
    import paths
    import companycam_api as cc
    monkeypatch.setattr(cc, "_call", Mock(side_effect=RuntimeError("offline")))
    monkeypatch.setattr(paths, "CHANNEL", "main")
    setup.action(None, "skip_companycam")
    assert setup.status(None)["all_done"]
    monkeypatch.setattr(paths, "CHANNEL", "trial")
    assert not setup.status(None)["all_done"]


def test_verified_user_all_probes_raise(monkeypatch):
    import account_access
    import trello_client
    import companycam_api as cc
    import supabase_client as sb
    assert setup.status(None)["all_done"]
    for obj, name in [(account_access, "current_access"), (trello_client, "_call"),
                      (cc, "_call"), (sb, "rest"), (sb, "external_connection_status"),
                      (setup, "_read_folder"), (settings_web.Api, "employee_setup_status")]:
        monkeypatch.setattr(obj, name, Mock(side_effect=RuntimeError("offline")))
    assert shell().first_run()["show"] is False


def test_verified_user_signed_out(isolated):
    assert setup.status(None)["all_done"]
    isolated[1].update(signed_in=False, identity={})
    assert shell().first_run()["show"] is True


@pytest.mark.parametrize("changed", ["user", "channel", "franchise", "backend"])
def test_verified_record_other_scope_ignored(isolated, monkeypatch, changed):
    import config
    import paths
    import trello_client
    assert setup.status(None)["all_done"]
    cfg, access = isolated
    if changed == "user":
        access["identity"] = {"id": "different-user"}
    elif changed == "channel":
        monkeypatch.setattr(paths, "CHANNEL", "different-channel")
    elif changed == "franchise":
        monkeypatch.setattr(config, "active_department", lambda: "OTHER")
    else:
        cfg["supabase_url"] = "https://another.invalid"
    monkeypatch.setattr(trello_client, "_call", Mock(side_effect=RuntimeError("offline")))
    assert shell().first_run()["show"] is True


def test_fresh_user_probe_raises(monkeypatch):
    import trello_client
    monkeypatch.setattr(trello_client, "_call", Mock(side_effect=RuntimeError("offline")))
    assert shell().first_run()["show"] is True
    assert not setup._choices()


def test_verified_access_error_is_not_revocation(isolated):
    assert setup.status(None)["all_done"]
    isolated[1].update(error="offline", departments=[])
    assert shell().first_run()["show"] is False
    isolated[1]["error"] = ""
    assert shell().first_run()["show"] is True


def test_completion_preserved_by_optional_skip():
    assert setup.status(None)["all_done"]
    setup.action(None, "skip_companycam")
    record = next(iter(setup._choices().values()))
    assert record["verified_complete"] is True
    assert record["companycam_skipped"] is True
