"""📚 The Resources panel — the reading end of the index.

Search is a round trip to SQLite, so it can run on keystrokes. The
REBUILD is the slow one — 47.6s against the live share — and everything
about how this panel is wired follows from that: it runs on a thread and
is polled, because a window blocked for 47 seconds is indistinguishable
from a hang.
"""
import os

import pytest

import resources_index as ri
import resources_web


@pytest.fixture
def api(tmp_path, monkeypatch):
    base = tmp_path / "IE_Public"
    (base / "Forms_Contracts").mkdir(parents=True)
    (base / "2026 Jobs" / "Smith").mkdir(parents=True)
    (base / "Forms_Contracts" / "Decline Form 28625.pdf").write_text("x")
    (base / "2026 Jobs" / "Smith" / "photo.jpg").write_text("x")
    monkeypatch.setattr(ri, "DB_PATH", str(tmp_path / "resources.db"))
    monkeypatch.setattr(ri, "default_root", lambda: str(base))
    a = resources_web.Api()
    return a, str(base)


# ── reading ──────────────────────────────────────────────────────────
def test_search_returns_indexed_files(api):
    a, base = api
    ri.rebuild(base)
    res = a.search("decline")
    assert res["ok"] is True
    assert res["rows"][0]["name"] == "Decline Form 28625.pdf"


def test_search_reports_a_readable_size(api):
    a, base = api
    ri.rebuild(base)
    assert "size_kb" in a.search("decline")["rows"][0]


def test_stats_carries_the_areas(api):
    """The area list is the index's table of contents AND the scope
    filter — "it's somewhere in Vendors" is how people remember."""
    a, base = api
    ri.rebuild(base)
    s = a.stats()
    assert s["files"] >= 1
    assert any(x["top"] == "Forms_Contracts" for x in s["areas"])


def test_stats_before_any_build_is_not_an_error(api):
    a, _ = api
    s = a.stats()
    assert s["built"] is False and s["files"] == 0


# ── opening ──────────────────────────────────────────────────────────
def test_opening_a_file_that_moved_says_so(api):
    """The index can outlive the share. A file moved since the last
    rebuild is the NORMAL case, not a crash."""
    a, base = api
    res = a.open_file(os.path.join(base, "Forms_Contracts", "gone.pdf"))
    assert res["ok"] is False
    assert "rebuild" in res["error"].lower()


def test_opening_nothing_is_refused(api):
    a, _ = api
    assert a.open_file("")["ok"] is False
    assert a.open_folder("")["ok"] is False


def test_a_missing_folder_is_reported(api):
    a, _ = api
    res = a.open_folder(r"Z:\nope\nothing")
    assert res["ok"] is False


def test_copy_path_hands_the_text_back_when_there_is_no_clipboard(api,
                                                                  monkeypatch):
    """The page can copy it itself — refusing outright would make the
    button dead on a machine without pyperclip."""
    a, _ = api
    import builtins
    real = builtins.__import__

    def _no_pyperclip(name, *args, **kw):
        if name == "pyperclip":
            raise ImportError("nope")
        return real(name, *args, **kw)

    monkeypatch.setattr(builtins, "__import__", _no_pyperclip)
    res = a.copy_path(r"X:\IE_Public\a.pdf")
    assert res["ok"] is False and res["text"] == r"X:\IE_Public\a.pdf"


# ── the rebuild ──────────────────────────────────────────────────────
def test_rebuild_returns_immediately(api):
    """It must not block the window for 47 seconds."""
    a, base = api
    res = a.rebuild()
    assert res["ok"] is True and res["started"] is True


def test_rebuild_progress_reports_the_result(api):
    import time
    a, base = api
    a.rebuild()
    for _ in range(100):
        p = a.rebuild_progress()
        if not p["building"]:
            break
        time.sleep(0.05)
    assert p["result"]["ok"] is True
    assert p["result"]["files"] >= 1


def test_two_rebuilds_at_once_are_refused(api, monkeypatch):
    """A second walk while one is running doubles the load on the share
    for no benefit."""
    a, _ = api
    monkeypatch.setattr(a, "_building", True)
    assert a.rebuild()["ok"] is False


def test_the_panel_is_registered_in_the_launcher():
    """A panel nobody can open is not shipped."""
    import launcher
    keys = [t["key"] for t in launcher.NAV_TOOLS]
    assert "resources_web" in keys
    spec = next(t for t in launcher.NAV_TOOLS if t["key"] == "resources_web")
    assert spec["module"] == "resources_web"


def test_the_assets_exist():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for f in ("index.html", "app.js", "app.css"):
        assert os.path.isfile(os.path.join(here, "resources_web_assets", f))
