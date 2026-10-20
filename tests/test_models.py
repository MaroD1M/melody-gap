# -*- coding: utf-8 -*-
"""数据模型测试。"""

import unittest

from app.models import MissingSong, PlayRecord, SongInfo


class TestSongInfo(unittest.TestCase):
    def test_display_fields(self):
        song = SongInfo(title="晴天", artist="周杰伦", player="qq")
        self.assertEqual(song.player_name, "QQ音乐")
        self.assertEqual(song.player_short_name, "QQ音乐")
        self.assertEqual(song.display_text, "[QQ音乐] 晴天 - 周杰伦")

    def test_unknown_player_falls_back(self):
        song = SongInfo(title="Song", artist="Artist", player="unknown")
        self.assertEqual(song.player_name, "unknown")


class TestPlayRecord(unittest.TestCase):
    def test_create_with_explicit_timestamp(self):
        song = SongInfo(title="晴天", artist="周杰伦", player="netease")
        record = PlayRecord.create(
            song=song,
            in_library=True,
            full_title="晴天 - 周杰伦",
            timestamp="2026-10-20 12:00:00",
        )
        self.assertEqual(record.timestamp, "2026-10-20 12:00:00")
        self.assertEqual(record.status_text, "在曲库")
        self.assertEqual(record.player_name, "网易云音乐")

    def test_csv_row(self):
        record = PlayRecord(
            timestamp="2026-10-20 12:00:00",
            title="晴天, 现场版",
            artist="周杰伦",
            in_library=False,
            full_title="晴天 - 周杰伦",
            player="qq",
        )
        row = record.csv_row()
        self.assertEqual(row["歌曲名称"], "晴天, 现场版")
        self.assertEqual(row["在曲库中"], "否")

    def test_unknown_status(self):
        record = PlayRecord(
            timestamp="2026-10-20 12:00:00",
            title="晴天",
            artist="周杰伦",
            in_library=None,
            full_title="晴天 - 周杰伦",
            player="qq",
        )
        self.assertTrue(record.is_unknown)
        self.assertEqual(record.status_key, "unknown")
        self.assertEqual(record.status_text, "未知")
        self.assertEqual(record.csv_row()["在曲库中"], "未知")


class TestMissingSong(unittest.TestCase):
    def test_display_and_csv(self):
        entry = MissingSong(
            key="周杰伦|晴天",
            title="晴天",
            artist="周杰伦",
            player="qq",
            first_seen="2026-10-20 12:00:00",
            last_seen="2026-10-20 12:05:00",
            play_count=2,
        )
        self.assertEqual(entry.copy_text, "晴天 - 周杰伦")
        self.assertEqual(entry.search_query, "晴天 周杰伦")
        self.assertEqual(entry.status_text, "待补")
        self.assertEqual(entry.csv_row()["发现次数"], 2)

    def test_round_trip(self):
        entry = MissingSong(
            key="周杰伦|晴天",
            title="晴天",
            artist="周杰伦",
            player="netease",
            first_seen="2026-10-20 12:00:00",
            last_seen="2026-10-20 12:05:00",
            play_count=3,
        )
        self.assertEqual(MissingSong.from_dict(entry.to_dict()), entry)


if __name__ == "__main__":
    unittest.main()
