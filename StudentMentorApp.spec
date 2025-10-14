# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files('tzdata')
binaries = []
hiddenimports = ['tenacity'] + collect_submodules('tenacity') + ['windows_service.controller']
hiddenimports += collect_submodules('windows_service')

_STATIC_FOLDERS = [
    ('windows_service/StudentMentorService.xml', 'windows_service'),
    ('src/ui', 'ui'),
    ('src/web', 'web'),
    ('windows_shared', 'windows_shared'),
    ('src/audit', 'audit'),
    ('src/phase6_import_to_sabt', 'phase6_import_to_sabt'),
]

for source, target in _STATIC_FOLDERS:
    if Path(source).exists():
        datas.append((source, target))


a = Analysis(
    ['windows_launcher\\launcher.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='StudentMentorApp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='StudentMentorApp',
)
