# -*- coding: utf-8 -*-
"""界面主题常量、字体与 ttk 样式。

设计方向：浅色内容区 + 深色顶栏 + 高饱和强调色，尽量减少传统 Tk
默认的灰色凹槽、黑色细边和窄间距。所有颜色集中在这里，方便整体换肤。
"""

from tkinter import ttk
from typing import Tuple

# 品牌 / 强调色
COLOR_PRIMARY = "#5B5BD6"
COLOR_PRIMARY_DARK = "#4646C6"
COLOR_PRIMARY_SOFT = "#EEF0FF"
COLOR_ACCENT = "#06B6D4"
COLOR_ACCENT_SOFT = "#E0F7FA"

# 语义色
COLOR_SUCCESS = "#059669"
COLOR_SUCCESS_DARK = "#047857"
COLOR_SUCCESS_SOFT = "#D1FAE5"
COLOR_DANGER = "#E11D48"
COLOR_DANGER_DARK = "#BE123C"
COLOR_DANGER_SOFT = "#FFE4E6"
COLOR_WARNING = "#D97706"
COLOR_WARNING_DARK = "#B45309"
COLOR_WARNING_SOFT = "#FEF3C7"
COLOR_NEUTRAL = "#475569"
COLOR_NEUTRAL_DARK = "#334155"

# 背景 / 文本 / 边框
COLOR_WINDOW_BG = "#F2F5FC"
COLOR_CARD_BG = "#FFFFFF"
COLOR_CARD_ALT_BG = "#F8FAFC"
COLOR_TEXT = "#0F172A"
COLOR_TEXT_MUTED = "#64748B"
COLOR_BORDER = "#E2E8F0"
COLOR_INPUT_BG = "#FFFFFF"
COLOR_SELECTION_BG = "#E0E7FF"

# 深色顶栏
COLOR_HEADER_BG = "#0B1220"
COLOR_HEADER_PANEL = "#111A2E"
COLOR_HEADER_TEXT = "#F8FAFC"
COLOR_HEADER_MUTED = "#94A3B8"
COLOR_HEADER_PILL_BG = "#17223A"
COLOR_HEADER_STATUS_OK = "#34D399"
COLOR_HEADER_STATUS_OFF = "#FB7185"
COLOR_HEADER_BADGE_BG = "#F59E0B"
COLOR_HEADER_BADGE_FG = "#111827"

# 当前播放主视觉
COLOR_HERO_BG = "#4338CA"
COLOR_HERO_ACCENT = "#6366F1"
COLOR_HERO_TEXT = "#FFFFFF"
COLOR_HERO_MUTED = "#C7D2FE"

# 页签 / 表格
COLOR_TAB_BG = "#E5EAF4"
COLOR_TAB_HOVER = "#D8E0EE"
COLOR_TABLE_HEADER_BG = "#EEF2FF"
COLOR_TABLE_HEADER_FG = "#3730A3"
COLOR_TABLE_HEADER_ACTIVE = "#E0E7FF"
COLOR_SCROLL_THUMB = "#CBD5E1"

# 状态标签
COLOR_STATUS_OK_BG = "#D1FAE5"
COLOR_STATUS_OK_FG = "#047857"
COLOR_STATUS_MISSING_BG = "#FFE4E6"
COLOR_STATUS_MISSING_FG = "#BE123C"
COLOR_STATUS_UNKNOWN_BG = "#E2E8F0"
COLOR_STATUS_UNKNOWN_FG = "#475569"
COLOR_STATUS_PENDING_BG = "#FEF3C7"
COLOR_STATUS_PENDING_FG = "#B45309"

# 统计卡片（浅色底 + 高饱和数字）
COLOR_STAT_TOTAL_BG = "#EEF0FF"
COLOR_STAT_TOTAL_FG = "#4F46E5"
COLOR_STAT_LIBRARY_BG = "#ECFDF5"
COLOR_STAT_LIBRARY_FG = "#059669"
COLOR_STAT_MISSING_BG = "#FFF7ED"
COLOR_STAT_MISSING_FG = "#EA580C"
COLOR_STAT_QQ_BG = "#EFF6FF"
COLOR_STAT_QQ_FG = "#2563EB"
COLOR_STAT_NETEASE_BG = "#FEF2F2"
COLOR_STAT_NETEASE_FG = "#DC2626"

# 表格行状态色
COLOR_ROW_IN_LIBRARY_BG = "#F0FDF4"
COLOR_ROW_IN_LIBRARY_FG = "#047857"
COLOR_ROW_MISSING_BG = "#FFF1F2"
COLOR_ROW_MISSING_FG = "#BE123C"
COLOR_ROW_UNKNOWN_BG = "#F8FAFC"
COLOR_ROW_UNKNOWN_FG = "#64748B"
COLOR_ROW_IGNORED_BG = "#F1F5F9"
COLOR_ROW_IGNORED_FG = "#94A3B8"

# 通知窗口
COLOR_NOTIFICATION_OK = "#059669"
COLOR_NOTIFICATION_MISSING = "#E11D48"
COLOR_NOTIFICATION_UNKNOWN = "#334155"

# 默认字体；Windows 使用微软雅黑 UI，其它平台由 Tk 自动回退
FONT_FAMILY = "Microsoft YaHei UI"


def ui_font(size: int, weight: str = "normal") -> Tuple[str, int, str]:
    """返回 Tkinter 字体元组。"""
    return (FONT_FAMILY, size, weight)


def darken_color(color: str, factor: float = 0.85) -> str:
    """把 ``#RRGGBB`` 颜色按比例变暗（factor < 1）。"""
    value = color.lstrip("#")
    if len(value) != 6:
        return color

    try:
        red = int(value[0:2], 16)
        green = int(value[2:4], 16)
        blue = int(value[4:6], 16)
    except ValueError:
        return color

    red = max(0, min(255, int(red * factor)))
    green = max(0, min(255, int(green * factor)))
    blue = max(0, min(255, int(blue * factor)))
    return f"#{red:02X}{green:02X}{blue:02X}"


def apply_modern_style(root) -> None:
    """应用统一的现代 ttk 外观（幂等，可被多个窗口调用）。"""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure(
        "Modern.TNotebook",
        background=COLOR_WINDOW_BG,
        borderwidth=0,
        tabmargins=(0, 0, 0, 0),
    )
    style.configure(
        "Modern.TNotebook.Tab",
        background=COLOR_TAB_BG,
        foreground=COLOR_TEXT_MUTED,
        lightcolor=COLOR_TAB_BG,
        darkcolor=COLOR_TAB_BG,
        padding=(20, 9),
        borderwidth=0,
        font=ui_font(10, "bold"),
    )
    style.map(
        "Modern.TNotebook.Tab",
        background=[
            ("selected", COLOR_PRIMARY),
            ("active", COLOR_TAB_HOVER),
        ],
        foreground=[
            ("selected", "#FFFFFF"),
            ("active", COLOR_TEXT),
        ],
        lightcolor=[
            ("selected", COLOR_PRIMARY),
            ("active", COLOR_TAB_HOVER),
        ],
        darkcolor=[
            ("selected", COLOR_PRIMARY),
            ("active", COLOR_TAB_HOVER),
        ],
    )

    style.configure(
        "Modern.Treeview",
        background=COLOR_CARD_BG,
        fieldbackground=COLOR_CARD_BG,
        foreground=COLOR_TEXT,
        rowheight=34,
        borderwidth=0,
        relief="flat",
        font=ui_font(10),
    )
    style.configure(
        "Modern.Treeview.Heading",
        background=COLOR_TABLE_HEADER_BG,
        foreground=COLOR_TABLE_HEADER_FG,
        relief="flat",
        borderwidth=0,
        padding=(10, 10),
        font=ui_font(9, "bold"),
    )
    style.map(
        "Modern.Treeview.Heading",
        background=[("active", COLOR_TABLE_HEADER_ACTIVE)],
    )
    style.map(
        "Modern.Treeview",
        background=[("selected", COLOR_SELECTION_BG)],
        foreground=[("selected", COLOR_PRIMARY_DARK)],
    )
    style.layout("Modern.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    style.configure(
        "Modern.TCombobox",
        fieldbackground=COLOR_INPUT_BG,
        background=COLOR_INPUT_BG,
        foreground=COLOR_TEXT,
        bordercolor=COLOR_BORDER,
        lightcolor=COLOR_BORDER,
        darkcolor=COLOR_BORDER,
        arrowcolor=COLOR_TEXT_MUTED,
        padding=(8, 6),
        relief="flat",
    )
    style.map(
        "Modern.TCombobox",
        fieldbackground=[("readonly", COLOR_INPUT_BG)],
        selectbackground=[("readonly", COLOR_INPUT_BG)],
        selectforeground=[("readonly", COLOR_TEXT)],
        bordercolor=[("focus", COLOR_PRIMARY)],
    )

    style.configure(
        "Modern.TSpinbox",
        fieldbackground=COLOR_INPUT_BG,
        background=COLOR_INPUT_BG,
        foreground=COLOR_TEXT,
        bordercolor=COLOR_BORDER,
        lightcolor=COLOR_BORDER,
        darkcolor=COLOR_BORDER,
        arrowcolor=COLOR_TEXT_MUTED,
        padding=(8, 6),
        relief="flat",
    )
    style.map(
        "Modern.TSpinbox",
        fieldbackground=[("readonly", COLOR_INPUT_BG)],
        bordercolor=[("focus", COLOR_PRIMARY)],
    )

    style.configure(
        "Modern.Vertical.TScrollbar",
        gripcount=0,
        background=COLOR_SCROLL_THUMB,
        darkcolor=COLOR_SCROLL_THUMB,
        lightcolor=COLOR_SCROLL_THUMB,
        troughcolor=COLOR_CARD_ALT_BG,
        bordercolor=COLOR_CARD_ALT_BG,
        arrowcolor=COLOR_TEXT_MUTED,
        relief="flat",
    )
    style.map(
        "Modern.Vertical.TScrollbar",
        background=[("active", COLOR_PRIMARY)],
    )

    root.option_add("*TCombobox*Listbox.font", ui_font(10))
    root.option_add("*TCombobox*Listbox.background", COLOR_CARD_BG)
    root.option_add("*TCombobox*Listbox.foreground", COLOR_TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", COLOR_PRIMARY_SOFT)
    root.option_add("*TCombobox*Listbox.selectForeground", COLOR_TEXT)
