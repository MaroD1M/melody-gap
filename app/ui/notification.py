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
* 绿色表示已在曲库，红色表示不在曲库/新待补，灰色表示无法查询；
* 两条歌曲几乎同时到达时进入队列，逐条展示，不会互相覆盖。
"""

import logging
import tkinter as tk
from dataclasses import dataclass
from typing import List, Optional, Tuple

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
from app.utils.clipboard import copy_text as write_clipboard

logger = logging.getLogger(__name__)

# 同时播放两个播放器时最多排队 5 条，避免长时间占用屏幕。
_QUEUE_MAX = 5


@dataclass
class _Notification:
    title: str
    artist: str
    status: Optional[bool]
    player: str
    is_new_missing: bool
    copy_text: str

    @property
    def key(self) -> Tuple[str, str, Optional[bool], str, bool, str]:
        return (
            self.title,
            self.artist,
            self.status,
            self.player,
            self.is_new_missing,
            self.copy_text,
        )


class NotificationWindow:
    """曲库状态通知窗（带队列）。"""

    def __init__(self, root: tk.Misc) -> None:
        self.root = root
        self.window: Optional[tk.Toplevel] = None
        self._queue: List[_Notification] = []
        self._current: Optional[_Notification] = None
        self._after_job: Optional[str] = None

    def show(
        self,
        title: str,
        artist: str,
        status: Optional[bool],
        player: str = "",
        is_new_missing: bool = False,
        copy_text: str = "",
    ) -> None:
        """显示通知（主线程调用）；已有通知时排队。"""
        item = _Notification(
            title=title,
            artist=artist,
            status=status,
            player=player,
            is_new_missing=is_new_missing,
            copy_text=copy_text,
        )
        if self._current is not None and self._current.key == item.key:
            return
        if any(queued.key == item.key for queued in self._queue):
            return

        if self._window_exists():
            if len(self._queue) < _QUEUE_MAX:
                self._queue.append(item)
            else:
                logger.debug("通知队列已满，忽略: %s", title)
            return

        self._show_now(item)

    def _window_exists(self) -> bool:
        if self.window is None:
            return False
        try:
            return bool(self.window.winfo_exists())
        except tk.TclError:
            return False

    def _show_now(self, item: _Notification) -> None:
        self._current = item
        try:
            self._build_window(item)
        except Exception:
            logger.exception("创建通知窗口失败: %s", item.title)
            self._finish_current(show_next=True)

    def _build_window(self, item: _Notification) -> None:
        if item.status is True:
            accent = COLOR_NOTIFICATION_OK
            icon_text = "✓"
        elif item.status is False:
            accent = COLOR_NOTIFICATION_MISSING
            icon_text = "＋" if item.is_new_missing else "✕"
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

        if item.status is True:
            status_text = "已在曲库中"
        elif item.status is False:
            status_text = "已加入待补清单" if item.is_new_missing else "不在曲库中"
        else:
            status_text = "无法查询曲库"
        tk.Label(
            status_frame,
            text=status_text,
            bg=COLOR_HEADER_BG,
            fg=accent,
            font=ui_font(10, "bold"),
        ).pack(side="left", padx=(10, 0))

        if item.player:
            tk.Label(
                status_frame,
                text=player_display_name(item.player),
                bg=COLOR_HEADER_PILL_BG,
                fg=COLOR_HEADER_MUTED,
                font=ui_font(8, "bold"),
                padx=9,
                pady=3,
            ).pack(side="right")

        song_text = item.title
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

        artist_text = item.artist
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

        hint_text = (
            "单击复制歌曲信息 · 6 秒后自动关闭"
            if item.copy_text
            else "单击关闭 · 6 秒后自动关闭"
        )
        tk.Label(
            frame,
            text=hint_text,
            bg=COLOR_HEADER_BG,
            fg=COLOR_HEADER_MUTED,
            font=ui_font(8),
            anchor="w",
        ).pack(fill="x", pady=(5, 0))

        self._bind_click(shell, item.copy_text)
        self._after_job = window.after(NOTIFICATION_DURATION_MS, self._advance)

    def _bind_click(self, widget: tk.Misc, text: str) -> None:
        """递归给容器及子控件绑定点击事件。"""
        try:
            widget.configure(cursor="hand2")
        except tk.TclError:
            pass
        widget.bind("<Button-1>", lambda _event: self._on_click(text))
        for child in widget.winfo_children():
            self._bind_click(child, text)

    def _on_click(self, text: str) -> None:
        if text:
            try:
                write_clipboard(self.root, text)
            except tk.TclError:
                logger.warning("复制歌曲信息到剪贴板失败")
        self._advance()

    def _advance(self) -> None:
        """关闭当前通知，并展示下一条排队通知。"""
        self._finish_current(show_next=True)

    def _finish_current(self, show_next: bool) -> None:
        if self.window is not None:
            try:
                if self._after_job is not None:
                    self.window.after_cancel(self._after_job)
            except tk.TclError:
                pass
            try:
                self.window.destroy()
            except tk.TclError:
                pass
            self.window = None
        self._after_job = None
        self._current = None

        if not show_next or not self._queue:
            return
        item = self._queue.pop(0)
        self._show_now(item)

    def close(self) -> None:
        """关闭当前通知并清空队列（应用退出时调用）。"""
        self._queue.clear()
        self._finish_current(show_next=False)
