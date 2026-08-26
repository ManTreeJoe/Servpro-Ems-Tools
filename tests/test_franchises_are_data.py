from pathlib import Path

import config


ROOT = Path(__file__).resolve().parents[1]


def test_empty_scaffold_does_not_invent_ie_or_oc(monkeypatch):
    state = {"departments": {}, "active_department": ""}
    monkeypatch.setattr(config, "load_base", lambda: dict(state))
    monkeypatch.setattr(config, "save", lambda value: state.update(value))
    result = config.ensure_departments_scaffold()
    assert result["departments"] == {}
    assert result.get("active_department", "") == ""


def test_settings_has_no_fixed_franchise_fallback():
    html = (ROOT / "settings_web_assets" / "index.html").read_text(encoding="utf-8")
    assert 'res.departments : ["IE", "OC"]' not in html
    assert "configure OC below" not in html
    assert "Inland Empire uses the main settings" not in html


def test_access_template_uses_placeholders_not_fixed_offices():
    sql = (ROOT / "supabase" / "002_grant_access.sql").read_text(encoding="utf-8")
    assert "<FRANCHISE_CODE>" in sql
    assert "<EMPLOYEE_EMAIL>" in sql
    assert "values ('IE'), ('OC')" not in sql
