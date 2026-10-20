# -*- coding: utf-8 -*-

import unittest

from app.models import SongInfo
from app.utils.clipboard import copy_text


class FakeClipboard:
    def __init__(self):
        self.text = ""
        self.refreshed = 0

    def clipboard_clear(self):
        self.text = ""

    def clipboard_append(self, text):
        self.text += text

    def update_idletasks(self):
        self.refreshed += 1


class TestClipboard(unittest.TestCase):
    def test_copy_text_writes_and_refreshes(self):
        widget = FakeClipboard()

        copy_text(widget, "晴天 - 周杰伦")

        self.assertEqual(widget.text, "晴天 - 周杰伦")
        self.assertEqual(widget.refreshed, 1)


class FakeHistoryTree:
    def __init__(self, values):
        self.values = values

    def selection(self):
        return ("row-1",)

    def item(self, _item, _option):
        return self.values


class TestMainWindowCopy(unittest.TestCase):
    def _window(self):
        try:
            from app.ui.main_window import MainWindow
        except Exception as exc:
            self.skipTest(f"Tk 不可用: {exc}")

        window = MainWindow.__new__(MainWindow)
        window._current_song = SongInfo("晴天", "周杰伦", "qq")
        window.window = FakeClipboard()
        window.messages = []
        window._set_message = window.messages.append
        return window

    def test_copy_current_uses_song_title_only(self):
        window = self._window()

        window.copy_current()

        self.assertEqual(window.window.text, "晴天")
        self.assertEqual(window.messages, ["已复制歌名"])

    def test_copy_current_info_uses_title_and_artist(self):
        window = self._window()

        window.copy_current_info()

        self.assertEqual(window.window.text, "晴天 - 周杰伦")
        self.assertEqual(window.messages, ["已复制歌曲信息"])

    def test_copy_history_title_and_info(self):
        window = self._window()
        window.history_tree = FakeHistoryTree(
            ("2026-10-20 10:00:00", "晴天", "周杰伦", "QQ音乐", "在曲库")
        )

        window.copy_selected_history_title()
        self.assertEqual(window.window.text, "晴天")
        self.assertEqual(window.messages[-1], "已复制歌名")

        window.copy_selected_history_info()
        self.assertEqual(window.window.text, "晴天 - 周杰伦")
        self.assertEqual(window.messages[-1], "已复制歌曲信息")


if __name__ == "__main__":
    unittest.main()
