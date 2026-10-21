# -*- coding: utf-8 -*-
"""SMTC / 混合检测的纯单元测试（不访问真实 Windows API）。"""

import asyncio
import os
import unittest

from app.constants import (
    PLAYBACK_SOURCE_SMTC,
    PLAYBACK_SOURCE_WINDOW,
    PLAYBACK_STATUS_PAUSED,
    PLAYBACK_STATUS_PLAYING,
    PLAYBACK_STATUS_STOPPED,
    PLAYBACK_STATUS_UNKNOWN,
)
from app.models import PlaybackCandidate, SongInfo
from app.services.playback_detector import HybridPlaybackDetector
from app.services.smtc_detector import (
    SmtcDetector,
    match_player_by_app_id,
    normalize_playback_status,
)


def candidate(
    player: str,
    title: str,
    artist: str,
    source: str,
    status: str = PLAYBACK_STATUS_PLAYING,
) -> PlaybackCandidate:
    return PlaybackCandidate(
        song=SongInfo(title=title, artist=artist, player=player),
        source=source,
        playback_status=status,
        full_title=f"{title} - {artist}",
    )


class FakeSmtc:
    def __init__(self, items=()):
        self.items = list(items)
        self.started = False
        self.stopped = False

    @property
    def available(self):
        return bool(self.items)

    @property
    def last_error(self):
        return None

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def snapshot(self):
        return list(self.items)


class FakeWindow:
    def __init__(self, items=()):
        self.items = list(items)
        self.calls = []

    def get_current_playings(self, player_keys=None):
        self.calls.append(list(player_keys) if player_keys is not None else None)
        return list(self.items)


class FakeProperties:
    def __init__(self, title, artist="", subtitle=""):
        self.title = title
        self.artist = artist
        self.subtitle = subtitle


class FakeInfo:
    def __init__(self, status):
        self.playback_status = status


class FakeSession:
    def __init__(self, app_id, props, status=4):
        self.source_app_user_model_id = app_id
        self.props = props
        self.status = status

    async def try_get_media_properties_async(self):
        return self.props

    def get_playback_info(self):
        return FakeInfo(self.status)


class FakeManager:
    def __init__(self, sessions):
        self.sessions = sessions

    def get_sessions(self):
        return list(self.sessions)


class TestSmtcHelpers(unittest.TestCase):
    def test_normalize_status_from_enum_text(self):
        self.assertEqual(
            normalize_playback_status(
                "GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING"
            ),
            PLAYBACK_STATUS_PLAYING,
        )
        self.assertEqual(
            normalize_playback_status(
                "GlobalSystemMediaTransportControlsSessionPlaybackStatus.PAUSED"
            ),
            PLAYBACK_STATUS_PAUSED,
        )
        self.assertEqual(
            normalize_playback_status(
                "GlobalSystemMediaTransportControlsSessionPlaybackStatus.STOPPED"
            ),
            PLAYBACK_STATUS_STOPPED,
        )

    def test_normalize_status_from_numeric_value(self):
        self.assertEqual(normalize_playback_status(4), PLAYBACK_STATUS_PLAYING)
        self.assertEqual(normalize_playback_status(5), PLAYBACK_STATUS_PAUSED)
        self.assertEqual(normalize_playback_status(3), PLAYBACK_STATUS_STOPPED)
        self.assertEqual(normalize_playback_status(None), PLAYBACK_STATUS_UNKNOWN)
        self.assertEqual(normalize_playback_status(object()), PLAYBACK_STATUS_UNKNOWN)

    def test_match_player_by_app_id(self):
        self.assertEqual(match_player_by_app_id("Tencent.QQMusicPC"), "qq")
        self.assertEqual(match_player_by_app_id("QQMusic.exe"), "qq")
        self.assertEqual(match_player_by_app_id("CloudMusic.exe"), "netease")
        self.assertEqual(match_player_by_app_id("Netease.CloudMusic"), "netease")
        self.assertIsNone(match_player_by_app_id("Spotify.exe"))
        self.assertIsNone(match_player_by_app_id(""))

    def test_detector_does_not_start_on_non_windows(self):
        if os.name == "nt":
            self.skipTest("仅验证非 Windows 平台的降级行为")
        detector = SmtcDetector()
        self.assertFalse(detector.start())
        self.assertEqual(detector.snapshot(), [])
        detector.stop()

    def test_read_sessions_maps_players_and_parses_title_fallback(self):
        manager = FakeManager([
            FakeSession("Tencent.QQMusicPC", FakeProperties("晴天", "周杰伦")),
            FakeSession("CloudMusic.exe", FakeProperties("稻香 - 周杰伦")),
            FakeSession("Spotify.exe", FakeProperties("起风了", "买辣椒也用券")),
            FakeSession("CloudMusic.exe", FakeProperties("", "周杰伦")),
        ])
        detector = SmtcDetector()

        result = {item.player: item for item in asyncio.run(
            detector._read_sessions(manager)
        )}

        self.assertEqual(set(result), {"qq", "netease"})
        self.assertEqual(result["qq"].song.artist, "周杰伦")
        self.assertEqual(result["netease"].song.title, "稻香")
        self.assertEqual(result["netease"].song.artist, "周杰伦")
        self.assertEqual(result["netease"].source, PLAYBACK_SOURCE_SMTC)
        self.assertEqual(result["netease"].playback_status, PLAYBACK_STATUS_PLAYING)

    def test_read_sessions_prefers_playing_over_paused(self):
        manager = FakeManager([
            FakeSession("QQMusic.exe", FakeProperties("旧歌", "A"), status=5),
            FakeSession("QQMusic.exe", FakeProperties("新歌", "B"), status=4),
        ])
        detector = SmtcDetector()

        result = asyncio.run(detector._read_sessions(manager))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].title, "新歌")
        self.assertEqual(result[0].playback_status, PLAYBACK_STATUS_PLAYING)


class TestHybridPlaybackDetector(unittest.TestCase):
    def test_prefers_smtc_and_uses_window_only_for_missing_player(self):
        smtc = FakeSmtc([
            candidate("qq", "晴天", "周杰伦", PLAYBACK_SOURCE_SMTC),
        ])
        window = FakeWindow([
            candidate("qq", "旧标题", "旧歌手", PLAYBACK_SOURCE_WINDOW),
            candidate("netease", "稻香", "周杰伦", PLAYBACK_SOURCE_WINDOW),
        ])
        detector = HybridPlaybackDetector(
            window_detector=window,
            smtc_detector=smtc,
        )

        result = {item.player: item for item in detector.get_current_playings()}

        self.assertEqual(result["qq"].title, "晴天")
        self.assertEqual(result["qq"].source, PLAYBACK_SOURCE_SMTC)
        self.assertEqual(result["netease"].title, "稻香")
        self.assertEqual(window.calls, [["netease"]])

    def test_falls_back_to_all_windows_without_smtc(self):
        window = FakeWindow([
            candidate("qq", "晴天", "周杰伦", PLAYBACK_SOURCE_WINDOW),
            candidate("netease", "稻香", "周杰伦", PLAYBACK_SOURCE_WINDOW),
        ])
        detector = HybridPlaybackDetector(
            window_detector=window,
            smtc_detector=FakeSmtc(),
        )

        result = detector.get_current_playings()

        self.assertEqual([item.player for item in result], ["qq", "netease"])
        self.assertEqual(window.calls, [["qq", "netease"]])

    def test_ignores_unsupported_and_empty_smtc_candidates(self):
        smtc = FakeSmtc([
            candidate("spotify", "晴天", "周杰伦", PLAYBACK_SOURCE_SMTC),
            PlaybackCandidate(
                song=SongInfo(title="", artist="", player="netease"),
                source=PLAYBACK_SOURCE_SMTC,
                playback_status=PLAYBACK_STATUS_PLAYING,
                full_title="",
            ),
        ])
        window = FakeWindow([
            candidate("netease", "稻香", "周杰伦", PLAYBACK_SOURCE_WINDOW),
        ])
        detector = HybridPlaybackDetector(
            window_detector=window,
            smtc_detector=smtc,
        )

        result = detector.get_current_playings()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].player, "netease")
        self.assertEqual(result[0].source, PLAYBACK_SOURCE_WINDOW)

    def test_old_window_detector_signature_is_supported(self):
        class OldWindow:
            def get_current_playings(self):
                return [
                    candidate("qq", "晴天", "周杰伦", PLAYBACK_SOURCE_WINDOW)
                ]

        detector = HybridPlaybackDetector(
            window_detector=OldWindow(),
            smtc_detector=FakeSmtc(),
        )
        self.assertEqual(len(detector.get_current_playings()), 1)

    def test_start_stop_delegate_to_smtc(self):
        smtc = FakeSmtc()
        detector = HybridPlaybackDetector(
            window_detector=FakeWindow(),
            smtc_detector=smtc,
        )
        detector.start()
        detector.stop()
        self.assertTrue(smtc.started)
        self.assertTrue(smtc.stopped)


if __name__ == "__main__":
    unittest.main()
