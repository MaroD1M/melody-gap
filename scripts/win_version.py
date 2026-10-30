# -*- coding: utf-8 -*-
"""生成 PyInstaller 使用的 Windows 版本资源。

版本号只从 :mod:`app.constants` 读取，避免 ``APP_VERSION`` 与打包元信息
不一致。版本资源能让 Windows 正确显示文件属性，也是杀毒软件判断“正常
软件还是未知样本”的重要信号之一。
"""

import re


def version_tuple(version: str) -> tuple:
    """把 ``1.2.0`` 转成 Windows 需要的四段式版本号 ``(1, 2, 0, 0)``。"""
    parts = [int(part) for part in re.findall(r"\d+", version)[:4]]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts)


def build_version_info(version: str, display_name: str):
    """构建设置了完整公司/产品/版权字段的版本资源。"""
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    numbers = version_tuple(version)
    number_text = ".".join(str(part) for part in numbers)
    strings = [
        StringStruct("CompanyName", "MaroD1M"),
        StringStruct("FileDescription", display_name),
        StringStruct("FileVersion", number_text),
        StringStruct("InternalName", "MelodyGap"),
        StringStruct("LegalCopyright", "Copyright (c) 2026 MaroD1M. MIT License."),
        StringStruct("OriginalFilename", "MelodyGap.exe"),
        StringStruct("ProductName", "MelodyGap"),
        StringStruct("ProductVersion", version),
        StringStruct(
            "Comments",
            "Subsonic / Navidrome missing-song tracker. No downloader, no telemetry.",
        ),
    ]
    return VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=numbers,
            prodvers=numbers,
            mask=0x3F,
            flags=0x0,
            OS=0x40004,
            fileType=0x1,
            subtype=0x0,
            date=(0, 0),
        ),
        kids=[
            StringFileInfo([StringTable("040904B0", strings)]),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )
