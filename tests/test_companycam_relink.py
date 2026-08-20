"""Changing which CompanyCam project a job is linked to.

Auto-matching by name is right most of the time and wrong often enough to
matter — two projects for one loss, or a near-name on another job. There
was no way to correct it once it had matched: the manual picker only ever
appeared when auto-match FAILED, so a wrong match was permanent.

Picking REPLACES the stored link, and find_project_id consults that link
before it consults names, so one correction sticks and auto-matching
carries on for every job you have not corrected.
"""
import io
import os

import pytest

import companycam_web_api as cw

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def js():
    return io.open(os.path.join(_ROOT, "web_shared", "audit_detail.js"),
                   encoding="utf-8").read()


@pytest.fixture
def api(monkeypatch):
    import companycam_api as cc
    projects = {
        "111": {"id": "111", "name": "Same Name", "address": "1 Main St",
                "score": 85},
        "222": {"id": "222", "name": "Same Name", "address": "1 Main St",
                "score": 85},
    }
    photos = {"111": [{"id": f"p{i}"} for i in range(151)]}

    def _photos(pid, **kw):
        if str(pid) not in photos:
            raise RuntimeError("404 Not Found")     # deleted project
        return photos[str(pid)]

    monkeypatch.setattr(cc, "is_configured", lambda: True)
    monkeypatch.setattr(cc, "find_project",
                        lambda q, **kw: {"ok": True,
                                         "candidates": list(projects.values())})
    monkeypatch.setattr(cc, "list_project_photos", _photos)
    return cw.CompanyCamApi.__new__(cw.CompanyCamApi)


# ── telling two identical candidates apart ───────────────────────────
def test_candidates_carry_a_photo_count(api):
    """The real Bell Mountain pair had the SAME name and the SAME
    address. Name and address alone make that choice a coin flip; the
    photo count is what a person is actually picking by."""
    cands = api.companycam_search("same")["candidates"]
    live = next(c for c in cands if c["id"] == "111")
    assert live["photo_count"] == 151


def test_a_dead_project_is_flagged_not_counted(api):
    """Deleted projects keep appearing in search results — one of the
    Bell Mountain pair 404s on a direct read."""
    cands = api.companycam_search("same")["candidates"]
    dead = next(c for c in cands if c["id"] == "222")
    assert dead.get("unavailable") is True
    assert "photo_count" not in dead


def test_counting_is_capped(api, monkeypatch):
    """One API call per candidate; nobody reads past the first handful."""
    import companycam_api as cc
    seen = []
    monkeypatch.setattr(cc, "find_project", lambda q, **kw: {
        "ok": True, "candidates": [{"id": str(i), "name": "n"} for i in range(30)]})
    monkeypatch.setattr(cc, "list_project_photos",
                        lambda pid, **kw: seen.append(pid) or [])
    api.companycam_search("x")
    assert len(seen) == 8


def test_search_still_works_when_counting_fails(api, monkeypatch):
    """A count is a nicety; the list is the point."""
    import companycam_api as cc
    monkeypatch.setattr(cc, "list_project_photos",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    res = api.companycam_search("same")
    assert res["ok"] is True and len(res["candidates"]) == 2


# ── the panel ────────────────────────────────────────────────────────
def test_there_is_a_way_to_change_the_project(js):
    """The whole gap: the picker only opened when auto-match FAILED."""
    assert 'action === "cc-relink"' in js


def test_the_pull_button_stays_one_click(js):
    """Pull is clicked all day; changing the project is a monthly
    correction. It used to sit on a caret BESIDE Pull, which spent
    permanent space on the rare action — it is now the right-click of
    Pull itself, so the common action is still a single left click and
    nothing extra is on screen.
    """
    assert "cc-more" not in js, "the caret button should be gone"
    i = js.index('if (b.dataset.action === "cc-pull")')
    body = js[i:i + 700]
    assert 'addEventListener("contextmenu"' in body
    assert '"cc-relink"' in body


def test_relink_shows_what_is_linked_now(js):
    """You cannot tell it grabbed the wrong one without being told which
    one it grabbed."""
    body = js[js.index('if (action === "cc-relink")'):]
    body = body[:body.index("return;")]
    assert "companycam_probe" in body
    assert "Currently linked" in body


def test_the_picker_shows_counts_and_marks_dead_ones(js):
    assert "photo_count" in js and "unavailable" in js


def test_a_dead_project_cannot_be_selected(js):
    """Linking one points the job at something that 404s on every pull."""
    body = js[js.index('el.addEventListener("click", async () => {'):]
    body = body[:body.index("companycam_pin")]
    assert "c.unavailable" in body


def test_picking_replaces_rather_than_adds(js):
    """companycam_pin drops the other links — without that the oldest
    one keeps winning and the correction is recorded but ignored."""
    src = io.open(os.path.join(_ROOT, "companycam_web_api.py"),
                  encoding="utf-8").read()
    body = src[src.index("def companycam_pin"):]
    body = body[:body.index("def companycam_probe")]
    assert "remove_link" in body


# ── the caret button is gone ───────────────────────────────────────────

def _detail_js():
    import io, os
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "web_shared", "audit_detail.js")
    return io.open(p, encoding="utf-8").read()


def test_the_change_project_caret_button_is_gone():
    """Changing the CompanyCam project is a correction, not a routine
    step. Its own button next to Pull spent permanent space on something
    used rarely."""
    src = _detail_js()
    assert 'data-action="cc-menu"' not in src
    assert "cc-more" not in src


def test_right_clicking_pull_opens_the_picker():
    src = _detail_js()
    i = src.index('if (b.dataset.action === "cc-pull")')
    body = src[i:i + 700]
    assert 'addEventListener("contextmenu"' in body
    assert '"cc-relink"' in body


def test_the_row_menu_does_not_also_open():
    """The container has its own contextmenu handler; without
    stopPropagation a right-click fires both."""
    src = _detail_js()
    i = src.index('if (b.dataset.action === "cc-pull")')
    body = src[i:i + 700]
    assert "stopPropagation" in body


def test_a_disabled_pull_button_does_not_relink():
    """No job path means nothing to pull and nothing to re-link."""
    src = _detail_js()
    i = src.index('if (b.dataset.action === "cc-pull")')
    body = src[i:i + 700]
    assert "b.disabled" in body


def test_the_action_survives_as_an_alias():
    """Older callers reaching for cc-menu must still land on the picker
    rather than silently doing nothing."""
    src = _detail_js()
    assert 'if (action === "cc-menu")' in src
