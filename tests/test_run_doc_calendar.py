"""Fast month navigation for the Daily Run audit."""
from pathlib import Path

import audit_web
import apa_web
import run_doc


def test_month_index_finds_ie_and_oc_filename_formats(tmp_path, monkeypatch):
    month = tmp_path / "August"
    month.mkdir()
    for name in (
        "Saturday 8.1.26.docx",
        "Sunday 08-02-2026.docx",
        "Monday 8032026.msg",
        "Tuesday 8_04_26.docx",
        "~$Tuesday 8.04.26.docx",
        "not-a-run.docx",
    ):
        (month / name).write_bytes(b"test")
    monkeypatch.setattr(run_doc, "_runs_dir", lambda: str(tmp_path))
    assert run_doc.run_doc_dates_for_month(2026, 8) == [
        "2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04"]


def test_month_index_handles_year_nested_run_root(tmp_path, monkeypatch):
    month = tmp_path / "2026" / "Aug"
    month.mkdir(parents=True)
    (month / "Monday 8.24.26.docx").write_bytes(b"test")
    monkeypatch.setattr(run_doc, "_runs_dir", lambda: str(tmp_path))
    assert run_doc.run_doc_dates_for_month(2026, 8) == ["2026-08-24"]


def test_calendar_api_returns_iso_dates(monkeypatch):
    monkeypatch.setattr(audit_web, "run_doc_dates_for_month",
                        lambda year, month: ["2026-08-21", "2026-08-24"])
    result = audit_web.Api().run_doc_calendar(2026, 8)
    assert result == {"ok": True, "year": 2026, "month": 8,
                      "dates": ["2026-08-21", "2026-08-24"], "count": 2}


def test_day_lookup_returns_machine_readable_date(monkeypatch):
    monkeypatch.setattr(audit_web, "_find_run_doc_for_date", lambda day: None)
    result = audit_web.Api().find_run_doc_for(0)
    assert result["date_iso"].count("-") == 2


def test_audit_calendar_ui_has_run_dots_and_date_jump():
    root = Path(__file__).resolve().parents[1] / "audit_web_assets"
    html = (root / "index.html").read_text(encoding="utf-8")
    css = (root / "app.css").read_text(encoding="utf-8")
    js = (root / "app.js").read_text(encoding="utf-8")
    assert 'id="run-calendar"' in html
    assert 'class="run-dot"' in html and ".calendar-day.has-run::after" in css
    assert "run_doc_calendar" in js
    assert "selectCalendarDate" in js and "Date.UTC" in js
    assert 'app.js?v=20260827b' in html


def test_apa_calendar_marks_existing_documents(monkeypatch):
    monkeypatch.setattr(apa_web.apa, "doc_path_for_today",
                        lambda day: f"C:/runs/{day.isoformat()}.docx")
    monkeypatch.setattr(apa_web.os.path, "isfile",
                        lambda path: path.endswith("2026-08-03.docx") or
                                     path.endswith("2026-08-24.docx"))
    result = apa_web.Api().run_doc_calendar(2026, 8)
    assert result["ok"] is True
    assert result["dates"] == ["2026-08-03", "2026-08-24"]


def test_apa_uses_daily_run_calendar_instead_of_date_chip_strip():
    root = Path(__file__).resolve().parents[1] / "apa_web_assets"
    html = (root / "index.html").read_text(encoding="utf-8")
    css = (root / "app.css").read_text(encoding="utf-8")
    js = (root / "app.js").read_text(encoding="utf-8")
    assert 'id="run-calendar"' in html
    assert 'id="date-strip"' not in html
    assert ".calendar-day.has-run::after" in css
    assert "pywebview.api.run_doc_calendar" in js
