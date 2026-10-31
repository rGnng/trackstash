# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-folder build for the macOS TrackStash app."""

import os

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
hiddenimports = (
    collect_submodules("mutagen")
    + collect_submodules("watchdog")
    + collect_submodules("platformdirs")
)

a = Analysis(
    [os.path.join(ROOT, "src", "trackstash", "__main__.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TrackStash",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
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
    upx=False,
    upx_exclude=[],
    name="TrackStash",
)

app = BUNDLE(
    coll,
    name="TrackStash.app",
    icon=os.path.join(ROOT, "packaging", "macos", "TrackStash.icns"),
    bundle_identifier="app.trackstash.TrackStash",
    info_plist={
        "CFBundleDisplayName": "TrackStash",
        "CFBundleName": "TrackStash",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "GPL-3.0-only",
    },
)
