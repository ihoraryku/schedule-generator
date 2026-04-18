# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for ScheduleGenerator Windows .exe

Usage:
    pyinstaller schedule_generator.spec
    
Or build directly:
    pyinstaller --name=ScheduleGenerator --onefile --windowed schedule_askue/main.py
"""

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Hidden imports for PyQt6 and dependencies
hiddenimports = [
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'schedule_askue',
    'schedule_askue.db.repository',
    'schedule_askue.core.generator',
    'schedule_askue.core.priority_scheduler',
    'schedule_askue.core.validator',
    'schedule_askue.ui.main_window',
]

# Collect all submodules from schedule_askue
hiddenimports += collect_submodules('schedule_askue')

# Data files to include
datas = [
    ('config.yaml', '.'),
]

a = Analysis(
    ['schedule_askue/main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.binaries,
    a.zip,
    a.datas,
    [],
    name='ScheduleGenerator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)