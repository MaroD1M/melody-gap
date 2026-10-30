# -*- mode: python ; coding: utf-8 -*-
"""MelodyGap 的 PyInstaller 构建描述。

用法::

    set MELODYGAP_MODE=onedir   # 或不设置，默认 onedir
    pyinstaller --noconfirm --clean scripts/MelodyGap.spec

    set MELODYGAP_MODE=onefile
    pyinstaller --noconfirm --clean scripts/MelodyGap.spec

两种模式都会嵌入统一的版本资源与应用程序清单，并禁用 UPX。推荐分发
``onedir`` 便携版：它不需要运行时自解压，误报概率明显低于单文件版。
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

SPEC_DIR = Path(SPECPATH).resolve()  # noqa: F821 - PyInstaller 注入的全局变量
ROOT = SPEC_DIR.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SPEC_DIR))

from app.constants import APP_DISPLAY_NAME, APP_NAME, APP_VERSION  # noqa: E402
from win_version import build_version_info  # noqa: E402

MODE = os.environ.get("MELODYGAP_MODE", "onedir").strip().lower()
if MODE not in ("onefile", "onedir"):
    raise SystemExit("MELODYGAP_MODE 只能是 onefile 或 onedir，当前为: %r" % MODE)

ICON_PATH = str(ROOT / "icon.ico")
MANIFEST_PATH = str(SPEC_DIR / "MelodyGap.manifest")

hidden_imports = collect_submodules("winrt")
winrt_binaries = collect_dynamic_libs("winrt")

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=winrt_binaries,
    datas=[(ICON_PATH, ".")],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

common_exe_args = dict(
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_PATH,
    version=build_version_info(APP_VERSION, APP_DISPLAY_NAME),
    manifest=MANIFEST_PATH,
)

if MODE == "onefile":
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        **common_exe_args,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        **common_exe_args,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name=APP_NAME,
    )
