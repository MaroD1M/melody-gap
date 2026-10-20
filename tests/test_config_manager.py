# -*- coding: utf-8 -*-
"""配置管理测试（使用临时目录，不污染项目配置）。"""

import tempfile
import unittest
from pathlib import Path

from app.config_manager import ConfigManager


class TestConfigManager(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config_path = Path(self._tmp.name) / "config.ini"

    def tearDown(self):
        self._tmp.cleanup()

    def test_creates_default_config(self):
        manager = ConfigManager(self.config_path)
        self.assertTrue(self.config_path.exists())
        self.assertFalse(manager.is_subsonic_configured())

    def test_update_and_reload(self):
        manager = ConfigManager(self.config_path)
        manager.update_subsonic_config(
            "https://music.example.com:4533/", "demo", "secret"
        )

        reloaded = ConfigManager(self.config_path)
        cfg = reloaded.get_subsonic_config()
        self.assertEqual(cfg["server_url"], "https://music.example.com:4533/")
        self.assertEqual(cfg["username"], "demo")
        self.assertEqual(cfg["password"], "secret")
        self.assertEqual(cfg["verify_ssl"], "1")
        self.assertTrue(reloaded.is_subsonic_configured())

    def test_verify_ssl_can_be_disabled(self):
        manager = ConfigManager(self.config_path)
        manager.update_subsonic_config(
            "https://example.com/", "demo", "secret", verify_ssl=False
        )
        reloaded = ConfigManager(self.config_path)
        self.assertEqual(reloaded.get_subsonic_config()["verify_ssl"], "0")

    def test_password_with_percent_sign(self):
        # configparser 默认插值会把 % 当特殊字符，本测试防止回归
        manager = ConfigManager(self.config_path)
        manager.update_subsonic_config("https://example.com/", "user", "p%ss%word")

        reloaded = ConfigManager(self.config_path)
        self.assertEqual(reloaded.get_subsonic_config()["password"], "p%ss%word")

    def test_placeholder_is_not_configured(self):
        manager = ConfigManager(self.config_path)
        manager.update_subsonic_config(
            "https://your-server.com:port/", "your_username", "your_password"
        )
        self.assertFalse(manager.is_subsonic_configured())

    def test_utf8_bom_config_is_read(self):
        self.config_path.write_bytes(
            (
                "\ufeff[SUBSONIC]\n"
                "server_url = https://music.example.com/\n"
                "username = demo\n"
                "password = secret\n"
                "verify_ssl = 1\n"
            ).encode("utf-8")
        )

        manager = ConfigManager(self.config_path)

        self.assertEqual(
            manager.get_subsonic_config()["server_url"],
            "https://music.example.com/",
        )
        self.assertEqual(manager.get_subsonic_config()["username"], "demo")
        self.assertFalse(
            list(self.config_path.parent.glob("config.corrupt_*.ini"))
        )

    def test_corrupt_config_is_backed_up_instead_of_overwritten(self):
        self.config_path.write_text("{not valid ini", encoding="utf-8")

        manager = ConfigManager(self.config_path)

        self.assertTrue(self.config_path.exists())
        self.assertFalse(manager.is_subsonic_configured())
        backups = list(self.config_path.parent.glob("config.corrupt_*.ini"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "{not valid ini")

    def test_missing_file_recreated(self):
        manager = ConfigManager(self.config_path)
        self.config_path.unlink()
        manager.load()
        self.assertTrue(self.config_path.exists())

    def test_default_app_settings(self):
        manager = ConfigManager(self.config_path)
        settings = manager.get_app_settings()
        self.assertEqual(settings["reminder_mode"], "new_missing")
        self.assertEqual(settings["reminder_cooldown_minutes"], "10")
        self.assertEqual(manager.get_reminder_settings()["cooldown_minutes"], 10)

    def test_update_app_settings_persists(self):
        manager = ConfigManager(self.config_path)
        manager.update_app_settings(
            reminder_mode="missing",
            reminder_cooldown_minutes=30,
            last_tab=1,
        )

        reloaded = ConfigManager(self.config_path)
        settings = reloaded.get_app_settings()
        self.assertEqual(settings["reminder_mode"], "missing")
        self.assertEqual(settings["reminder_cooldown_minutes"], "30")
        self.assertEqual(settings["last_tab"], "1")

    def test_invalid_app_settings_fall_back(self):
        manager = ConfigManager(self.config_path)
        manager.update_app_settings(
            reminder_mode="unknown",
            reminder_cooldown_minutes="not-a-number",
        )
        settings = manager.get_app_settings()
        self.assertEqual(settings["reminder_mode"], "new_missing")
        self.assertEqual(settings["reminder_cooldown_minutes"], "10")

    def test_cooldown_is_clamped(self):
        manager = ConfigManager(self.config_path)
        manager.update_app_settings(reminder_cooldown_minutes=9999)
        self.assertEqual(manager.get_app_settings()["reminder_cooldown_minutes"], "1440")
        manager.update_app_settings(reminder_cooldown_minutes=-5)
        self.assertEqual(manager.get_app_settings()["reminder_cooldown_minutes"], "0")


if __name__ == "__main__":
    unittest.main()
