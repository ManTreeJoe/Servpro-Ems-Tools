"""Tenant extraction in run-doc parser + multi-name SharePoint matching
+ extra photo roots.

The user's case: unit jobs like
"Keystone-Highland Village (Anibal Humberto) (Unit 168): 168 W. Walnut …"
sometimes have the SharePoint photo folder filed under the tenant name
(Anibal Humberto) instead of the property name. The cross-check has to
search both, AND scan extra SharePoint libraries beyond the per-tech
PHOTOS_ROOT (one tech uploads to a sibling site library).

Pinning the three pieces here so a refactor can't quietly drop them."""
import os

import pytest
from docx import Document

import config
import sharepoint
from run_audit_gui import parse_run_doc


def _build_doc(tmp_path, paragraphs, name="run.docx"):
    p = tmp_path / name
    doc = Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    doc.save(str(p))
    return str(p)


# ── Tenant extraction ───────────────────────────────────────────────────────

def test_tenant_extracted_from_parens_before_unit(tmp_path):
    path = _build_doc(tmp_path, [
        "Date: 4/29/26",
        "Work to be performed",
        "Keystone-Highland Village (Anibal Humberto) (Unit 168): "
        "168 W. Walnut Ave Rialto, 92376 (Mold After) ME",
    ])
    jobs, _ = parse_run_doc(path)
    assert len(jobs) == 1
    j = jobs[0]
    # Tenant pulled from the parens immediately before (Unit ...).
    assert j.get("tenant") == "Anibal Humberto"
    # Client name has both paren groups stripped — matchers see the bare
    # property name only.
    assert j["client"] == "Keystone-Highland Village"
    assert j["unit"] == "168"


def test_no_tenant_when_no_parens(tmp_path):
    path = _build_doc(tmp_path, [
        "Date: 4/29/26",
        "Work to be performed",
        "Smith John: 123 Main St (water) Cesar",
    ])
    jobs, _ = parse_run_doc(path)
    assert jobs[0].get("tenant") is None
    assert jobs[0]["client"] == "Smith John"


def test_parens_after_address_dont_become_tenant(tmp_path):
    """`(water)` after the address is the cause-of-loss tag, not a
    tenant — only parens IN the client side that are immediately
    followed by `(Unit …)` count."""
    path = _build_doc(tmp_path, [
        "Date: 4/29/26",
        "Work to be performed",
        "Smith John: 123 Main St (water) Cesar",
    ])
    jobs, _ = parse_run_doc(path)
    assert jobs[0].get("tenant") is None


def test_tenant_carried_through_merge(tmp_path):
    """When the same property appears twice in the run doc, the tenant
    survives the dedup merge."""
    path = _build_doc(tmp_path, [
        "Date: 4/29/26",
        "Work to be performed",
        "Keystone (Anibal) (Unit 168): 168 W. Walnut (Mold) ME",
        "Keystone (Unit 168): 168 W. Walnut (Mold After) JL",
    ])
    jobs, _ = parse_run_doc(path)
    assert len(jobs) == 1, f"Expected merged, got {len(jobs)}"
    assert jobs[0].get("tenant") == "Anibal"


# ── Multi-name SharePoint match ────────────────────────────────────────────

def test_extra_names_finds_tenant_named_folder(tmp_path, monkeypatch):
    """A SharePoint folder named after the tenant (not the property) gets
    matched when the tenant is passed via extra_names."""
    root = tmp_path / "photos"
    tech = root / "ME"
    folder = tech / "ME 4.29.26 Anibal Humberto"
    folder.mkdir(parents=True)
    (folder / "img1.jpg").write_bytes(b"x")

    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(root))
    monkeypatch.setattr(sharepoint, "_extra_photo_roots", lambda: [])

    # Without tenant — property name isn't in the folder, so no match.
    out = sharepoint.find_sharepoint_folders_for_client(
        "Keystone-Highland Village", run_date="04-29-2026")
    assert out == []

    # With tenant as extra_names — the same folder matches.
    out = sharepoint.find_sharepoint_folders_for_client(
        "Keystone-Highland Village",
        run_date="04-29-2026",
        extra_names=["Anibal Humberto"])
    assert len(out) == 1
    assert "Anibal Humberto" in out[0]["name"]


def test_extra_names_doesnt_double_count_when_both_match(
        tmp_path, monkeypatch):
    """If a folder name contains BOTH the property name and the tenant,
    we should only emit one match record."""
    root = tmp_path / "photos"
    tech = root / "ME"
    folder = tech / "ME 4.29.26 Keystone Anibal"
    folder.mkdir(parents=True)
    (folder / "img1.jpg").write_bytes(b"x")

    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(root))
    monkeypatch.setattr(sharepoint, "_extra_photo_roots", lambda: [])

    out = sharepoint.find_sharepoint_folders_for_client(
        "Keystone", run_date="04-29-2026", extra_names=["Anibal"])
    assert len(out) == 1


def test_unit_jobs_dont_cross_pollinate_sp_matches(tmp_path, monkeypatch):
    """Two units of the same property must not surface each other's
    SharePoint folders. Without unit-specific matching, Unit 168's
    audit row was showing Unit 182's photos (and vice-versa) because
    "Keystone" is in every folder name. Locking the match to
    unit-number OR tenant-name keeps each row's photos separate."""
    root = tmp_path / "photos"
    tech = root / "ME"
    tech.mkdir(parents=True)
    # Two SharePoint folders, one per unit, both starting with the same
    # property name.
    f168 = tech / "ME 5.1.26 Keystone Anibal Humberto Unit 168"
    f182 = tech / "ME 5.1.26 Keystone Erin Sanchez Unit 182"
    f168.mkdir()
    f182.mkdir()
    (f168 / "img1.jpg").write_bytes(b"x")
    (f182 / "img2.jpg").write_bytes(b"x")

    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(root))
    monkeypatch.setattr(sharepoint, "_extra_photo_roots", lambda: [])

    # Unit 168 row — should match ONLY the Anibal folder.
    out_168 = sharepoint.find_sharepoint_folders_for_client(
        "Keystone-Highland Village", run_date="05-01-2026",
        extra_names=["Anibal Humberto"], unit="168")
    paths_168 = {m["path"] for m in out_168}
    assert str(f168) in paths_168
    assert str(f182) not in paths_168, (
        f"Unit 168 audit row picked up Unit 182's folder: {paths_168}")

    # Unit 182 row — should match ONLY the Erin folder.
    out_182 = sharepoint.find_sharepoint_folders_for_client(
        "Keystone-Highland Village", run_date="05-01-2026",
        extra_names=["Erin Sanchez"], unit="182")
    paths_182 = {m["path"] for m in out_182}
    assert str(f182) in paths_182
    assert str(f168) not in paths_182


def test_unit_match_falls_through_to_tenant_when_unit_not_in_name(
        tmp_path, monkeypatch):
    """SP folder named after the tenant only ("ME 5.1.26 Anibal")
    should still match when the audit row passes both tenant and unit
    — the tenant name catches it even when the unit number is absent
    from the folder name."""
    root = tmp_path / "photos"
    tech = root / "ME"
    folder = tech / "ME 5.1.26 Anibal Humberto"
    folder.mkdir(parents=True)
    (folder / "img1.jpg").write_bytes(b"x")

    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(root))
    monkeypatch.setattr(sharepoint, "_extra_photo_roots", lambda: [])

    out = sharepoint.find_sharepoint_folders_for_client(
        "Keystone-Highland Village", run_date="05-01-2026",
        extra_names=["Anibal Humberto"], unit="168")
    assert len(out) == 1


def test_unit_job_rejects_bare_property_name_match(tmp_path, monkeypatch):
    """A folder named just "Keystone" with no unit/tenant context
    must NOT match a unit job — that was the cross-pollination
    bug. Unit jobs require unit-number or tenant-name specificity."""
    root = tmp_path / "photos"
    tech = root / "ME"
    folder = tech / "ME 5.1.26 Keystone"  # generic property name only
    folder.mkdir(parents=True)
    (folder / "img1.jpg").write_bytes(b"x")

    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(root))
    monkeypatch.setattr(sharepoint, "_extra_photo_roots", lambda: [])

    out = sharepoint.find_sharepoint_folders_for_client(
        "Keystone-Highland Village", run_date="05-01-2026",
        extra_names=["Anibal Humberto"], unit="168")
    assert out == [], f"Bare property folder leaked into unit match: {out}"


def test_size_count_helper_returns_counts(tmp_path):
    """`list_image_size_counts_in_tree` returns {size: count} so the
    audit can require uniqueness before treating size as a match key."""
    from sharepoint import list_image_size_counts_in_tree
    d = tmp_path / "od"
    d.mkdir()
    # Two photos at 100 bytes, one at 200 bytes.
    (d / "a.jpg").write_bytes(b"x" * 100)
    (d / "b.jpg").write_bytes(b"y" * 100)
    (d / "c.jpg").write_bytes(b"z" * 200)
    counts = list_image_size_counts_in_tree(str(d))
    assert counts[100] == 2
    assert counts[200] == 1


def test_size_match_requires_uniqueness(tmp_path, monkeypatch):
    """End-to-end: when a SP folder gets new photos added, those new
    photos must NOT be hidden by coincidental same-size old OD photos.
    The user's report — adding photos to an already-imported SP folder
    didn't surface them as new because some OD photos shared sizes.

    Build an OD tree where a size occurs twice (so it can't uniquely
    identify any one file), then add a NEW SP file at that exact size
    with a different name and fingerprint. The diff must flag it new."""
    import os as _os
    od = tmp_path / "od"
    od.mkdir()
    old1 = od / "old1.jpg"
    old2 = od / "old2.jpg"
    old1.write_bytes(b"x" * 1000)  # size 1000
    old2.write_bytes(b"y" * 1000)  # size 1000 — colliding
    # Force distinct mtimes so the (size, mtime) fingerprint check
    # isn't accidentally satisfied by filesystem-second collisions.
    _os.utime(str(old1), (1700000000, 1700000000))
    _os.utime(str(old2), (1700000100, 1700000100))

    sp_root = tmp_path / "sp"
    tech = sp_root / "ME"
    folder = tech / "ME 5.1.26 Smith John"
    folder.mkdir(parents=True)
    # NEW photo, same size as both old files but a fresh mtime so its
    # fingerprint is genuinely distinct.
    new = folder / "new_demo.jpg"
    new.write_bytes(b"q" * 1000)
    _os.utime(str(new), (1700000200, 1700000200))

    # Stub run_audit_gui's helpers so enrich_with_sharepoint runs
    # without needing a real audit folder layout.
    import run_audit_gui as rag
    import sp_enrich
    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(sp_root))
    monkeypatch.setattr(sharepoint, "_extra_photo_roots", lambda: [])
    # enrich_with_sharepoint + _resolve_all_pics_folders live in sp_enrich;
    # patch there so the running function sees the stub.
    monkeypatch.setattr(sp_enrich, "_resolve_all_pics_folders",
                         lambda _p: [("Job", str(od), 2)])

    r = {"client": "Smith John", "path": str(od)}
    rag.enrich_with_sharepoint(r, run_date="05-01-2026")
    matches = r.get("sharepoint_matches") or []
    assert matches, "SharePoint match should have been found"
    # The new file must be flagged as new — not silently swallowed by
    # the colliding-size old OD photo.
    assert r.get("sharepoint_new", 0) >= 1, (
        f"New SP file at colliding size was hidden — sharepoint_new="
        f"{r.get('sharepoint_new')!r}")


def test_size_match_still_works_when_unique(tmp_path, monkeypatch):
    """The size-only fallback still fires for genuinely unique OD
    sizes — that's its purpose (catches OD-sync mtime rewrites)."""
    import os as _os
    od = tmp_path / "od"
    od.mkdir()
    only = od / "only.jpg"
    only.write_bytes(b"x" * 5000)  # unique size
    _os.utime(str(only), (1700000000, 1700000000))

    sp_root = tmp_path / "sp"
    tech = sp_root / "ME"
    folder = tech / "ME 5.1.26 Smith John"
    folder.mkdir(parents=True)
    # Same content as `only.jpg` (same size) under a different name +
    # different mtime — simulates a rename-on-copy with mtime drift.
    renamed = folder / "renamed.jpg"
    renamed.write_bytes(b"x" * 5000)
    _os.utime(str(renamed), (1700000200, 1700000200))

    import run_audit_gui as rag
    import sp_enrich
    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(sp_root))
    monkeypatch.setattr(sharepoint, "_extra_photo_roots", lambda: [])
    # enrich_with_sharepoint + _resolve_all_pics_folders live in sp_enrich;
    # patch there so the running function sees the stub.
    monkeypatch.setattr(sp_enrich, "_resolve_all_pics_folders",
                         lambda _p: [("Job", str(od), 1)])

    r = {"client": "Smith John", "path": str(od)}
    rag.enrich_with_sharepoint(r, run_date="05-01-2026")
    # Unique-size match → not flagged as new.
    assert r.get("sharepoint_new", 0) == 0, (
        f"Unique-size SP file should match its OD twin, got "
        f"sharepoint_new={r.get('sharepoint_new')!r}")


def test_non_unit_job_still_matches_property_name(tmp_path, monkeypatch):
    """Non-unit jobs keep the original liberal matching — no unit
    means we accept any folder containing the client name."""
    root = tmp_path / "photos"
    tech = root / "ME"
    folder = tech / "ME 5.1.26 Smith John"
    folder.mkdir(parents=True)
    (folder / "img1.jpg").write_bytes(b"x")

    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(root))
    monkeypatch.setattr(sharepoint, "_extra_photo_roots", lambda: [])

    out = sharepoint.find_sharepoint_folders_for_client(
        "Smith John", run_date="05-01-2026")
    assert len(out) == 1


# ── Extra photo roots ──────────────────────────────────────────────────────

def test_scans_extra_root_for_client(tmp_path, monkeypatch):
    """When `photos_extra_roots` is set, folders under those roots are
    matched in addition to PHOTOS_ROOT. Used for techs who upload to a
    sibling SharePoint library instead of the per-tech tree."""
    primary = tmp_path / "primary_photos"
    primary.mkdir()
    extra = tmp_path / "extra_documents"
    folder = extra / "ME 4.29.26 Smith John"
    folder.mkdir(parents=True)
    (folder / "img1.jpg").write_bytes(b"x")

    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(primary))
    monkeypatch.setattr(sharepoint, "_extra_photo_roots",
                         lambda: [str(extra)])

    out = sharepoint.find_sharepoint_folders_for_client(
        "Smith John", run_date="04-29-2026")
    assert len(out) == 1
    assert out[0]["path"] == str(folder)


def test_extra_root_handles_root_level_job_folders(tmp_path, monkeypatch):
    """Some libraries dump job folders at the root with no tech segment.
    The recursive scan must still find them."""
    primary = tmp_path / "primary_photos"
    primary.mkdir()
    extra = tmp_path / "extra_documents"
    extra.mkdir()
    # Job folder placed DIRECTLY under the extra root — no tech subfolder.
    folder = extra / "Smith John 4.29.26"
    folder.mkdir()
    (folder / "img1.jpg").write_bytes(b"x")

    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(primary))
    monkeypatch.setattr(sharepoint, "_extra_photo_roots",
                         lambda: [str(extra)])

    out = sharepoint.find_sharepoint_folders_for_client(
        "Smith John", run_date="04-29-2026")
    assert len(out) == 1


def test_missing_extra_root_is_silent(tmp_path, monkeypatch):
    """A configured extra root that doesn't exist on disk (e.g. user's
    laptop hasn't synced it yet) should no-op cleanly, not crash."""
    primary = tmp_path / "primary_photos"
    primary.mkdir()
    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(primary))
    monkeypatch.setattr(
        sharepoint, "_extra_photo_roots",
        lambda: [r"C:\nonexistent\path\that\was\never\synced"])

    out = sharepoint.find_sharepoint_folders_for_client(
        "Smith John", run_date="04-29-2026")
    assert out == []


def test_extra_photo_roots_reads_config(monkeypatch):
    """`_extra_photo_roots()` reads from config — a list comes back as
    a list, a single string is tolerated (one path), and missing/blank
    yields []."""
    monkeypatch.setattr(
        config, "load",
        lambda: {"photos_extra_roots": ["A", "B", "  ", ""]})
    assert sharepoint._extra_photo_roots() == ["A", "B"]

    monkeypatch.setattr(config, "load",
                         lambda: {"photos_extra_roots": "single"})
    assert sharepoint._extra_photo_roots() == ["single"]

    monkeypatch.setattr(config, "load", lambda: {})
    assert sharepoint._extra_photo_roots() == []


# ── Multi-unit folder disambiguation ───────────────────────────────────────

def _make_year_folder(tmp_path, year_label, *job_folders):
    yf = tmp_path / year_label
    yf.mkdir(parents=True, exist_ok=True)
    for jf in job_folders:
        (yf / jf).mkdir(parents=True, exist_ok=True)
    return yf


def test_audit_picks_unit_specific_folder(tmp_path):
    """When two property folders exist (different units), the audit
    locks onto the one whose name encodes the requested unit number
    instead of returning whichever came back first from listdir."""
    from audit_logic import audit_jobs as _aj
    base = tmp_path / "IE_Public"
    base.mkdir()
    _make_year_folder(
        base, "2026 EMS Files",
        "Keystone-Highland Village (Unit 168)",
        "Keystone-Highland Village (Unit 250)")
    job = {"client": "Keystone-Highland Village", "unit": "168",
           "tenant": "Anibal Humberto", "techs": [], "new_loss": False}
    results, err = _aj([job], str(base), year=2026)
    assert err is None
    assert len(results) == 1
    r = results[0]
    assert r["found"] is True
    assert "168" in r["folder"], (
        f"Expected unit 168 folder, got {r['folder']!r}")
    assert "250" not in r["folder"]


def test_audit_falls_back_to_property_only_when_no_unit_match(tmp_path):
    """If the year only has a generic property folder (no unit
    encoded), use that — the unit-specific check is a *preference*, not
    a hard requirement."""
    from audit_logic import audit_jobs as _aj
    base = tmp_path / "IE_Public"
    base.mkdir()
    _make_year_folder(base, "2026 EMS Files", "Keystone-Highland Village")
    job = {"client": "Keystone-Highland Village", "unit": "168",
           "tenant": "Anibal Humberto", "techs": [], "new_loss": False}
    results, _ = _aj([job], str(base), year=2026)
    assert results[0]["found"] is True
    assert "Keystone" in results[0]["folder"]


def test_audit_prefers_prior_year_with_unit_specific_match(tmp_path):
    """2026 has a different-unit folder, 2025 has the right unit's
    folder. The cross-year search should land on 2025 instead of
    silently picking 2026's wrong-unit folder."""
    from audit_logic import audit_jobs as _aj
    base = tmp_path / "IE_Public"
    base.mkdir()
    _make_year_folder(base, "2026 EMS Files",
                       "Keystone-Highland Village (Unit 250)")
    _make_year_folder(base, "2025 EMS Files",
                       "Keystone-Highland Village (Unit 168)")
    job = {"client": "Keystone-Highland Village", "unit": "168",
           "tenant": "Anibal Humberto", "techs": [], "new_loss": False}
    results, _ = _aj([job], str(base), year=2026)
    assert results[0]["found"] is True
    assert "168" in results[0]["folder"]
    # Year tag tells the auditor where the match came from.
    assert "(2025)" in results[0]["folder"]


def test_audit_unit_job_rejects_generic_prior_year_fallback(tmp_path):
    """Unit jobs must NOT silently fall back to a generic prior-year
    folder. A 2025 folder named just "Keystone" is a different job
    from Keystone-Highland Village (Unit 168) — without this guard,
    the audit was tagging the wrong folder with "(2025)" and showing
    SP+N counts that belonged to someone else's job."""
    from audit_logic import audit_jobs as _aj
    base = tmp_path / "IE_Public"
    base.mkdir()
    # 2026 has no Keystone folder.
    _make_year_folder(base, "2026 EMS Files")
    # 2025 has a generic Keystone folder for an unrelated job.
    _make_year_folder(base, "2025 EMS Files", "Keystone")
    job = {"client": "Keystone-Highland Village", "unit": "168",
           "tenant": "Anibal Humberto", "techs": [], "new_loss": False}
    results, _ = _aj([job], str(base), year=2026)
    # Better to flag "no folder" than auto-pick the wrong job's folder.
    assert results[0]["found"] is False, (
        f"Expected not-found, got {results[0].get('folder')!r}")


def test_non_unit_job_still_uses_prior_year_fallback(tmp_path):
    """The strict-fallback rule is scoped to jobs with a unit/tenant.
    A regular client (no unit) carrying over from December still
    resolves to the prior year's folder."""
    from audit_logic import audit_jobs as _aj
    base = tmp_path / "IE_Public"
    base.mkdir()
    _make_year_folder(base, "2026 EMS Files")
    _make_year_folder(base, "2025 EMS Files", "Smith John")
    job = {"client": "Smith John", "unit": None, "tenant": None,
           "techs": [], "new_loss": False}
    results, _ = _aj([job], str(base), year=2026)
    assert results[0]["found"] is True
    assert "(2025)" in results[0]["folder"]


def test_audit_unit_match_uses_word_boundary(tmp_path):
    """Unit "16" must not match "Unit 168" — the candidate filter uses
    a word-boundary check so substrings can't trip it."""
    from audit_logic import audit_jobs as _aj
    base = tmp_path / "IE_Public"
    base.mkdir()
    _make_year_folder(base, "2026 EMS Files",
                       "Keystone-Highland Village (Unit 168)",
                       "Keystone-Highland Village (Unit 16)")
    job = {"client": "Keystone-Highland Village", "unit": "16",
           "techs": [], "new_loss": False}
    results, _ = _aj([job], str(base), year=2026)
    assert results[0]["found"] is True
    assert "(Unit 16)" in results[0]["folder"]
    assert "168" not in results[0]["folder"]


# --- lazy-root contract -----------------------------------------------
# These lock in the rule that made 38 tests fail silently: PHOTOS_ROOT is
# resolved lazily through `sharepoint._photos_root()`, so a test that
# patches the module CONSTANT must still redirect the scan. PEP 562
# `__getattr__` only fires when normal lookup fails, so the moment a test
# assigns the name it stops running — and before the override check in
# `_photos_root`, every internal caller quietly went back to reading
# config and walking the real SharePoint share.

def test_patching_photos_root_redirects_the_lazy_getter(tmp_path,
                                                          monkeypatch):
    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(tmp_path),
                        raising=False)
    assert sharepoint._photos_root() == str(tmp_path)


def test_daily_photos_gui_reads_the_root_through_sharepoint(tmp_path,
                                                              monkeypatch):
    """daily_photos_gui must not own a second copy of the root. If this
    fails, someone re-introduced a module-local PHOTOS_ROOT and the
    photo-folder tests are scanning the live share again."""
    import daily_photos_gui as dpg
    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(tmp_path),
                        raising=False)
    assert dpg.PHOTOS_ROOT == str(tmp_path)
