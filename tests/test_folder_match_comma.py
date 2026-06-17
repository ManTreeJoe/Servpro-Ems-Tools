"""
Folder-match coverage for comma-separated `<lastname>, <firstname>`
folders that the original substring matcher missed. Catches the
regression where audit reported a job not found because the folder
listed the surname first with a comma.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))

import audit_logic


def _setup_year_dir(tmp, year, folders):
    base = os.path.join(tmp, "audit_base")
    year_dir = os.path.join(base, str(year))
    os.makedirs(year_dir)
    for f in folders:
        os.makedirs(os.path.join(year_dir, f))
    return base


def _audit_one(base, name, year):
    """Run audit_jobs for one client and return the resolved folder name
    (or None when the matcher couldn't pick one). All sections disabled
    so we don't go on to check forms/photos."""
    rows, _err = audit_logic.audit_jobs(
        [{"client": name, "techs": []}],
        base, year=year)
    if not rows:
        return None
    r = rows[0]
    return r.get("folder")


def test_first_last_matches_last_comma_first():
    """run-doc 'John Smith' must match folder 'Smith, John'."""
    with tempfile.TemporaryDirectory() as tmp:
        base = _setup_year_dir(tmp, 2026, ["Smith, John"])
        folder = _audit_one(base, "John Smith", 2026)
        assert folder == "Smith, John"


def test_first_last_matches_last_comma_first_with_middle():
    """run-doc 'John Smith' must match folder 'Smith, John A' (middle initial)."""
    with tempfile.TemporaryDirectory() as tmp:
        base = _setup_year_dir(tmp, 2026, ["Smith, John A"])
        folder = _audit_one(base, "John Smith", 2026)
        assert folder == "Smith, John A"


def test_three_word_matches_comma_form():
    """run-doc 'John Adam Smith' must match folder 'Smith, John Adam'."""
    with tempfile.TemporaryDirectory() as tmp:
        base = _setup_year_dir(tmp, 2026, ["Smith, John Adam"])
        folder = _audit_one(base, "John Adam Smith", 2026)
        assert folder == "Smith, John Adam"


def test_first_last_matches_comma_form_with_extra_suffix():
    """run-doc 'John Smith' must match folder 'Smith, John 2026 EMS'
    (extra suffix is common when techs append job identifiers)."""
    with tempfile.TemporaryDirectory() as tmp:
        base = _setup_year_dir(tmp, 2026, ["Smith, John 2026 EMS"])
        folder = _audit_one(base, "John Smith", 2026)
        assert folder == "Smith, John 2026 EMS"


def test_comma_runforward_reverse_matches_first_last_folder():
    """The reverse direction also has to keep working —
    run-doc 'Smith, John' must match folder 'John Smith'."""
    with tempfile.TemporaryDirectory() as tmp:
        base = _setup_year_dir(tmp, 2026, ["John Smith"])
        folder = _audit_one(base, "Smith, John", 2026)
        assert folder == "John Smith"


def test_single_word_does_not_token_match_unrelated_folder():
    """Token-overlap fallback must NOT fire for single-word names —
    'Costco' should not match an unrelated 'Smith John' folder."""
    with tempfile.TemporaryDirectory() as tmp:
        base = _setup_year_dir(tmp, 2026, ["Smith, John"])
        folder = _audit_one(base, "Costco", 2026)
        assert folder is None or folder != "Smith, John"


def test_disjoint_two_word_name_does_not_match():
    """Two completely disjoint two-word names must not match —
    'Alice Brown' should not pull 'Smith, John'."""
    with tempfile.TemporaryDirectory() as tmp:
        base = _setup_year_dir(tmp, 2026, ["Smith, John"])
        folder = _audit_one(base, "Alice Brown", 2026)
        assert folder is None or folder != "Smith, John"
