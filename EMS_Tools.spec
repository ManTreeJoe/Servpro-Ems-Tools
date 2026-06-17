# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for EMS Tools.

Build:
    cd "<scripts folder>"
    pyinstaller --noconfirm EMS_Tools.spec

Output:
    dist\EMS Tools\EMS Tools.exe        ← double-click to launch
    dist\EMS Tools\_internal\           ← Python runtime + bundled resources

Distribution:
    Ship the entire `dist\EMS Tools\` folder. The .exe will not run by itself.

User data lives in %APPDATA%\EMS Automation\ — created on first run.
"""

from PyInstaller.utils.hooks import collect_data_files

# ── Bundled resources (read-only) ───────────────────────────────────────────
datas = [
    ('wrench.ico',                '.'),
    ('trello.png',                '.'),
    ('EMS_Admin_Cheat_Sheet.md',  '.'),
    ('config.json',               '.'),       # default; user override goes to %APPDATA%
    ('Sort Files.bat',            '.'),
    ('sort_files.ps1',            '.'),
]
# python-docx ships its default.docx template as a package data file
datas += collect_data_files('docx')


# ── Hidden imports (dispatched dynamically by launcher.__import__) ──────────
hiddenimports = [
    'run_audit_gui',
    'daily_photos_gui',
    'apa_monitor_gui',
    'snapshot_gui',
    'print_audit_gui',
    'sort_files_gui',
    'cheat_sheet_gui',
    'new_job_gui',
    'job_notes_gui',
    'settings_gui',
    'initial_upload_queue',
    'sp_recent_audit',
    'snapshots_excel',
    'openpyxl',
    'openpyxl.workbook',
    'openpyxl.utils',
    'openpyxl.styles',
    'send2trash',
    'PIL._tkinter_finder',
]


a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'pytest', 'matplotlib', 'numpy.random._examples',
    ],
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='EMS Tools',
    icon='wrench.ico',
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
    name='EMS Tools',
)
