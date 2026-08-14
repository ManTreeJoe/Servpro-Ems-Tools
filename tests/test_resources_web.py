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


def test_the_panel_is_in_the_WEB_sidebar():
    """The web home is the app. `launcher.py` is the Tk launcher and is
    NOT where a panel gets registered — putting it there is why this
    shipped with no tab at all. Everything is built in *_web.py +
    *_web_assets; nothing new goes near Tk."""
    import home_web
    keys = [k for _, tools in home_web.NAV_GROUPS for k, _i, _l in tools]
    assert "resources" in keys
    assert home_web.SUB_MODULES["resources"] == "resources_web"


def test_nothing_registered_it_with_tk():
    import launcher
    assert not [t for t in launcher.NAV_TOOLS
                if t.get("module") == "resources_web"]


def test_the_asset_folder_follows_the_convention():
    """The iframe src is derived from the key, so `resources` has to map
    to resources_web_assets or the panel loads a blank frame."""
    import home_web
    assert home_web._asset_folder_for("resources") == \
        "../resources_web_assets/index.html"


def test_the_assets_exist():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for f in ("index.html", "app.js", "app.css"):
        assert os.path.isfile(os.path.join(here, "resources_web_assets", f))


# ── browsing, not just searching ─────────────────────────────────────
def test_an_area_lists_its_files_without_a_query(api):
    """Clicking "Vendors" means "show me what's in Vendors". The panel
    listed every area and its count and then none of the files in them,
    because an empty search box was treated as no question at all."""
    a, base = api
    ri.rebuild(base)
    res = a.search("", "", "Forms_Contracts", 50)
    assert res["ok"] is True
    assert [r["name"] for r in res["rows"]] == ["Decline Form 28625.pdf"]


def test_a_type_filter_alone_is_also_a_question(api):
    a, base = api
    ri.rebuild(base)
    assert a.search("", "pdf", "", 50)["count"] >= 1


def test_no_query_no_area_no_type_returns_nothing(api):
    """Listing 49,602 files answers nothing — the UI prompts instead."""
    a, base = api
    ri.rebuild(base)
    assert a.search("", "", "", 50)["count"] == 0


def test_the_panel_does_not_bail_on_an_empty_box(api):
    """Guards the regression directly: the early return has to consider
    the area and the type, not just the query."""
    import io
    import os
    js = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "resources_web_assets", "app.js"),
        encoding="utf-8").read()
    assert "!q && !state.area && !ext" in js
