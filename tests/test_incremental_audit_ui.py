from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_audit_reports_incremental_reuse_and_rechecks():
    backend = (ROOT / "audit_web.py").read_text(encoding="utf-8")
    frontend = (ROOT / "audit_web_assets" / "app.js").read_text(encoding="utf-8")
    for key in ('"cached"', '"rechecked"', '"ran_at_iso"'):
        assert key in backend
    assert "unchanged" in frontend
    assert "full scan" in frontend


def test_full_rescan_remains_manual_fallback():
    html = (ROOT / "audit_web_assets" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "audit_web_assets" / "app.js").read_text(encoding="utf-8")
    assert 'id="rerun-btn"' in html
    assert '$("#rerun-btn").addEventListener("click", () => runAudit(false))' in js
