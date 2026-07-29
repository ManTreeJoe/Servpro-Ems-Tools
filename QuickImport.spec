# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for QUICK IMPORT — the standalone mini tool for general
office users. A SEPARATE exe/bundle from EMS Tools so a simple user can have
just this, and it runs fully independently (own process, own _internal — the
main app can be open while this rebuilds and vice-versa).

Build:
    pyinstaller --noconfirm --distpath "<dest>" QuickImport.spec

Output:
    <dest>\Quick Import\Quick Import.exe

Entry point is quickimport_web.py, which loads its UI via file:// and reuses
the full audit_web backend. Shares user data with EMS Tools
(%APPDATA%\EMS Automation\) so pins/config are common.
"""

import os
import glob
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

base = SPECPATH
pkg = os.path.join(base, '_packaging')

# ── Bundled data ────────────────────────────────────────────────────────────
# quickimport loads quickimport_web_assets/index.html which references
# ../web_shared/*, so both must sit next to each other in the bundle. We ship
# ALL *_web_assets (harmless, tiny) so nothing the reused backend touches is
# missing.
datas = []
for d in sorted(glob.glob(os.path.join(base, '*_web_assets'))):
    datas.append((d, os.path.basename(d)))
datas.append((os.path.join(base, 'web_shared'), 'web_shared'))
datas.append((os.path.join(base, '_quickimport_root.html'), '.'))
datas.append((os.path.join(pkg, 'config.json'), '.'))

for f in ('wrench.ico', 'trello.png', 'EMS_Admin_Cheat_Sheet.md',
          'Sort Files.bat', 'sort_files.ps1'):
    p = os.path.join(base, f)
    if os.path.exists(p):
        datas.append((p, '.'))

datas += collect_data_files('docx')
try:
    datas += collect_data_files('customtkinter')
except Exception:
    pass

# ── Hidden imports ──────────────────────────────────────────────────────────
# quickimport_web imports audit_web function-locally, which PyInstaller's
# static analysis can't follow — so list every *_web module (audit_web pulls
# the rest of the dep tree once it's a declared hiddenimport) plus the same
# dynamic libs the main spec lists.
web_modules = sorted(
    os.path.splitext(os.path.basename(f))[0]
    for f in glob.glob(os.path.join(base, '*_web.py'))
)
hiddenimports = web_modules + [
    'openpyxl', 'send2trash', 'PIL._tkinter_finder',
    'msg_reader', 'olefile', 'new_loss_intake',
    'companycam_api', 'companycam_import', 'dept_browser',
]
hiddenimports += collect_submodules('openpyxl')
hiddenimports += ['bottle', 'proxy_tools',
                  'webview.platforms.edgechromium', 'webview.platforms.winforms']

excludes = [
    'playwright', 'pytest', 'matplotlib',
    'numpy.random._examples', 'PyQt5', 'PySide2', 'PySide6',
]

a = Analysis(
    ['quickimport_web.py'],
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
    name='Quick Import',
    icon='wrench.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
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
    name='Quick Import',
)
