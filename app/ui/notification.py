# -*- coding: utf-8 -*-
"""歌曲切换通知窗口。

线程约束
--------
本类所有方法**只能在 Tk 主线程调用**。监控线程产生的记录由 TrayApp 放入
UI 队列，再在主线程消费，禁止直接调用 ``show()``。

交互
----
* 右下角无边框悬浮窗，6 秒自动关闭；
* 点击任意位置复制歌曲信息并关闭（无复制文本时只关闭）；
* 绿色表示已在曲库，红色表示不在曲库/新待补，灰色表示无法查询。
"""

import logging
import tkinter as tk
from typing import Optional

from app.constants import (
    NOTIFICATION_ALPHA,
    NOTIFICATION_ARTIST_MAX,
    NOTIFICATION_DURATION_MS,
    NOTIFICATION_HEIGHT,
    NOTIFICATION_MARGIN_BOTTOM,
    NOTIFICATION_MARGIN_RIGHT,
    NOTIFICATION_TITLE_MAX,
    NOTIFICATION_WIDTH,
    player_display_name,
)
from app.ui.theme import (
    COLOR_HEADER_BG,
    COLOR_HEADER_MUTED,
    COLOR_HEADER_PILL_BG,
    COLOR_HEADER_TEXT,
    COLOR_NOTIFICATION_MISSING,
    COLOR_NOTIFICATION_OK,
    COLOR_NOTIFICATION_UNKNOWN,
    ui_font,
)

logger = logging.getLogger(__name__)


class NotificationWindow:
    """曲库状态通知窗。"""

    def __init__(self, root: tk.Misc) -> None:
        self.root = root
        self.window: Optional[tk.Toplevel] = None

    def show(
        self,
        title: str,
        artist: str,
        status: Optional[bool],
        player: str = "",
        is_new_missing: bool = False,
        copy_text: str = "",
    ) -> None:
        """显示通知（主线程调用）。

        Args:
            title: 歌曲名
            artist: 歌手名
            status: True 在库、False 不在库、None 查询失败
            player: 播放器标识
            is_new_missing: 是否刚加入待补清单
            copy_text: 点击通知时复制的文本；为空则只关闭
        """
        self.close()

        if status is True:
            accent = COLOR_NOTIFICATION_OK
            icon_text = "✓"
        elif status is False:
            accent = COLOR_NOTIFICATION_MISSING
            icon_text = "＋" if is_new_missing else "✕"
        else:
            accent = COLOR_NOTIFICATION_UNKNOWN
            icon_text = "?"

        window = tk.Toplevel(self.root)
        self.window = window
        window.overrideredirect(True)          # 无边框
        window.attributes("-topmost", True)    # 置顶
        window.attributes("-alpha", NOTIFICATION_ALPHA)
        window.configure(bg=COLOR_HEADER_BG)

        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        x = screen_width - NOTIFICATION_WIDTH - NOTIFICATION_MARGIN_RIGHT
        y = screen_height - NOTIFICATION_HEIGHT - NOTIFICATION_MARGIN_BOTTOM
        window.geometry(f"{NOTIFICATION_WIDTH}x{NOTIFICATION_HEIGHT}+{x}+{y}")

        shell = tk.Frame(window, bg=COLOR_HEADER_BG)
        shell.pack(fill="both", expand=True)
        tk.Frame(shell, bg=accent, width=6).pack(side="left", fill="y")

        frame = tk.Frame(shell, bg=COLOR_HEADER_BG, padx=18, pady=14)
        frame.pack(side="left", fill="both", expand=True)

        status_frame = tk.Frame(frame, bg=COLOR_HEADER_BG)
        status_frame.pack(fill="x", pady=(0, 7))

        icon = tk.Frame(status_frame, bg=accent, width=30, height=30)
        icon.pack(side="left")
        icon.pack_propagate(False)
        tk.Label(
            icon,
            text=icon_text,
            bg=accent,
            fg="white",
            font=ui_font(12, "bold"),
        ).pack(expand=True)

        if status is True:
            status_text = "已在曲库中"
        elif status is False:
            status_text = "已加入待补清单" if is_new_missing else "不在曲库中"
        else:
            status_text = "无法查询曲库"
        tk.Label(
            status_frame,
            text=status_text,
            bg=COLOR_HEADER_BG,
            fg=accent,
            font=ui_font(10, "bold"),
        ).pack(side="left", padx=(10, 0))

        if player:
            tk.Label(
                status_frame,
                text=player_display_name(player),
                bg=COLOR_HEADER_PILL_BG,
                fg=COLOR_HEADER_MUTED,
                font=ui_font(8, "bold"),
                padx=9,
                pady=3,
            ).pack(side="right")

        song_text = title
        if len(song_text) > NOTIFICATION_TITLE_MAX:
            song_text = song_text[: NOTIFICATION_TITLE_MAX - 3] + "..."

        tk.Label(
            frame,
            text=song_text,
            bg=COLOR_HEADER_BG,
            fg=COLOR_HEADER_TEXT,
            font=ui_font(11, "bold"),
            anchor="w",
        ).pack(fill="x")

        artist_text = artist
        if len(artist_text) > NOTIFICATION_ARTIST_MAX:
            artist_text = artist_text[: NOTIFICATION_ARTIST_MAX - 3] + "..."

        tk.Label(
            frame,
            text=artist_text,
            bg=COLOR_HEADER_BG,
            fg=COLOR_HEADER_MUTED,
            font=ui_font(9),
            anchor="w",
        ).pack(fill="x", pady=(2, 0))

        hint_text = "点击复制歌曲信息" if copy_text else "点击关闭"
        tk.Label(
            frame,
            text=hint_text,
            bg=COLOR_HEADER_BG,
            fg=COLOR_HEADER_MUTED,
            font=ui_font(8),
            anchor="w",
        ).pack(fill="x", pady=(5, 0))

        self._bind_click(shell, copy_text)

        window.after(NOTIFICATION_DURATION_MS, self.close)

    def _bind_click(self, widget: tk.Misc, copy_text: str) -> None:
        """递归给容器及子控件绑定点击事件。"""
        widget.bind("<Button-1>", lambda _event: self._on_click(copy_text))
        for child in widget.winfo_children():
            self._bind_click(child, copy_text)

    def _on_click(self, copy_text: str) -> None:
        if copy_text:
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(copy_text)
                self.root.update_idletasks()
            except tk.TclError:
                logger.warning("复制歌曲信息到剪贴板失败")
        self.close()

    def close(self) -> None:
        """关闭当前通知（幂等）。"""
        if self.window is None:
            return
        try:
            self.window.destroy()
        except tk.TclError:
            pass
        finally:
            self.window = None
