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
