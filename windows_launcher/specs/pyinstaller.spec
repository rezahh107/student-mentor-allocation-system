# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

block_cipher = None

if "__file__" in globals():
    SPEC_DIR = Path(__file__).resolve().parent
else:
    SPEC_DIR = (Path.cwd() / "windows_launcher" / "specs").resolve()

PROJECT_ROOT = SPEC_DIR.parent.parent
DIST_ROOT = PROJECT_ROOT / "dist" / "StudentMentorApp"

datas = []
binaries = []
hiddenimports = []

for folder_name in ("static", "assets"):
    source = PROJECT_ROOT / folder_name
    if source.exists():
        datas.append((str(source), folder_name))

a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
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
    name="StudentMentorApp.exe",
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
    destdir=str(DIST_ROOT),
)
