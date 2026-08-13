"""Initial Photo Report presence check.

Checked like a form, but gated on the initial photos existing — the
report can't be produced before the inspection, and flagging it
unconditionally lit up 272 of 608 live jobs, 224 of them simply not yet
inspected. Gated it's 48, all real.

The two traps here both came from the share, not from imagination:
misspelled filenames that DO count, and other photo reports that DON'T.
"""
import os

import pytest

import audit_logic


def _job(tmp_path, *, docs=(), initial_photos=0, other_pics=None):
    """Build a job's EMS tree. Returns the EMS path."""
    ems = tmp_path / "EMS"
    (ems / "DOCS").mkdir(parents=True)
    for name in docs:
        (ems / "DOCS" / name).write_text("x", encoding="utf-8")
    if initial_photos:
        d = ems / "PICS" / "Initial"
        d.mkdir(parents=True)
        for i in range(initial_photos):
            (d / f"IMG_{i}.jpg").write_bytes(b"\xff\xd8\xff")
    if other_pics:
        d = ems / "PICS" / other_pics
        d.mkdir(parents=True)
        (d / "IMG_9.jpg").write_bytes(b"\xff\xd8\xff")
    return str(ems)


def _missing_ipr(ems):
    return audit_logic.IPR_FORM_NAME in (audit_logic.check_forms(ems) or [])


# ── the gate ──────────────────────────────────────────────────────────

def test_no_initial_photos_is_not_missing_anything(tmp_path):
    """A job that hasn't been inspected yet isn't behind."""
    assert not _missing_ipr(_job(tmp_path))


def test_initial_photos_without_the_report_is_flagged(tmp_path):
    assert _missing_ipr(_job(tmp_path, initial_photos=3))


def test_photos_in_another_stage_do_not_trigger_it(tmp_path):
    """Demo photos are not initial photos."""
    assert not _missing_ipr(_job(tmp_path, other_pics="Demo"))


# ── what counts as the report ─────────────────────────────────────────

def test_report_present_clears_it(tmp_path):
    assert not _missing_ipr(
        _job(tmp_path, docs=["Initial Photo Report.pdf"], initial_photos=1))


@pytest.mark.parametrize("name", [
    "Initial photo report.pdf",     # 198 on the share
    "Initial Photo Report.pdf",     # 128
    "initial photo report.pdf",     # 4
    "Inital Photo Report.pdf",      # 4 — real misspelling
    "Intial Photo Report.pdf",      # 1 — real misspelling
    "Nichols Initial Photo Report.pdf",
    "Initial Photo Report FINAL.pdf",
])
def test_real_filenames_from_the_share_all_count(tmp_path, name):
    """Every one of these exists on X:. Missing a spelling would nag a
    job that already has its report — the fastest way to get a checklist
    ignored."""
    assert not _missing_ipr(_job(tmp_path, docs=[name], initial_photos=1))


@pytest.mark.parametrize("name", [
    "Mold photo report.pdf",            # 19 of these on the share
    "MOLD photo report.pdf",
    "Demo Photo Report.pdf",
    "Re-inspection photo report.pdf",
    "Contents photo report.pdf",
    "Post Abatement Photo Report.pdf",
    "Additional Photo Report.pdf",
    "Photo Inventory Report.pdf",
])
def test_other_photo_reports_do_not_satisfy_it(tmp_path, name):
    """A false pass is worse than a nag: it says the initial report is
    filed when it isn't."""
    assert _missing_ipr(_job(tmp_path, docs=[name], initial_photos=1))


def test_report_loose_in_ems_root_also_counts(tmp_path):
    """check_forms reads EMS root as well as DOCS."""
    ems = _job(tmp_path, initial_photos=1)
    with open(os.path.join(ems, "Initial Photo Report.pdf"), "w") as fh:
        fh.write("x")
    assert not _missing_ipr(ems)


# ── it doesn't disturb the existing forms ─────────────────────────────

def test_missing_ems_folder_does_not_add_the_report(tmp_path):
    """No folder means no photos, so the report isn't due — the existing
    every-form-missing behaviour must not gain a sixth entry."""
    missing = audit_logic.check_forms(str(tmp_path / "nope")) or []
    assert audit_logic.IPR_FORM_NAME not in missing
    assert "Auth to Perform" in missing


def test_the_other_forms_still_report_normally(tmp_path):
    ems = _job(tmp_path, docs=["ATP signed.pdf"], initial_photos=1)
    missing = audit_logic.check_forms(ems) or []
    assert "Auth to Perform" not in missing
    assert "Customer Info Form" in missing
    assert audit_logic.IPR_FORM_NAME in missing


def test_initial_folder_named_with_a_suffix_still_gates(tmp_path):
    """"Initial pics" shouldn't make the check silently miss."""
    ems = tmp_path / "EMS"
    (ems / "DOCS").mkdir(parents=True)
    d = ems / "PICS" / "Initial pics"
    d.mkdir(parents=True)
    (d / "IMG_1.jpg").write_bytes(b"\xff\xd8\xff")
    assert _missing_ipr(str(ems))


def test_empty_initial_folder_is_not_photos(tmp_path):
    """A scaffolded-but-empty folder means the visit hasn't happened."""
    ems = tmp_path / "EMS"
    (ems / "DOCS").mkdir(parents=True)
    (ems / "PICS" / "Initial").mkdir(parents=True)
    assert not _missing_ipr(str(ems))
