"""Settings changes apply without restarting the app.

`config.load()` is mtime-cached so most values were already live, but every
module that DERIVED something from config kept it forever — a Trello board
id resolved by name, the department→folder-root map, the storage backend.
Those were what forced a restart.

The same list also has to run on a department switch. It used to live in
home_web and had already fallen behind: it didn't know about the
department-root map or the backend selection, so switching department kept
serving the previous department's folder roots.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cache_bust


def test_invalidate_all_clears_the_known_caches():
    res = cache_bust.invalidate_all("test")
    assert res["failed"] == [], f"invalidator errors: {res['failed']}"
    assert res["cleared"], "nothing was cleared"


@pytest.mark.parametrize("target", [
    "trello_client.invalidate_caches",       # board / list / member ids
    "ems_db.invalidate_department_cache",    # department → audit_base map
    "ems_db.invalidate_backend",             # sqlite vs supabase
    "audit_logic.invalidate_year_index_cache",
    "companycam_api.invalidate_tag_cache",
])
def test_each_config_derived_cache_is_covered(target):
    assert target in cache_bust.invalidate_all("test")["cleared"]


def test_config_mtime_cache_is_forced_stale():
    """A save inside the same second can land on an unchanged mtime, so the
    next read would keep the OLD config — invisible and maddening."""
    import config
    config._CACHE = {"stale": True}
    config._CACHE_MTIME = 12345
    cache_bust.invalidate_all("test")
    assert config._CACHE is None and config._CACHE_MTIME is None


def test_a_broken_invalidator_never_blocks_the_save(monkeypatch):
    """Worst case for a failed invalidation is stale data; worst case for
    raising is the user can't change their settings at all."""
    import trello_client

    def boom():
        raise RuntimeError("nope")

    monkeypatch.setattr(trello_client, "invalidate_caches", boom)
    res = cache_bust.invalidate_all("test")
    assert any("trello_client" in f for f in res["failed"])
    assert res["cleared"], "the other caches must still be cleared"


def test_department_roots_actually_re_resolve(tmp_path, monkeypatch):
    """The end-to-end point: change audit_base, and the map that stamps
    jobs.department must follow without a restart."""
    import json
    import config
    import ems_db

    p = tmp_path / "config.json"

    def write(ie_root):
        p.write_text(json.dumps({
            "multi_department_enabled": True,
            "active_department": "IE",
            "departments": {
                "IE": {"audit_base": ie_root},
                "OC": {"audit_base": str(tmp_path / "oc")},
            },
        }), encoding="utf-8")

    monkeypatch.setattr(config, "_USER_CFG", str(p))
    write(str(tmp_path / "first"))
    cache_bust.invalidate_all("test")
    assert ems_db.department_for_path(str(tmp_path / "first" / "job")) == "IE"

    write(str(tmp_path / "second"))
    cache_bust.invalidate_all("settings save")
    assert ems_db.department_for_path(str(tmp_path / "second" / "job")) == "IE"
    assert ems_db.department_for_path(str(tmp_path / "first" / "job")) is None


def test_settings_save_invalidates(tmp_path, monkeypatch):
    """Wiring check — saving through the Settings API must bust caches."""
    import json
    import config
    import settings_web

    p = tmp_path / "config.json"
    p.write_text(json.dumps({"workcenter_url": "old"}), encoding="utf-8")
    monkeypatch.setattr(config, "_USER_CFG", str(p))
    monkeypatch.setattr(config, "_CACHE", None)
    monkeypatch.setattr(config, "_CACHE_MTIME", None)

    calls = []
    monkeypatch.setattr(cache_bust, "invalidate_all",
                        lambda reason="": calls.append(reason) or
                        {"cleared": [], "failed": []})
    res = settings_web.Api().save({"workcenter_url": "new"})
    assert res["ok"] and res.get("applied_live")
    assert calls, "settings save did not invalidate caches"
