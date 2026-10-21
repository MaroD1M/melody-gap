# -*- coding: utf-8 -*-
"""混合播放检测：SMTC 优先，窗口标题回退。

同一播放器只要 SMTC 提供了歌曲，就忽略它的窗口标题；SMTC 没有覆盖到的
播放器再走窗口检测。这样既能在关闭主窗口/托盘时继续识别，也保留了旧版
Windows 上的兼容性。
"""

import logging
from typing import Dict, List, Optional, Tuple

from app.constants import (
    PLAYBACK_SOURCE_SMTC,
    PLAYBACK_SOURCE_WINDOW,
    SUPPORTED_PLAYERS,
)
from app.models import PlaybackCandidate
from app.services.player_detector import PlayerDetector
from app.services.smtc_detector import SmtcDetector

logger = logging.getLogger(__name__)


class HybridPlaybackDetector:
    """组合 SMTC 与窗口标题检测，返回每个播放器的当前候选。"""

    def __init__(
        self,
        window_detector: Optional[object] = None,
        smtc_detector: Optional[object] = None,
    ) -> None:
        self.window_detector = window_detector or PlayerDetector()
        self.smtc_detector = smtc_detector if smtc_detector is not None else SmtcDetector()

    def start(self) -> None:
        start = getattr(self.smtc_detector, "start", None)
        if callable(start):
            start()

    def stop(self) -> None:
        stop = getattr(self.smtc_detector, "stop", None)
        if callable(stop):
            stop()

    @property
    def smtc_available(self) -> bool:
        return bool(getattr(self.smtc_detector, "available", False))

    @property
    def smtc_error(self) -> Optional[str]:
        return getattr(self.smtc_detector, "last_error", None)

    def get_current_playings(self) -> List[PlaybackCandidate]:
        smtc_candidates: Dict[str, PlaybackCandidate] = {}
        for candidate in self.smtc_detector.snapshot():
            if (
                candidate.player in SUPPORTED_PLAYERS
                and candidate.title
                and candidate.player not in smtc_candidates
            ):
                smtc_candidates[candidate.player] = candidate

        window_candidates: Dict[str, PlaybackCandidate] = {}
        needed = [key for key in SUPPORTED_PLAYERS if key not in smtc_candidates]
        if needed:
            try:
                found = self.window_detector.get_current_playings(player_keys=needed)
            except TypeError:
                found = self.window_detector.get_current_playings()
            for candidate in found:
                if (
                    candidate.player in SUPPORTED_PLAYERS
                    and candidate.title
                    and candidate.player not in smtc_candidates
                    and candidate.player not in window_candidates
                ):
                    window_candidates[candidate.player] = candidate

        result: List[PlaybackCandidate] = []
        for player_key in SUPPORTED_PLAYERS:
            candidate = smtc_candidates.get(player_key) or window_candidates.get(player_key)
            if candidate is not None:
                result.append(candidate)

        if result:
            logger.debug(
                "检测到播放: %s",
                [
                    (item.player, item.full_title, item.source)
                    for item in result
                ],
            )
        return result

    def get_current_playing(self) -> Optional[Tuple[str, str]]:
        """兼容旧接口：返回第一个播放器及原始标题。"""
        candidates = self.get_current_playings()
        if not candidates:
            return None
        return candidates[0].player, candidates[0].full_title


__all__ = [
    "HybridPlaybackDetector",
    "PLAYBACK_SOURCE_SMTC",
    "PLAYBACK_SOURCE_WINDOW",
]
