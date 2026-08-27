"""Job Workspace stays mounted through unrelated audit detail repaints."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_workspace_load_is_cached_and_deduplicated():
    shared = (ROOT / "web_shared" / "audit_detail.js").read_text(
        encoding="utf-8")
    assert "const _crmWorkspaceCache = new Map()" in shared
    assert "const _crmWorkspaceLoads = new Map()" in shared
    assert 'box.dataset.crmReady === "1"' in shared
    assert "loadCrmWorkspace(container, r, ctx, true)" in shared


def test_audit_repaint_preserves_loaded_workspace_for_same_job():
    audit = (ROOT / "audit_web_assets" / "app.js").read_text(
        encoding="utf-8")
    assert "const priorWorkspace = view.querySelector" in audit
    assert "priorWorkspaceClient === String(r.client" in audit
    assert "nextWorkspace.replaceWith(priorWorkspace)" in audit
