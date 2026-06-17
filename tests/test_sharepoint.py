"""SharePoint helpers — extracted from daily_photos_gui in 2026-04 so
both the photo-folder creator and the run-audit's match dialog can be
equal consumers.

These tests pin: per-folder match builder shape (and the empty/missing
edge cases that previously caused phantom rows), date-variant set
generation, and the find-folders-for-client orchestrator's substring +
override merge logic."""
import os

import pytest

import sharepoint


# ── _date_variants ──────────────────────────────────────────────────────────

def test_date_variants_covers_separators_and_lengths():
    out = sharepoint._date_variants("04-24-2026")
    # The audit relies on these exact forms — locking them in.
    assert "4-24-26" in out
    assert "04-24-2026" in out
    assert "4/24/26" in out
    assert "04.24.2026" in out
    assert "4-24-2026" in out


def test_date_variants_malformed_input_returns_input_only():
    """Bad input shouldn't raise — caller may pass garbage."""
    out = sharepoint._date_variants("not a date")
    assert out == {"not a date"}


def test_date_variants_none_safe():
    """None must not blow up — split() would raise. The except branch
    catches it and returns {None}."""
    assert sharepoint._date_variants(None) == {None}


# ── _build_sp_match ─────────────────────────────────────────────────────────

def test_build_sp_match_returns_none_for_missing_path():
    assert sharepoint._build_sp_match("/no/such/path") is None


def test_build_sp_match_returns_match_for_empty_folder(tmp_path):
    """Folder exists but has no images yet — still match. A folder named
    `<Tech> <date> <Client>` that's been created but not populated is a
    valid "tech acknowledged the job" signal. Previously this returned
    None and silently hid the folder; the Guadalupe Arrenquin / Danny
    case 2026-05-18 was the canonical example."""
    (tmp_path / "empty").mkdir()
    rec = sharepoint._build_sp_match(str(tmp_path / "empty"))
    assert rec is not None
    assert rec["count"] == 0
    assert rec["files"] == []
    assert rec["empty"] is True


def test_build_sp_match_walks_images(tmp_path, monkeypatch):
    """Tech inferred from the parent dir's basename — verify both the
    tech name and image count come through."""
    # Layout: tmp/PhotosRoot/Cesar/Smith John/img1.jpg
    photos_root = tmp_path / "PhotosRoot"
    cesar = photos_root / "Cesar"
    sub = cesar / "Smith John 4-27"
    sub.mkdir(parents=True)
    (sub / "img1.jpg").write_bytes(b"x")
    (sub / "img2.png").write_bytes(b"x")
    (sub / "ignored.txt").write_bytes(b"not an image")
    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(photos_root))
    rec = sharepoint._build_sp_match(str(sub))
    assert rec is not None
    assert rec["tech"] == "Cesar"
    assert rec["count"] == 2  # txt file ignored
    assert rec["name"] == "Smith John 4-27"
    assert "img1.jpg" in rec["filenames"]
    assert "img2.png" in rec["filenames"]
    assert rec["override"] is False


def test_build_sp_match_override_flag_passes_through(tmp_path, monkeypatch):
    photos_root = tmp_path / "PhotosRoot"
    sub = photos_root / "Mark" / "Some Folder"
    sub.mkdir(parents=True)
    (sub / "p.jpg").write_bytes(b"x")
    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(photos_root))
    rec = sharepoint._build_sp_match(str(sub), override=True)
    assert rec["override"] is True


def test_build_sp_match_matches_date_variant(tmp_path, monkeypatch):
    """When the folder name contains any date variant, matches_date=True."""
    photos_root = tmp_path / "PhotosRoot"
    sub = photos_root / "Cesar" / "Smith 4-27-26"
    sub.mkdir(parents=True)
    (sub / "p.jpg").write_bytes(b"x")
    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(photos_root))
    variants = sharepoint._date_variants("04-27-2026")
    rec = sharepoint._build_sp_match(str(sub), run_date_variants=variants)
    assert rec["matches_date"] is True


def test_build_sp_match_no_date_means_no_match_flag(tmp_path, monkeypatch):
    photos_root = tmp_path / "PhotosRoot"
    sub = photos_root / "Cesar" / "Smith John"
    sub.mkdir(parents=True)
    (sub / "p.jpg").write_bytes(b"x")
    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(photos_root))
    rec = sharepoint._build_sp_match(str(sub))
    assert rec["matches_date"] is False


# ── find_sharepoint_folders_for_client ─────────────────────────────────────

@pytest.fixture
def share(tmp_path, monkeypatch):
    """Build a tmp PHOTOS_ROOT with a couple tech folders and jobs."""
    photos_root = tmp_path / "PhotosRoot"
    cesar = photos_root / "Cesar"
    mark = photos_root / "Mark"
    cesar.mkdir(parents=True)
    mark.mkdir(parents=True)
    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(photos_root))
    # Disable extra-roots scan for the existing tests — they pre-date the
    # photos_extra_roots feature and expect the search to be confined to
    # the tmp PHOTOS_ROOT only. Without this, find_* would walk the
    # user's real "Servpro-10100 Photos - Documents" library and surface
    # folders the test didn't create.
    monkeypatch.setattr(sharepoint, "_extra_photo_roots", lambda: [])
    return {"root": photos_root, "Cesar": cesar, "Mark": mark}


def _add_folder(parent, name, n_images=1):
    sub = parent / name
    sub.mkdir(parents=True, exist_ok=True)
    for i in range(n_images):
        (sub / f"img{i}.jpg").write_bytes(b"x")
    return sub


def test_find_returns_empty_when_no_root(monkeypatch):
    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", "/no/such/dir")
    monkeypatch.setattr(sharepoint, "_extra_photo_roots", lambda: [])
    assert sharepoint.find_sharepoint_folders_for_client("Smith John") == []


def test_find_returns_empty_for_blank_client(share):
    assert sharepoint.find_sharepoint_folders_for_client("") == []
    assert sharepoint.find_sharepoint_folders_for_client(None) == []


def test_find_substring_matches_full_name(share):
    """'smith john' substring → match."""
    _add_folder(share["Cesar"], "Smith John 4-27")
    out = sharepoint.find_sharepoint_folders_for_client("Smith John")
    assert len(out) == 1
    assert out[0]["name"] == "Smith John 4-27"


def test_find_substring_falls_back_to_last_name(share):
    """If full name isn't in folder, try the last name."""
    _add_folder(share["Cesar"], "Aldana 4-27")  # only last name
    out = sharepoint.find_sharepoint_folders_for_client("Celia Aldana")
    assert len(out) == 1


def test_find_skips_short_last_names(share):
    """Last name < 3 chars → don't substring-match (would false-positive
    on 'lee', 'an', etc.)."""
    _add_folder(share["Cesar"], "Lee folder")
    out = sharepoint.find_sharepoint_folders_for_client("Bob An")
    # 'an' is 2 chars; shouldn't false-positive on 'Lee folder' anyway,
    # but more importantly shouldn't match anything containing 'an'.
    assert out == []


def test_last_name_fallback_uses_word_boundary(share):
    """Bridgette Miles bug: 'miles' must NOT match folders whose name
    just contains the substring (e.g. 'Smiles Dental', 'Documiles').
    Plain `last in folder_name` was the original logic — that surfaced
    unrelated folders on her audit row. Word boundaries treat the
    surname as its own token."""
    _add_folder(share["Cesar"], "Smiles Dental Clinic")
    _add_folder(share["Cesar"], "Documiles Storage")
    _add_folder(share["Mark"], "Family Smiles")
    out = sharepoint.find_sharepoint_folders_for_client("Bridgette Miles")
    assert out == [], (
        f"Expected no matches, got: {[m['name'] for m in out]}")


def test_last_name_fallback_still_matches_real_folders(share):
    """Word-boundary fix shouldn't break legitimate last-name matches."""
    _add_folder(share["Cesar"], "Miles 4-27")
    _add_folder(share["Mark"], "Miles, Bridgette ME 4-28")
    out = sharepoint.find_sharepoint_folders_for_client("Bridgette Miles")
    names = {m["name"] for m in out}
    assert "Miles 4-27" in names
    assert "Miles, Bridgette ME 4-28" in names


def test_last_name_fallback_rejects_other_first_name(share):
    """Antonio Garcia bug: a folder named 'Garcia, Maria' or
    'Maria Garcia' should NOT match Antonio Garcia's audit row,
    because it explicitly belongs to a different first name."""
    _add_folder(share["Cesar"], "Garcia, Maria 4-27")
    _add_folder(share["Mark"], "Maria Garcia 4-28")
    _add_folder(share["Cesar"], "Sanchez Garcia 4-29")
    out = sharepoint.find_sharepoint_folders_for_client("Antonio Garcia")
    assert out == [], (
        f"Expected no matches, got: {[m['name'] for m in out]}")


def test_last_name_fallback_keeps_bare_last_name_folders(share):
    """Antonio Garcia fix shouldn't reject 'Garcia 4-27' (bare last
    name + date) — that's the most common tech-folder shape and the
    user types the full client name expecting it to find them."""
    _add_folder(share["Cesar"], "Garcia 4-27")
    _add_folder(share["Mark"], "Garcia ME 4-28")  # 'me' is in NON_NAME_TOKENS
    out = sharepoint.find_sharepoint_folders_for_client("Antonio Garcia")
    names = {m["name"] for m in out}
    assert "Garcia 4-27" in names
    assert "Garcia ME 4-28" in names


def test_last_name_fallback_keeps_full_first_name_folders(share):
    """When the folder explicitly names *our* first name, that's a
    perfect match — first name appearing in the folder shouldn't
    accidentally trigger the 'other first name' rejection."""
    _add_folder(share["Cesar"], "Garcia, Antonio 4-27")
    _add_folder(share["Mark"], "Antonio Garcia ME 4-28")
    out = sharepoint.find_sharepoint_folders_for_client("Antonio Garcia")
    names = {m["name"] for m in out}
    assert "Garcia, Antonio 4-27" in names
    assert "Antonio Garcia ME 4-28" in names


def test_last_name_fallback_keeps_carrier_in_folder_name(share):
    """Carrier names in folder ('Hilber, David - State Farm', 'Smith
    John AAA') must NOT be treated as 'other first name' tokens —
    they're the insurance carrier, not a different person. Without
    this guard, every job folder that happens to mention the carrier
    silently fails to match the client's audit row."""
    _add_folder(share["Cesar"], "Hilber, David - State Farm 4-27")
    _add_folder(share["Mark"],  "Hilber David Allstate 4-28")
    _add_folder(share["Cesar"], "Hilber AAA 4-29")
    out = sharepoint.find_sharepoint_folders_for_client("David Hilber")
    names = {m["name"] for m in out}
    assert "Hilber, David - State Farm 4-27" in names
    assert "Hilber David Allstate 4-28" in names
    assert "Hilber AAA 4-29" in names


def test_tech_root_folders_never_match(share, tmp_path):
    """A tech folder named 'Robert' (depth-1 under PHOTOS_ROOT) must
    NOT be returned as a match for client Robert — only the actual job
    folders nested inside the tech's directory should match. Otherwise
    the matcher pulls every Robert client's audit row into Robert the
    tech's own root folder."""
    # Add a tech named "Robert" with one legitimate Robert client job
    # AND one Smith client job inside.
    robert_tech = tmp_path / "PhotosRoot" / "Robert"
    robert_tech.mkdir(parents=True, exist_ok=True)
    (robert_tech / "x.jpg").write_bytes(b"")  # tech root has stray file
    (robert_tech / "Robert Hayes 4-27").mkdir()
    (robert_tech / "Robert Hayes 4-27" / "a.jpg").write_bytes(b"x")
    (robert_tech / "Smith John 4-28").mkdir()
    (robert_tech / "Smith John 4-28" / "a.jpg").write_bytes(b"x")

    out_robert = sharepoint.find_sharepoint_folders_for_client("Robert Hayes")
    names_robert = {m["name"] for m in out_robert}
    assert "Robert Hayes 4-27" in names_robert
    # The tech's own root folder must NOT be in the matches.
    assert "Robert" not in names_robert, (
        f"Tech root 'Robert' should be excluded but got matches: "
        f"{names_robert}")


def test_tech_root_excluded_from_index_too(share, tmp_path):
    """Same exclusion via the cached folder_index path used by full
    audit sweeps."""
    cesar_tech = tmp_path / "PhotosRoot" / "Cesar"
    cesar_tech.mkdir(parents=True, exist_ok=True)
    (cesar_tech / "Smith John 4-27").mkdir()
    (cesar_tech / "Smith John 4-27" / "a.jpg").write_bytes(b"x")

    idx = sharepoint.build_sharepoint_folder_index()
    # Index should mark 'Cesar' as a tech root.
    cesar_entry = next(
        (e for e in idx if os.path.basename(e["path"]) == "Cesar"), None)
    assert cesar_entry is not None
    assert cesar_entry.get("is_tech_root") is True

    # And the matcher should skip tech roots even when a client name
    # would happen to match the tech's name.
    out = sharepoint.find_sharepoint_folders_for_client(
        "Cesar Smith", folder_index=idx)
    names = {m["name"] for m in out}
    assert "Cesar" not in names


def test_last_name_fallback_one_word_client_no_first_name_filter(share):
    """If the client is just 'Garcia' (no first name), every Garcia
    folder is a legitimate match — the other-first-name rejection
    should be skipped because we have no first name to compare."""
    _add_folder(share["Cesar"], "Garcia, Maria 4-27")
    _add_folder(share["Mark"], "Garcia 4-28")
    out = sharepoint.find_sharepoint_folders_for_client("Garcia")
    names = {m["name"] for m in out}
    assert "Garcia, Maria 4-27" in names
    assert "Garcia 4-28" in names


def test_find_surfaces_empty_folders(share):
    """Folder name matches but has no images yet — still surface it.
    Empty folders signal "tech acknowledged the job, photos coming";
    hiding them used to mask cases like Guadalupe Arrenquin / Danny
    where two created-but-empty folders existed but the audit said
    "no SP folders found."""
    (share["Cesar"] / "Smith John empty").mkdir()
    out = sharepoint.find_sharepoint_folders_for_client("Smith John")
    assert len(out) == 1
    assert out[0]["name"] == "Smith John empty"
    assert out[0]["count"] == 0
    assert out[0]["empty"] is True


def test_find_sorts_date_match_first(share):
    """Folders matching the run date sort before non-matching ones."""
    _add_folder(share["Cesar"], "Smith John (no date)", n_images=10)
    _add_folder(share["Mark"], "Smith John 4-27-26", n_images=1)
    out = sharepoint.find_sharepoint_folders_for_client(
        "Smith John", run_date="04-27-2026")
    # Date-matched folder comes first despite having fewer images.
    assert out[0]["matches_date"] is True
    assert out[1]["matches_date"] is False


def test_find_sorts_by_count_within_same_date_match(share):
    """When date-match status ties, more images wins."""
    _add_folder(share["Cesar"], "Smith John", n_images=2)
    _add_folder(share["Mark"], "Smith John folder b", n_images=10)
    out = sharepoint.find_sharepoint_folders_for_client("Smith John")
    assert out[0]["count"] == 10


def test_find_includes_user_overrides(share, monkeypatch, tmp_path):
    """A folder the user pinned via add_sp_match_override must appear
    even if its name doesn't contain the client substring."""
    pinned = _add_folder(share["Mark"], "Recon Photos", n_images=3)
    # Stub persistence so we don't need real state.json.
    monkeypatch.setattr(sharepoint.persistence,
        "get_sp_match_overrides",
        lambda client: [str(pinned)] if client == "Smith John" else [])
    out = sharepoint.find_sharepoint_folders_for_client("Smith John")
    # No name match would have returned []; override forces it in.
    assert len(out) == 1
    assert out[0]["override"] is True
    assert out[0]["name"] == "Recon Photos"


def test_find_overrides_render_first(share, monkeypatch):
    """Override matches sit ahead of auto-matches in the result list."""
    auto = _add_folder(share["Cesar"], "Smith John 4-27", n_images=5)
    over = _add_folder(share["Mark"], "Random Folder", n_images=2)
    monkeypatch.setattr(sharepoint.persistence,
        "get_sp_match_overrides",
        lambda client: [str(over)])
    out = sharepoint.find_sharepoint_folders_for_client("Smith John")
    assert out[0]["override"] is True
    assert out[1]["override"] is False


def test_find_override_dedupes_with_auto(share, monkeypatch):
    """If an override path also gets auto-matched (folder name happens
    to contain the client), don't double-count — flip the auto entry's
    override flag instead."""
    same = _add_folder(share["Cesar"], "Smith John pinned", n_images=2)
    monkeypatch.setattr(sharepoint.persistence,
        "get_sp_match_overrides",
        lambda client: [str(same)])
    out = sharepoint.find_sharepoint_folders_for_client("Smith John")
    assert len(out) == 1  # not 2
    assert out[0]["override"] is True


# ── Image-tree walks (the OneDrive-diff side) ──────────────────────────────

def test_list_image_names_in_tree(tmp_path):
    sub = tmp_path / "PICS"
    sub.mkdir()
    (sub / "a.JPG").write_bytes(b"x")
    (sub / "nested").mkdir()
    (sub / "nested" / "b.png").write_bytes(b"x")
    (sub / "nested" / "ignore.txt").write_bytes(b"x")
    out = sharepoint.list_image_names_in_tree(str(sub))
    # Names lowercased, non-images excluded.
    assert "a.jpg" in out
    assert "b.png" in out
    assert "ignore.txt" not in out


def test_list_image_names_missing_path():
    assert sharepoint.list_image_names_in_tree("/nope") == set()
    assert sharepoint.list_image_names_in_tree(None) == set()


def test_list_image_sizes_in_tree(tmp_path):
    sub = tmp_path / "PICS"
    sub.mkdir()
    (sub / "a.jpg").write_bytes(b"hello")  # size 5
    (sub / "b.png").write_bytes(b"hi")     # size 2
    out = sharepoint.list_image_sizes_in_tree(str(sub))
    assert {2, 5} <= out


def test_file_fingerprint_returns_none_on_missing():
    assert sharepoint._file_fingerprint("/no/such/file") is None


def test_tech_inferred_through_month_archive(tmp_path, monkeypatch):
    """After the monthly-archive feature runs, jobs nest as
    `<tech>/<MonthName YYYY>/<job>`. The tech inference must walk
    UP past the archive folder so the tech is correctly "Nestor",
    not "April 2026"."""
    photos = tmp_path / "PhotosRoot"
    nestor = photos / "Nestor"
    archived_job = nestor / "April 2026" / "Smith John 4-15-26"
    archived_job.mkdir(parents=True)
    (archived_job / "img.jpg").write_bytes(b"x")

    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(photos))
    monkeypatch.setattr(sharepoint, "_extra_photo_roots", lambda: [])

    out = sharepoint.find_sharepoint_folders_for_client("Smith John")
    assert len(out) == 1
    assert out[0]["tech"] == "Nestor"
    assert out[0]["name"] == "Smith John 4-15-26"


def test_month_archive_folder_not_treated_as_job(tmp_path, monkeypatch):
    """A folder named "April 2026" should NOT itself match — it's an
    archive shell. Even if a client happens to have a name that
    overlaps (e.g. surname April), the archive folder is excluded.
    The actual job folders nested INSIDE the archive still match
    normally per their own names + dates."""
    photos = tmp_path / "PhotosRoot"
    cesar = photos / "Cesar"
    archive = cesar / "April 2026"
    archive.mkdir(parents=True)
    # A bare last-name dated folder inside the archive — should still
    # match a "Mary April" client search per the normal date+last-name
    # rules (no other first-name token in the folder to reject it).
    job = archive / "April 4-10-26"
    job.mkdir()
    (job / "img.jpg").write_bytes(b"x")
    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(photos))
    monkeypatch.setattr(sharepoint, "_extra_photo_roots", lambda: [])

    out = sharepoint.find_sharepoint_folders_for_client("Mary April")
    names = {m["name"] for m in out}
    # The "April 2026" archive folder must not be in matches.
    assert "April 2026" not in names
    # The archived job folder (bare last name + date) IS a real
    # match and should still be returned.
    assert "April 4-10-26" in names


def _stamp_mtime(path, year, month, day=15):
    """Force a folder's mtime onto a known date so the archive
    planner's mtime fallback doesn't accidentally pick it up based
    on the wall clock at test time."""
    from datetime import datetime as _dt
    ts = _dt(year, month, day, 12, 0, 0).timestamp()
    os.utime(path, (ts, ts))


def test_plan_month_archive_finds_dated_folders(tmp_path, monkeypatch):
    """plan_month_archive should pick up tech subfolders whose name has
    a date in the target (year, month) and route them into a tech-local
    `<MonthName YYYY>` archive."""
    photos = tmp_path / "PhotosRoot"
    cesar = photos / "Cesar"; cesar.mkdir(parents=True)
    mark  = photos / "Mark";  mark.mkdir(parents=True)
    # April 2026 folders — should be in the plan
    (cesar / "Smith John 4-15-26").mkdir()
    (cesar / "Aldana 4.20.2026").mkdir()
    (mark  / "Miles 4-3-26").mkdir()
    # March (different month) — should be skipped
    (cesar / "Buchanan 3-22-26").mkdir()
    # No date — pin its mtime to January 2025 so the new mtime
    # fallback can't accidentally route it into April 2026.
    flood = cesar / "FloodAtVersa"; flood.mkdir()
    _stamp_mtime(str(flood), 2025, 1)
    # Existing month archive — should be skipped (don't archive the archive)
    (cesar / "April 2026").mkdir()

    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(photos))
    monkeypatch.setattr(sharepoint, "_extra_photo_roots", lambda: [])
    plan = sharepoint.plan_month_archive(2026, 4)
    names = sorted(p["name"] for p in plan)
    assert names == ["Aldana 4.20.2026", "Miles 4-3-26", "Smith John 4-15-26"]
    # Each plan entry routes under its tech to "April 2026"
    for p in plan:
        assert p["dst"].endswith(os.path.join(p["tech"], "April 2026", p["name"]))


def test_plan_month_archive_picks_up_partial_date_no_year(tmp_path, monkeypatch):
    """Common shorthand: techs name folders with M-D and no year ('Smith
    John 4-29', 'Smith 4.22'). When archiving April 2026, those should
    be included too — the month matches and the user's target year is
    implicit. Lead folders especially tend to use the dot form."""
    photos = tmp_path / "PhotosRoot"
    cesar = photos / "Cesar"; cesar.mkdir(parents=True)
    (cesar / "Smith John 4-29").mkdir()
    (cesar / "Garcia 4.3").mkdir()
    (cesar / "Brown 4.22").mkdir()         # the lead-style "<name> M.D"
    (cesar / "Lopez 4/15 lead").mkdir() if False else None  # path sep illegal on Windows
    # Different month, no year — should be skipped
    (cesar / "Buchanan 3-22").mkdir()
    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(photos))
    monkeypatch.setattr(sharepoint, "_extra_photo_roots", lambda: [])
    plan = sharepoint.plan_month_archive(2026, 4)
    names = sorted(p["name"] for p in plan)
    assert names == ["Brown 4.22", "Garcia 4.3", "Smith John 4-29"]


def test_plan_month_archive_falls_back_to_mtime_for_undated(tmp_path,
                                                              monkeypatch):
    """Folders with no date at all in the name ('FloodAtVersa') still
    archive correctly when their latest file mtime falls in the
    target month — covers the 'tech forgot to date the folder' case."""
    photos = tmp_path / "PhotosRoot"
    cesar = photos / "Cesar"; cesar.mkdir(parents=True)
    in_month  = cesar / "FloodAtVersa";   in_month.mkdir()
    out_month = cesar / "AnotherUnnamed"; out_month.mkdir()
    _stamp_mtime(str(in_month),  2026, 4, 12)
    _stamp_mtime(str(out_month), 2026, 2, 12)
    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(photos))
    monkeypatch.setattr(sharepoint, "_extra_photo_roots", lambda: [])
    plan = sharepoint.plan_month_archive(2026, 4)
    names = sorted(p["name"] for p in plan)
    assert names == ["FloodAtVersa"]


def test_plan_month_archive_respects_explicit_year_in_name(tmp_path,
                                                            monkeypatch):
    """If the folder name explicitly encodes a YEAR, that year wins —
    even if the folder's mtime happens to fall in the target month.
    Otherwise re-touching an old folder would silently re-archive it
    into the wrong month."""
    photos = tmp_path / "PhotosRoot"
    cesar = photos / "Cesar"; cesar.mkdir(parents=True)
    # Name says March 2025; mtime says April 2026 → respect the name.
    f = cesar / "Smith 3-15-25"; f.mkdir()
    _stamp_mtime(str(f), 2026, 4, 12)
    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(photos))
    monkeypatch.setattr(sharepoint, "_extra_photo_roots", lambda: [])
    plan = sharepoint.plan_month_archive(2026, 4)
    assert plan == []


def test_scans_folder_excluded_from_all_walks(tmp_path, monkeypatch):
    """The shared 'Scans' folder under PHOTOS_ROOT is not a tech and
    holds no per-job content — every walker (matcher single-client
    mode, sweep-mode index, archive planner) must skip it entirely.
    Without this guard, loose scan files surface as match candidates
    and the archive planner tries to bucket them by month."""
    photos = tmp_path / "PhotosRoot"
    cesar  = photos / "Cesar"; cesar.mkdir(parents=True)
    scans  = photos / "Scans"; scans.mkdir()
    # Real job inside Cesar — should still be visible
    real_job = cesar / "Smith John 4-15-26"
    real_job.mkdir()
    (real_job / "img.jpg").write_bytes(b"x")
    # Inside Scans: a folder that would otherwise match by name and a
    # dated folder that would otherwise be archive-eligible.
    (scans / "Smith John loose").mkdir()
    bait = scans / "Loose 4-20-26"
    bait.mkdir()
    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(photos))
    monkeypatch.setattr(sharepoint, "_extra_photo_roots", lambda: [])

    # 1. Single-client matcher must not return Scans contents
    out = sharepoint.find_sharepoint_folders_for_client("Smith John")
    paths = [m["path"] for m in out]
    assert all("Scans" not in p for p in paths), (
        f"Scans content leaked into matcher results: {paths}")

    # 2. Sweep-mode folder index must not contain Scans entries
    idx = sharepoint.build_sharepoint_folder_index()
    assert all("Scans" not in e["path"] for e in idx), (
        f"Scans content leaked into folder index: "
        f"{[e['path'] for e in idx]}")

    # 3. Archive planner must not propose moving Scans contents
    plan = sharepoint.plan_month_archive(2026, 4)
    names = [p["name"] for p in plan]
    assert "Loose 4-20-26" not in names
    # And the legitimate job IS still in the plan
    assert "Smith John 4-15-26" in names


def test_plan_month_archive_skips_bare_month_folders(tmp_path, monkeypatch):
    """Folders whose entire name is a month — 'March', 'April 2026',
    'March 26' — are organizational shells some techs already use to
    bucket their own work. They are NEVER jobs, so the archiver must
    skip them regardless of mtime. Without this guard, a tech's
    'March' container shows up alongside real jobs in the archive
    plan whenever its mtime drifts into the target month."""
    photos = tmp_path / "PhotosRoot"
    danny = photos / "Danny"; danny.mkdir(parents=True)
    george = photos / "George"; george.mkdir(parents=True)
    # Bare-month containers — must always be skipped
    bare_month  = danny / "March";       bare_month.mkdir()
    short_year  = george / "March 26";   short_year.mkdir()
    full_year   = george / "March 2026"; full_year.mkdir()
    _stamp_mtime(str(bare_month),  2026, 4, 12)  # April mtime — would
    _stamp_mtime(str(short_year),  2026, 4, 12)  # otherwise hit the
    _stamp_mtime(str(full_year),   2026, 4, 12)  # mtime fallback.
    # And one real April-dated job so the plan isn't empty
    (danny / "Smith 4-15-26").mkdir()
    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(photos))
    monkeypatch.setattr(sharepoint, "_extra_photo_roots", lambda: [])
    plan = sharepoint.plan_month_archive(2026, 4)
    names = sorted(p["name"] for p in plan)
    assert names == ["Smith 4-15-26"], (
        f"month-name folders leaked into plan: {names}")


def test_plan_month_archive_skips_already_archived(tmp_path, monkeypatch):
    """A folder that's already inside a `<MonthName YYYY>` archive
    shouldn't be re-archived — `plan` only walks one level under the
    tech root."""
    photos = tmp_path / "PhotosRoot"
    cesar = photos / "Cesar"
    archive = cesar / "April 2026"
    archive.mkdir(parents=True)
    # A dated April folder already inside the April 2026 archive.
    (archive / "Smith 4-15-26").mkdir()
    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(photos))
    monkeypatch.setattr(sharepoint, "_extra_photo_roots", lambda: [])
    plan = sharepoint.plan_month_archive(2026, 4)
    assert plan == []


def test_apply_month_archive_moves_folders(tmp_path, monkeypatch):
    """apply_month_archive should actually move the dated folders into
    their archive parents."""
    photos = tmp_path / "PhotosRoot"
    cesar = photos / "Cesar"; cesar.mkdir(parents=True)
    src = cesar / "Smith John 4-15-26"
    src.mkdir()
    (src / "img.jpg").write_bytes(b"x")
    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(photos))
    monkeypatch.setattr(sharepoint, "_extra_photo_roots", lambda: [])
    plan = sharepoint.plan_month_archive(2026, 4)
    assert len(plan) == 1
    result = sharepoint.apply_month_archive(plan)
    assert len(result["moved"]) == 1
    assert result["errors"] == []
    moved_dst = cesar / "April 2026" / "Smith John 4-15-26" / "img.jpg"
    assert moved_dst.exists()
    assert not src.exists()


def test_apply_month_archive_reports_dest_collision(tmp_path, monkeypatch):
    """If a destination folder already exists (e.g. user retried after a
    partial run), apply_month_archive should report it as an error
    rather than silently overwrite."""
    photos = tmp_path / "PhotosRoot"
    cesar = photos / "Cesar"; cesar.mkdir(parents=True)
    src = cesar / "Smith 4-15-26"
    src.mkdir()
    # Pre-create the destination
    pre_existing = cesar / "April 2026" / "Smith 4-15-26"
    pre_existing.mkdir(parents=True)
    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(photos))
    monkeypatch.setattr(sharepoint, "_extra_photo_roots", lambda: [])
    plan = sharepoint.plan_month_archive(2026, 4)
    result = sharepoint.apply_month_archive(plan)
    assert result["moved"] == []
    assert len(result["errors"]) == 1
    assert "already exists" in result["errors"][0][1]
    # Source must remain untouched
    assert src.exists()


def test_file_fingerprint_returns_size_and_int_mtime(tmp_path):
    p = tmp_path / "x.jpg"
    p.write_bytes(b"hello")
    fp = sharepoint._file_fingerprint(str(p))
    assert fp is not None
    size, mtime = fp
    assert size == 5
    assert isinstance(mtime, int)
