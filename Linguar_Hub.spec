# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Linguar Hub — WEB UI build (pywebview single window).

Build:
    cd "<scripts folder>"
    pyinstaller --noconfirm Linguar_Hub.spec

Output:
    dist\Linguar Hub\Linguar Hub.exe        <- double-click to launch
    dist\Linguar Hub\_internal\           <- Python runtime + bundled web assets

Distribution:
    Ship the entire `dist\Linguar Hub\` folder (or zip it). The .exe will not
    run by itself.

User data lives in %APPDATA%\Linguar Hub\ — created/seeded on first run
from the bundled (sanitized) config.json. The shipped config carries NO
secrets: each user enters their own Trello key/token + paths in Settings.

Entry point is home_web.py (the pywebview app). The legacy Tk launcher spec
is kept as EMS_Tools_legacy_tk.spec.bak.
"""

import os
import glob
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

base = SPECPATH
pkg  = os.path.join(base, '_packaging')

# App name is env-driven so the SAME spec builds both channels:
#   Main:  pyinstaller Linguar_Hub.spec                        -> "Linguar Hub"
#   Trial: LINGUAR_APP_NAME="Linguar Hub Trial" pyinstaller ...    -> "Linguar Hub Trial"
# The exe/folder name carries the channel; paths._detect_channel() reads it at
# runtime (a build whose path contains "trial" polls the trial update branch
# and shows the TRIAL title). Data + config are shared between channels.
APP_NAME = os.environ.get('LINGUAR_APP_NAME', 'Linguar Hub')
ICON_FILE = 'wrench.ico'

# ── Bundled data ────────────────────────────────────────────────────────────
# pywebview runs with http_server=True rooted at the dir of the URL file
# (_ems_root_index.html, bundled at the bundle root). Each tool's UI loads via
# a sibling `../<tool>_web_assets/index.html`, so every asset folder must sit
# at the bundle root next to home_web_assets. We glob them so a new tool can't
# be forgotten.
datas = []
for d in sorted(glob.glob(os.path.join(base, '*_web_assets'))):
    datas.append((d, os.path.basename(d)))
datas.append((os.path.join(base, 'web_shared'), 'web_shared'))

# Sanitized default config + root redirect shim (safety net; home_web also
# rewrites the shim at startup).
datas.append((os.path.join(pkg, 'config.json'),          '.'))
datas.append((os.path.join(pkg, '_ems_root_index.html'), '.'))
datas.append((os.path.join(base, ICON_FILE), '.'))
datas.append((os.path.join(base, 'version.txt'), '.'))

# Static read-only resources used by various panels.
for f in ('wrench.ico', 'trello.png', 'EMS_Admin_Cheat_Sheet.md',
          'Sort Files.bat', 'sort_files.ps1'):
    p = os.path.join(base, f)
    if os.path.exists(p):
        datas.append((p, '.'))

# python-docx ships its default.docx template as package data.
datas += collect_data_files('docx')
# customtkinter (only reached by a few lazy Tk paths) needs its theme assets
# when it IS loaded — harmless to include otherwise.
try:
    datas += collect_data_files('customtkinter')
except Exception:
    pass

# ── Hidden imports ──────────────────────────────────────────────────────────
# home_web instantiates each tool via `__import__(mod_name)` (a runtime string),
# which PyInstaller's static analysis can't see. Auto-derive every `*_web`
# module by globbing (same source of truth as the asset folders above) so a
# NEW panel can never be silently dropped from the build the way it would be
# with a hand-maintained list.
web_modules = sorted(
    os.path.splitext(os.path.basename(f))[0]
    for f in glob.glob(os.path.join(base, '*_web.py'))
)
hiddenimports = web_modules + [
    # data/runtime libs reached dynamically.
    'openpyxl', 'send2trash', 'PIL._tkinter_finder',
    # OC daily-run docs are Outlook .msg; msg_reader reads them via olefile.
    # Both are reached through a function-local import in run_audit_gui, so
    # list them explicitly rather than rely on static analysis.
    'msg_reader', 'olefile',
    # The health banner reaches web_health through a function-local
    # import on HomeApi. A shipped build where the failure reporter is
    # the thing that silently went missing is the joke writing itself.
    'web_health',
    # New-loss intake is a function-local import from audit_web; list it so
    # static analysis can't drop it from the build.
    'new_loss_intake',
    # CompanyCam + dept-browser are reached via function-local imports too.
    'companycam_api', 'companycam_import', 'dept_browser', 'update_check',
    # ems_db is a FAÇADE that selects its backend with
    # importlib.import_module(<variable>). Static analysis cannot see
    # through that, so without these the packaged app has no job index at
    # all — every folder pin, card link and audit row lookup fails. Not
    # optional, unlike the belt-and-suspenders entries above.
    'ems_db_sqlite', 'ems_db_supabase', 'ems_db_common', 'ems_db_offline',
    # Reached only through function-local imports.
    'cache_bust', 'job_folders', 'trello_auth', 'supabase_client',
    'job_search', 'job_settings', 'job_settings_api',
    'companycam_web_api',
]
hiddenimports += collect_submodules('openpyxl')
# pywebview Windows backend + its http-server deps. pywebview 6.x ships a
# __pyinstaller hook that also covers these; listed for belt-and-suspenders.
hiddenimports += ['bottle', 'proxy_tools',
                  'webview.platforms.edgechromium', 'webview.platforms.winforms']

# ── Excludes ────────────────────────────────────────────────────────────────
# playwright/Chromium is only used by the lazy Workcenter-browser import
# (lowest-priority feature). Excluding it keeps the build small and avoids the
# separate `playwright install chromium` step. PyQt/PySide pulled by neither.
excludes = [
    'playwright', 'pytest', 'matplotlib',
    'numpy.random._examples', 'PyQt5', 'PySide2', 'PySide6',
]


a = Analysis(
    ['home_web.py'],
    pathex=[base],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    icon=ICON_FILE,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,        # GUI app — no console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
