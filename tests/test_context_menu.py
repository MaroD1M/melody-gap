# -*- coding: utf-8 -*-
"""右键菜单文案与状态测试（不创建 Tk 窗口）。"""

import unittest

from app.constants import MISSING_STATUS_IGNORED, MISSING_STATUS_PENDING
from app.models import MissingSong


class FakeRepo:
    def __init__(self, pending_count):
        self.pending_count = pending_count

    def count_pending(self):
        return self.pending_count


class FakeMenu:
    def __init__(self):
        self.entries = {}

    def entryconfigure(self, index, **kwargs):
        self.entries[index] = kwargs


def make_entry(title, status=MISSING_STATUS_PENDING):
    return MissingSong(
        key=title,
        title=title,
        artist="周杰伦",
        player="qq",
        first_seen="2026-10-20 10:00:00",
        last_seen="2026-10-20 10:00:00",
        status=status,
    )


class TestContextMenu(unittest.TestCase):
    def setUp(self):
        try:
            from app.ui.main_window import MainWindow
        except Exception as exc:
            self.skipTest(f"Tk 不可用: {exc}")
        self.window = MainWindow.__new__(MainWindow)
        self.window.missing_menu = FakeMenu()
        self.window.history_menu = FakeMenu()
        self.window.missing_repo = FakeRepo(3)

    def test_missing_menu_uses_counts_and_disables_invalid_actions(self):
        entries = [
            make_entry("晴天"),
            make_entry("夜曲"),
            make_entry("稻香"),
            make_entry("七里香", MISSING_STATUS_IGNORED),
        ]

        self.window._prepare_missing_menu(entries)

        menu = self.window.missing_menu.entries
        self.assertEqual(menu[0]["label"], "复制 4 首歌名")
        self.assertEqual(menu[1]["label"], "复制 4 首歌曲信息")
        self.assertEqual(menu[3]["state"], "disabled")
        self.assertEqual(menu[4]["state"], "disabled")
        self.assertIn("核验选中 4 首", menu[6]["label"])
        self.assertIn("3 首", menu[7]["label"])
        self.assertEqual(menu[9]["label"], "忽略选中 3 首")
        self.assertEqual(menu[10]["label"], "恢复为待补")
        self.assertEqual(menu[12]["label"], "删除选中 4 首")

    def test_history_menu_quotes_selected_song(self):
        self.window._prepare_history_menu(
            ("2026-10-20 10:00:00", "晴天", "周杰伦", "QQ音乐", "在曲库")
        )

        menu = self.window.history_menu.entries
        self.assertIn("《晴天》", menu[0]["label"])
        self.assertIn("《晴天》", menu[1]["label"])
        self.assertIn("《晴天》", menu[3]["label"])
        self.assertIn("《晴天》", menu[4]["label"])


if __name__ == "__main__":
    unittest.main()
