"""The main Settings form may only write its own fields.

This bug bit twice in one day. The page's save loop used a GLOBAL
`[data-key]` selector, which also matched the Departments editor (showing
whichever department was picked — OC by default) and the panel-visibility
checkboxes. Clicking 💾 Save therefore wrote that department's values,
including `trello_workspace_id`, into the config.

First time it landed in the base, and IE — which inherited the base —
started searching OC's Trello workspace and matched nothing. After the save
was rerouted to the active department it landed straight in IE's profile
and did the same thing again.

Two defences, both tested here:
  1. the selector is scoped to #form-fields          (UI)
  2. save() ignores any key not declared in FIELDS   (API)
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import settings_web

_SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_IE_WS = "6000dbdc5bc7840c91334167"
_OC_WS = "67b3aa86edf2c0f18da56a8f"


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """A realistic two-department config with IE active."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "multi_department_enabled": True,
        "active_department": "IE",
        "trello_workspace_id": _IE_WS,
        "audit_base": r"X:\IE_Public",
        "workcenter_url": "https://wc.example",
        "departments": {
            "IE": {"label": "IE", "trello_workspace_id": _IE_WS,
                   "audit_base": r"X:\IE_Public"},
            "OC": {"label": "OC", "trello_workspace_id": _OC_WS,
                   "audit_base": r"C:\OC"},
        },
    }), encoding="utf-8")
    monkeypatch.setattr(config, "_USER_CFG", str(path))
    monkeypatch.setattr(config, "_CACHE", None)
    monkeypatch.setattr(config, "_CACHE_MTIME", None)
    return path


def _reload():
    config._CACHE = None
    config._CACHE_MTIME = None
    return config.load_base()


# ── the guard ───────────────────────────────────────────────────────────

def test_the_exact_bug_cannot_recur(cfg):
    """Save the main form while the Departments editor happens to be
    showing OC — the payload carries OC's workspace id. It must not land
    anywhere."""
    res = settings_web.Api().save({
        "workcenter_url": "https://new",       # a real main-form field
        "trello_workspace_id": _OC_WS,         # swept from the dept editor
    })
    assert res["ok"]
    assert "trello_workspace_id" in res["ignored_keys"]
    base = _reload()
    assert base["trello_workspace_id"] == _IE_WS
    assert base["departments"]["IE"]["trello_workspace_id"] == _IE_WS
    assert base["workcenter_url"] == "https://new", "the real field saved"


def test_panel_visibility_checkboxes_are_ignored(cfg):
    """Those carry data-key too and were swept up by the same selector."""
    res = settings_web.Api().save({"panel_hidden_kpi": True,
                                   "workcenter_url": "https://x"})
    assert res["ok"] and "panel_hidden_kpi" in res["ignored_keys"]
    assert "panel_hidden_kpi" not in _reload()


def test_dept_only_keys_are_all_blocked(cfg):
    """Every DEPT_FIELDS key that is NOT also a main-form field must be
    unwritable here."""
    main = {f[0] for f in settings_web.FIELDS}
    dept_only = [f[0] for f in settings_web.DEPT_FIELDS if f[0] not in main]
    assert dept_only, "expected some department-only fields"
    res = settings_web.Api().save({k: "x" for k in dept_only})
    assert sorted(res["ignored_keys"]) == sorted(dept_only)


def test_unknown_keys_never_reach_the_config(cfg):
    settings_web.Api().save({"totally_made_up": "1"})
    assert "totally_made_up" not in _reload()


def test_a_rejected_key_does_not_fail_the_save(cfg):
    """Ignoring is deliberate — failing would block a legitimate change."""
    res = settings_web.Api().save({"junk": 1, "workcenter_url": "https://ok"})
    assert res["ok"]
    assert _reload()["workcenter_url"] == "https://ok"


def test_legitimate_dept_scoped_field_still_routes(cfg):
    """audit_base IS a main-form field and also department-scoped — it must
    still reach the active department, not be blocked by the guard."""
    res = settings_web.Api().save({"audit_base": r"X:\NewRoot"})
    assert res["ok"] and res["routed_to_department"] == ["audit_base"]
    base = _reload()
    assert base["departments"]["IE"]["audit_base"] == r"X:\NewRoot"
    assert base["departments"]["OC"]["audit_base"] == r"C:\OC", "OC untouched"


# ── the UI half ─────────────────────────────────────────────────────────

def test_save_selector_is_scoped_to_the_main_form():
    """A global [data-key] sweep is what collected the department editor."""
    html = open(os.path.join(_SCRIPTS, "settings_web_assets", "index.html"),
                encoding="utf-8").read()
    assert 'querySelectorAll("#form-fields [data-key]")' in html
    assert 'querySelectorAll("[data-key]")' not in html, (
        "global data-key selector is back — it also matches the Departments "
        "editor and the panel-visibility checkboxes")


def test_department_editor_saves_through_its_own_api():
    """The dept editor has its own scoped selector + endpoint, so the two
    forms can't write each other's fields."""
    html = open(os.path.join(_SCRIPTS, "settings_web_assets", "index.html"),
                encoding="utf-8").read()
    assert 'querySelectorAll("#dept-fields input[data-key]")' in html
    assert "save_department(" in html
