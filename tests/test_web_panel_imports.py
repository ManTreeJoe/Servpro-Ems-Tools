"""Web panels must not drag the Tk stack in at import time.

Every panel is lazy-loaded on first visit, so whatever a panel imports at
module scope is time the user waits staring at an empty window. Pulling
customtkinter / tkinter / PIL / reportlab into a panel that renders HTML
costs ~400-900ms and buys nothing.

This regresses easily: it happens by importing a *_gui module for one
pure helper, or a shared module (audit_logic, audit_export, wc_zip_import)
that itself imports Tk at the top. audit_web was 407 modules and 600ms
because audit_logic did `from docx.oxml.ns import qn` for one function.

Each panel is imported in a SUBPROCESS — inside one pytest run sys.modules
is shared, so a panel imported after a Tk-using test would look dirty (and
a clean panel could hide behind an earlier import).
"""
import subprocess
import sys
import textwrap

import pytest

HEAVY = ("customtkinter", "tkinter", "docx", "PIL", "openpyxl",
         "reportlab", "lxml")

# Panels that still pull something heavy, with the reason. These are
# EXPECTED failures, not permission to add more — the test asserts each
# one is still exactly as dirty as recorded, so cleaning one up (or
# making one worse) shows here.
KNOWN_HEAVY = {
    # spreadsheet_gui registers its workbook specs as an import side
    # effect (wbr.register), so the Tk module has to load. Fixing this
    # means moving registration out of the GUI module.
    "spreadsheet_web":   {"customtkinter", "tkinter", "PIL", "openpyxl", "lxml"},
    # daily_photos_gui owns _photo_folder_path / make_folders plus the
    # helper cluster they need (_TECH_INITIALS, _date_variants,
    # _client_match_tokens, _resolve_tech_root_folder). Extracting that
    # cluster is a real refactor, not a moved import.
    "photo_folders_web": {"customtkinter", "tkinter", "PIL"},
    # apa_web writes .docx run documents; docx is the panel's job.
    "apa_web":           {"docx", "lxml"},
    # disputes_web reads the dispute workbook via openpyxl.
    "disputes_web":      {"PIL", "openpyxl", "lxml"},
}

CLEAN = [
    "audit_web", "snapshot_web", "home_web", "hygiene_web", "job_notes_web",
    "kpi_web", "multi_unit_web", "notifications_web", "pipeline_web",
    "quickimport_web", "settings_web", "wc_audit_web", "cheat_sheet_web",
]

_PROBE = textwrap.dedent("""
    import sys, json
    import {mod}
    print(json.dumps(sorted(m for m in {heavy!r} if m in sys.modules)))
""")


def _heavy_after_import(mod):
    """Import `mod` in a clean interpreter; return the heavy modules it pulled."""
    import os
    scripts = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE.format(mod=mod, heavy=list(HEAVY))],
        capture_output=True, text=True, cwd=scripts, timeout=120)
    if proc.returncode != 0:
        pytest.skip(f"{mod} not importable here: {proc.stderr.strip()[-300:]}")
    import json
    return set(json.loads(proc.stdout.strip().splitlines()[-1]))


@pytest.mark.parametrize("mod", CLEAN)
def test_panel_imports_nothing_heavy(mod):
    got = _heavy_after_import(mod)
    assert not got, (
        f"{mod} now imports {sorted(got)} at module scope. Move the import "
        f"inside the function that needs it, or split the pure helper out "
        f"of the *_gui module — don't add it to KNOWN_HEAVY.")


@pytest.mark.parametrize("mod", sorted(KNOWN_HEAVY))
def test_known_heavy_panels_are_not_getting_worse(mod):
    got = _heavy_after_import(mod)
    expected = KNOWN_HEAVY[mod]
    added = got - expected
    assert not added, f"{mod} gained heavy imports: {sorted(added)}"
    removed = expected - got
    assert not removed, (
        f"{mod} no longer imports {sorted(removed)} — nice. Remove it from "
        f"KNOWN_HEAVY (or move the panel to CLEAN) so the win stays locked in.")


def test_shared_modules_stay_light():
    """The three shared modules that caused this in the first place.

    audit_logic and audit_export are imported by most panels; wc_zip_import
    is imported by audit_web for two regexes and a directory scan.
    """
    for mod in ("audit_logic", "audit_export", "wc_zip_import"):
        got = _heavy_after_import(mod)
        assert not got, f"{mod} imports {sorted(got)} at module scope"
