"""Consistency: when EMS / DOCS / PICS folders don't exist on disk,
the audit checks must flag every required item as missing instead of
silently returning [].

The original short-circuits made the audit row look clean for jobs
whose folders weren't scaffolded yet — the user re-discovered the gap
days later and re-did uploads thinking they'd been lost. Lock the
flag-when-missing behavior in here so a refactor can't quietly bring
the silent pass back."""
import os

from audit_logic import (
    REQUIRED_FORMS,
    check_docusketch,
    check_forms,
    check_photos,
)


def test_check_forms_missing_ems_returns_all_required(tmp_path):
    nope = str(tmp_path / "no_ems")
    missing = check_forms(nope)
    expected = [name for name, _pat in REQUIRED_FORMS]
    assert missing == expected


def test_check_forms_missing_ems_with_carrier_appends_carrier_row(tmp_path):
    nope = str(tmp_path / "no_ems")
    missing = check_forms(nope, carrier="Farmers Insurance")
    assert "Auth to Perform" in missing
    assert any("Farmers" in m for m in missing)


def test_check_docusketch_missing_ems_flags_missing(tmp_path):
    nope = str(tmp_path / "no_ems")
    assert check_docusketch(nope) == ["Docusketch folder missing from DOCS"]


def test_check_photos_missing_pics_flags_initial(tmp_path):
    """Missing PICS = Initial pics flagged (no activity context)."""
    nope = str(tmp_path / "no_pics")
    assert check_photos(nope) == ["Initial pics"]


def test_check_photos_missing_pics_with_demo_activity(tmp_path):
    """Missing PICS + Demo in activity = both Initial AND Demo flagged."""
    nope = str(tmp_path / "no_pics")
    missing = check_photos(nope, raw_text="Initial inspection then Demo")
    assert "Initial pics" in missing
    assert "Demo pics" in missing
