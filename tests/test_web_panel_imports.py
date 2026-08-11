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
    # The LAST Tk holdout. spreadsheet_gui registers its workbook specs as
    # an import side effect (wbr.register at module scope), so the web
    # panel imports the Tk module purely to populate the registry. The
    # specs themselves are Tk-free; only their `actions` (Tk button
    # factories the web panel never uses) are not.
    "spreadsheet_web":   {"customtkinter", "tkinter", "PIL", "openpyxl", "lxml"},
    # apa_web writes .docx run documents; docx is the panel's job.
    "apa_web":           {"docx", "lxml"},
    # disputes_web reads the dispute workbook via openpyxl.
    "disputes_web":      {"PIL", "openpyxl", "lxml"},
}

CLEAN = [
    "audit_web", "snapshot_web", "home_web", "hygiene_web", "job_notes_web",
    "kpi_web", "multi_unit_web", "notifications_web", "pipeline_web",
    "quickimport_web", "settings_web", "wc_audit_web", "cheat_sheet_web",
    # Was Tk-heavy until the helper cluster moved to daily_photos_logic
    # and theme stopped calling apply_appearance() at import.
    "photo_folders_web",
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
    """The shared modules that caused this in the first place.

    audit_logic and audit_export are imported by most panels;
    wc_zip_import by audit_web for two regexes and a directory scan;
    daily_photos_logic is the pure half split out of daily_photos_gui.
    """
    for mod in ("audit_logic", "audit_export", "wc_zip_import",
                "daily_photos_logic"):
        got = _heavy_after_import(mod)
        assert not got, f"{mod} imports {sorted(got)} at module scope"


def test_theme_does_not_pull_the_tk_stack():
    """`theme` is imported for colour constants by panels that never
    create a widget, and it is the single biggest lever here — it was
    dragging tkinter + customtkinter + PIL into all of them.

    Its CTk import was already written to be lazy; the module then
    CALLED apply_appearance() at the bottom, which made it eager anyway.
    The Tk half lives in ctk_helpers now.
    """
    assert not _heavy_after_import("theme")


def test_ctk_helpers_still_applies_the_appearance():
    """The Tk side must keep matching the palette. ctk_helpers is
    imported by every Tk panel and by nothing else, so it is where the
    CTk half belongs — but only if it actually runs."""
    import inspect

    import ctk_helpers
    src = inspect.getsource(ctk_helpers)
    assert "apply_appearance()" in src
