import apa_web
from pathlib import Path


def test_bulk_name_key_ignores_carrier_and_status():
    api = apa_web.Api()
    assert api._bulk_name_key("Smith, John - AAA - pending") == "smith, john"
    assert api._bulk_name_key("Smith, John - uploaded") == "smith, john"


def test_bulk_name_checker_finds_unknowns_across_sections(monkeypatch):
    api = apa_web.Api()
    monkeypatch.setattr(apa_web.os.path, "isfile", lambda _p: True)
    monkeypatch.setattr(apa_web.apa, "parse_existing_doc", lambda _p: {
        "Initial Uploads": [("Smith, John - AAA - pending", False)],
        "Final Uploads": [("Doe, Jane - Mercury", False)],
    })
    result = api.check_bulk_items([
        "Smith, John - uploaded",
        "Brown, Bob - Farmers",
        "Brown, Bob - pending",
    ])
    assert result["ok"] is True
    assert result["unknown"] == ["Brown, Bob - Farmers"]
    assert [row["line"] for row in result["existing"]] == ["Smith, John - uploaded"]
    assert result["repeated"] == ["Brown, Bob - pending"]


def test_apa_page_busts_cache_for_name_checker_script():
    root = Path(__file__).resolve().parents[1]
    html = (root / "apa_web_assets" / "index.html").read_text(encoding="utf-8")
    assert 'app.js?v=20260826b' in html
