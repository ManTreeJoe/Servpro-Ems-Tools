"""Daily Run email pull + WorkCenter action regressions."""
from __future__ import annotations

import pathlib
import sys
import types

import audit_web


ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_email_pull_prefers_customer_from_trello(monkeypatch):
    api = audit_web.Api()
    monkeypatch.setattr(api, "trello_enrichment", lambda *_a, **_k: {
        "ok": True,
        "customer_email": "mailto:insured@example.com",
        "adjuster_email": "adjuster@carrier.com",
    })
    assert api.get_job_email("Customer", "card1") == {
        "ok": True, "email": "insured@example.com",
        "kind": "Customer", "source": "Trello",
    }


def test_email_pull_falls_back_to_saved_job(monkeypatch):
    api = audit_web.Api()
    monkeypatch.setattr(api, "trello_enrichment",
                        lambda *_a, **_k: {"ok": False, "error": "offline"})
    fake_db = types.SimpleNamespace(find_job_by_name=lambda _name: {
        "email": "", "adjuster_email": "claims@carrier.test",
    })
    monkeypatch.setitem(sys.modules, "ems_db", fake_db)
    result = api.get_job_email("Customer", "card1")
    assert result["ok"] is True
    assert result["email"] == "claims@carrier.test"
    assert result["source"] == "saved job"


def test_email_button_is_clickable_and_can_retry_itself():
    shared = (ROOT / "web_shared" / "audit_detail.js").read_text(encoding="utf-8")
    button = shared[shared.index('data-action="copy-email"'):]
    button = button[:button.index("</button>")]
    assert "disabled" not in button
    assert "📧 Copy email" in button
    assert "get_job_email(" in shared
    assert 'btn.textContent = "Getting email…"' in shared


def test_workcenter_uses_configured_url(monkeypatch):
    import workcenter_client

    opened = []
    monkeypatch.setattr(workcenter_client, "_config_url",
                        lambda: "https://wc.example/")
    monkeypatch.setattr(audit_web.dept_browser, "open_url", opened.append)
    result = audit_web.Api().open_workcenter()
    assert result == {"ok": True, "url": "https://wc.example/"}
    assert opened == ["https://wc.example/"]


def test_job_card_has_workcenter_button_and_handler():
    shared = (ROOT / "web_shared" / "audit_detail.js").read_text(encoding="utf-8")
    audit_js = (ROOT / "audit_web_assets" / "app.js").read_text(encoding="utf-8")
    assert 'data-action="open-workcenter"' in shared
    assert 'action === "open-workcenter"' in shared
    assert "pywebview.api.open_workcenter()" in audit_js
    assert "app.workcenter.servpro.net" not in audit_js


def test_every_shared_card_loader_has_the_new_version():
    versions = set()
    for path in ROOT.glob("*_web_assets/index.html"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        marker = "audit_detail.js?v="
        if marker in text:
            versions.add(text.split(marker, 1)[1].split('"', 1)[0])
    assert versions == {"20260825h"}
