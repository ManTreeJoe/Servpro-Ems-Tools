"""A job is not always a top-level folder.

Units, second claims and commercial sub-jobs live INSIDE their client, and
the folder search only ever read the year folder. So
"Menifee School District - Bell Mountain - 8.14.26" was invisible —
searching "Bell Mountain" returned "Bell Kimberly" and "Bell Samantha"
while the real job sat under "Menifee Union School District" the whole
time.

The ones this misses hardest are exactly the ones that matter: a child
named after its own site shares no token with the parent it lives under,
which is the same reason the new-loss parent picker has to be a picker.

Cost is why it wasn't done before, and why it can be now. One scandir per
client folder is ~31ms of network LATENCY on the share — 614 folders
measured at 19.0s serially. Across 32 threads the same scan is 545ms,
because the wait is the network, not the disk.
"""
import os

import pytest

import audit_logic as al


@pytest.fixture
def share(tmp_path):
    yd = tmp_path / "2026 Jobs"
    (yd / "Menifee Union School District" /
     "Menifee School District - Bell Mountain - 8.14.26").mkdir(parents=True)
    (yd / "Menifee Union School District" /
     "Menifee Union School District Quail Valley Elementry").mkdir(parents=True)
    (yd / "Bell Kimberly").mkdir()
    # The job skeleton is a container, not a child job.
    for shell in ("EMS", "PICS", "DOCS", "RECON", "CONTENTS"):
        (yd / "Bell Kimberly" / shell).mkdir()
    al.invalidate_year_index_cache()
    return str(yd)


def test_children_are_listed_with_their_parent(share):
    got = al.cached_child_listing(share)
    assert ("Menifee Union School District",
            "Menifee School District - Bell Mountain - 8.14.26") in got


def test_the_job_skeleton_is_not_a_child(share):
    """EMS / PICS / DOCS are containers — listing them as jobs would put
    five fake rows under every client."""
    kids = [c for p, c in al.cached_child_listing(share)]
    for shell in ("EMS", "PICS", "DOCS", "RECON", "CONTENTS"):
        assert shell not in kids


def test_a_top_level_folder_with_no_children_contributes_nothing(share):
    parents = {p for p, c in al.cached_child_listing(share)}
    assert "Bell Kimberly" not in parents


def test_the_listing_is_cached(share, monkeypatch):
    al.cached_child_listing(share)
    monkeypatch.setattr(os, "scandir",
                        lambda *a, **k: pytest.fail("should be cached"))
    al.cached_child_listing(share)


def test_a_full_rescan_clears_it(share):
    al.cached_child_listing(share)
    al.invalidate_year_index_cache()
    assert al._child_index_cache == {}


def test_a_missing_year_folder_is_not_an_error():
    assert al.cached_child_listing(r"X:\nope\nothing here") == []
    assert al.cached_child_listing("") == []


def test_the_scan_is_parallel():
    """Serially this is 19 seconds on the real share, which is why the
    search never looked inside folders before."""
    import inspect
    src = inspect.getsource(al.cached_child_listing)
    assert "ThreadPoolExecutor" in src
    assert al._CHILD_SCAN_WORKERS >= 16


def test_there_is_a_fallback_without_threads():
    """A scan that can't start threads must still return the children,
    slowly, rather than silently returning none."""
    import inspect
    src = inspect.getsource(al.cached_child_listing)
    assert "except Exception:" in src and "for item in tops:" in src


# ── the search itself ────────────────────────────────────────────────
@pytest.fixture
def api(share, monkeypatch):
    import audit_web
    import config
    a = audit_web.Api.__new__(audit_web.Api)
    yf = [{"name": "2026 Jobs", "path": share, "year": "2026",
           "is_fire": False}]
    monkeypatch.setattr(audit_web.Api, "list_year_folders",
                        lambda self: {"folders": yf})
    # list_folder_candidates does `import config as _cfg` inside the
    # function, so the MODULE is what has to be patched.
    monkeypatch.setattr(config, "load",
                        lambda *a, **k: {"audit_base": os.path.dirname(share)})
    return a


def test_the_child_job_is_found_by_its_own_name(api):
    """The report: "Bell Mountain is not showing up"."""
    res = api.list_folder_candidates("Bell Mountain", "")
    hits = [c for c in res["candidates"] if c["score"] > 0]
    assert hits[0]["name"] == "Menifee School District - Bell Mountain - 8.14.26"


def test_the_child_beats_an_unrelated_top_level_near_miss(api):
    """"Bell Kimberly" shares one token and is not the job."""
    res = api.list_folder_candidates("Bell Mountain", "")
    hits = [c for c in res["candidates"] if c["score"] > 0]
    assert hits[0]["score"] > next(
        c["score"] for c in hits if c["name"] == "Bell Kimberly")


def test_the_child_path_points_inside_its_parent(api):
    """Audit the child's folder, not the umbrella — pinning the parent
    would send its imports to the district root."""
    res = api.list_folder_candidates("Bell Mountain", "")
    hit = next(c for c in res["candidates"] if c["score"] > 0)
    assert hit["path"].endswith(os.path.join(
        "Menifee Union School District",
        "Menifee School District - Bell Mountain - 8.14.26"))
    assert hit["parent"] == "Menifee Union School District"


def test_unscored_children_are_not_returned(api):
    """980 children on the live share. Listing them all would bury the
    top-level matches for every other search."""
    res = api.list_folder_candidates("Bell Mountain", "")
    names = [c["name"] for c in res["candidates"]]
    assert "Menifee Union School District Quail Valley Elementry" not in names


def test_a_top_level_search_still_works(api):
    res = api.list_folder_candidates("Bell Kimberly", "")
    hits = [c for c in res["candidates"] if c["score"] > 0]
    assert hits[0]["name"] == "Bell Kimberly"
    assert not hits[0].get("parent")
