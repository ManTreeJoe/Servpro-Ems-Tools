from pathlib import Path

import pytest

import settings_web


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def administrator(monkeypatch):
    monkeypatch.setattr(settings_web, "_is_admin", lambda: True)


def test_settings_schema_separates_personal_and_admin_fields():
    rows = settings_web.Api().schema()
    by_key = {row["key"]: row for row in rows}
    assert by_key["appearance"]["scope"] == "personal"
    assert by_key["global_hotkey"]["scope"] == "personal"
    assert by_key["audit_base"]["scope"] == "personal"
    assert by_key["runs_dir"]["scope"] == "personal"
    assert by_key["trello_token"]["scope"] == "personal"
    assert by_key["companycam_api_token"]["scope"] == "admin"
    assert by_key["supabase_anon_key"]["scope"] == "admin"


def test_previously_raw_operational_settings_are_exposed():
    keys = {row["key"] for row in settings_web.Api().schema()}
    required = {
        "snapshots_root", "dispute_tracker_path", "wc_audit_dir",
        "photos_extra_roots", "enable_workcenter_alpha",
        "snapshot_auto_reconcile", "trello_workspace_id",
        "trello_snapshot_list_id", "trello_boards_exclude",
        "disputes_board_short_link", "franchise_name", "office_phone",
        "graph_client_id", "graph_tenant_id", "preferred_browser",
    }
    assert required <= keys


def test_settings_page_has_role_tabs_and_scoped_sections():
    html = (ROOT / "settings_web_assets" / "index.html").read_text(encoding="utf-8")
    assert 'data-scope-tab="personal"' in html
    assert 'data-scope-tab="admin"' in html
    assert 'data-settings-scope="personal"' in html
    assert 'data-settings-scope="admin"' in html
    assert 'data-settings-scope="both"' in html
    assert 'aria-label="Settings level"' in html
    assert 'SETTINGS_ACCESS.is_admin || field.scope === "personal"' in html
    assert "if (!writable.has(k)) return" in html
    assert 'id="folder-path-preview"' in html
    assert 'id="folder-path-apply"' in html
    assert "portable_folder_migration" in html


def test_list_settings_are_normalized_on_save(monkeypatch):
    state = {"photos_extra_roots": []}
    monkeypatch.setattr(settings_web.config, "load_base", lambda: dict(state))
    monkeypatch.setattr(settings_web.config, "save", lambda cfg: state.update(cfg))
    monkeypatch.setattr(settings_web, "_invalidate", lambda reason: {})
    result = settings_web.Api().save({
        "photos_extra_roots": "X:/Photos\nY:/Photos; Z:/Photos",
    })
    assert result["ok"] is True
    assert state["photos_extra_roots"] == ["X:/Photos", "Y:/Photos", "Z:/Photos"]


def test_regular_employee_can_save_machine_local_paths(monkeypatch):
    state = {"multi_department_enabled": False}
    monkeypatch.setattr(settings_web, "_is_admin", lambda: False)
    monkeypatch.setattr(settings_web, "_admin_enforcement_active", lambda: True)
    monkeypatch.setattr(settings_web.config, "load", lambda: dict(state))
    monkeypatch.setattr(settings_web.config, "load_base", lambda: dict(state))
    monkeypatch.setattr(settings_web.config, "save", lambda cfg: state.update(cfg))
    monkeypatch.setattr(settings_web, "_invalidate", lambda reason: {})
    result = settings_web.Api().save({
        "audit_base": r"C:\Users\Laura\OneDrive\Jobs",
        "runs_dir": r"C:\Users\Laura\OneDrive\Runs",
        "trello_token": "laura-personal-token",
    })
    assert result["ok"]
    assert state["audit_base"].endswith(r"OneDrive\Jobs")
    assert state["runs_dir"].endswith(r"OneDrive\Runs")
    assert state["trello_token"] == "laura-personal-token"
