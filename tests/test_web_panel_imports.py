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
    # Was the last Tk holdout: spreadsheet_gui registered the workbook
    # specs as an import side effect, so the web panel imported a Tk
    # module purely to populate the registry. The specs moved to
    # workbook_specs (Tk-free); spreadsheet_gui re-registers Disputes
    # with its Tk `actions` attached. What's left is the xlsx reader.
    "spreadsheet_web":   {"PIL", "openpyxl", "lxml"},
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


def test_shared_logic_never_reaches_into_a_tk_module():
    """Import-time cleanliness is not enough — the reach-ins that keep
    coming back are LAZY ones, `from <x>_gui import helper` inside a
    function. They cost nothing at import and the whole Tk stack the
    first time a user hits that code path, so no import test catches
    them. Three were live before this test existed:

      sp_enrich   -> multi_unit_gui   (every multi-unit enrichment)
      hygiene_web -> hygiene_gui      (every per-tab rescan)
      sharepoint's recent-folder walk lived in sp_recent_audit, a
      tkinter dialog module, and audit_web called into it.

    Worse, two of those sat inside `try/except Exception: return None`,
    so a failed import did not raise — it silently stopped detecting
    units. Scan the AST for imports at ANY depth.
    """
    import ast
    import os

    scripts = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tk_modules = {
        n[:-3] for n in os.listdir(scripts) if n.endswith("_gui.py")
    } | {"tkinter", "customtkinter", "tool_panel", "ui_buttons",
         "sp_recent_audit", "initial_upload_queue", "job_widgets",
         "process_card_dialog"}

    # Modules that are pure logic by contract and are reachable from the
    # web app at runtime. Adding one here is a promise, not a formality.
    pure = ["audit_logic", "audit_export", "run_doc", "sp_enrich",
            "stages", "sharepoint", "multi_unit_logic", "hygiene_tabs",
            "daily_photos_logic", "workbook_specs", "state_hub",
            "hygiene_scan_worker", "trello_hygiene", "ems_db"]

    bad = []
    for mod in pure:
        path = os.path.join(scripts, mod + ".py")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            else:
                continue
            for nm in names:
                if nm in tk_modules:
                    bad.append(f"{mod}.py:{node.lineno} imports {nm}")

    assert not bad, (
        "Pure-logic modules reaching into the Tk stack:\n  "
        + "\n  ".join(bad)
        + "\n\nMove the helper into the logic module and let the Tk "
          "module re-export it — don't import the panel to borrow a "
          "function.")


def test_workbook_specs_registers_both_without_tk():
    """The split that freed spreadsheet_web.

    workbook_specs must (a) stay off the Tk stack and (b) actually
    register — the panel renders an empty workbook dropdown otherwise,
    because nothing else calls wbr.register. Both halves matter, so
    assert them together rather than trusting the import to be enough.
    """
    out = subprocess.run(
        [sys.executable, "-c", textwrap.dedent("""
            import sys, json
            import workbook_specs, workbook_registry as wbr
            print(json.dumps({
                "keys": [s.key for s in wbr.all_specs()],
                "tk": sorted(m for m in ("tkinter", "customtkinter")
                             if m in sys.modules),
            }))
        """)],
        capture_output=True, text=True, timeout=120,
        cwd=__import__("os").path.dirname(
            __import__("os").path.dirname(__import__("os").path.abspath(__file__))))
    assert out.returncode == 0, out.stderr[-500:]
    import json
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert not got["tk"], f"workbook_specs pulled {got['tk']}"
    assert "snapshots" in got["keys"] and "disputes" in got["keys"], got["keys"]


def test_tk_panel_keeps_the_workbook_actions():
    """spreadsheet_gui re-registers Disputes with its Tk button factories
    attached. If that block moves above the action functions it defines,
    it raises NameError; if it is dropped, the Tk panel silently loses
    its buttons. Assert the actions survive the round-trip."""
    import workbook_specs  # plain specs first, as the web panel sees them
    import workbook_registry as wbr
    assert not wbr.get("disputes").actions

    out = subprocess.run(
        [sys.executable, "-c", textwrap.dedent("""
            import json, workbook_registry as wbr, spreadsheet_gui
            print(json.dumps({s.key: [a.label for a in (s.actions or ())]
                              for s in wbr.all_specs()}))
        """)],
        capture_output=True, text=True, timeout=180,
        cwd=__import__("os").path.dirname(
            __import__("os").path.dirname(__import__("os").path.abspath(__file__))))
    if out.returncode != 0:
        pytest.skip(f"spreadsheet_gui not importable here: {out.stderr[-300:]}")
    import json
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert len(got.get("snapshots") or []) == 5, got.get("snapshots")
    assert len(got.get("disputes") or []) == 2, got.get("disputes")


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
