# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

build_dir = os.path.join("build", "launcher")
dist_dir = os.path.join("dist")

datas = collect_data_files("tzdata")
binaries = []
hiddenimports = ["tenacity"] + collect_submodules("tenacity") + ["windows_service.controller"]
hiddenimports += collect_submodules("windows_service")

_STATIC_FOLDERS = [
    ("windows_service/StudentMentorService.xml", "windows_service"),
    ("src/ui", "ui"),
    ("src/web", "web"),
    ("windows_shared", "windows_shared"),
    ("src/audit", "audit"),
    ("src/phase6_import_to_sabt", "phase6_import_to_sabt"),
]

for source, target in _STATIC_FOLDERS:
    if Path(source).exists():
        datas.append((source, target))

# Deduplicate while preserving order
def _unique(sequence):
    seen = set()
    result = []
    for item in sequence:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result

datas = _unique(datas)
binaries = _unique(binaries)
hiddenimports = _unique(hiddenimports)

a = Analysis(
    ["windows_launcher/launcher.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="StudentMentorApp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=True,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="StudentMentorApp",
    destdir=dist_dir,
)
