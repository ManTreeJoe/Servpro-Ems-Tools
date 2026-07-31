"""make_folders dedup tests.

Regression coverage for the "duplicate folder created even though one
already exists" bug. The detection side (`_photo_folder_path`) uses a
fuzzy 3-level walk that catches date-format / client-name variants;
the creation side used to use exact `os.path.exists` only, which missed
the variant folders and silently created duplicates. `make_folders`
now consults the same fuzzy detector first.
"""
import os
import pytest

import daily_photos_gui as dpg
import sharepoint


@pytest.fixture
def fake_photos_root(tmp_path, monkeypatch):
    """Spin up a tmp PHOTOS_ROOT with an `FB` tech subfolder and
    pin _TECH_INITIALS so "Fernando" → "FB".

    Patch the root on `sharepoint`, not on `dpg`: daily_photos_gui
    delegates PHOTOS_ROOT to sharepoint as the single lazy source, so
    patching the dpg name only shadows an alias nothing reads and leaves
    the scan pointed at the real share."""
    root = tmp_path / "photos"
    fb = root / "FB"
    fb.mkdir(parents=True)
    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT", str(root), raising=False)
    monkeypatch.setattr(dpg, "_TECH_INITIALS", {"Fernando": "FB"})
    return root, fb


def test_make_folders_skips_existing_folder_with_2_digit_year(fake_photos_root):
    """Folder created earlier with `5-13-26` must not be duplicated when
    the run today is `05-13-2026`. The fuzzy date variants cover both."""
    _root, fb = fake_photos_root
    (fb / "FB 5-13-26 Smith, John").mkdir()
    jobs = [{"client": "Smith, John", "techs": ["Fernando"]}]

    created, skipped = dpg.make_folders(jobs, "05-13-2026")

    assert created == []
    assert len(skipped) == 1
    assert "existing" in skipped[0].lower()


def test_make_folders_skips_existing_folder_with_dot_separators(fake_photos_root):
    """SP techs sometimes type `5.13.26` instead of `5-13-26`. Same
    folder, different separator — still must not duplicate."""
    _root, fb = fake_photos_root
    (fb / "FB 5.13.26 Smith, John").mkdir()
    jobs = [{"client": "Smith, John", "techs": ["Fernando"]}]

    created, skipped = dpg.make_folders(jobs, "05-13-2026")

    assert created == []
    assert any("existing" in s.lower() for s in skipped)


def test_make_folders_creates_when_no_match(fake_photos_root):
    """Sanity: when no folder exists for the (tech, date, client), we
    actually create one and report it."""
    _root, fb = fake_photos_root
    jobs = [{"client": "Smith, John", "techs": ["Fernando"]}]

    created, skipped = dpg.make_folders(jobs, "05-13-2026")

    assert len(created) == 1
    assert "Smith, John" in created[0]
    assert skipped == []
    # Folder actually landed on disk.
    assert (fb / "FB 05-13-2026 Smith, John").is_dir()


def test_make_folders_is_idempotent_on_second_run(fake_photos_root):
    """Same call twice in a row — the second run must skip every job."""
    _root, _fb = fake_photos_root
    jobs = [{"client": "Smith, John", "techs": ["Fernando"]}]

    first_created, _ = dpg.make_folders(jobs, "05-13-2026")
    assert len(first_created) == 1

    second_created, second_skipped = dpg.make_folders(jobs, "05-13-2026")
    assert second_created == []
    assert any("existing" in s.lower() for s in second_skipped)


def test_make_folders_skips_when_client_format_differs(fake_photos_root):
    """Existing folder was created with `Smith John` (no comma); the
    new run-doc spells it `Smith, John`. Still the same job — the
    detector matches on the name token, not the exact string."""
    _root, fb = fake_photos_root
    (fb / "FB 05-13-2026 Smith John").mkdir()
    jobs = [{"client": "Smith, John", "techs": ["Fernando"]}]

    created, skipped = dpg.make_folders(jobs, "05-13-2026")

    assert created == []
    assert any("existing" in s.lower() for s in skipped)


def test_make_folders_skips_unreachable_root_gracefully(tmp_path, monkeypatch):
    """If PHOTOS_ROOT doesn't exist, every job is skipped with a
    "folder not found" message — never a created entry."""
    monkeypatch.setattr(sharepoint, "PHOTOS_ROOT",
                          str(tmp_path / "does_not_exist"), raising=False)
    monkeypatch.setattr(dpg, "_TECH_INITIALS", {"Fernando": "FB"})
    jobs = [{"client": "Smith, John", "techs": ["Fernando"]}]

    created, skipped = dpg.make_folders(jobs, "05-13-2026")

    assert created == []
    assert len(skipped) == 1
    assert "not found" in skipped[0].lower()
