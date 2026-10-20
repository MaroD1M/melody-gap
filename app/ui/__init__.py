# -*- coding: utf-8 -*-
"""Tkinter / pystray 界面层。

所有控件操作必须发生在 Tk 主线程。跨线程事件统一通过
:class:`app.ui.tray.TrayApp` 的 UI 事件队列（``queue.Queue`` + ``root.after``）
投递，禁止在监控线程里直接创建/销毁窗口。
"""
