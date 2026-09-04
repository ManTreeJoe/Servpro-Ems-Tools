from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_home_shell_does_not_expose_the_retired_tk_launcher():
    html = _read("home_web_assets/index.html")
    js = _read("home_web_assets/app.js")
    home_api = _read("home_web.py")
    browser_host = _read("browser_tools.py")

    assert "legacy-btn" not in html
    assert "legacy-btn" not in js
    assert "open_tk_launcher" not in home_api
    assert "open_tk_launcher" not in browser_host


def test_product_headers_do_not_show_internal_web_prototype_labels():
    panel_paths = (
        "apa_web_assets/index.html",
        "cheat_sheet_web_assets/index.html",
        "disputes_web_assets/index.html",
        "job_notes_web_assets/index.html",
        "kpi_web_assets/index.html",
        "multi_unit_web_assets/index.html",
        "photo_folders_web_assets/index.html",
        "spreadsheet_web_assets/index.html",
        "wc_audit_web_assets/index.html",
    )
    retired_labels = (">web<", ">web spike<", ">web spike · read-only<", ">web · viewer<")
    for path in panel_paths:
        html = _read(path)
        assert all(label not in html for label in retired_labels), path


def test_snapshot_tracker_uses_named_layout_styles_instead_of_repeated_inline_rules():
    html = _read("snapshot_web_assets/index.html")

    assert 'class="snapshot-tabs"' in html
    assert 'class="tracked-table"' in html
    assert 'class="tracked-table-head"' in html
    assert "text-align:left;padding:8px 10px;font-weight:600" not in html
