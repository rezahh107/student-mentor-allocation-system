# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

import os

build_dir = os.path.join("build", "launcher")
dist_dir = os.path.join("dist")

a = Analysis(
    ["windows_launcher/launcher.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=["windows_service.controller"],
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
