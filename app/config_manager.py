# -*- coding: utf-8 -*-
"""配置文件读写。

配置文件为 INI 格式，默认位于 ``get_app_dir()/config.ini``：

    [SUBSONIC]
    server_url = https://your-server.com:port/
    username = your_username
    password = your_password

    [APP]
    reminder_mode = new_missing
    reminder_cooldown_minutes = 10
    window_geometry = 1080x760+100+100
    window_zoomed = 0
    last_tab = 0
"""

import configparser
import logging
from pathlib import Path
from typing import Dict, Optional

from app.constants import (
    APP_SECTION,
    CONFIG_FILE_NAME,
    DEFAULT_LAST_TAB,
    DEFAULT_REMINDER_COOLDOWN_MINUTES,
    DEFAULT_REMINDER_MODE,
    REMINDER_MODE_LABELS,
    SUBSONIC_PLACEHOLDER_SERVER,
    SUBSONIC_SECTION,
)
from app.paths import get_app_dir

logger = logging.getLogger(__name__)

DEFAULT_CONFIG: Dict[str, str] = {
    "server_url": f"{SUBSONIC_PLACEHOLDER_SERVER}:port/",
    "username": "your_username",
    "password": "your_password",
}

DEFAULT_APP_SETTINGS: Dict[str, str] = {
    "reminder_mode": DEFAULT_REMINDER_MODE,
    "reminder_cooldown_minutes": str(DEFAULT_REMINDER_COOLDOWN_MINUTES),
    "window_geometry": "",
    "window_zoomed": "0",
    "last_tab": str(DEFAULT_LAST_TAB),
}

APP_SETTING_KEYS = tuple(DEFAULT_APP_SETTINGS)


class ConfigManager:
    """读取/保存 Subsonic 连接与应用设置。

    Args:
        config_path: 配置文件路径；默认使用可写数据目录下的 config.ini。
            显式传入路径便于单元测试。

    注意：
        * 使用 ``interpolation=None``，否则密码中的 ``%`` 会被 configparser
          当作插值语法并抛异常。
        * 当前版本仍以明文保存密码。生产环境建议后续接入 Windows 凭据管理器
          或至少做本地加密（已列入技术债）。
    """

    def __init__(self, config_path: Optional[Path] = None) -> None:
        self.config_path = Path(config_path) if config_path else get_app_dir() / CONFIG_FILE_NAME
        self.config = configparser.ConfigParser(interpolation=None)
        self.load()

    # ---------- 读写 ----------

    def load(self) -> None:
        """加载配置；文件不存在时创建默认配置。"""
        if self.config_path.exists():
            try:
                self.config.read(self.config_path, encoding="utf-8")
            except (configparser.Error, OSError) as exc:
                logger.exception("读取配置失败，将使用默认配置: %s", exc)
                self._create_default()
            else:
                if not self.config.has_section(SUBSONIC_SECTION):
                    self.config.add_section(SUBSONIC_SECTION)
                if not self.config.has_section(APP_SECTION):
                    self.config.add_section(APP_SECTION)
        else:
            self._create_default()

    def save(self) -> None:
        """将当前配置写回文件。"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as fp:
            self.config.write(fp)

    def _create_default(self) -> None:
        """写入默认占位配置，方便用户直接编辑。"""
        if not self.config.has_section(SUBSONIC_SECTION):
            self.config.add_section(SUBSONIC_SECTION)
        if not self.config.has_section(APP_SECTION):
            self.config.add_section(APP_SECTION)
        for key, value in DEFAULT_CONFIG.items():
            self.config.set(SUBSONIC_SECTION, key, value)
        for key, value in DEFAULT_APP_SETTINGS.items():
            self.config.set(APP_SECTION, key, value)
        try:
            self.save()
        except OSError as exc:
            logger.error("创建默认配置失败: %s", exc)

    # ---------- Subsonic 配置 ----------

    def get_subsonic_config(self) -> Dict[str, str]:
        """返回 Subsonic 配置字典（缺失字段返回空字符串）。"""
        return {
            "server_url": self.config.get(SUBSONIC_SECTION, "server_url", fallback=""),
            "username": self.config.get(SUBSONIC_SECTION, "username", fallback=""),
            "password": self.config.get(SUBSONIC_SECTION, "password", fallback=""),
        }

    def update_subsonic_config(self, server_url: str, username: str, password: str) -> None:
        """更新并持久化 Subsonic 配置。"""
        if not self.config.has_section(SUBSONIC_SECTION):
            self.config.add_section(SUBSONIC_SECTION)
        self.config.set(SUBSONIC_SECTION, "server_url", server_url)
        self.config.set(SUBSONIC_SECTION, "username", username)
        self.config.set(SUBSONIC_SECTION, "password", password)
        self.save()

    def is_subsonic_configured(self) -> bool:
        """判断配置是否可用（三个字段齐全且不是默认占位地址）。"""
        cfg = self.get_subsonic_config()
        if not all(cfg.values()):
            return False
        return not cfg["server_url"].startswith(SUBSONIC_PLACEHOLDER_SERVER)

    # ---------- 应用设置 ----------

    def get_app_settings(self) -> Dict[str, str]:
        """返回应用设置（缺失项使用默认值，非法值做保守修正）。"""
        settings = dict(DEFAULT_APP_SETTINGS)
        if self.config.has_section(APP_SECTION):
            for key in APP_SETTING_KEYS:
                settings[key] = self.config.get(APP_SECTION, key, fallback=settings[key])

        if settings["reminder_mode"] not in REMINDER_MODE_LABELS:
            settings["reminder_mode"] = DEFAULT_REMINDER_MODE

        try:
            cooldown = int(settings["reminder_cooldown_minutes"])
        except (TypeError, ValueError):
            cooldown = DEFAULT_REMINDER_COOLDOWN_MINUTES
        settings["reminder_cooldown_minutes"] = str(min(1440, max(0, cooldown)))

        try:
            last_tab = int(settings["last_tab"])
        except (TypeError, ValueError):
            last_tab = DEFAULT_LAST_TAB
        settings["last_tab"] = str(max(0, last_tab))

        if settings["window_zoomed"] not in ("0", "1"):
            settings["window_zoomed"] = "0"
        return settings

    def update_app_settings(self, **values: object) -> None:
        """更新并持久化应用设置；未知键会被忽略。"""
        if not self.config.has_section(APP_SECTION):
            self.config.add_section(APP_SECTION)
        for key, value in values.items():
            if key in APP_SETTING_KEYS:
                self.config.set(APP_SECTION, key, str(value))
        self.save()

    def get_reminder_settings(self) -> Dict[str, object]:
        """返回提醒策略及其冷却时间（已转换为正确类型）。"""
        settings = self.get_app_settings()
        return {
            "mode": settings["reminder_mode"],
            "cooldown_minutes": int(settings["reminder_cooldown_minutes"]),
        }
