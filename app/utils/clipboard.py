# -*- coding: utf-8 -*-
"""剪贴板写入工具。

Tk 的剪贴板接口需要由具体控件（通常是 root/Toplevel）提供。这里不直接
依赖 Tk 类型，便于用假控件做单元测试，也避免各窗口重复实现。
"""

from typing import Any


def copy_text(widget: Any, text: str) -> None:
    """把文本写入系统剪贴板并立即刷新 Tk 事件队列。

    Args:
        widget: 具备 ``clipboard_clear`` / ``clipboard_append`` /
            ``update_idletasks`` 的 Tk 控件。
    """
    widget.clipboard_clear()
    widget.clipboard_append(text)
    widget.update_idletasks()
