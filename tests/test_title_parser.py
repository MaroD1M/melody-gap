# -*- coding: utf-8 -*-
"""窗口标题过滤 / 解析 / 择优测试。"""

import unittest

from app.services.title_parser import (
    is_valid_song_title,
    parse_title,
    select_best_title,
)


class TestIsValidSongTitle(unittest.TestCase):
    def test_accepts_separator_titles(self):
        for title in (
            "晴天 - 周杰伦",
            "晴天 — 周杰伦",
            "晴天 – 周杰伦",
            "晴天 | 周杰伦",
        ):
            with self.subTest(title=title):
                self.assertTrue(is_valid_song_title(title, "netease"))

    def test_accepts_song_containing_function_word(self):
        # 不能因为歌名含“我的”就误杀
        self.assertTrue(is_valid_song_title("我的天空 - 南征北战", "qq"))

    def test_strips_trailing_player_name(self):
        self.assertTrue(
            is_valid_song_title("晴天 - 周杰伦 - 网易云音乐", "netease")
        )
        self.assertTrue(is_valid_song_title("晴天 - 周杰伦 - QQ音乐", "qq"))

    def test_rejects_function_page_segment(self):
        self.assertFalse(is_valid_song_title("设置 - 我的", "qq"))

    def test_rejects_main_window_titles(self):
        for title in ("网易云音乐", "QQ音乐", "我的歌单", "设置", "搜索"):
            with self.subTest(title=title):
                self.assertFalse(is_valid_song_title(title, "netease"))

    def test_rejects_player_specific_keyword(self):
        self.assertFalse(is_valid_song_title("QQ音乐 - 发现", "qq"))
        self.assertFalse(is_valid_song_title("CloudMusic - 首页", "netease"))

    def test_rejects_plain_text_without_separator(self):
        self.assertFalse(is_valid_song_title("晴天", "qq"))
        self.assertFalse(is_valid_song_title("", "qq"))


class TestParseTitle(unittest.TestCase):
    def test_parse_common_title(self):
        song = parse_title("晴天 - 周杰伦", "netease")
        self.assertIsNotNone(song)
        self.assertEqual(song.title, "晴天")
        self.assertEqual(song.artist, "周杰伦")
        self.assertEqual(song.player, "netease")

    def test_parse_all_separators(self):
        for title in (
            "Hello — Adele",
            "Hello – Adele",
            "Hello | Adele",
        ):
            with self.subTest(title=title):
                song = parse_title(title, "qq")
                self.assertIsNotNone(song)
                self.assertEqual(song.title, "Hello")
                self.assertEqual(song.artist, "Adele")

    def test_parse_returns_none_for_invalid(self):
        self.assertIsNone(parse_title("", "qq"))
        self.assertIsNone(parse_title("没有分隔符", "qq"))

    def test_parse_strips_whitespace(self):
        song = parse_title("  晴天  -  周杰伦  ", "qq")
        self.assertIsNotNone(song)
        self.assertEqual(song.title, "晴天")
        self.assertEqual(song.artist, "周杰伦")

    def test_parse_ignores_trailing_player_name(self):
        song = parse_title("晴天 - 周杰伦 - 网易云音乐", "netease")
        self.assertIsNotNone(song)
        self.assertEqual(song.title, "晴天")
        self.assertEqual(song.artist, "周杰伦")


class TestSelectBestTitle(unittest.TestCase):
    def test_empty_and_single(self):
        self.assertIsNone(select_best_title([]))
        self.assertEqual(select_best_title(["A - B"]), "A - B")

    def test_prefers_dash_title(self):
        titles = ["网易云音乐", "晴天 - 周杰伦", "晴天 (Live)"]
        self.assertEqual(select_best_title(titles), "晴天 - 周杰伦")

    def test_penalizes_brackets(self):
        titles = ["Song - Artist", "[歌词] Song - Artist"]
        self.assertEqual(select_best_title(titles), "Song - Artist")


if __name__ == "__main__":
    unittest.main()
