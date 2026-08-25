from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_import_hub_keeps_all_sources_in_one_entry_point():
    js = (ROOT / "audit_web_assets" / "app.js").read_text(encoding="utf-8")
    block = js[js.index("async function openJobImportModal"):
               js.index("// ── Match diagnostic modal")]
    for source in ("job-source-downloads", "job-import-pick", "job-source-sp",
                   "job-source-cc", "job-source-trello"):
        assert source in block
    assert "Nothing imports until you press Extract or choose a file" in block


def test_import_hub_has_session_result_ledger():
    js = (ROOT / "audit_web_assets" / "app.js").read_text(encoding="utf-8")
    assert "function addImportResult" in js
    assert 'id="job-import-result-list"' in js
