"""CompanyCam pages at 50 no matter what you ask for.

`list_projects` defaulted to per_page=100 and stopped as soon as a page
came back shorter than requested — so page one, 50 rows against a request
for 100, read as the last page. Live, that returned **50 of 287
projects** and reported success.

It matters because `find_project()` is the auto-linker: a project past
the cap is invisible, so the job shows "no CompanyCam project" or binds
to a worse-scoring match. Identical in shape to the Supabase 1000-row cap
that hid two thirds of job_lifecycle — a server-side limit mistaken for
the end of the data.
"""
import pytest

import companycam_api as cc


def _pager(monkeypatch, total, cap=50):
    """Fake the API: `cap` rows per page however many are requested."""
    calls = []

    def _call(path, *, params=None, method="GET", data=None, **kw):
        params = params or {}
        page = int(params.get("page") or 1)
        calls.append(page)
        start = (page - 1) * cap
        return [{"id": i, "name": f"p{i}"}
                for i in range(start, min(start + cap, total))]

    monkeypatch.setattr(cc, "_call", _call)
    return calls


def test_every_project_is_returned_past_the_server_cap(monkeypatch):
    _pager(monkeypatch, total=287, cap=50)
    got = cc.list_projects(per_page=100, max_pages=40)
    assert len(got) == 287, (
        "stopped at the server's page cap and called it the last page")


def test_a_genuinely_short_page_still_ends_it(monkeypatch):
    """The stop condition has to keep working, or every call walks to
    max_pages and pays for it."""
    calls = _pager(monkeypatch, total=120, cap=50)
    got = cc.list_projects(per_page=100, max_pages=40)
    assert len(got) == 120
    assert calls == [1, 2, 3], f"walked too far: {calls}"


def test_an_exact_multiple_stops_on_the_empty_page(monkeypatch):
    """100 rows at 50/page gives two full pages and then nothing — the
    empty page is the only signal that it's over."""
    calls = _pager(monkeypatch, total=100, cap=50)
    got = cc.list_projects(per_page=100, max_pages=40)
    assert len(got) == 100
    assert calls == [1, 2, 3]


def test_max_pages_is_still_a_hard_stop(monkeypatch):
    _pager(monkeypatch, total=10_000, cap=50)
    got = cc.list_projects(per_page=100, max_pages=3)
    assert len(got) == 150


def test_no_results_is_not_an_error(monkeypatch):
    _pager(monkeypatch, total=0, cap=50)
    assert cc.list_projects() == []


# ── deleted and archived projects are not projects ─────────────────────

def _pages(monkeypatch, rows, size=50):
    """Serve `rows` in pages of `size` through the low-level _call."""
    import companycam_api as cc
    pages = [rows[i:i + size] for i in range(0, len(rows), size)] or [[]]

    def _call(path, params=None, **k):
        p = (params or {}).get("page", 1)
        return pages[p - 1] if 1 <= p <= len(pages) else []

    monkeypatch.setattr(cc, "_call", _call)
    return cc


def test_deleted_projects_are_excluded(monkeypatch):
    """The API returns them with status='deleted'. Nothing filtered them,
    so a job was auto-linked to a deleted project and then showed zero
    photos forever."""
    cc = _pages(monkeypatch, [
        {"id": 1, "name": "Live", "status": "active"},
        {"id": 2, "name": "Gone", "status": "deleted"},
    ])
    assert [p["id"] for p in cc.list_projects()] == [1]


def test_archived_projects_are_excluded(monkeypatch):
    cc = _pages(monkeypatch, [
        {"id": 1, "name": "Live", "status": "active"},
        {"id": 2, "name": "Filed", "status": "active", "archived": True},
    ])
    assert [p["id"] for p in cc.list_projects()] == [1]


def test_they_can_be_asked_for_explicitly(monkeypatch):
    """A cleanup report still needs to SEE them — it just must not treat
    them as live."""
    cc = _pages(monkeypatch, [
        {"id": 1, "name": "Live", "status": "active"},
        {"id": 2, "name": "Gone", "status": "deleted"},
    ])
    got = cc.list_projects(include_deleted=True)
    assert [p["id"] for p in got] == [1, 2]


def test_filtering_happens_after_paging(monkeypatch):
    """Dropping rows mid-page would make a full page look short and stop
    the walk — the 50-of-287 bug wearing a different hat. 50 deleted rows
    on page one must not hide page two."""
    rows = ([{"id": i, "name": f"D{i}", "status": "deleted"} for i in range(50)]
            + [{"id": 100 + i, "name": f"L{i}", "status": "active"} for i in range(20)])
    cc = _pages(monkeypatch, rows, size=50)
    got = cc.list_projects()
    assert len(got) == 20, "page two was never fetched"
