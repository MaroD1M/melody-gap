# -*- coding: utf-8 -*-
"""MelodyGap 启动入口。

运行：
    python main.py

打包：
    python scripts/build_release.py

职责：
1. 初始化日志；
2. 获取单实例锁；
3. 创建并运行 TrayApp（延迟导入，便于非 GUI 环境做静态检查/测试）。
"""

import logging
import os
import sys

from app.constants import APP_DISPLAY_NAME, APP_NAME
from app.logging_setup import setup_logging
from app.paths import get_app_dir
from app.utils.single_instance import SingleInstanceLock

logger = logging.getLogger(__name__)


def _enable_windows_dpi_awareness() -> None:
    """让 Tk 在 Windows 高 DPI 屏幕上按物理像素渲染，避免界面发虚。

    Windows 8.1+ 使用 shcore；旧系统退回 user32。失败不影响程序运行。
    """
    if os.name != "nt":
        return
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        logger.debug("设置 DPI 感知失败，继续使用系统默认缩放", exc_info=True)


def _run_packaging_smoke_test() -> int:
    """验证冻结包内关键依赖可导入（不启动 GUI、不访问播放器）。"""
    try:
        import tkinter  # noqa: F401
        import winrt.windows.media.control  # noqa: F401

        from app.services.playback_detector import HybridPlaybackDetector  # noqa: F401
    except Exception:
        logger.exception("打包自检失败：关键依赖不可导入")
        return 2
    logger.info("打包自检通过：tkinter / WinRT SMTC / 混合检测器可导入")
    return 0


def _show_message(title: str, message: str, error: bool = False) -> None:
    """在无主窗口场景下弹系统消息框（失败则退回控制台）。"""
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        if error:
            messagebox.showerror(title, message)
        else:
            messagebox.showwarning(title, message)
        root.destroy()
    except Exception:
        print(f"{title}: {message}", file=sys.stderr)


def main() -> int:
    """程序入口，返回进程退出码。"""
    app_dir = get_app_dir()
    setup_logging(app_dir)
    logger.info("启动 %s", APP_DISPLAY_NAME)

    if "--smoke-test" in sys.argv[1:]:
        return _run_packaging_smoke_test()

    if os.name != "nt":
        logger.error("当前平台不受支持：播放器检测依赖 Windows API")
        _show_message(
            "不支持的系统",
            "本程序仅支持 Windows。\n"
            "核心匹配逻辑可在其它平台运行，但无法检测播放器窗口。",
            error=True,
        )
        return 1

    _enable_windows_dpi_awareness()

    lock = SingleInstanceLock(APP_NAME)
    if not lock.acquire():
        logger.warning("程序已在运行，本次启动被忽略")
        _show_message("提示", "程序已在运行中，请检查系统托盘。")
        return 1

    try:
        # 延迟导入：避免在仅做测试/静态检查时加载 tkinter/pystray
        from app.ui.tray import TrayApp

        TrayApp(app_dir).run()
        return 0
    except Exception:
        logger.exception("程序运行失败")
        _show_message("错误", "程序启动失败，请查看日志文件。", error=True)
        return 1
    finally:
        lock.release()
        logger.info("进程退出")


if __name__ == "__main__":
    sys.exit(main())
