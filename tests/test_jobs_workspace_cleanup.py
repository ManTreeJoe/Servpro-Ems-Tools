from pathlib import Path

import home_web


ROOT = Path(__file__).resolve().parents[1]


def test_pipeline_is_the_primary_jobs_workspace_and_reporting_is_grouped():
    groups = {name: items for name, items in home_web.NAV_GROUPS}
    work = {key: label for key, _icon, label in groups["Work"]}
    reports = {key: label for key, _icon, label in groups["Reports"]}

    assert list(work)[0] == "pipeline"
    assert work["pipeline"] == "Jobs"
    assert list(work)[1] == "daily_run"
    assert work["daily_run"] == "Daily Run"
    assert home_web._asset_folder_for("daily_run").endswith(
        "audit_web_assets/index.html?surface=daily")
    assert work["audit"] == "Clients"
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
