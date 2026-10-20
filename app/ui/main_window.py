# -*- coding: utf-8 -*-
"""主窗口：当前播放、待补清单、播放记录与设置入口。

设计目标
--------
* “待补清单”是默认页签，支持搜索、筛选、复制、导出、忽略、删除和重查；
* 播放记录保留原始功能，退居第二页签；
* UI 只读取监控器/仓库快照，不直接访问监控线程内部状态；
* 表格仅在内容签名变化时重建，并保留滚动位置。
"""

import csv
import logging
import tkinter as tk
import webbrowser
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

from app.constants import (
    APP_DISPLAY_NAME,
    APP_TITLE,
    DEFAULT_LAST_TAB,
    DEFAULT_WINDOW_GEOMETRY,
    MISSING_EXPORT_HEADERS,
    MISSING_STATUS_IGNORED,
    MISSING_STATUS_PENDING,
    UI_REFRESH_INTERVAL_MS,
)
from app.models import MissingSong, PlayRecord, SongInfo
from app.services.matcher import make_song_key
from app.ui.icons import load_window_icon
from app.ui.settings_window import SettingsWindow
from app.ui.theme import (
    COLOR_ACCENT,
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_DANGER,
    COLOR_HEADER_BADGE_BG,
    COLOR_HEADER_BADGE_FG,
    COLOR_HEADER_BG,
    COLOR_HEADER_MUTED,
    COLOR_HEADER_PILL_BG,
    COLOR_HEADER_STATUS_OFF,
    COLOR_HEADER_STATUS_OK,
    COLOR_HEADER_TEXT,
    COLOR_HERO_ACCENT,
    COLOR_HERO_BG,
    COLOR_HERO_MUTED,
    COLOR_HERO_TEXT,
    COLOR_INPUT_BG,
    COLOR_NEUTRAL,
    COLOR_PRIMARY,
    COLOR_PRIMARY_DARK,
    COLOR_PRIMARY_SOFT,
    COLOR_ROW_IGNORED_BG,
    COLOR_ROW_IGNORED_FG,
    COLOR_ROW_IN_LIBRARY_BG,
    COLOR_ROW_IN_LIBRARY_FG,
    COLOR_ROW_MISSING_BG,
    COLOR_ROW_MISSING_FG,
    COLOR_ROW_UNKNOWN_BG,
    COLOR_ROW_UNKNOWN_FG,
    COLOR_STATUS_MISSING_BG,
    COLOR_STATUS_MISSING_FG,
    COLOR_STATUS_OK_BG,
    COLOR_STATUS_OK_FG,
    COLOR_STATUS_PENDING_BG,
    COLOR_STATUS_PENDING_FG,
    COLOR_STATUS_UNKNOWN_BG,
    COLOR_STATUS_UNKNOWN_FG,
    COLOR_STAT_LIBRARY_BG,
    COLOR_STAT_LIBRARY_FG,
    COLOR_STAT_MISSING_BG,
    COLOR_STAT_MISSING_FG,
    COLOR_STAT_NETEASE_BG,
    COLOR_STAT_NETEASE_FG,
    COLOR_STAT_QQ_BG,
    COLOR_STAT_QQ_FG,
    COLOR_STAT_TOTAL_BG,
    COLOR_STAT_TOTAL_FG,
    COLOR_SUCCESS,
    COLOR_TEXT,
    COLOR_TEXT_MUTED,
    COLOR_WARNING,
    COLOR_WINDOW_BG,
    apply_modern_style,
    darken_color,
    ui_font,
)
from app.services.monitor import MusicMonitor

logger = logging.getLogger(__name__)

CSV_HEADERS = ("播放时间", "歌曲名称", "歌手", "播放器", "在曲库中")
MISSING_COLUMNS = ("title", "artist", "player", "first_seen", "last_seen", "count", "status")
HISTORY_COLUMNS = ("time", "title", "artist", "player", "status")
MISSING_HEADINGS = {
    "title": "歌曲名称",
    "artist": "歌手",
    "player": "播放器",
    "first_seen": "首次发现",
    "last_seen": "最后发现",
    "count": "次数",
    "status": "状态",
}
HISTORY_HEADINGS = {
    "time": "播放时间",
    "title": "歌曲名称",
    "artist": "歌手",
    "player": "播放器",
    "status": "曲库状态",
}
MISSING_STATUS_FILTERS = {
    "待补": MISSING_STATUS_PENDING,
    "已忽略": MISSING_STATUS_IGNORED,
    "全部": None,
}
HISTORY_STATUS_FILTERS = {
    "全部": "all",
    "在库": True,
    "不在库": False,
    "未知": "unknown",
}


class MainWindow:
    """应用主窗口（Toplevel）。"""

    def __init__(self, root: tk.Tk, monitor: MusicMonitor, app) -> None:
        self.root = root
        self.monitor = monitor
        self.app = app
        self.missing_repo = app.missing_repo
        self.window: Optional[tk.Toplevel] = None
        self.settings_window: Optional[SettingsWindow] = None

        self.is_closing = False
        self._refresh_job: Optional[str] = None
        self._missing_signature: Optional[Tuple] = None
        self._history_signature: Optional[Tuple] = None
        self._icon_photo = None
        self._current_song: Optional[SongInfo] = None

        self._missing_sort_column = "first_seen"
        self._missing_sort_reverse = True
        self._missing_search_var = tk.StringVar()
        self._missing_status_var = tk.StringVar(value="待补")
        self._history_search_var = tk.StringVar()
        self._history_status_var = tk.StringVar(value="全部")
        self._footer_message_var = tk.StringVar(value="")

        self.stats_labels: Dict[str, tk.Label] = {}

    # ---------- 窗口生命周期 ----------

    def create_window(self) -> None:
        """创建主窗口（已存在则恢复并置顶）。"""
        if self.window is not None and self.window.winfo_exists():
            self.window.deiconify()
            self.window.lift()
            self.window.focus_force()
            return

        window = tk.Toplevel(self.root)
        self.window = window
        window.title(APP_TITLE)
        window.minsize(980, 700)
        window.configure(bg=COLOR_WINDOW_BG)
        window.protocol("WM_DELETE_WINDOW", self.app.request_close)
        apply_modern_style(window)

        settings = self.app.config_manager.get_app_settings()
        self._apply_saved_geometry(settings)

        self._icon_photo = load_window_icon(window)
        self.is_closing = False

        self.create_widgets()
        self._restore_tab(settings)
        self.refresh_data()
        self.start_auto_refresh()

    def _apply_saved_geometry(self, settings: Dict[str, str]) -> None:
        assert self.window is not None
        geometry = settings.get("window_geometry") or DEFAULT_WINDOW_GEOMETRY
        try:
            self.window.geometry(geometry)
        except tk.TclError:
            self.window.geometry(DEFAULT_WINDOW_GEOMETRY)

        if settings.get("window_zoomed") == "1":
            self.window.after(50, self._restore_zoomed)

    def _restore_zoomed(self) -> None:
        if self.window is None or not self.window.winfo_exists():
            return
        try:
            self.window.state("zoomed")
        except tk.TclError:
            logger.debug("当前窗口管理器不支持 zoomed 状态")

    def _restore_tab(self, settings: Dict[str, str]) -> None:
        try:
            index = int(settings.get("last_tab", DEFAULT_LAST_TAB))
        except (TypeError, ValueError):
            index = DEFAULT_LAST_TAB
        if 0 <= index < self.notebook.index("end"):
            self.notebook.select(index)

    def show_window(self) -> None:
        """显示主窗口（主线程调用）。"""
        if self.window is None or not self.window.winfo_exists():
            self.create_window()
            return

        self.is_closing = False
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()
        self.start_auto_refresh()

    def show_missing_tab(self) -> None:
        """显示主窗口并切到待补清单。"""
        self.show_window()
        if self.window is None or not self.window.winfo_exists():
            return
        self.notebook.select(0)
        self.window.lift()

    def hide_window(self) -> None:
        """隐藏到托盘（不销毁，保留数据与状态）。"""
        if self.window is None or not self.window.winfo_exists():
            return
        self._save_window_state()
        self.is_closing = True
        self._cancel_refresh_job()
        self.window.withdraw()

    def destroy_window(self) -> None:
        """销毁窗口并取消定时刷新。"""
        self._save_window_state()
        self.is_closing = True
        self._cancel_refresh_job()
        if self.window is not None and self.window.winfo_exists():
            try:
                self.window.destroy()
            except tk.TclError:
                pass
        self.window = None
        self._missing_signature = None
        self._history_signature = None

    def _save_window_state(self) -> None:
        if self.window is None or not self.window.winfo_exists():
            return
        try:
            zoomed = "1" if self.window.state() == "zoomed" else "0"
            tab_index = self.notebook.index(self.notebook.select())
            self.app.config_manager.update_app_settings(
                window_geometry=self.window.geometry(),
                window_zoomed=zoomed,
                last_tab=tab_index,
            )
        except (tk.TclError, OSError):
            logger.exception("保存窗口状态失败")

    # ---------- 界面构建 ----------

    def create_widgets(self) -> None:
        """构建所有界面组件。"""
        assert self.window is not None
        shell = tk.Frame(self.window, bg=COLOR_WINDOW_BG)
        shell.pack(fill="both", expand=True)

        self._create_header(shell)

        body = tk.Frame(shell, bg=COLOR_WINDOW_BG)
        body.pack(fill="both", expand=True, padx=24, pady=(14, 12))
        self._create_current_card(body)
        self._create_stats_panel(body)
        self._create_notebook(body)
        self._create_footer(body)

    def _create_header(self, parent: tk.Misc) -> None:
        header = tk.Frame(parent, bg=COLOR_HEADER_BG)
        header.pack(fill="x")

        inner = tk.Frame(header, bg=COLOR_HEADER_BG)
        inner.pack(fill="x", padx=26, pady=14)

        brand = tk.Frame(inner, bg=COLOR_PRIMARY, width=48, height=48)
        brand.pack(side="left", anchor="center")
        brand.pack_propagate(False)
        tk.Label(
            brand,
            text="♪",
            bg=COLOR_PRIMARY,
            fg="white",
            font=ui_font(22, "bold"),
        ).pack(expand=True)

        title_frame = tk.Frame(inner, bg=COLOR_HEADER_BG)
        title_frame.pack(side="left", padx=(14, 0), fill="y")
        tk.Label(
            title_frame,
            text=APP_DISPLAY_NAME,
            bg=COLOR_HEADER_BG,
            fg=COLOR_HEADER_TEXT,
            font=ui_font(17, "bold"),
        ).pack(anchor="w")
        tk.Label(
            title_frame,
            text="Subsonic · 实时监测与待补清单",
            bg=COLOR_HEADER_BG,
            fg=COLOR_HEADER_MUTED,
            font=ui_font(9),
        ).pack(anchor="w", pady=(3, 0))

        right = tk.Frame(inner, bg=COLOR_HEADER_BG)
        right.pack(side="right", fill="y")
        self.status_label = tk.Label(
            right,
            text="● 监控中",
            bg=COLOR_HEADER_PILL_BG,
            fg=COLOR_HEADER_STATUS_OK,
            font=ui_font(9, "bold"),
            padx=12,
            pady=6,
        )
        self.status_label.pack(side="right", anchor="center", padx=(10, 0))

        self.pending_badge = tk.Label(
            right,
            text="待补 0",
            bg=COLOR_HEADER_BADGE_BG,
            fg=COLOR_HEADER_BADGE_FG,
            font=ui_font(9, "bold"),
            padx=12,
            pady=6,
        )
        self.pending_badge.pack(side="right", anchor="center")

    def _create_current_card(self, parent: tk.Misc) -> None:
        card = tk.Frame(parent, bg=COLOR_HERO_BG)
        card.pack(fill="x", pady=(0, 12))

        inner = tk.Frame(card, bg=COLOR_HERO_BG)
        inner.pack(fill="x", padx=24, pady=16)

        left = tk.Frame(inner, bg=COLOR_HERO_BG)
        left.pack(side="left", fill="both", expand=True)

        tk.Label(
            left,
            text="正在播放",
            bg=COLOR_HERO_BG,
            fg=COLOR_HERO_MUTED,
            font=ui_font(9, "bold"),
        ).pack(anchor="w")

        self.current_song_label = tk.Label(
            left,
            text="暂无播放",
            bg=COLOR_HERO_BG,
            fg=COLOR_HERO_TEXT,
            font=ui_font(18, "bold"),
            anchor="w",
        )
        self.current_song_label.pack(anchor="w", pady=(5, 0))

        self.current_meta_label = tk.Label(
            left,
            text="等待播放器开始播放",
            bg=COLOR_HERO_BG,
            fg=COLOR_HERO_MUTED,
            font=ui_font(10),
            anchor="w",
        )
        self.current_meta_label.pack(anchor="w", pady=(4, 0))

        right = tk.Frame(inner, bg=COLOR_HERO_BG)
        right.pack(side="right", fill="y")

        self.current_status_label = tk.Label(
            right,
            text="—",
            bg=COLOR_STATUS_UNKNOWN_BG,
            fg=COLOR_STATUS_UNKNOWN_FG,
            font=ui_font(9, "bold"),
            padx=12,
            pady=4,
        )
        self.current_status_label.pack(anchor="e")

        actions = tk.Frame(right, bg=COLOR_HERO_BG)
        actions.pack(anchor="e", pady=(10, 0))

        self.current_copy_btn = self._make_button(
            actions,
            "复制歌名",
            self.copy_current,
            COLOR_HERO_ACCENT,
            small=True,
        )
        self.current_copy_btn.configure(disabledforeground=COLOR_HERO_MUTED)
        self.current_copy_btn.pack(side="right", padx=(8, 0))

        self.current_recheck_btn = self._make_button(
            actions,
            "核验待补",
            self.recheck_current,
            "#FFFFFF",
            small=True,
            foreground=COLOR_PRIMARY_DARK,
            hover_color=COLOR_PRIMARY_SOFT,
        )
        self.current_recheck_btn.pack(side="right")

    def _create_stats_panel(self, parent: tk.Misc) -> None:
        stats_frame = tk.Frame(parent, bg=COLOR_WINDOW_BG)
        stats_frame.pack(fill="x", pady=(0, 12))

        cards = (
            (
                "total",
                "总播放",
                "本次运行",
                COLOR_STAT_TOTAL_BG,
                COLOR_STAT_TOTAL_FG,
                self._show_all_history,
            ),
            (
                "in_library",
                "在库",
                "点击筛选",
                COLOR_STAT_LIBRARY_BG,
                COLOR_STAT_LIBRARY_FG,
                self._show_in_library_history,
            ),
            (
                "missing",
                "待补",
                "点击查看",
                COLOR_STAT_MISSING_BG,
                COLOR_STAT_MISSING_FG,
                self._show_pending_filter,
            ),
            (
                "qq",
                "QQ音乐",
                "点击筛选",
                COLOR_STAT_QQ_BG,
                COLOR_STAT_QQ_FG,
                lambda: self._show_history_filter(None, search="QQ音乐"),
            ),
            (
                "netease",
                "网易云",
                "点击筛选",
                COLOR_STAT_NETEASE_BG,
                COLOR_STAT_NETEASE_FG,
                lambda: self._show_history_filter(None, search="网易云"),
            ),
        )
        for index, (key, title, subtitle, background, foreground, command) in enumerate(cards):
            card = tk.Frame(stats_frame, bg=background)
            card.grid(
                row=0,
                column=index,
                sticky="nsew",
                padx=(0 if index == 0 else 10, 0),
            )
            stats_frame.grid_columnconfigure(index, weight=1, uniform="stats")

            tk.Frame(card, bg=foreground, height=4).pack(fill="x")

            content = tk.Frame(card, bg=background)
            content.pack(fill="both", expand=True, padx=16, pady=(8, 10))

            value_label = tk.Label(
                content,
                text="0",
                bg=background,
                fg=foreground,
                font=ui_font(22, "bold"),
            )
            value_label.pack(anchor="w")
            tk.Label(
                content,
                text=title,
                bg=background,
                fg=COLOR_TEXT,
                font=ui_font(10, "bold"),
            ).pack(anchor="w", pady=(1, 0))
            tk.Label(
                content,
                text=subtitle,
                bg=background,
                fg=COLOR_TEXT_MUTED,
                font=ui_font(8),
            ).pack(anchor="w", pady=(1, 0))

            self.stats_labels[key] = value_label
            self._bind_click(card, command)

    def _create_notebook(self, parent: tk.Misc) -> None:
        self.notebook = ttk.Notebook(parent, style="Modern.TNotebook")
        self.notebook.pack(fill="both", expand=True)

        self.missing_tab = tk.Frame(self.notebook, bg=COLOR_WINDOW_BG)
        self.history_tab = tk.Frame(self.notebook, bg=COLOR_WINDOW_BG)
        self.notebook.add(self.missing_tab, text="待补清单")
        self.notebook.add(self.history_tab, text="播放记录")

        self._create_missing_tab(self.missing_tab)
        self._create_history_tab(self.history_tab)

    def _create_missing_tab(self, parent: tk.Misc) -> None:
        toolbar = tk.Frame(
            parent,
            bg=COLOR_CARD_BG,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
        )
        toolbar.pack(fill="x", pady=(0, 10))

        inner = tk.Frame(toolbar, bg=COLOR_CARD_BG)
        inner.pack(fill="x", padx=14, pady=8)

        tk.Label(
            inner,
            text="搜索",
            bg=COLOR_CARD_BG,
            fg=COLOR_TEXT_MUTED,
            font=ui_font(9),
        ).pack(side="left")
        search_entry = tk.Entry(
            inner,
            textvariable=self._missing_search_var,
            font=ui_font(10),
            width=22,
            bg=COLOR_INPUT_BG,
            fg=COLOR_TEXT,
            insertbackground=COLOR_TEXT,
            relief="flat",
            highlightbackground=COLOR_BORDER,
            highlightcolor=COLOR_PRIMARY,
            highlightthickness=1,
        )
        search_entry.pack(side="left", padx=(6, 10), ipady=6)
        search_entry.bind("<KeyRelease>", self._on_missing_filter_change)

        self.missing_status_combo = ttk.Combobox(
            inner,
            textvariable=self._missing_status_var,
            values=list(MISSING_STATUS_FILTERS),
            state="readonly",
            width=7,
            font=ui_font(10),
            style="Modern.TCombobox",
        )
        self.missing_status_combo.pack(side="left", ipady=1)
        self.missing_status_combo.bind(
            "<<ComboboxSelected>>", self._on_missing_filter_change
        )

        self.missing_count_label = tk.Label(
            inner,
            text="0 首",
            bg=COLOR_PRIMARY_SOFT,
            fg=COLOR_PRIMARY_DARK,
            font=ui_font(9, "bold"),
            padx=10,
            pady=4,
        )
        self.missing_count_label.pack(side="left", padx=(10, 0))

        actions = (
            ("复制选中", self.copy_selected_missing, COLOR_ACCENT),
            ("复制全部", self.copy_all_missing, COLOR_NEUTRAL),
            ("导出", self.export_missing, COLOR_SUCCESS),
            ("核验选中", self.recheck_selected, COLOR_PRIMARY),
            ("核验全部", self.recheck_all_missing, COLOR_WARNING),
            ("忽略", self.ignore_missing, COLOR_NEUTRAL),
            ("删除", self.delete_missing, COLOR_DANGER),
        )
        for text, command, color in actions:
            self._make_button(inner, text, command, color, small=True).pack(
                side="right", padx=(6, 0)
            )

        table_frame = tk.Frame(
            parent,
            bg=COLOR_CARD_BG,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
        )
        table_frame.pack(fill="both", expand=True)
        container = tk.Frame(table_frame, bg=COLOR_CARD_BG)
        container.pack(fill="both", expand=True, padx=1, pady=1)

        self.missing_tree = ttk.Treeview(
            container,
            columns=MISSING_COLUMNS,
            show="headings",
            style="Modern.Treeview",
            selectmode="extended",
            height=4,
        )
        widths = {
            "title": (220, 150),
            "artist": (160, 100),
            "player": (85, 70),
            "first_seen": (135, 120),
            "last_seen": (135, 120),
            "count": (60, 50),
            "status": (80, 60),
        }
        for column in MISSING_COLUMNS:
            width, minwidth = widths[column]
            self.missing_tree.heading(
                column,
                text=MISSING_HEADINGS[column],
                command=lambda value=column: self._sort_missing(value),
            )
            self.missing_tree.column(
                column,
                width=width,
                minwidth=minwidth,
                anchor="center" if column in ("player", "count", "status") else "w",
            )

        self.missing_tree.tag_configure(
            "pending",
            background=COLOR_ROW_MISSING_BG,
            foreground=COLOR_ROW_MISSING_FG,
        )
        self.missing_tree.tag_configure(
            "ignored",
            background=COLOR_ROW_IGNORED_BG,
            foreground=COLOR_ROW_IGNORED_FG,
        )

        scrollbar = ttk.Scrollbar(
            container,
            orient="vertical",
            command=self.missing_tree.yview,
            style="Modern.Vertical.TScrollbar",
        )
        self.missing_tree.configure(yscrollcommand=scrollbar.set)
        self.missing_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.missing_tree.bind("<Double-1>", self._on_missing_double_click)
        self.missing_tree.bind("<Button-3>", self._on_missing_context_menu)
        self._create_missing_context_menu()
        self._update_missing_headings()

    def _create_missing_context_menu(self) -> None:
        assert self.window is not None
        self.missing_menu = tk.Menu(
            self.window,
            tearoff=0,
            bg=COLOR_CARD_BG,
            fg=COLOR_TEXT,
            activebackground=COLOR_PRIMARY,
            activeforeground="white",
            font=ui_font(9),
            bd=0,
            relief="flat",
        )
        self.missing_menu.add_command(
            label="复制歌曲信息", command=self.copy_selected_missing
        )
        self.missing_menu.add_command(
            label="在 QQ 音乐搜索", command=lambda: self._search_selected("qq")
        )
        self.missing_menu.add_command(
            label="在网易云搜索", command=lambda: self._search_selected("netease")
        )
        self.missing_menu.add_separator()
        self.missing_menu.add_command(label="核验选中", command=self.recheck_selected)
        self.missing_menu.add_command(label="核验全部待补", command=self.recheck_all_missing)
        self.missing_menu.add_command(label="标记已忽略", command=self.ignore_missing)
        self.missing_menu.add_command(label="恢复为待补", command=self.restore_missing)
        self.missing_menu.add_separator()
        self.missing_menu.add_command(label="从清单删除", command=self.delete_missing)

    def _create_history_tab(self, parent: tk.Misc) -> None:
        toolbar = tk.Frame(
            parent,
            bg=COLOR_CARD_BG,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
        )
        toolbar.pack(fill="x", pady=(0, 10))

        inner = tk.Frame(toolbar, bg=COLOR_CARD_BG)
        inner.pack(fill="x", padx=14, pady=8)

        self._make_button(
            inner, "刷新", self.refresh_data, COLOR_PRIMARY, small=True
        ).pack(side="left", padx=(0, 8))
        self._make_button(
            inner, "导出", self.export_records, COLOR_SUCCESS, small=True
        ).pack(side="left", padx=(0, 8))
        self._make_button(
            inner, "清空", self.clear_records, COLOR_DANGER, small=True
        ).pack(side="left")

        self.history_count_label = tk.Label(
            inner,
            text="0 条",
            bg=COLOR_PRIMARY_SOFT,
            fg=COLOR_PRIMARY_DARK,
            font=ui_font(9, "bold"),
            padx=10,
            pady=4,
        )
        self.history_count_label.pack(side="right")

        history_status_combo = ttk.Combobox(
            inner,
            textvariable=self._history_status_var,
            values=list(HISTORY_STATUS_FILTERS),
            state="readonly",
            width=7,
            font=ui_font(10),
            style="Modern.TCombobox",
        )
        history_status_combo.pack(side="right", padx=(8, 8), ipady=1)
        history_status_combo.bind("<<ComboboxSelected>>", self._on_history_filter_change)

        history_search_entry = tk.Entry(
            inner,
            textvariable=self._history_search_var,
            font=ui_font(10),
            width=18,
            bg=COLOR_INPUT_BG,
            fg=COLOR_TEXT,
            insertbackground=COLOR_TEXT,
            relief="flat",
            highlightbackground=COLOR_BORDER,
            highlightcolor=COLOR_PRIMARY,
            highlightthickness=1,
        )
        history_search_entry.pack(side="right", padx=(8, 0), ipady=6)
        history_search_entry.bind("<KeyRelease>", self._on_history_filter_change)
        tk.Label(
            inner,
            text="搜索",
            bg=COLOR_CARD_BG,
            fg=COLOR_TEXT_MUTED,
            font=ui_font(9),
        ).pack(side="right", padx=(8, 0))

        table_frame = tk.Frame(
            parent,
            bg=COLOR_CARD_BG,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
        )
        table_frame.pack(fill="both", expand=True)
        container = tk.Frame(table_frame, bg=COLOR_CARD_BG)
        container.pack(fill="both", expand=True, padx=1, pady=1)

        self.history_tree = ttk.Treeview(
            container,
            columns=HISTORY_COLUMNS,
            show="headings",
            style="Modern.Treeview",
            selectmode="browse",
            height=4,
        )
        widths = {
            "time": (145, 120),
            "title": (255, 180),
            "artist": (180, 130),
            "player": (85, 70),
            "status": (95, 80),
        }
        for column in HISTORY_COLUMNS:
            width, minwidth = widths[column]
            self.history_tree.heading(column, text=HISTORY_HEADINGS[column])
            self.history_tree.column(
                column,
                width=width,
                minwidth=minwidth,
                anchor="center" if column in ("time", "player", "status") else "w",
            )

        self.history_tree.tag_configure(
            "in_library",
            background=COLOR_ROW_IN_LIBRARY_BG,
            foreground=COLOR_ROW_IN_LIBRARY_FG,
        )
        self.history_tree.tag_configure(
            "not_in_library",
            background=COLOR_ROW_MISSING_BG,
            foreground=COLOR_ROW_MISSING_FG,
        )
        self.history_tree.tag_configure(
            "unknown",
            background=COLOR_ROW_UNKNOWN_BG,
            foreground=COLOR_ROW_UNKNOWN_FG,
        )

        scrollbar = ttk.Scrollbar(
            container,
            orient="vertical",
            command=self.history_tree.yview,
            style="Modern.Vertical.TScrollbar",
        )
        self.history_tree.configure(yscrollcommand=scrollbar.set)
        self.history_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.history_tree.bind("<Double-1>", self._on_history_double_click)

    def _create_footer(self, parent: tk.Misc) -> None:
        footer = tk.Frame(parent, bg=COLOR_WINDOW_BG)
        footer.pack(fill="x", pady=(10, 0))

        tk.Frame(footer, bg=COLOR_BORDER, height=1).pack(fill="x", pady=(0, 8))

        row = tk.Frame(footer, bg=COLOR_WINDOW_BG)
        row.pack(fill="x")

        left = tk.Frame(row, bg=COLOR_WINDOW_BG)
        left.pack(side="left", fill="x", expand=True)
        self.server_status_label = tk.Label(
            left,
            text="服务器：未配置",
            bg=COLOR_WINDOW_BG,
            fg=COLOR_TEXT_MUTED,
            font=ui_font(9),
        )
        self.server_status_label.pack(side="left")
        self.last_query_label = tk.Label(
            left,
            text="最后查询：—",
            bg=COLOR_WINDOW_BG,
            fg=COLOR_TEXT_MUTED,
            font=ui_font(9),
        )
        self.last_query_label.pack(side="left", padx=(14, 0))
        tk.Label(
            left,
            textvariable=self._footer_message_var,
            bg=COLOR_WINDOW_BG,
            fg=COLOR_PRIMARY,
            font=ui_font(9, "bold"),
        ).pack(side="left", padx=(14, 0))

        right = tk.Frame(row, bg=COLOR_WINDOW_BG)
        right.pack(side="right")
        self._make_button(
            right,
            "设置",
            self.show_settings,
            COLOR_CARD_BG,
            small=True,
            foreground=COLOR_TEXT,
            hover_color=COLOR_BORDER,
        ).pack(side="left", padx=(0, 8))
        self._make_button(
            right,
            "最小化",
            self.hide_window,
            COLOR_CARD_BG,
            small=True,
            foreground=COLOR_TEXT,
            hover_color=COLOR_BORDER,
        ).pack(side="left")

    def _make_button(
        self,
        parent: tk.Misc,
        text: str,
        command,
        color: str,
        small: bool = False,
        foreground: str = "white",
        hover_color: Optional[str] = None,
    ) -> tk.Button:
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg=color,
            fg=foreground,
            activebackground=hover_color or darken_color(color),
            activeforeground=foreground,
            relief="flat",
            font=ui_font(9 if small else 10, "bold"),
            padx=12 if small else 17,
            pady=6 if small else 9,
            cursor="hand2",
            bd=0,
            highlightthickness=0,
        )
        hover = hover_color or darken_color(color)
        button.bind("<Enter>", lambda _e: button.configure(bg=hover))
        button.bind("<Leave>", lambda _e: button.configure(bg=color))
        return button

    @staticmethod
    def _bind_click(widget: tk.Misc, command) -> None:
        try:
            widget.configure(cursor="hand2")
        except tk.TclError:
            pass
        widget.bind("<Button-1>", lambda _e: command())
        for child in widget.winfo_children():
            MainWindow._bind_click(child, command)

    def _clipboard_text(root: tk.Misc, text: str) -> None:
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update_idletasks()

    def _set_message(self, message: str) -> None:
        self._footer_message_var.set(message)

    def set_message(self, message: str) -> None:
        """供托盘层在批量核验结束后写入底部状态栏。"""
        self._footer_message_var.set(message)

    # ---------- 刷新 ----------

    def start_auto_refresh(self) -> None:
        if self._refresh_job is not None:
            return
        if self.window is None or not self.window.winfo_exists() or self.is_closing:
            return
        self._refresh_job = self.window.after(
            UI_REFRESH_INTERVAL_MS, self._auto_refresh_tick
        )

    def _auto_refresh_tick(self) -> None:
        self._refresh_job = None
        if self.is_closing:
            return
        self.refresh_data()
        self.start_auto_refresh()

    def _cancel_refresh_job(self) -> None:
        if self._refresh_job is None:
            return
        try:
            if self.window is not None and self.window.winfo_exists():
                self.window.after_cancel(self._refresh_job)
        except tk.TclError:
            pass
        finally:
            self._refresh_job = None

    def refresh_data(self) -> None:
        """刷新表格、统计、当前播放与底部状态。"""
        if self.window is None or not self.window.winfo_exists() or self.is_closing:
            return

        try:
            records: List[PlayRecord] = list(reversed(self.monitor.play_history))
            self._update_stats(records)
            self._update_current()
            self._refresh_missing()
            self._refresh_history(records)
            self._update_footer(records)
        except Exception:
            logger.exception("刷新界面数据失败")

    def _update_stats(self, records: List[PlayRecord]) -> None:
        total = len(records)
        in_library = sum(1 for record in records if record.in_library is True)
        pending = self.missing_repo.count_pending()

        self.stats_labels["total"].config(text=str(total))
        self.stats_labels["in_library"].config(text=str(in_library))
        self.stats_labels["missing"].config(text=str(pending))
        self.stats_labels["qq"].config(
            text=str(sum(1 for record in records if record.player == "qq"))
        )
        self.stats_labels["netease"].config(
            text=str(sum(1 for record in records if record.player == "netease"))
        )

        if pending:
            self.pending_badge.config(
                text=f"待补 {pending}",
                bg=COLOR_HEADER_BADGE_BG,
                fg=COLOR_HEADER_BADGE_FG,
            )
        else:
            self.pending_badge.config(
                text="待补 0",
                bg=COLOR_HEADER_PILL_BG,
                fg=COLOR_HEADER_MUTED,
            )

    def _update_current(self) -> None:
        song = self.monitor.current_song
        self._current_song = song

        if song is None:
            self.current_song_label.config(text="暂无播放", fg=COLOR_HERO_TEXT)
            self.current_meta_label.config(
                text="等待播放器开始播放", fg=COLOR_HERO_MUTED
            )
            self._set_current_status(
                "—", COLOR_STATUS_UNKNOWN_BG, COLOR_STATUS_UNKNOWN_FG
            )
            self.current_copy_btn.config(state="disabled")
            self.current_recheck_btn.pack_forget()
            return

        self.current_song_label.config(text=song.title, fg=COLOR_HERO_TEXT)
        self.current_meta_label.config(
            text=f"{song.artist} · {song.player_name}",
            fg=COLOR_HERO_MUTED,
        )
        self.current_copy_btn.config(state="normal")

        record = self.monitor.current_record
        entry = self.missing_repo.get(make_song_key(song.artist, song.title))
        can_recheck = (
            record is not None
            and record.in_library is False
            and entry is not None
            and entry.is_pending
        )
        if can_recheck:
            if not self.current_recheck_btn.winfo_manager():
                self.current_recheck_btn.pack(side="right", padx=(8, 0))
        else:
            self.current_recheck_btn.pack_forget()

        if record is None:
            if self.monitor.subsonic is None:
                self._set_current_status(
                    "未配置服务器",
                    COLOR_STATUS_UNKNOWN_BG,
                    COLOR_STATUS_UNKNOWN_FG,
                )
            else:
                self._set_current_status(
                    "查询中…",
                    COLOR_STATUS_PENDING_BG,
                    COLOR_STATUS_PENDING_FG,
                )
        elif record.in_library is True:
            self._set_current_status(
                "✓ 在库",
                COLOR_STATUS_OK_BG,
                COLOR_STATUS_OK_FG,
            )
        elif record.in_library is False:
            self._set_current_status(
                "✕ 不在库",
                COLOR_STATUS_MISSING_BG,
                COLOR_STATUS_MISSING_FG,
            )
        else:
            self._set_current_status(
                "未知",
                COLOR_STATUS_UNKNOWN_BG,
                COLOR_STATUS_UNKNOWN_FG,
            )

    def _set_current_status(self, text: str, background: str, foreground: str) -> None:
        self.current_status_label.config(text=text, bg=background, fg=foreground)

    def _filtered_missing(self) -> List[MissingSong]:
        query = self._missing_search_var.get().strip().lower()
        status = MISSING_STATUS_FILTERS.get(self._missing_status_var.get(), None)
        entries: List[MissingSong] = []

        for entry in self.missing_repo.snapshot():
            if status is not None and entry.status != status:
                continue
            haystack = f"{entry.title} {entry.artist} {entry.player_name}".lower()
            if query and query not in haystack:
                continue
            entries.append(entry)

        return self._sort_missing_entries(entries)

    def _sort_missing_entries(self, entries: List[MissingSong]) -> List[MissingSong]:
        column = self._missing_sort_column
        reverse = self._missing_sort_reverse

        def key_func(entry: MissingSong):
            if column == "count":
                return entry.play_count
            if column == "player":
                return entry.player_name.lower()
            if column == "status":
                return entry.status_text
            if column == "last_seen":
                return entry.last_seen
            if column == "artist":
                return entry.artist.lower()
            if column == "title":
                return entry.title.lower()
            return entry.first_seen

        return sorted(entries, key=key_func, reverse=reverse)

    def _refresh_missing(self, force: bool = False) -> None:
        entries = self._filtered_missing()
        signature = tuple(
            (
                entry.key,
                entry.status,
                entry.title,
                entry.artist,
                entry.player,
                entry.first_seen,
                entry.last_seen,
                entry.play_count,
            )
            for entry in entries
        )
        self.missing_count_label.config(text=f"{len(entries)} 首")

        if not force and signature == self._missing_signature:
            return

        top_fraction = self.missing_tree.yview()[0]
        for item in self.missing_tree.get_children():
            self.missing_tree.delete(item)

        for entry in entries:
            tag = "pending" if entry.is_pending else "ignored"
            self.missing_tree.insert(
                "",
                "end",
                iid=entry.key,
                values=(
                    entry.title,
                    entry.artist,
                    entry.player_short_name,
                    entry.first_seen,
                    entry.last_seen,
                    entry.play_count,
                    entry.status_text,
                ),
                tags=(tag,),
            )

        self._missing_signature = signature
        self._update_missing_headings()
        if top_fraction > 0:
            self.missing_tree.yview_moveto(top_fraction)

    def _filtered_history(self, records: List[PlayRecord]) -> List[PlayRecord]:
        query = self._history_search_var.get().strip().lower()
        status = HISTORY_STATUS_FILTERS.get(self._history_status_var.get(), "all")
        filtered: List[PlayRecord] = []

        for record in records:
            if status is True and record.in_library is not True:
                continue
            if status is False and record.in_library is not False:
                continue
            if status == "unknown" and record.in_library is not None:
                continue

            haystack = (
                f"{record.title} {record.artist} "
                f"{record.player_name} {record.status_text}"
            ).lower()
            if query and query not in haystack:
                continue
            filtered.append(record)

        return filtered

    def _refresh_history(self, records: List[PlayRecord]) -> None:
        filtered = self._filtered_history(records)
        self.history_count_label.config(text=f"{len(filtered)} 条")
        signature = tuple(
            (
                record.timestamp,
                record.title,
                record.artist,
                record.player,
                record.status_key,
            )
            for record in filtered
        )
        if signature == self._history_signature:
            return

        top_fraction = self.history_tree.yview()[0]
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)

        for record in filtered:
            self.history_tree.insert(
                "",
                "end",
                values=(
                    record.timestamp,
                    record.title,
                    record.artist,
                    record.player_short_name,
                    record.status_text,
                ),
                tags=(record.status_key,),
            )

        self._history_signature = signature
        if top_fraction > 0:
            self.history_tree.yview_moveto(top_fraction)

    def _update_footer(self, records: List[PlayRecord]) -> None:
        if self.monitor.subsonic is None:
            self.server_status_label.config(text="服务器：未配置", fg=COLOR_DANGER)
        else:
            self.server_status_label.config(text="服务器：已配置", fg=COLOR_SUCCESS)

        if records:
            self.last_query_label.config(text=f"最后查询：{records[0].timestamp}")
        else:
            self.last_query_label.config(text="最后查询：—")

        if self.monitor.running:
            self.status_label.config(
                text="● 监控中", fg=COLOR_HEADER_STATUS_OK
            )
        else:
            self.status_label.config(
                text="● 已停止", fg=COLOR_HEADER_STATUS_OFF
            )

    # ---------- 待补清单操作 ----------

    def _on_missing_filter_change(self, _event=None) -> None:
        self._refresh_missing(force=True)

    def _on_history_filter_change(self, _event=None) -> None:
        self._history_signature = None
        self.refresh_data()

    def _sort_missing(self, column: str) -> None:
        if column == self._missing_sort_column:
            self._missing_sort_reverse = not self._missing_sort_reverse
        else:
            self._missing_sort_column = column
            self._missing_sort_reverse = column in ("first_seen", "last_seen", "count")
        self._refresh_missing(force=True)

    def _update_missing_headings(self) -> None:
        for column in MISSING_COLUMNS:
            text = MISSING_HEADINGS[column]
            if column == self._missing_sort_column:
                text += " ▼" if self._missing_sort_reverse else " ▲"
            self.missing_tree.heading(column, text=text)

    def _selected_missing(self) -> List[MissingSong]:
        entries = []
        for item in self.missing_tree.selection():
            entry = self.missing_repo.get(item)
            if entry is not None:
                entries.append(entry)
        return entries

    def _copy_missing(self, entries: List[MissingSong], label: str) -> None:
        if not entries:
            self._set_message("没有可复制的歌曲")
            return
        text = "\n".join(entry.copy_text for entry in entries)
        try:
            self._clipboard_text(self.window, text)
        except tk.TclError:
            logger.exception("复制待补清单失败")
            self._set_message("复制失败")
            return
        self._set_message(f"已复制{label} {len(entries)} 首")

    def copy_selected_missing(self) -> None:
        self._copy_missing(self._selected_missing(), "选中")

    def copy_all_missing(self) -> None:
        self._copy_missing(self._filtered_missing(), "列表")

    def ignore_missing(self) -> None:
        entries = self._selected_missing()
        if not entries:
            self._set_message("请先选择歌曲")
            return
        for entry in entries:
            self.missing_repo.set_status(entry.key, MISSING_STATUS_IGNORED)
        self._set_message(f"已忽略 {len(entries)} 首")
        self._refresh_missing(force=True)

    def restore_missing(self) -> None:
        entries = self._selected_missing()
        if not entries:
            self._set_message("请先选择歌曲")
            return
        for entry in entries:
            self.missing_repo.set_status(entry.key, MISSING_STATUS_PENDING)
        self._set_message(f"已恢复 {len(entries)} 首")
        self._refresh_missing(force=True)

    def delete_missing(self) -> None:
        entries = self._selected_missing()
        if not entries:
            self._set_message("请先选择歌曲")
            return
        if not messagebox.askyesno(
            "确认", f"从待补清单删除 {len(entries)} 首歌曲？", parent=self.window
        ):
            return
        for entry in entries:
            self.missing_repo.remove_key(entry.key)
        self._set_message(f"已删除 {len(entries)} 首")
        self._refresh_missing(force=True)

    def _confirm_batch_recheck(self, count: int) -> bool:
        if count <= 20:
            return True
        return messagebox.askyesno(
            "确认",
            f"将对 {count} 首歌曲逐首核验，可能耗时较长，是否继续？",
            parent=self.window,
        )

    def recheck_selected(self) -> None:
        entries = self._selected_missing()
        if not entries:
            self._set_message("请先选择歌曲")
            return
        if not self._confirm_batch_recheck(len(entries)):
            return
        self.app.request_recheck(entries, quiet=len(entries) > 1)
        if len(entries) == 1:
            self._set_message(f"正在核验：{entries[0].title}")
        else:
            self._set_message(f"正在核验选中 {len(entries)} 首…")

    def recheck_all_missing(self) -> None:
        entries = [
            entry
            for entry in self.missing_repo.snapshot()
            if entry.is_pending
        ]
        if not entries:
            self._set_message("待补清单为空")
            return
        if not self._confirm_batch_recheck(len(entries)):
            return
        self.app.request_recheck(entries, quiet=True)
        self._set_message(f"正在核验全部待补 {len(entries)} 首…")

    def recheck_current(self) -> None:
        song = self._current_song
        if song is None:
            self._set_message("当前没有播放歌曲")
            return
        entry = self.missing_repo.get(make_song_key(song.artist, song.title))
        if entry is None:
            self._set_message("当前歌曲不在待补清单")
            return
        self.app.request_recheck([entry])
        self._set_message("正在核验当前待补歌曲…")

    def _search_selected(self, platform: str) -> None:
        entries = self._selected_missing()
        if not entries:
            self._set_message("请先选择歌曲")
            return
        entry = entries[0]
        query = quote(entry.search_query)
        if platform == "qq":
            url = f"https://y.qq.com/n/ryqq/search?w={query}"
            name = "QQ 音乐"
        else:
            url = f"https://music.163.com/#/search/m/?s={query}&type=1"
            name = "网易云音乐"
        webbrowser.open(url)
        self._set_message(f"已在浏览器打开{name}搜索")

    def _on_missing_double_click(self, _event=None) -> None:
        self.copy_selected_missing()

    def _on_missing_context_menu(self, event) -> None:
        item = self.missing_tree.identify_row(event.y)
        if not item:
            return
        if item not in self.missing_tree.selection():
            self.missing_tree.selection_set(item)
        try:
            self.missing_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.missing_menu.grab_release()

    def _show_pending_filter(self) -> None:
        self.notebook.select(0)
        self._missing_status_var.set("待补")
        self._missing_search_var.set("")
        self._refresh_missing(force=True)

    def _show_history_filter(
        self,
        status: Optional[bool],
        search: str = "",
    ) -> None:
        self.notebook.select(1)
        for label, value in HISTORY_STATUS_FILTERS.items():
            if value is status or (status is None and value == "all"):
                self._history_status_var.set(label)
                break
        self._history_search_var.set(search)
        self._history_signature = None
        self.refresh_data()

    def _show_all_history(self) -> None:
        self._show_history_filter(None)

    def _show_in_library_history(self) -> None:
        self._show_history_filter(True)

    def export_missing(self) -> None:
        entries = self._filtered_missing()
        if not entries:
            self._set_message("没有可导出的歌曲")
            return

        filename = filedialog.asksaveasfilename(
            parent=self.window,
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv"), ("文本文件", "*.txt"), ("所有文件", "*.*")],
            initialfile=f"待补歌曲_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        )
        if not filename:
            return

        try:
            if filename.lower().endswith(".txt"):
                with open(filename, "w", encoding="utf-8") as fp:
                    fp.write("\n".join(entry.copy_text for entry in entries))
            else:
                with open(filename, "w", encoding="utf-8-sig", newline="") as fp:
                    writer = csv.DictWriter(fp, fieldnames=MISSING_EXPORT_HEADERS)
                    writer.writeheader()
                    for entry in entries:
                        writer.writerow(entry.csv_row())
        except OSError as exc:
            logger.exception("导出待补清单失败: %s", exc)
            messagebox.showerror("错误", f"导出失败: {exc}", parent=self.window)
            return

        self._set_message(f"已导出 {len(entries)} 首")
        messagebox.showinfo("成功", f"已导出到:\n{filename}", parent=self.window)

    # ---------- 播放记录操作 ----------

    def _on_history_double_click(self, _event=None) -> None:
        selection = self.history_tree.selection()
        if not selection:
            return
        values = self.history_tree.item(selection[0], "values")
        if len(values) >= 3:
            try:
                self._clipboard_text(self.window, f"{values[1]} - {values[2]}")
            except tk.TclError:
                return
            self._set_message("已复制歌曲信息")

    def export_records(self) -> None:
        """导出播放记录为 CSV（utf-8-sig，Excel 可直接打开）。"""
        if self.window is None:
            return

        records = self.monitor.play_history
        if not records:
            messagebox.showinfo("提示", "没有记录可以导出", parent=self.window)
            return

        filename = filedialog.asksaveasfilename(
            parent=self.window,
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")],
            initialfile=f"音乐播放记录_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        )
        if not filename:
            return

        try:
            with open(filename, "w", encoding="utf-8-sig", newline="") as fp:
                writer = csv.DictWriter(fp, fieldnames=CSV_HEADERS)
                writer.writeheader()
                for record in records:
                    writer.writerow(record.csv_row())
        except OSError as exc:
            logger.exception("导出 CSV 失败: %s", exc)
            messagebox.showerror("错误", f"导出失败: {exc}", parent=self.window)
            return

        messagebox.showinfo("成功", f"记录已导出到:\n{filename}", parent=self.window)

    def clear_records(self) -> None:
        """清空播放历史。"""
        if self.window is None:
            return
        if not messagebox.askyesno(
            "确认", "确定要清空本次运行的所有播放记录吗？\n待补清单不会受到影响。", parent=self.window
        ):
            return

        self.monitor.clear_history()
        self._history_signature = None
        self.refresh_data()
        messagebox.showinfo("完成", "播放记录已清空", parent=self.window)

    # ---------- 其他 ----------

    def copy_current(self) -> None:
        song = self._current_song
        if song is None:
            self._set_message("当前没有播放歌曲")
            return
        try:
            self._clipboard_text(self.window, f"{song.title} - {song.artist}")
        except tk.TclError:
            self._set_message("复制失败")
            return
        self._set_message("已复制当前歌曲")

    def show_settings(self) -> None:
        """打开设置窗口。"""
        if self.window is None:
            return
        if self.settings_window is None:
            self.settings_window = SettingsWindow(
                self.window,
                self.app.config_manager,
                self.app.on_config_changed,
            )
        self.settings_window.show()
