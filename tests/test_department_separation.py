"""Department (IE / OC) separation guards.

Covers the failure that shipped: IE had an empty department profile, so it
inherited the base config — and the base's `trello_workspace_id` had been
overwritten with OC's. Every IE card search then ran against the OC
workspace and silently matched nothing.

  - check_department_integrity flags two departments sharing an identity
  - it flags an identity value inherited from the (writable) base
  - it stays quiet on a correctly separated setup
  - load_for resolves any department without switching
  - settings save routes department-scoped keys to the ACTIVE department
    instead of the base
  - ensure_departments_scaffold pins IE's identity explicitly
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config


def _write(tmp_path, monkeypatch, cfg):
    """Point config at a throwaway config.json and clear its mtime cache."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(config, "_USER_CFG", str(path))
    monkeypatch.setattr(config, "_CACHE", None)
    monkeypatch.setattr(config, "_CACHE_MTIME", None)
    return path


def _base(**over):
    cfg = {
        "multi_department_enabled": True,
        "active_department": "IE",
        "trello_workspace_id": "ie-workspace",
        "audit_base": r"X:\IE_Public",
        "runs_dir": r"X:\IE_Public\Runs",
        "departments": {
            "IE": {"label": "Inland Empire",
                   "trello_workspace_id": "ie-workspace",
                   "audit_base": r"X:\IE_Public",
                   "runs_dir": r"X:\IE_Public\Runs"},
            "OC": {"label": "Orange County",
                   "trello_workspace_id": "oc-workspace",
                   "audit_base": r"C:\OC",
                   "runs_dir": r"C:\OC\Runs"},
        },
    }
    cfg.update(over)
    return cfg


def _levels(problems, key=None):
    return [p for p in problems
            if key is None or p["key"] == key]


def test_clean_setup_reports_nothing(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, _base())
    assert config.check_department_integrity() == []


def test_shared_workspace_is_an_error(tmp_path, monkeypatch):
    """The exact live bug: both departments on one Trello workspace."""
    cfg = _base()
    cfg["departments"]["OC"]["trello_workspace_id"] = "ie-workspace"
    _write(tmp_path, monkeypatch, cfg)
    problems = config.check_department_integrity()
    collisions = [p for p in problems
                  if p["level"] == "error"
                  and p["key"] == "trello_workspace_id"]
    assert len(collisions) == 1
    assert "IE" in collisions[0]["dept"] and "OC" in collisions[0]["dept"]


def test_inherited_identity_is_flagged(tmp_path, monkeypatch):
    """An empty profile inherits the base — the setup that made the
    collision possible in the first place."""
    cfg = _base()
    cfg["departments"]["IE"] = {"label": "Inland Empire"}
    _write(tmp_path, monkeypatch, cfg)
    problems = config.check_department_integrity()
    inherited = [p for p in problems
                 if p["level"] == "warn" and p["dept"] == "IE"]
    assert {p["key"] for p in inherited} == set(config.DEPT_IDENTITY_KEYS)


def test_inherited_base_collision_reproduces_the_live_bug(tmp_path, monkeypatch):
    """IE inherits; the base holds OC's workspace. Must be an ERROR, not
    just a warning — this is the state that broke card matching."""
    cfg = _base(trello_workspace_id="oc-workspace")
    cfg["departments"]["IE"] = {"label": "Inland Empire"}
    _write(tmp_path, monkeypatch, cfg)
    problems = config.check_department_integrity()
    assert any(p["level"] == "error" and p["key"] == "trello_workspace_id"
               for p in problems)


def test_missing_identity_is_an_error(tmp_path, monkeypatch):
    cfg = _base(trello_workspace_id="")
    cfg["departments"]["IE"] = {"label": "Inland Empire"}
    _write(tmp_path, monkeypatch, cfg)
    problems = config.check_department_integrity()
    assert any(p["level"] == "error" and p["dept"] == "IE"
               and p["key"] == "trello_workspace_id" for p in problems)


def test_paths_compare_case_and_separator_insensitively(tmp_path, monkeypatch):
    """Windows: X:\\IE_Public and x:/ie_public/ are the same share."""
    cfg = _base()
    cfg["departments"]["OC"]["audit_base"] = "x:/ie_public"
    _write(tmp_path, monkeypatch, cfg)
    problems = config.check_department_integrity()
    assert any(p["level"] == "error" and p["key"] == "audit_base"
               for p in problems)


def test_check_is_quiet_when_multi_dept_off(tmp_path, monkeypatch):
    cfg = _base(multi_department_enabled=False)
    cfg["departments"]["OC"]["trello_workspace_id"] = "ie-workspace"
    _write(tmp_path, monkeypatch, cfg)
    assert config.check_department_integrity() == []


def test_load_for_resolves_a_non_active_department(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, _base())
    assert config.load()["trello_workspace_id"] == "ie-workspace"
    assert config.load_for("OC")["trello_workspace_id"] == "oc-workspace"
    # ...without changing which department is active.
    assert config.active_department() == "IE"


def test_scaffold_pins_ie_identity_explicitly(tmp_path, monkeypatch):
    """A fresh multi-dept install must not leave IE inheriting."""
    cfg = {
        "multi_department_enabled": True,
        "trello_workspace_id": "ie-workspace",
        "audit_base": r"X:\IE_Public",
        "runs_dir": r"X:\IE_Public\Runs",
    }
    _write(tmp_path, monkeypatch, cfg)
    base = config.ensure_departments_scaffold()
    ie = base["departments"]["IE"]
    for k in config.DEPT_IDENTITY_KEYS:
        assert ie.get(k) == cfg[k], f"{k} not pinned onto IE"


class _StubSettings:
    """settings_web.Api.save without pywebview."""


def test_settings_save_routes_dept_keys_to_active_department(tmp_path,
                                                             monkeypatch):
    import settings_web

    _write(tmp_path, monkeypatch, _base(active_department="OC"))
    api = settings_web.Api()
    res = api.save({
        "audit_base": r"C:\OC\NewRoot",   # department-scoped
        "workcenter_url": "https://wc",   # global
    })
    assert res["ok"]
    assert res["routed_to_department"] == ["audit_base"]

    monkeypatch.setattr(config, "_CACHE", None)
    monkeypatch.setattr(config, "_CACHE_MTIME", None)
    base = config.load_base()
    # The global key landed on the base...
    assert base["workcenter_url"] == "https://wc"
    # ...the franchise-scoped one landed on OC, NOT the base (which IE
    # would otherwise have inherited).
    assert base["departments"]["OC"]["audit_base"] == r"C:\OC\NewRoot"
    assert base["audit_base"] == r"X:\IE_Public"
    assert config.load_for("IE")["audit_base"] == r"X:\IE_Public"


def test_settings_save_still_writes_base_in_single_dept_mode(tmp_path,
                                                            monkeypatch):
    import settings_web

    _write(tmp_path, monkeypatch, _base(multi_department_enabled=False))
    api = settings_web.Api()
    res = api.save({"audit_base": r"X:\Other"})
    assert res["ok"] and res["routed_to_department"] == []
    monkeypatch.setattr(config, "_CACHE", None)
    monkeypatch.setattr(config, "_CACHE_MTIME", None)
    assert config.load_base()["audit_base"] == r"X:\Other"


def test_settings_load_shows_effective_not_base(tmp_path, monkeypatch):
    """What-you-see-is-what-you-save: with OC active the form must show
    OC's values, or a save would copy IE's paths onto OC."""
    import settings_web

    _write(tmp_path, monkeypatch, _base(active_department="OC"))
    assert settings_web.Api().load()["audit_base"] == r"C:\OC"


@pytest.mark.parametrize("key", config.DEPT_IDENTITY_KEYS)
def test_identity_keys_are_department_overridable(key):
    """An identity key that isn't overridable per department could never be
    separated in the first place."""
    assert key in config.DEPT_OVERRIDE_KEYS
