# -*- coding: utf-8 -*-
"""设置窗口：Subsonic 连接与提醒策略。

模态对话框，校验规则：
1. 三项服务器信息必填；
2. 地址必须以 http:// 或 https:// 开头；
3. 自动补齐末尾斜杠（Subsonic 的 ``/rest/...`` 拼接要求）；
4. 提醒冷却时间为 0~1440 分钟的整数。
"""

import logging
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Optional, Tuple

from app.config_manager import ConfigManager
from app.constants import (
    DEFAULT_REMINDER_MODE,
    REMINDER_MODE_LABELS,
    SUBSONIC_PLACEHOLDER_SERVER,
)
from app.services.subsonic import SubsonicClient, normalize_server_url
from app.ui.icons import load_window_icon
from app.ui.theme import (
    COLOR_BORDER,
    COLOR_CARD_BG,
    COLOR_DANGER,
    COLOR_HEADER_BG,
    COLOR_HEADER_MUTED,
    COLOR_HEADER_TEXT,
    COLOR_INPUT_BG,
    COLOR_PRIMARY,
    COLOR_PRIMARY_DARK,
    COLOR_PRIMARY_SOFT,
    COLOR_SUCCESS,
    COLOR_TEXT,
    COLOR_TEXT_MUTED,
    COLOR_WINDOW_BG,
    apply_modern_style,
    darken_color,
    ui_font,
)

logger = logging.getLogger(__name__)


class SettingsWindow:
    """服务器配置对话框。"""

    def __init__(
        self,
        parent: tk.Misc,
        config_manager: ConfigManager,
        on_saved: Optional[Callable[[], None]] = None,
    ) -> None:
        self.parent = parent
        self.config_manager = config_manager
        self.on_saved = on_saved
        self.window: Optional[tk.Toplevel] = None
        self._icon_photo = None
        self._test_queue: "queue.Queue[Tuple[bool, str]]" = queue.Queue()
        self._test_job: Optional[str] = None
        self._testing = False

    def show(self) -> None:
        """显示窗口；已存在时聚焦。"""
        if self.window is not None and self.window.winfo_exists():
            self.window.lift()
            self.window.focus_force()
            return

        window = tk.Toplevel(self.parent)
        self.window = window
        window.title("设置")
        window.configure(bg=COLOR_WINDOW_BG)
        window.resizable(False, False)
        window.transient(self.parent)
        window.grab_set()
        window.protocol("WM_DELETE_WINDOW", self.close)
        apply_modern_style(window)

        self._icon_photo = load_window_icon(window)
        self._create_widgets()
        self._center_window()

    def _center_window(self) -> None:
        """按实际内容尺寸居中（在控件创建后调用）。"""
        if self.window is None:
            return
        self.window.update_idletasks()
        width = self.window.winfo_reqwidth()
        height = self.window.winfo_reqheight()
        x = (self.window.winfo_screenwidth() - width) // 2
        y = (self.window.winfo_screenheight() - height) // 2
        self.window.geometry(f"{width}x{height}+{x}+{y}")

    def _create_widgets(self) -> None:
        """创建表单控件。"""
        assert self.window is not None

        header = tk.Frame(self.window, bg=COLOR_HEADER_BG)
        header.pack(fill="x")
        header_inner = tk.Frame(header, bg=COLOR_HEADER_BG)
        header_inner.pack(fill="x", padx=26, pady=14)

        tk.Label(
            header_inner,
            text="设置",
            bg=COLOR_HEADER_BG,
            fg=COLOR_HEADER_TEXT,
            font=ui_font(18, "bold"),
        ).pack(anchor="w")
        tk.Label(
            header_inner,
            text="连接曲库服务器，调整提醒策略",
            bg=COLOR_HEADER_BG,
            fg=COLOR_HEADER_MUTED,
            font=ui_font(9),
        ).pack(anchor="w", pady=(3, 0))

        main_frame = tk.Frame(self.window, bg=COLOR_WINDOW_BG)
        main_frame.pack(fill="both", expand=True, padx=24, pady=16)

        config = self.config_manager.get_subsonic_config()

        server_section = self._create_section(
            main_frame,
            "服务器配置",
            "Subsonic / Navidrome 连接信息",
        )
        self.server_entry = self._add_entry(
            server_section, "服务器地址", config["server_url"]
        )

        account_row = tk.Frame(server_section, bg=COLOR_CARD_BG)
        account_row.pack(fill="x")
        username_column = tk.Frame(account_row, bg=COLOR_CARD_BG)
        username_column.pack(side="left", fill="x", expand=True, padx=(0, 10))
        password_column = tk.Frame(account_row, bg=COLOR_CARD_BG)
        password_column.pack(side="left", fill="x", expand=True)

        self.username_entry = self._add_entry(
            username_column, "用户名", config["username"], width=26
        )
        self.password_entry = self._add_entry(
            password_column, "密码", config["password"], show="*", width=26
        )
        self.username_entry.pack_configure(pady=(0, 0))
        self.password_entry.pack_configure(pady=(0, 0))

        self.verify_ssl_var = tk.BooleanVar(value=config.get("verify_ssl", "1") != "0")
        tk.Checkbutton(
            server_section,
            text="验证 HTTPS 证书（自签名服务器可关闭，不推荐）",
            variable=self.verify_ssl_var,
            bg=COLOR_CARD_BG,
            fg=COLOR_TEXT_MUTED,
            activebackground=COLOR_CARD_BG,
            activeforeground=COLOR_TEXT,
            selectcolor=COLOR_CARD_BG,
            font=ui_font(9),
            anchor="w",
        ).pack(fill="x", pady=(0, 2))

        self._create_reminder_section(main_frame)

        tip = tk.Frame(main_frame, bg=COLOR_PRIMARY_SOFT)
        tip.pack(fill="x", pady=(0, 14))
        tk.Label(
            tip,
            text=(
                "使用提示\n"
                f"服务器地址示例：{SUBSONIC_PLACEHOLDER_SERVER}:port/\n"
                "填写服务器根地址即可，程序会自动处理末尾斜杠和 /rest 路径。\n"
                "保存前可先点“测试连接”检查地址、账号和证书设置。"
            ),
            bg=COLOR_PRIMARY_SOFT,
            fg=COLOR_PRIMARY_DARK,
            font=ui_font(9),
            justify="left",
        ).pack(anchor="w", padx=16, pady=12)

        self.test_status_label = tk.Label(
            main_frame,
            text="",
            bg=COLOR_WINDOW_BG,
            fg=COLOR_TEXT_MUTED,
            font=ui_font(9),
            anchor="w",
            justify="left",
            wraplength=460,
        )
        self.test_status_label.pack(fill="x", pady=(0, 8))

        button_frame = tk.Frame(main_frame, bg=COLOR_WINDOW_BG)
        button_frame.pack(fill="x")

        self.test_button = self._make_button(
            button_frame,
            "测试连接",
            self._test_connection,
            COLOR_CARD_BG,
            foreground=COLOR_TEXT,
            hover_color=COLOR_BORDER,
            bordered=True,
        )
        self.test_button.pack(side="left")

        self._make_button(
            button_frame,
            "保存设置",
            self._save,
            COLOR_SUCCESS,
        ).pack(side="right")
        self._make_button(
            button_frame,
            "取消",
            self.close,
            COLOR_CARD_BG,
            foreground=COLOR_TEXT,
            hover_color=COLOR_BORDER,
            bordered=True,
        ).pack(side="right", padx=(0, 10))

    def _create_reminder_section(self, parent: tk.Misc) -> None:
        settings = self.config_manager.get_app_settings()
        frame = self._create_section(
            parent,
            "提醒设置",
            "控制不在库歌曲的通知频率",
        )

        row = tk.Frame(frame, bg=COLOR_CARD_BG)
        row.pack(fill="x")
        mode_column = tk.Frame(row, bg=COLOR_CARD_BG)
        mode_column.pack(side="left", fill="x", expand=True, padx=(0, 10))
        cooldown_column = tk.Frame(row, bg=COLOR_CARD_BG)
        cooldown_column.pack(side="left", fill="x", expand=True)

        tk.Label(
            mode_column,
            text="提醒模式",
            bg=COLOR_CARD_BG,
            fg=COLOR_TEXT,
            font=ui_font(10, "bold"),
        ).pack(anchor="w", pady=(0, 6))

        current_mode = settings["reminder_mode"]
        self.reminder_mode_var = tk.StringVar(
            value=REMINDER_MODE_LABELS.get(
                current_mode, REMINDER_MODE_LABELS[DEFAULT_REMINDER_MODE]
            )
        )
        self.reminder_mode_combo = ttk.Combobox(
            mode_column,
            textvariable=self.reminder_mode_var,
            values=list(REMINDER_MODE_LABELS.values()),
            state="readonly",
            font=ui_font(10),
            style="Modern.TCombobox",
        )
        self.reminder_mode_combo.pack(fill="x", ipady=2)

        tk.Label(
            cooldown_column,
            text="提醒冷却（分钟）",
            bg=COLOR_CARD_BG,
            fg=COLOR_TEXT,
            font=ui_font(10, "bold"),
        ).pack(anchor="w", pady=(0, 6))

        self.cooldown_var = tk.StringVar(
            value=settings["reminder_cooldown_minutes"]
        )
        self.cooldown_spinbox = ttk.Spinbox(
            cooldown_column,
            from_=0,
            to=1440,
            textvariable=self.cooldown_var,
            font=ui_font(10),
            style="Modern.TSpinbox",
        )
        self.cooldown_spinbox.pack(fill="x", ipady=2)

    def _add_entry(
        self,
        parent: tk.Misc,
        label: str,
        value: str,
        show: str = "",
        width: int = 56,
    ) -> tk.Entry:
        """创建“标签 + 输入框”表单项并返回输入框。"""
        tk.Label(
            parent,
            text=label,
            bg=COLOR_CARD_BG,
            fg=COLOR_TEXT,
            font=ui_font(10, "bold"),
        ).pack(anchor="w", pady=(0, 6))

        entry = tk.Entry(
            parent,
            font=ui_font(10),
            width=width,
            bg=COLOR_INPUT_BG,
            fg=COLOR_TEXT,
            insertbackground=COLOR_TEXT,
            relief="flat",
            highlightbackground=COLOR_BORDER,
            highlightcolor=COLOR_PRIMARY,
            highlightthickness=1,
            show=show,
        )
        entry.pack(fill="x", pady=(0, 12), ipady=7)
        entry.insert(0, value)
        return entry

    def _create_section(
        self,
        parent: tk.Misc,
        title: str,
        subtitle: str,
    ) -> tk.Frame:
        """创建带顶部强调条的白色设置卡片。"""
        card = tk.Frame(
            parent,
            bg=COLOR_CARD_BG,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
        )
        card.pack(fill="x", pady=(0, 14))

        tk.Frame(card, bg=COLOR_PRIMARY, height=3).pack(fill="x")

        content = tk.Frame(card, bg=COLOR_CARD_BG)
        content.pack(fill="x", padx=20, pady=14)

        tk.Label(
            content,
            text=title,
            bg=COLOR_CARD_BG,
            fg=COLOR_TEXT,
            font=ui_font(12, "bold"),
        ).pack(anchor="w")
        tk.Label(
            content,
            text=subtitle,
            bg=COLOR_CARD_BG,
            fg=COLOR_TEXT_MUTED,
            font=ui_font(9),
        ).pack(anchor="w", pady=(3, 12))

        return content

    def _make_button(
        self,
        parent: tk.Misc,
        text: str,
        command,
        color: str,
        foreground: str = "white",
        hover_color: Optional[str] = None,
        bordered: bool = False,
    ) -> tk.Button:
        hover = hover_color or darken_color(color)
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg=color,
            fg=foreground,
            activebackground=hover,
            activeforeground=foreground,
            font=ui_font(10, "bold"),
            padx=22,
            pady=9,
            relief="flat",
            bd=0,
            cursor="hand2",
            highlightthickness=1 if bordered else 0,
            highlightbackground=COLOR_BORDER,
        )
        button.bind("<Enter>", lambda _e: button.configure(bg=hover))
        button.bind("<Leave>", lambda _e: button.configure(bg=color))
        return button

    def _read_server_form(self) -> Optional[Tuple[str, str, str, bool]]:
        """读取并校验服务器表单，返回规范化的地址、账号、密码与证书选项。"""
        assert self.window is not None

        server_url = self.server_entry.get().strip()
        username = self.username_entry.get().strip()
        password = self.password_entry.get()

        if not server_url:
            self._show_form_error("请填写服务器地址", self.server_entry)
            return None
        if not username:
            self._show_form_error("请填写用户名", self.username_entry)
            return None
        if not password:
            self._show_form_error("请填写密码", self.password_entry)
            return None

        if not server_url.lower().startswith(("http://", "https://")):
            self._show_form_error(
                "服务器地址必须以 http:// 或 https:// 开头",
                self.server_entry,
            )
            return None

        normalized = normalize_server_url(server_url)
        if not normalized:
            self._show_form_error("服务器地址无效", self.server_entry)
            return None

        return (
            normalized + "/",
            username,
            password,
            bool(self.verify_ssl_var.get()),
        )

    def _set_form_status(self, message: str, color: str = COLOR_TEXT_MUTED) -> None:
        self.test_status_label.config(text=message, fg=color)

    def _show_form_error(self, message: str, widget=None) -> None:
        self._set_form_status(message, COLOR_DANGER)
        if widget is not None:
            widget.focus_set()

    def _test_connection(self) -> None:
        """在后台测试服务器连接，不阻塞设置窗口。"""
        if self._testing:
            return
        data = self._read_server_form()
        if data is None:
            return
        server_url, username, password, verify_ssl = data

        self._testing = True
        self._test_queue = queue.Queue()
        self.test_button.config(state="disabled", text="测试中…")
        self._set_form_status("正在连接服务器…")

        def worker() -> None:
            try:
                client = SubsonicClient(
                    server_url, username, password, verify_ssl=verify_ssl
                )
                info = client.ping()
                name = info.get("type") or "Subsonic"
                version = info.get("server_version") or info.get("api_version")
                message = f"连接成功：{name} {version}".strip()
                self._test_queue.put((True, message))
            except Exception as exc:
                self._test_queue.put((False, f"连接失败：{exc}"))

        threading.Thread(
            target=worker, name="ConnectionTest", daemon=True
        ).start()
        self._poll_test_result()

    def _poll_test_result(self) -> None:
        """主线程轮询连接测试结果。"""
        if self.window is None or not self.window.winfo_exists():
            return
        try:
            ok, message = self._test_queue.get_nowait()
        except queue.Empty:
            self._test_job = self.window.after(100, self._poll_test_result)
            return

        self._test_job = None
        self._testing = False
        self.test_button.config(state="normal", text="测试连接")
        self._set_form_status(message, COLOR_SUCCESS if ok else COLOR_DANGER)

    def _save(self) -> None:
        """校验并保存配置。"""
        assert self.window is not None

        data = self._read_server_form()
        if data is None:
            return
        server_url, username, password, verify_ssl = data

        try:
            cooldown = int(self.cooldown_var.get())
        except (TypeError, ValueError):
            self._show_form_error("提醒冷却时间必须是整数", self.cooldown_spinbox)
            return
        if cooldown < 0 or cooldown > 1440:
            self._show_form_error(
                "提醒冷却时间需在 0~1440 分钟之间", self.cooldown_spinbox
            )
            return

        mode = next(
            (
                key
                for key, label in REMINDER_MODE_LABELS.items()
                if label == self.reminder_mode_var.get()
            ),
            DEFAULT_REMINDER_MODE,
        )

        try:
            self.config_manager.update_app_settings(
                reminder_mode=mode,
                reminder_cooldown_minutes=cooldown,
            )
            self.config_manager.update_subsonic_config(
                server_url, username, password, verify_ssl=verify_ssl
            )
        except OSError as exc:
            logger.exception("保存配置失败: %s", exc)
            messagebox.showerror(
                "保存失败", f"无法写入配置文件：\n{exc}", parent=self.window
            )
            return

        if self.on_saved is not None:
            try:
                self.on_saved()
            except Exception:
                logger.exception("配置变更回调执行失败")

        self.close()

    def close(self) -> None:
        """关闭窗口。"""
        if self.window is None:
            return
        if self._test_job is not None:
            try:
                self.window.after_cancel(self._test_job)
            except tk.TclError:
                pass
            self._test_job = None
        self._testing = False
        try:
            self.window.grab_release()
            self.window.destroy()
        except tk.TclError:
            pass
        finally:
            self.window = None
