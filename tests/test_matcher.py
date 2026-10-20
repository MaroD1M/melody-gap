# -*- coding: utf-8 -*-
"""文本标准化与匹配算法测试。"""

import unittest

from app.services.matcher import SongMatcher


class TestNormalizeText(unittest.TestCase):
    def setUp(self):
        self.matcher = SongMatcher()

    def test_lowercase_and_punctuation(self):
        self.assertEqual(self.matcher.normalize_text("Hello, World!"), "hello world")

    def test_removes_english_modifiers(self):
        self.assertEqual(self.matcher.normalize_text("Song (Live Remix)"), "song")
        self.assertEqual(self.matcher.normalize_text("Track [Acoustic]"), "track")

    def test_does_not_break_words_containing_live(self):
        # 回归：旧实现 replace("live", "") 会把 Olive 变成 O
        self.assertEqual(self.matcher.normalize_text("Olive"), "olive")
        self.assertEqual(self.matcher.normalize_text("Deliver"), "deliver")

    def test_chinese_modifiers(self):
        self.assertEqual(self.matcher.normalize_text("晴天（现场版）"), "晴天")
        self.assertEqual(self.matcher.normalize_text("晴天 伴奏"), "晴天")

    def test_fullwidth_normalization(self):
        self.assertEqual(self.matcher.normalize_text("ＡＢＣ　１２３"), "abc 123")

    def test_empty(self):
        self.assertEqual(self.matcher.normalize_text(""), "")


class TestSimilarity(unittest.TestCase):
    def setUp(self):
        self.matcher = SongMatcher()

    def test_identical(self):
        self.assertAlmostEqual(self.matcher.calculate_similarity("abc", "abc"), 1.0)

    def test_empty(self):
        self.assertEqual(self.matcher.calculate_similarity("", "abc"), 0.0)

    def test_substring_boost_requires_min_length(self):
        # 单字符不触发子串加分
        self.assertLess(self.matcher.calculate_similarity("a", "abc"), 0.8)
        # 长度足够的子串至少 0.8
        self.assertGreaterEqual(
            self.matcher.calculate_similarity("love", "love story"), 0.8
        )


class TestFindBestMatch(unittest.TestCase):
    def setUp(self):
        self.matcher = SongMatcher()

    def test_exact_match(self):
        songs = [
            {"id": "1", "title": "晴天", "artist": "周杰伦"},
            {"id": "2", "title": "稻香", "artist": "周杰伦"},
        ]
        result = self.matcher.find_best_match(songs, "周杰伦", "晴天")
        self.assertTrue(result.matched)
        self.assertEqual(result.song["id"], "1")
        self.assertGreaterEqual(result.score, 0.75)

    def test_match_with_version_suffix(self):
        songs = [{"id": "1", "title": "晴天 (Live)", "artist": "周杰伦"}]
        result = self.matcher.find_best_match(songs, "周杰伦", "晴天")
        self.assertTrue(result.matched)

    def test_no_match(self):
        songs = [{"id": "1", "title": "完全不同的歌", "artist": "某歌手"}]
        result = self.matcher.find_best_match(songs, "周杰伦", "晴天")
        self.assertFalse(result.matched)
        self.assertIsNone(result.song)

    def test_empty_candidates(self):
        result = self.matcher.find_best_match([], "周杰伦", "晴天")
        self.assertFalse(result.matched)
        self.assertEqual(result.score, 0.0)

    def test_custom_threshold(self):
        songs = [{"id": "1", "title": "晴天", "artist": "周杰伦"}]
        strict = SongMatcher(threshold=1.01)
        self.assertFalse(strict.find_best_match(songs, "周杰伦", "晴天").matched)


if __name__ == "__main__":
    unittest.main()
