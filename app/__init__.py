# -*- coding: utf-8 -*-
"""MelodyGap 应用包。

模块分层（详见 docs/DEVELOPMENT.md）：

    app/
    ├── constants.py     全局常量（播放器、颜色、阈值、接口参数）
    ├── models.py        数据模型（SongInfo / PlayRecord）
    ├── paths.py         运行时路径解析（源码运行 / PyInstaller 冻结）
    ├── config_manager.py  config.ini 读写
    ├── logging_setup.py  日志初始化
    ├── services/        与 UI 无关的业务逻辑
    ├── ui/              Tkinter / pystray 界面层
    └── utils/           通用工具（单实例锁等）

重要约定：
1. 业务层（services）不得导入 ui 包，保证可测试、可替换界面。
2. 所有 Tkinter 控件只能在主线程创建和操作，跨线程事件统一写入
   ``TrayApp`` 的 UI 队列，由主线程轮询消费。
3. 仅支持 Windows：窗口标题检测依赖 Win32 API。
"""

from app.constants import APP_VERSION as __version__  # noqa: F401  (包版本单一来源)
