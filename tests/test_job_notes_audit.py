"""Live-audit integration for the Job Notes 'Expected Files' panel.

The panel used to show expected files derived purely from prose. Now it
calls audit_logic against the loaded client's actual folder so each
expected row is marked ✓ (present), ✗ (missing), or • (no audit yet).

These tests pin the three render states + the audit refresh against a
real on-disk folder layout so the right-pane behavior can't drift."""
import os

import pytest

import job_notes_gui


@pytest.fixture
def audit_layout(tmp_path):
    """Mimic the X:\\IE_Public\\<year>\\<client>\\EMS\\... layout."""
    base = tmp_path / "IE_Public"
    year_folder = base / "2026 EMS Files"
    client_folder = year_folder / "Smith John"
    ems = client_folder / "EMS"
    # PICS lives under EMS (audit_logic.resolve_pics_dir expects this).
    pics = ems / "PICS"
    docs = ems / "DOCS"
    initial = pics / "Initial"
    demo = pics / "Demo"
    for d in (base, year_folder, client_folder, ems, pics, docs, initial, demo):
        d.mkdir(parents=True, exist_ok=True)
    # Initial folder has a photo so it satisfies the "Initial pics" check.
    (initial / "img1.jpg").write_bytes(b"x")
    # Demo folder is empty → "Demo pics" is missing.
    return {"base": str(base), "year": "2026 EMS Files",
            "client": "Smith John", "client_path": str(client_folder),
            "pics": str(pics)}


@pytest.fixture
def job_notes_app(tk_root, audit_layout, monkeypatch, tmp_path):
    """Build a JobNotesApp pointed at the tmp audit layout."""
    monkeypatch.setattr(job_notes_gui, "AUDIT_BASE", audit_layout["base"])
    notes_root = tmp_path / "notes"
    notes_root.mkdir()
    monkeypatch.setattr(job_notes_gui, "_NOTES_ROOT", str(notes_root))
    # Avoid the read-side effects of persistence's folder-path memory
    # leaking real X:\ paths into the test.
    monkeypatch.setattr(job_notes_gui.persistence,
                        "get_folder_path", lambda _name: None)
    app = job_notes_gui.JobNotesApp(tk_root)
    yield app
    try:
        app.destroy()
    except Exception:
        pass


def test_render_neutral_marks_when_no_audit_yet(job_notes_app):
    """Before _refresh_audit_status runs, rows show • neutral marks."""
    app = job_notes_app
    app._audit_missing = None
    app._render_expected(["Initial pics", "Demo pics"])
    _, mark_initial, _ = app._ef_rows["Initial pics"]
    _, mark_demo, _ = app._ef_rows["Demo pics"]
    assert mark_initial.cget("text") == "•"
    assert mark_demo.cget("text") == "•"


def test_render_check_when_present(job_notes_app):
    """File NOT in missing set → ✓ green."""
    app = job_notes_app
    app._audit_missing = set()  # nothing missing
    app._render_expected(["Initial pics"])
    _, mark, _ = app._ef_rows["Initial pics"]
    assert mark.cget("text") == "✓"


def test_render_x_when_missing(job_notes_app):
    """File listed as missing → ✗ red."""
    app = job_notes_app
    app._audit_missing = {"Demo pics"}
    app._render_expected(["Initial pics", "Demo pics"])
    _, mark_initial, _ = app._ef_rows["Initial pics"]
    _, mark_demo, _ = app._ef_rows["Demo pics"]
    assert mark_initial.cget("text") == "✓"
    assert mark_demo.cget("text") == "✗"


def test_refresh_audit_status_finds_missing_demo(job_notes_app, audit_layout):
    """End-to-end: prose mentions demo, demo folder is empty on disk →
    audit returns 'Demo pics' as missing."""
    app = job_notes_app
    app._year = audit_layout["year"]
    app._client = audit_layout["client"]
    # Drive the stage parse from the textarea so check_photos receives
    # log_rows that include 'demo'.
    app._textarea.config(state="normal")
    app._textarea.insert("1.0", "demo on Friday")
    app._refresh_audit_status()
    assert app._audit_missing is not None
    assert "Demo pics" in app._audit_missing
    # Initial folder has a file → not missing.
    assert "Initial pics" not in app._audit_missing


def test_refresh_audit_status_initial_photo_report_missing(job_notes_app):
    """The Initial photo report check pulls from EMS/DOCS, not PICS;
    when no photo-report file exists, the audit flags it."""
    app = job_notes_app
    app._year = "2026 EMS Files"
    app._client = "Smith John"
    app._refresh_audit_status()
    assert app._audit_missing is not None
    assert "Initial photo report missing" in app._audit_missing


def test_refresh_audit_status_no_client_leaves_none(job_notes_app):
    app = job_notes_app
    app._client = None
    app._year = None
    app._audit_missing = "previous"  # sentinel to confirm reset
    app._refresh_audit_status()
    assert app._audit_missing is None


def test_refresh_audit_status_unfindable_year_leaves_none(job_notes_app):
    """If _year doesn't contain a 4-digit year, leave the audit empty
    rather than crashing."""
    app = job_notes_app
    app._client = "Smith John"
    app._year = "garbage"
    app._refresh_audit_status()
    assert app._audit_missing is None


def test_refresh_audit_status_unknown_client_leaves_none(job_notes_app):
    """Client folder doesn't exist → audit returns found=False, panel
    falls back to neutral state."""
    app = job_notes_app
    app._client = "Nonexistent Person"
    app._year = "2026 EMS Files"
    app._refresh_audit_status()
    assert app._audit_missing is None
