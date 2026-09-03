from pathlib import Path

import home_web


ROOT = Path(__file__).resolve().parents[1]


def test_pipeline_is_the_primary_jobs_workspace_and_reporting_is_grouped():
    groups = {name: items for name, items in home_web.NAV_GROUPS}
    work = {key: label for key, _icon, label in groups["Work"]}
    reports = {key: label for key, _icon, label in groups["Reports"]}

    assert list(work)[0] == "pipeline"
    assert work["pipeline"] == "Jobs"
    assert "daily_run" not in work
    assert home_web._asset_folder_for("daily_run").endswith(
        "audit_web_assets/index.html?surface=daily")
    assert work["clients"] == "Clients"
    assert home_web._asset_folder_for("clients").endswith(
        "clients_web_assets/index.html")
    assert work["snapshot"] == "Snapshot"
    assert reports["apa"] == "APA"
    assert "hygiene" in reports
    assert "pipeline" not in reports
    assert "kpi" not in reports


def test_snapshot_session_reopens_snapshot(monkeypatch):
    monkeypatch.setattr(home_web.persistence, "get",
                        lambda key, default=None:
                        "snapshot" if key == "home_last_panel" else False)
    api = object.__new__(home_web.HomeApi)
    api._failed_subs = {}
    assert api.get_last_panel() == "snapshot"


def test_job_card_groups_actions_and_opens_closeout_workspace():
    shared = (ROOT / "web_shared" / "audit_detail.js").read_text(
        encoding="utf-8")
    audit = (ROOT / "audit_web_assets" / "app.js").read_text(
        encoding="utf-8")
    shell = (ROOT / "home_web_assets" / "app.js").read_text(
        encoding="utf-8")

    for label in ("Open", "Import", "Job details", "Update", "Finish"):
        assert f'class="action-group-label">{label}</span>' in shared
    assert 'data-action="snapshot-closeout"' in shared
    assert 'type: "ems-open-tool-modal"' in audit
    assert 'd.key === "snapshot"' in shell
    assert "function openSnapshotModal" in shell


def test_audit_no_longer_appends_duplicate_shared_actions():
    audit = (ROOT / "audit_web_assets" / "app.js").read_text(
        encoding="utf-8")
    extension = audit[audit.index("const origRenderDetail"):
                      audit.index("async function doReaudit")]
    assert 'add("📋 Scope"' not in extension
    assert 'add("↻ Re-audit"' not in extension
    assert 'add("⋯ More actions"' not in extension


def test_clients_use_division_views_and_new_loss_lives_in_jobs():
    clients_html = (ROOT / "clients_web_assets" / "index.html").read_text(
        encoding="utf-8")
    clients_js = (ROOT / "clients_web_assets" / "app.js").read_text(
        encoding="utf-8")
    jobs_html = (ROOT / "pipeline_web_assets" / "index.html").read_text(
        encoding="utf-8")
    shell_js = (ROOT / "home_web_assets" / "app.js").read_text(
        encoding="utf-8")

    for key in ("all", "EMS", "CONTENTS", "RECON"):
        assert f'data-division="{key}"' in clients_html
    assert 'id="new-loss-btn"' not in clients_html
    assert "divisionText" in clients_js
    assert 'id="new-loss-btn" class="btn"' in jobs_html
    assert 'id="view-daily-btn"' in jobs_html
    assert "linguar-open-new-loss" in shell_js


def test_jobs_search_can_surface_cards_outside_the_visible_board():
    jobs_js = (ROOT / "pipeline_web_assets" / "app.js").read_text(
        encoding="utf-8")
    backend = (ROOT / "pipeline_web.py").read_text(encoding="utf-8")
    assert "globalSearchResults" in jobs_js
    assert "global_card_search" in jobs_js
    assert "def global_card_search" in backend
