"""The reference material on the share, made findable.

X:\\IE_Public has 53 top-level folders: three are the year job folders the
audit already covers, and the other 50 are the office's reference
material — Forms_Contracts, W9_Insurance, COIs, Safety, Vendors,
Estimating Department — plus loose files at the root like ON CALL
PROTOCOL.docx.

Measured first, because it decided the design: **49,602 files in 2,069
folders, 47.6 seconds to walk**. That rules out searching live, and rules
out JSON — 50k rows is a ~12MB document to parse per keystroke, which is
the cost the index exists to remove. So: SQLite, rebuilt deliberately,
read instantly.
"""
import os
import time

import pytest

import resources_index as ri


@pytest.fixture
def share(tmp_path, monkeypatch):
    """A share shaped like the real one."""
    base = tmp_path / "IE_Public"
    (base / "2026 Jobs" / "Smith, John").mkdir(parents=True)
    (base / "2025 LA FIRES" / "Someone").mkdir(parents=True)
    (base / "Forms_Contracts").mkdir(parents=True)
    (base / "W9_Insurance" / "2026").mkdir(parents=True)
    (base / "2026 Jobs" / "Smith, John" / "a_job_photo.jpg").write_text("x")
    (base / "Forms_Contracts" / "Decline Form 28625.pdf").write_text("x")
    (base / "Forms_Contracts" / "~$draft.docx").write_text("x")
    (base / "Forms_Contracts" / "Thumbs.db").write_text("x")
    (base / "W9_Insurance" / "2026" / "W9 Vendor Acme.pdf").write_text("x")
    (base / "ON CALL PROTOCOL.docx").write_text("x")
    monkeypatch.setattr(ri, "DB_PATH", str(tmp_path / "resources.db"))
    monkeypatch.setattr(ri, "default_root", lambda: str(base))
    return str(base)


# ── what gets indexed ────────────────────────────────────────────────
def test_job_year_folders_are_excluded(share):
    """They are the biggest part of the share, they change constantly,
    and the audit already resolves them."""
    tops = [os.path.basename(r) for r in ri.roots(share)]
    assert "2026 Jobs" not in tops
    assert "2025 LA FIRES" not in tops
    assert "Forms_Contracts" in tops


def test_a_job_photo_never_reaches_the_index(share):
    ri.rebuild(share)
    # Not `== []`: pytest names the tmp dir after the test, so the
    # FOLDER of every row contains this test's own name. Ask the question
    # that actually matters instead.
    assert not [h for h in ri.search("a_job_photo")
                if h["name"] == "a_job_photo.jpg"]


def test_an_underscore_is_not_a_wildcard(share):
    """`_` matches any single character in SQL LIKE. Unescaped, a search
    for "W9_Insurance" returned every row in the index — the answer to a
    question nobody asked, which reads as broken rather than empty."""
    ri.rebuild(share)
    assert ri.search("acme_vendor") == []      # no such literal anywhere
    assert [h["name"] for h in ri.search("w9 vendor")] == ["W9 Vendor Acme.pdf"]


def test_a_percent_is_not_a_wildcard(share):
    ri.rebuild(share)
    assert ri.search("%") == []


def test_reference_files_are_indexed(share):
    ri.rebuild(share)
    assert [h["name"] for h in ri.search("decline form")] == \
        ["Decline Form 28625.pdf"]


def test_loose_files_at_the_share_root_are_indexed(share):
    """ON CALL PROTOCOL.docx and the extension list live at the root, not
    in a folder — skipping them would miss the two most-asked-for files."""
    ri.rebuild(share)
    assert [h["name"] for h in ri.search("on call protocol")] == \
        ["ON CALL PROTOCOL.docx"]


@pytest.mark.parametrize("junk", ["~$draft.docx", "Thumbs.db"])
def test_office_and_windows_debris_is_skipped(share, junk):
    ri.rebuild(share)
    assert not [h for h in ri.search(junk.replace("~$", ""))
                if h["name"] == junk]


def test_rebuild_reports_what_it_did(share):
    res = ri.rebuild(share)
    assert res["ok"] is True
    assert res["files"] >= 3
    assert res["roots"] == 2               # Forms_Contracts + W9_Insurance


# ── searching ────────────────────────────────────────────────────────
def test_every_word_must_match_not_any(share):
    """A two-word search returning MORE than a one-word search is never
    what anyone means."""
    ri.rebuild(share)
    assert len(ri.search("w9 vendor")) == 1
    assert ri.search("w9 nonexistentword") == []


def test_search_matches_the_folder_too(share):
    """You often remember where it lives, not what it's called."""
    ri.rebuild(share)
    assert [h["name"] for h in ri.search("w9_insurance")] == \
        ["W9 Vendor Acme.pdf"]


def test_search_can_be_filtered_by_extension(share):
    ri.rebuild(share)
    assert ri.search("decline", ext="pdf")
    assert ri.search("decline", ext="docx") == []


def test_search_can_be_scoped_to_one_area(share):
    ri.rebuild(share)
    assert ri.search("w9", top="W9_Insurance")
    assert ri.search("w9", top="Forms_Contracts") == []


def test_newest_first(share):
    """The current version of a form is the one being looked for."""
    old = os.path.join(share, "Forms_Contracts", "Renewal v1.pdf")
    new = os.path.join(share, "Forms_Contracts", "Renewal v2.pdf")
    for p in (old, new):
        open(p, "w").write("x")
    os.utime(old, (time.time() - 86400, time.time() - 86400))
    ri.rebuild(share)
    assert [h["name"] for h in ri.search("renewal")] == \
        ["Renewal v2.pdf", "Renewal v1.pdf"]


def test_an_empty_query_returns_nothing(share):
    ri.rebuild(share)
    assert ri.search("") == []
    assert ri.search("   ") == []


def test_searching_before_the_first_build_is_not_an_error(tmp_path,
                                                          monkeypatch):
    monkeypatch.setattr(ri, "DB_PATH", str(tmp_path / "none.db"))
    assert ri.search("anything") == []
    assert ri.stats()["built"] is False


# ── the index's own table of contents ────────────────────────────────
def test_top_folders_counts_each_area(share):
    ri.rebuild(share)
    got = {t["top"]: t["n"] for t in ri.top_folders()}
    assert got["W9_Insurance"] == 1
    assert "" not in got, "root files are not an area"


def test_stats_reports_age(share):
    ri.rebuild(share)
    s = ri.stats()
    assert s["files"] >= 3 and s["age_hours"] is not None
    assert s["base"] == share


# ── the reason it is built this way ──────────────────────────────────
def test_a_rebuild_replaces_rather_than_accumulates(share):
    """A deleted file must leave the index, or search sends people to
    paths that no longer exist."""
    ri.rebuild(share)
    os.remove(os.path.join(share, "Forms_Contracts", "Decline Form 28625.pdf"))
    ri.rebuild(share)
    assert ri.search("decline form") == []


def test_the_walk_is_parallel_and_uses_scandir():
    """os.walk hands back names only, so size/mtime cost a stat PER FILE
    — 50k round trips to the share, which is why the first rebuild never
    finished. A DirEntry carries that data from the directory read."""
    import inspect
    fn = ri._walk_one
    src = inspect.getsource(fn).replace(fn.__doc__ or "", "")
    assert "scandir" in src and "os.walk" not in src
    assert "ThreadPoolExecutor" in inspect.getsource(ri.rebuild)


def test_an_unreachable_share_is_reported_not_crashed(monkeypatch, tmp_path):
    monkeypatch.setattr(ri, "DB_PATH", str(tmp_path / "x.db"))
    res = ri.rebuild(r"Z:\not-a-share")
    assert res["ok"] is False and res["files"] == 0
