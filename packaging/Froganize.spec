# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


PROJECT_ROOT = Path(SPECPATH).parent
VERSION = "0.3.0"
CODESIGN_IDENTITY = os.environ.get("FROGANIZE_CODESIGN_IDENTITY") or None

a = Analysis(
    [str(PROJECT_ROOT / "scripts" / "froganize_app_entry.py")],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=[],
    datas=collect_data_files("dropnest"),
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(PROJECT_ROOT / "packaging" / "runtime_collections_abc.py")],
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
    name="Froganize",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=CODESIGN_IDENTITY,
    entitlements_file=None,
    icon=[str(PROJECT_ROOT / "assets" / "Froganize.icns")],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Froganize",
)
app = BUNDLE(
    coll,
    name="Froganize.app",
    icon=str(PROJECT_ROOT / "assets" / "Froganize.icns"),
    bundle_identifier="app.froganize.Froganize",
    version=VERSION,
    info_plist={
        "CFBundleDisplayName": "Froganize",
        "CFBundleName": "Froganize",
        "NSHighResolutionCapable": True,
        "NSDesktopFolderUsageDescription": (
            "Froganize checks the top level of your Desktop only after you open "
            "the app, and collects safe items only when you press Collect Desktop."
        ),
        "NSDocumentsFolderUsageDescription": (
            "Froganize stores the local Timeline workspace in Documents."
        ),
        "LSApplicationCategoryType": "public.app-category.productivity",
    },
)
