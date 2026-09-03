from pathlib import Path

import clients_web


ROOT = Path(__file__).resolve().parents[1]


def test_clients_is_a_standalone_workspace():
    shell = (ROOT / "home_web.py").read_text(encoding="utf-8")
    assert '("clients",     "👥", "Clients")' in shell
    assert '"clients":     "clients_web"' in shell
    assert 'surface=clients' not in shell
    assert (ROOT / "clients_web.py").exists()
    assert (ROOT / "clients_web_assets" / "index.html").exists()


def test_client_hierarchy_and_job_tabs_are_owned_by_clients_module():
    backend = (ROOT / "clients_web.py").read_text(encoding="utf-8")
    js = (ROOT / "clients_web_assets" / "app.js").read_text(encoding="utf-8")
    for marker in ("job_folders.list_children", "job_folders.shells_at",
                   "job_folders.is_child_job_folder", "def client_account"):
        assert marker in backend
    for marker in ("data-job-tab", "data-job-panel", "data-open-job",
                   'type: "linguar-open-job"'):
        assert marker in js


def test_client_job_opens_shared_card_above_the_current_page():
    clients = (ROOT / "clients_web_assets" / "app.js").read_text(encoding="utf-8")
    shell = (ROOT / "home_web_assets" / "app.js").read_text(encoding="utf-8")
    pipeline = (ROOT / "pipeline_web_assets" / "app.js").read_text(encoding="utf-8")
    assert 'window.parent.postMessage({ type: "linguar-open-job"' in clients
    assert 'd.type === "linguar-open-job"' in shell
    assert "function openJobWorkspace(" in shell
    assert 'job_workspace: "1"' in shell
    assert 'pipelineQuery.get("job_workspace") === "1"' in pipeline
    assert "await onAuditCard(requestedFocus" in pipeline


def test_audit_did_not_gain_client_account_rendering():
    backend = (ROOT / "audit_web.py").read_text(encoding="utf-8")
    js = (ROOT / "audit_web_assets" / "app.js").read_text(encoding="utf-8")
    assert "client_account_workspace" not in backend
    assert "renderClientAccount" not in js


def test_job_cards_route_to_new_client_workspace():
    js = (ROOT / "pipeline_web_assets" / "app.js").read_text(encoding="utf-8")
    assert 'emsNavigateTo("clients", client)' in js
    assert 'emsNavigateTo("clients", res.client || "")' in js


def test_management_job_title_resolves_to_real_parent_client(monkeypatch):
    def search(query, *, limit=250, **_kwargs):
        if query == "PCM":
            return [{"name": "PCM", "path": r"X:\IE_Public\2026 Jobs\PCM",
                     "children": ["Kellogg Terrace Condominium"]}]
        return []

    import job_folders
    monkeypatch.setattr(job_folders, "search_clients", search)
    monkeypatch.setattr(clients_web.Api, "_divisions", staticmethod(lambda _path: ["EMS"]))

    result = clients_web.Api().list_clients(
        "PCM - (Kellogg Terrace) - Cruz, Sarah 8/28")

    assert result["ok"] is True
    assert [row["name"] for row in result["clients"]] == ["PCM"]
    assert result["clients"][0]["job_count"] == 2


def test_client_page_exposes_dates_full_job_info_and_logs():
    backend = (ROOT / "clients_web.py").read_text(encoding="utf-8")
    js = (ROOT / "clients_web_assets" / "app.js").read_text(encoding="utf-8")
    assert '"date_received"' in backend
    assert '"job_log": client_logs' in backend
    assert "list_job_log_entries" in backend
    for label in ("Date received", "Date of loss", "Claim number", "Carrier",
                  "Cause of loss", "Adjuster", "Job log"):
        assert label in js


def test_management_property_with_nested_claims_uses_claim_tabs():
    backend = (ROOT / "clients_web.py").read_text(encoding="utf-8")
    assert 'combined = f"{child_name} — {nested_name}"' in backend
    assert "nested_path" in backend
