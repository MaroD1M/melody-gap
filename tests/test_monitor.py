# -*- coding: utf-8 -*-
"""监控核心流程测试（使用假检测器/假 Subsonic，不依赖 Windows 与网络）。"""

import tempfile
import unittest
from pathlib import Path
from typing import Optional, Tuple

from app.config_manager import ConfigManager
from app.constants import PLAYBACK_SOURCE_SMTC, PLAYBACK_SOURCE_WINDOW
from app.models import PlaybackCandidate, SongInfo
from app.services.monitor import MusicMonitor
from app.services.subsonic import SubsonicError


class FakeDetector:
    """可手动控制返回值的检测器。"""

    def __init__(self) -> None:
        self.current: Optional[Tuple[str, str]] = None

    def get_current_playing(self) -> Optional[Tuple[str, str]]:
        return self.current


class FakeMultiDetector:
    """返回多个播放器候选的假检测器。"""

    def __init__(self) -> None:
        self.candidates = []

    def get_current_playings(self):
        return list(self.candidates)


def make_candidate(
    player: str,
    title: str,
    artist: str,
    source: str = PLAYBACK_SOURCE_WINDOW,
) -> PlaybackCandidate:
    return PlaybackCandidate(
        song=SongInfo(title=title, artist=artist, player=player),
        source=source,
        playback_status="playing",
        full_title=f"{title} - {artist}",
    )


class FakeSubsonic:
    """记录查询调用并返回预设结果。"""

    def __init__(self) -> None:
        self.calls = []
        self.result = True
        self.error = None

    def find_exact_match(self, artist: str, title: str) -> bool:
        self.calls.append((artist, title))
        if self.error is not None:
            raise self.error
        return self.result


class TestMusicMonitor(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config = ConfigManager(Path(self._tmp.name) / "config.ini")
        self.config.update_subsonic_config("https://demo.example.com/", "u", "p")
        self.detector = FakeDetector()
        self.subsonic = FakeSubsonic()
        self.records = []
        self.factory_kwargs = None

        def factory(**kwargs):
            self.factory_kwargs = kwargs
            return self.subsonic

        self.monitor = MusicMonitor(
            self.config,
            on_record=lambda record, song: self.records.append((record, song)),
            detector=self.detector,
            subsonic_factory=factory,
        )

    def tearDown(self):
        self.monitor.stop()
        self._tmp.cleanup()

    def test_poll_records_new_song(self):
        self.detector.current = ("qq", "晴天 - 周杰伦")
        self.monitor._poll_once()

        history = self.monitor.play_history
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].title, "晴天")
        self.assertEqual(history[0].artist, "周杰伦")
        self.assertTrue(history[0].in_library)
        self.assertEqual(self.monitor.current_song.title, "晴天")
        self.assertEqual(self.subsonic.calls, [("周杰伦", "晴天")])
        self.assertEqual(len(self.records), 1)

    def test_poll_deduplicates_same_title(self):
        self.detector.current = ("netease", "晴天 - 周杰伦")
        self.monitor._poll_once()
        self.monitor._poll_once()

        self.assertEqual(len(self.monitor.play_history), 1)
        self.assertEqual(len(self.records), 1)

    def test_title_change_creates_new_record(self):
        self.detector.current = ("qq", "晴天 - 周杰伦")
        self.monitor._poll_once()
        self.detector.current = ("qq", "稻香 - 周杰伦")
        self.monitor._poll_once()

        self.assertEqual(len(self.monitor.play_history), 2)

    def test_no_playing_clears_current_song(self):
        self.detector.current = ("qq", "晴天 - 周杰伦")
        self.monitor._poll_once()
        self.detector.current = None
        self.monitor._poll_once()

        self.assertIsNone(self.monitor.current_song)
        self.assertEqual(len(self.monitor.play_history), 1)

    def test_invalid_title_is_ignored(self):
        self.detector.current = ("qq", "QQ音乐")
        self.monitor._poll_once()
        self.assertEqual(self.monitor.play_history, [])

    def test_play_history_is_snapshot(self):
        self.detector.current = ("qq", "晴天 - 周杰伦")
        self.monitor._poll_once()

        snapshot = self.monitor.play_history
        snapshot.clear()
        self.assertEqual(len(self.monitor.play_history), 1)

    def test_clear_history(self):
        self.detector.current = ("qq", "晴天 - 周杰伦")
        self.monitor._poll_once()
        self.monitor.clear_history()
        self.assertEqual(self.monitor.play_history, [])

    def test_start_stop(self):
        self.monitor.start()
        self.assertTrue(self.monitor.running)
        self.monitor.stop()
        self.assertFalse(self.monitor.running)

    def test_library_failure_marks_missing(self):
        self.subsonic.result = False
        self.detector.current = ("qq", "晴天 - 周杰伦")
        self.monitor._poll_once()
        self.assertFalse(self.monitor.play_history[0].in_library)

    def test_query_error_marks_unknown(self):
        self.subsonic.error = SubsonicError("服务器超时")
        self.detector.current = ("qq", "晴天 - 周杰伦")
        self.monitor._poll_once()

        record = self.monitor.play_history[0]
        self.assertIsNone(record.in_library)
        self.assertTrue(record.is_unknown)
        self.assertIsNotNone(self.monitor.current_record)
        self.assertTrue(self.monitor.current_record.is_unknown)
        self.assertIsNotNone(self.monitor.current_song)
        self.assertFalse(self.monitor.query_ok)
        self.assertIn("服务器超时", self.monitor.last_query_error)

    def test_successful_query_clears_error_state(self):
        self.subsonic.error = SubsonicError("服务器超时")
        self.detector.current = ("qq", "晴天 - 周杰伦")
        self.monitor._poll_once()
        self.assertIsNotNone(self.monitor.last_query_error)

        self.subsonic.error = None
        self.monitor.recheck_song(self.monitor.current_song)
        self.assertTrue(self.monitor.query_ok)
        self.assertIsNone(self.monitor.last_query_error)

    def test_unknown_retries_without_duplicate_history(self):
        self.subsonic.error = SubsonicError("临时超时")
        self.detector.current = ("qq", "晴天 - 周杰伦")
        self.monitor._poll_once()
        self.assertEqual(len(self.monitor.play_history), 1)

        self.subsonic.error = None
        self.subsonic.result = True
        self.monitor._unknown_retries["qq"].next_at = 0
        self.monitor._poll_once()

        self.assertEqual(len(self.monitor.play_history), 1)
        self.assertEqual(len(self.subsonic.calls), 2)
        self.assertTrue(self.monitor.current_record.in_library)
        self.assertEqual(len(self.records), 2)

    def test_unknown_retry_stops_after_max(self):
        self.subsonic.error = SubsonicError("持续失败")
        self.detector.current = ("qq", "晴天 - 周杰伦")
        self.monitor._poll_once()

        self.monitor._retry_interval = 0
        self.monitor._unknown_retries["qq"].next_at = 0
        for _ in range(10):
            self.monitor._poll_once()

        self.assertEqual(len(self.subsonic.calls), 1 + self.monitor._retry_max)

    def test_factory_receives_verify_ssl(self):
        self.assertTrue(self.factory_kwargs["verify_ssl"])
        self.config.update_subsonic_config(
            "https://demo.example.com/", "u", "p", verify_ssl=False
        )
        self.monitor.reload_config()
        self.assertFalse(self.factory_kwargs["verify_ssl"])

    def test_missing_subsonic_marks_unknown(self):
        self.monitor.subsonic = None
        self.detector.current = ("qq", "晴天 - 周杰伦")
        self.monitor._poll_once()

        self.assertIsNone(self.monitor.play_history[0].in_library)

    def test_result_cache_avoids_repeat_query(self):
        self.detector.current = ("qq", "晴天 - 周杰伦")
        self.monitor._poll_once()
        self.detector.current = ("qq", "稻香 - 周杰伦")
        self.monitor._poll_once()
        self.detector.current = ("qq", "晴天 - 周杰伦")
        self.monitor._poll_once()

        self.assertEqual(len(self.subsonic.calls), 2)

    def test_update_current_result_only_for_current_song(self):
        self.detector.current = ("qq", "晴天 - 周杰伦")
        self.monitor._poll_once()

        self.assertTrue(self.monitor.update_current_result("周杰伦", "晴天", False))
        self.assertFalse(self.monitor.current_record.in_library)

        self.assertFalse(self.monitor.update_current_result("周杰伦", "稻香", True))
        self.assertFalse(self.monitor.current_record.in_library)

    def test_recheck_bypasses_cache(self):
        self.detector.current = ("qq", "晴天 - 周杰伦")
        self.monitor._poll_once()
        self.subsonic.result = False

        result = self.monitor.recheck_song(
            SongInfo(title="晴天", artist="周杰伦", player="qq")
        )
        self.assertFalse(result)
        self.assertEqual(len(self.subsonic.calls), 2)

    def test_reload_config_clears_cache(self):
        self.detector.current = ("qq", "晴天 - 周杰伦")
        self.monitor._poll_once()
        self.monitor.reload_config()
        self.detector.current = ("qq", "稻香 - 周杰伦")
        self.monitor._poll_once()
        self.detector.current = ("qq", "晴天 - 周杰伦")
        self.monitor._poll_once()

        self.assertEqual(len(self.subsonic.calls), 3)

    def test_two_players_are_tracked_simultaneously(self):
        detector = FakeMultiDetector()
        detector.candidates = [
            make_candidate("qq", "晴天", "周杰伦", PLAYBACK_SOURCE_SMTC),
            make_candidate("netease", "稻香", "周杰伦", PLAYBACK_SOURCE_WINDOW),
        ]
        self.monitor.detector = detector
        self.monitor._poll_once()

        self.assertEqual(len(self.monitor.play_history), 2)
        self.assertEqual(set(self.monitor.current_songs), {"qq", "netease"})
        self.assertEqual(self.monitor.current_songs["qq"].title, "晴天")
        self.assertEqual(self.monitor.current_songs["netease"].title, "稻香")
        self.assertEqual(self.monitor.current_sources["qq"], PLAYBACK_SOURCE_SMTC)
        self.assertEqual(
            self.monitor.current_sources["netease"], PLAYBACK_SOURCE_WINDOW
        )

    def test_same_song_on_two_players_updates_selected_player(self):
        detector = FakeMultiDetector()
        detector.candidates = [
            make_candidate("qq", "晴天", "周杰伦", PLAYBACK_SOURCE_SMTC),
            make_candidate("netease", "晴天", "周杰伦", PLAYBACK_SOURCE_SMTC),
        ]
        self.monitor.detector = detector
        self.monitor._poll_once()

        self.assertEqual(len(self.monitor.play_history), 2)
        self.assertEqual(len(self.subsonic.calls), 1)
        self.assertTrue(
            self.monitor.update_current_result(
                "周杰伦", "晴天", False, player="netease"
            )
        )
        self.assertTrue(self.monitor.current_records["qq"].in_library)
        self.assertFalse(self.monitor.current_records["netease"].in_library)

    def test_player_disappearing_only_clears_its_state(self):
        detector = FakeMultiDetector()
        detector.candidates = [
            make_candidate("qq", "晴天", "周杰伦"),
            make_candidate("netease", "稻香", "周杰伦"),
        ]
        self.monitor.detector = detector
        self.monitor._poll_once()

        detector.candidates = [make_candidate("netease", "稻香", "周杰伦")]
        self.monitor._poll_once()

        self.assertEqual(set(self.monitor.current_songs), {"netease"})
        self.assertEqual(self.monitor.current_song.player, "netease")
        self.assertEqual(len(self.monitor.play_history), 2)

    def test_same_title_is_restored_after_transient_empty_poll(self):
        self.detector.current = ("qq", "晴天 - 周杰伦")
        self.monitor._poll_once()
        self.detector.current = None
        self.monitor._poll_once()
        self.assertIsNone(self.monitor.current_song)

        self.detector.current = ("qq", "晴天 - 周杰伦")
        self.monitor._poll_once()

        self.assertEqual(len(self.monitor.play_history), 1)
        self.assertEqual(self.monitor.current_song.title, "晴天")
        self.assertIsNotNone(self.monitor.current_record)

    def test_same_title_after_long_absence_records_new_play(self):
        self.detector.current = ("qq", "晴天 - 周杰伦")
        self.monitor._poll_once()
        self.detector.current = None
        self.monitor._poll_once()

        self.monitor._missing_since["qq"] = 0.0
        self.monitor._poll_once()
        self.detector.current = ("qq", "晴天 - 周杰伦")
        self.monitor._poll_once()

        self.assertEqual(len(self.monitor.play_history), 2)
        self.assertEqual(self.monitor.current_song.title, "晴天")

    def test_source_switch_for_same_song_does_not_duplicate(self):
        detector = FakeMultiDetector()
        detector.candidates = [
            make_candidate("qq", "晴天", "周杰伦", PLAYBACK_SOURCE_SMTC)
        ]
        self.monitor.detector = detector
        self.monitor._poll_once()

        detector.candidates = [
            make_candidate("qq", "晴天", "周杰伦", PLAYBACK_SOURCE_WINDOW)
        ]
        self.monitor._poll_once()

        self.assertEqual(len(self.monitor.play_history), 1)
        self.assertEqual(self.monitor.current_sources["qq"], PLAYBACK_SOURCE_WINDOW)

    def test_unknown_retry_survives_transient_empty_poll(self):
        self.subsonic.error = SubsonicError("临时超时")
        self.detector.current = ("qq", "晴天 - 周杰伦")
        self.monitor._poll_once()
        self.detector.current = None
        self.monitor._poll_once()

        self.detector.current = ("qq", "晴天 - 周杰伦")
        self.monitor._poll_once()
        self.assertIn("qq", self.monitor._unknown_retries)

        self.subsonic.error = None
        self.subsonic.result = True
        self.monitor._retry_interval = 0
        self.monitor._unknown_retries["qq"].next_at = 0
        self.monitor._poll_once()

        self.assertTrue(self.monitor.current_record.in_library)
        self.assertEqual(len(self.monitor.play_history), 1)

    def test_unknown_retry_is_per_player(self):
        self.subsonic.error = SubsonicError("临时超时")
        detector = FakeMultiDetector()
        detector.candidates = [
            make_candidate("qq", "晴天", "周杰伦"),
            make_candidate("netease", "稻香", "周杰伦"),
        ]
        self.monitor.detector = detector
        self.monitor._poll_once()
        self.assertEqual(len(self.monitor.play_history), 2)

        self.subsonic.error = None
        self.monitor._retry_interval = 0
        self.monitor._unknown_retries["netease"].next_at = 0
        self.monitor._poll_once()

        self.assertTrue(self.monitor.current_records["netease"].in_library)
        self.assertIsNone(self.monitor.current_records["qq"].in_library)
        self.assertIn("qq", self.monitor._unknown_retries)


if __name__ == "__main__":
    unittest.main()
