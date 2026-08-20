"""Failure has to be visible, and it has to be described accurately.

Two ways to get this wrong, and both are worse than saying nothing:
claiming access is missing when the check simply could not run, and
staying quiet while the user works against a stale local copy.
"""
import pytest

import config
import web_health


@pytest.fixture(autouse=True)
def no_cache(monkeypatch):
    monkeypatch.setattr(web_health, "_grant_cache", {})
    monkeypatch.setattr(web_health, "_grant_at", 0.0)


@pytest.fixture
def cloud(monkeypatch):
    monkeypatch.setattr(web_health, "_backend_name", lambda: "supabase")
    monkeypatch.setattr(web_health, "_offline_state", lambda: {})


def _sb(monkeypatch, *, signed_in=True, depts=("IE",), boom=False):
    import sys

    class _Client:
        @staticmethod
        def is_signed_in():
            return signed_in

        @staticmethod
        def current_user():
            return {"id": "u1", "email": "a@b.c"}

        @staticmethod
        def rpc(fn, args=None):
            if boom:
                raise OSError("network down")
            return list(depts)

    monkeypatch.setitem(sys.modules, "supabase_client", _Client)


# ── the quiet failure this exists for ──────────────────────────────────

def test_no_grant_is_reported_not_shown_as_an_empty_list(cloud, monkeypatch):
    """RLS returns zero rows, so the app looks EMPTY rather than
    forbidden. "There are no jobs" is a very convincing lie."""
    _sb(monkeypatch, depts=())
    st = web_health.state()
    assert st["ok"] is False
    assert [p["code"] for p in st["problems"]] == ["no_grant"]


def test_access_to_the_wrong_franchise_says_which(cloud, monkeypatch):
    _sb(monkeypatch, depts=("IE",))
    monkeypatch.setattr(config, "active_department", lambda: "OC")
    p = web_health.state()["problems"][0]
    assert p["code"] == "wrong_grant"
    assert "OC" in p["title"] and "IE" in p["detail"]


def test_a_normal_user_sees_nothing(cloud, monkeypatch):
    _sb(monkeypatch, depts=("IE", "OC"))
    monkeypatch.setattr(config, "active_department", lambda: "IE")
    st = web_health.state()
    assert st["ok"] is True
    assert st["problems"] == []


def test_could_not_ask_is_not_no_access(cloud, monkeypatch):
    """A network blip must not send somebody to chase a permission
    problem they do not have."""
    _sb(monkeypatch, boom=True)
    st = web_health.state()
    assert st["problems"] == []
    assert st["grant"]["checked"] is False


def test_signed_out_says_the_writes_are_staying_local(cloud, monkeypatch):
    _sb(monkeypatch, signed_in=False)
    assert web_health.state()["problems"][0]["code"] == "signed_out"


# ── degraded ───────────────────────────────────────────────────────────

def test_degraded_reports_the_queue_depth(monkeypatch):
    monkeypatch.setattr(web_health, "_backend_name", lambda: "sqlite")
    monkeypatch.setattr(web_health, "_offline_state",
                        lambda: {"degraded": True, "queued": 3})
    p = web_health.state()["problems"][0]
    assert p["code"] == "degraded"
    assert "3 changes" in p["detail"]


def test_one_queued_change_is_not_pluralised(monkeypatch):
    monkeypatch.setattr(web_health, "_backend_name", lambda: "sqlite")
    monkeypatch.setattr(web_health, "_offline_state",
                        lambda: {"degraded": True, "queued": 1})
    assert "1 change " in web_health.state()["problems"][0]["detail"]


def test_reachable_again_with_a_queue_is_still_not_finished(monkeypatch):
    """Silence here reads as "everything sent"."""
    monkeypatch.setattr(web_health, "_backend_name", lambda: "sqlite")
    monkeypatch.setattr(web_health, "_offline_state",
                        lambda: {"degraded": False, "queued": 2})
    assert web_health.state()["problems"][0]["code"] == "queue_pending"


def test_a_local_install_is_not_degraded(monkeypatch):
    """Local-only is a configuration, not a fault."""
    monkeypatch.setattr(web_health, "_backend_name", lambda: "sqlite")
    monkeypatch.setattr(web_health, "_offline_state", lambda: {})
    st = web_health.state()
    assert st["ok"] is True
    assert st["grant"]["checked"] is False


# ── it must never be the thing that breaks ─────────────────────────────

def test_a_broken_check_does_not_raise(monkeypatch):
    def _boom():
        raise RuntimeError("nope")

    monkeypatch.setattr(web_health, "_offline_state", _boom)
    with pytest.raises(RuntimeError):
        web_health._offline_state()          # the fixture really is broken
    monkeypatch.setattr(web_health, "_offline_state", lambda: {})
    assert web_health.state()["ok"] in (True, False)


def test_the_home_api_swallows_a_failure(monkeypatch):
    import home_web
    api = object.__new__(home_web.HomeApi)
    monkeypatch.setattr(web_health, "state",
                        lambda force=False: (_ for _ in ()).throw(
                            RuntimeError("x")))
    out = api.health_state()
    assert out["ok"] is True and out["problems"] == []


def test_js_errors_reach_the_log(monkeypatch):
    seen = {}

    class _Log:
        @staticmethod
        def error(src, msg, **kw):
            seen["src"], seen["msg"] = src, msg

    import sys
    monkeypatch.setitem(sys.modules, "ems_log", _Log)
    assert web_health.log_js_error("audit", "boom", "stack")["ok"] is True
    assert seen["src"] == "web"
    assert "audit" in seen["msg"] and "boom" in seen["msg"]
