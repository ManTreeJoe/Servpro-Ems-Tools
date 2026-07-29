"""Regression tests for the batch bug-fix sweep (2026-07-01)."""
import os
import zipfile

import snapshots_excel as sx
import companycam_import as cc
from audit_web import _parse_simple_scope


# ── #1: deferred routing override survives the pending sidecar ──────────
def test_route_override_survives_persist():
    r = {"client": "X", "_route_override": "completed", "_claim": "123",
         "form_issues": [], "photo_issues": []}
    out = sx._row_for_persist(r)
    assert out["_route_override"] == "completed"
    assert out["_claim"] == "123"


def test_persist_drops_non_json_underscore_values():
    import datetime
    r = {"client": "X", "_date_received": datetime.datetime(2026, 1, 1),
         "_route_override": "new_loss"}
    out = sx._row_for_persist(r)
    assert out["_route_override"] == "new_loss"
    assert "_date_received" not in out   # datetime not JSON-safe → dropped


# ── #14: simple scope parser handles 10+ numbered items ────────────────
def test_simple_scope_double_digit_numbered():
    raw = "Kitchen\n1. Remove drywall\n10. Replace trim\n11. Paint walls"
    rooms = _parse_simple_scope(raw)
    kitchen = next((r for r in rooms if r["name"] == "Kitchen"), None)
    assert kitchen is not None
    items = kitchen["items"]
    assert "Replace trim" in items      # "10." stripped, not a room header
    assert "Paint walls" in items       # "11." stripped
    assert "Remove drywall" in items


# ── CompanyCam: same-day re-import combines instead of duplicating ─────
def _zip(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return str(path)


def test_companycam_same_day_reimport_dedups(tmp_path):
    zp = _zip(tmp_path / "proj.zip", {
        "proj/alpha.jpg": b"i", "proj/bravo.jpg": b"i"})
    pics = tmp_path / "PICS"
    pics.mkdir()
    cc.import_zip(zp, str(pics), force_subfolder="Demo")
    # Re-import the SAME export (photos arrived at different times).
    cc.import_zip(zp, str(pics), force_subfolder="Demo")
    # Exactly one of each photo across the whole tree — no "(2)" duplicates.
    all_files = []
    for _root, _dirs, files in os.walk(str(pics)):
        all_files.extend(files)
    assert sorted(all_files) == ["alpha.jpg", "bravo.jpg"]
