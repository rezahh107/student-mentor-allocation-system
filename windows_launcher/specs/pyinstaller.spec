# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

import os

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

build_dir = os.path.join("build", "launcher")
dist_dir = os.path.join("dist")

datas = []
binaries = []
hiddenimports = ["windows_service.controller"]

datas += collect_data_files("tzdata")
hiddenimports += collect_submodules("tenacity")

phase6_datas, phase6_binaries, phase6_hidden = collect_all("phase6_import_to_sabt")
datas += phase6_datas
binaries += phase6_binaries
hiddenimports += phase6_hidden

service_datas, service_binaries, service_hidden = collect_all("windows_service")
datas += service_datas
binaries += service_binaries
hiddenimports += service_hidden

for package in ("audit", "ui", "web", "windows_shared"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

assets_dir = os.path.join("assets")
if os.path.isdir(assets_dir):
    datas.append((assets_dir, "assets"))

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
