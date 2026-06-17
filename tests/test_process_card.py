"""Unit tests for process_card_dialog._detect_state. UI-level dialog
behaviour is exercised manually via the IUQ ⚡ Process button; this
file covers the pure-Python detection that drives the dialog's
default checkboxes."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                 "..")))

import process_card_dialog as pcd


def _seed(tmp_path, *, ems=True, docs=True, pics_initial=True,
           paperwork=False, photos=False, sketch=False, scope=False):
    """Build a tmp job folder structure matching the flags. Returns
    the job_path string."""
    job = tmp_path / "Smith, John"
    job.mkdir()
    if ems:
        (job / "EMS").mkdir()
        if docs:
            (job / "EMS" / "DOCS").mkdir()
            if paperwork:
                (job / "EMS" / "DOCS" / "ATP.pdf").write_bytes(b"x")
            if scope:
                (job / "EMS" / "DOCS" / "Scope.pdf").write_bytes(b"x")
            if sketch:
                (job / "EMS" / "DOCS" / "Docusketch").mkdir()
        if pics_initial:
            (job / "EMS" / "PICS").mkdir()
            (job / "EMS" / "PICS" / "Initial").mkdir()
            if photos:
                (job / "EMS" / "PICS" / "Initial"
                     / "shot1.jpg").write_bytes(b"x")
    return str(job)


def test_detect_empty_job(tmp_path):
    """Empty EMS structure → all flags false, no missing folders."""
    job = _seed(tmp_path)
    state = pcd._detect_state(job)
    assert state["missing_folders"] == []
    assert state["has_initial_docs"] is False
    assert state["has_initial_photos"] is False
    assert state["has_docusketch"] is False
    assert state["has_scope"] is False


def test_detect_no_ems_at_all(tmp_path):
    """Bare job folder → all three EMS subs missing."""
    job = _seed(tmp_path, ems=False)
    state = pcd._detect_state(job)
    assert "EMS" in state["missing_folders"]
    assert any("DOCS" in m for m in state["missing_folders"])
    assert any("PICS" in m for m in state["missing_folders"])


def test_detect_paperwork_present(tmp_path):
    job = _seed(tmp_path, paperwork=True)
    state = pcd._detect_state(job)
    assert state["has_initial_docs"] is True


def test_detect_photos_present(tmp_path):
    job = _seed(tmp_path, photos=True)
    state = pcd._detect_state(job)
    assert state["has_initial_photos"] is True


def test_detect_sketch_present(tmp_path):
    job = _seed(tmp_path, sketch=True)
    state = pcd._detect_state(job)
    assert state["has_docusketch"] is True


def test_detect_scope_present(tmp_path):
    job = _seed(tmp_path, scope=True)
    state = pcd._detect_state(job)
    assert state["has_scope"] is True


def test_detect_sp_new_passthrough(tmp_path):
    job = _seed(tmp_path)
    state = pcd._detect_state(job, sp_new_count=7)
    assert state["sp_new"] == 7


def test_has_any_image_finds_recursively(tmp_path):
    folder = tmp_path / "PICS" / "Initial"
    folder.mkdir(parents=True)
    sub = folder / "Kitchen"
    sub.mkdir()
    (sub / "photo.jpg").write_bytes(b"x")
    assert pcd._has_any_image(str(folder)) is True


def test_has_any_image_ignores_non_image(tmp_path):
    folder = tmp_path / "PICS" / "Initial"
    folder.mkdir(parents=True)
    (folder / "notes.txt").write_text("not a photo")
    assert pcd._has_any_image(str(folder)) is False


def test_missing_ems_subs_order(tmp_path):
    """Missing folders should be returned in scaffolder order:
    parent EMS first, then DOCS/PICS underneath."""
    job = tmp_path / "Smith"
    job.mkdir()
    missing = pcd._missing_ems_subs(str(job))
    assert missing[0] == "EMS"
