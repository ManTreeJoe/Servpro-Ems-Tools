from pathlib import Path


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
                   'emsNavigateTo("pipeline"'):
        assert marker in js


def test_audit_did_not_gain_client_account_rendering():
    backend = (ROOT / "audit_web.py").read_text(encoding="utf-8")
    js = (ROOT / "audit_web_assets" / "app.js").read_text(encoding="utf-8")
    assert "client_account_workspace" not in backend
    assert "renderClientAccount" not in js


def test_job_cards_route_to_new_client_workspace():
    js = (ROOT / "pipeline_web_assets" / "app.js").read_text(encoding="utf-8")
    assert 'emsNavigateTo("clients", client)' in js
    assert 'emsNavigateTo("clients", res.client || "")' in js
