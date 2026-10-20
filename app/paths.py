# -*- coding: utf-8 -*-
"""运行时路径解析。

区分两类路径：

1. **可写数据目录** ``get_app_dir()``
   - 源码运行：项目根目录（main.py 所在目录）
   - PyInstaller 冻结：exe 所在目录
   - config.ini / 日志文件写在这里

2. **只读资源目录** ``get_resource_path(name)``
   - 源码运行：项目根目录
   - PyInstaller 冻结：``sys._MEIPASS`` 临时解包目录
   - icon.ico 等随包资源从这里读取

这样打包后不会把配置写进临时目录，也不会因为 CWD 不同而找不到文件。
"""

import sys
from pathlib import Path


def get_app_dir() -> Path:
    """返回可写数据目录（配置文件、日志所在目录）。"""
    if getattr(sys, "frozen", False):
        # PyInstaller 单文件模式：sys.executable 指向 exe 本身
        return Path(sys.executable).resolve().parent
    # app/paths.py -> app -> 项目根
    return Path(__file__).resolve().parent.parent


def get_resource_dir() -> Path:
    """返回只读资源目录（打包后为临时解包目录）。"""
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        return Path(bundle_dir)
    return get_app_dir()


def get_resource_path(name: str) -> Path:
    """拼接资源文件路径。"""
    return get_resource_dir() / name
