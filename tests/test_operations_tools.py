from pathlib import Path

import operations_tools
from operations_web import Api


ROOT = Path(__file__).resolve().parents[1]


def test_every_operations_tool_has_a_real_browser_asset():
    rows = operations_tools.asset_health(ROOT)
    assert rows
    assert all(row["ok"] for row in rows), [row for row in rows if not row["ok"]]


def test_new_loss_routes_to_mature_intake_in_both_shells():
    routes = operations_tools.browser_routes()
    assert routes["new_job"] == "/tools/?panel=daily_run&new_loss=1"
    calls = []
    result = operations_tools.launch_desktop(
        "new_job", lambda tool, *args: calls.append((tool, args)))
    assert result["ok"] is True
    assert calls == [("audit_web", ("--new-loss",))]


def test_every_visible_tool_uses_one_stable_catalog():
    catalog = operations_tools.catalog()
    expected = {
        "new_job", "audit_web", "snapshot_web", "job_notes_web",
        "apa_web", "disputes_web", "kpi_web", "photo_folders_web",
        "run_doc_editor_web",
        "resources_web", "cheat_sheet_web", "settings_web", "home_web",
    }
    assert set(catalog) == expected
    assert all(item["browser_url"].startswith("/tools/") for item in catalog.values())


def test_operations_desktop_exposes_field_notes_and_launch_interface():
    api = Api.__new__(Api)
    api.hub = object()
    api._window = None
    assert callable(Api.launch_tool)
    assert callable(Api.field_note_templates)
    assert callable(Api.save_field_note)


def test_home_shell_retries_new_loss_until_daily_run_is_ready():
    source = (ROOT / "home_web_assets" / "app.js").read_text(encoding="utf-8")
    assert "function openNewLossWhenReady(frame)" in source
    assert "Date.now() - started < 10000" in source
    assert source.count("openNewLossWhenReady(") >= 3


def test_standalone_audit_accepts_direct_new_loss_request():
    source = (ROOT / "audit_web.py").read_text(encoding="utf-8")
    assert '"--new-loss" in _argv' in source
    assert "openNewLossModal()" in source
