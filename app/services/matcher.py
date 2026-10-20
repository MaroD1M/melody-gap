# -*- coding: utf-8 -*-
"""歌曲文本标准化与相似度匹配。

匹配流程::

    输入(歌手, 歌名)
        │
        ├─ normalize_text：NFKC 归一化 → 小写 → 去标点 → 去修饰词 → 压缩空格
        │
        └─ 遍历搜索结果：
               艺人相似度 × 0.4
             + 歌名相似度 × 0.6
             = 综合评分
             取最高分，>= MATCH_THRESHOLD(0.75) 判定命中

与旧实现相比的修正：
1. 修饰词 ``live`` 使用单词边界匹配，不会再把 ``Olive`` / ``Deliver``
   破坏成 ``O`` / ``D``；
2. 标点替换为空格而不是直接删除，避免 ``love-me`` → ``loveme``；
3. 子串加分要求双方长度 >= 4，避免单字符标题“通配”所有结果；
4. 匹配结果返回结构化 ``MatchResult``，便于日志与后续 UI 展示。
"""

import difflib
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from app.constants import (
    ARTIST_WEIGHT,
    MATCH_THRESHOLD,
    MODIFIER_WORDS_EN,
    MODIFIER_WORDS_ZH,
    SUBSTRING_MIN_LENGTH,
    SUBSTRING_SCORE,
    TITLE_WEIGHT,
)

logger = logging.getLogger(__name__)

# 预编译：非“字母/数字/下划线/空白/中文”的字符替换为空格
_PUNCTUATION_RE = re.compile(r"[^\w\s\u4e00-\u9fff]", re.UNICODE)
# 预编译：英文修饰词按单词边界匹配
_MODIFIER_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(word) for word in MODIFIER_WORDS_EN) + r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MatchResult:
    """一次匹配的完整结果。

    Attributes:
        matched: 是否达到阈值
        song: 得分最高的候选歌曲（可能为 None）
        score: 最高综合评分（0~1）
    """

    matched: bool
    song: Optional[Dict[str, Any]]
    score: float


class SongMatcher:
    """可配置的歌曲匹配器。

    参数默认取自 constants，方便后续在设置界面开放“匹配灵敏度”。
    """

    def __init__(
        self,
        threshold: float = MATCH_THRESHOLD,
        artist_weight: float = ARTIST_WEIGHT,
        title_weight: float = TITLE_WEIGHT,
    ) -> None:
        self.threshold = threshold
        self.artist_weight = artist_weight
        self.title_weight = title_weight

    # ---------- 标准化 ----------

    @staticmethod
    def normalize_text(text: str) -> str:
        """标准化文本，消除大小写、全半角、标点、版本修饰词差异。

        示例::

            "Song (Live Remix)" -> "song"
            "Olivia - 现场版"   -> "olivia"
            "ＡＢＣ　１２３"     -> "abc 123"
        """
        if not text:
            return ""

        # NFKC：全角字母/数字/空格转半角，兼容不同输入法
        text = unicodedata.normalize("NFKC", text).lower()

        # 标点替换为空格，保留单词边界
        text = _PUNCTUATION_RE.sub(" ", text)

        # 英文修饰词按单词边界删除
        text = _MODIFIER_RE.sub(" ", text)

        # 中文修饰词直接删除
        for word in MODIFIER_WORDS_ZH:
            text = text.replace(word, " ")

        # 压缩连续空白
        return " ".join(text.split()).strip()

    # ---------- 相似度 ----------

    @staticmethod
    def calculate_similarity(text1: str, text2: str) -> float:
        """计算两个已标准化字符串的相似度（0~1）。

        使用 difflib.SequenceMatcher.ratio()；若一方是另一方的子串，
        且双方长度都不小于 SUBSTRING_MIN_LENGTH，则至少记为 0.8。
        """
        if not text1 or not text2:
            return 0.0

        similarity = difflib.SequenceMatcher(None, text1, text2).ratio()

        short, long = sorted((text1, text2), key=len)
        if len(short) >= SUBSTRING_MIN_LENGTH and short in long:
            similarity = max(similarity, SUBSTRING_SCORE)

        return similarity

    def score(
        self,
        artist: str,
        title: str,
        candidate_artist: str,
        candidate_title: str,
    ) -> float:
        """对单个候选歌曲计算加权综合评分。"""
        artist_similarity = self.calculate_similarity(
            self.normalize_text(artist), self.normalize_text(candidate_artist)
        )
        title_similarity = self.calculate_similarity(
            self.normalize_text(title), self.normalize_text(candidate_title)
        )
        return artist_similarity * self.artist_weight + title_similarity * self.title_weight

    # ---------- 匹配 ----------

    def find_best_match(
        self,
        songs: Iterable[Dict[str, Any]],
        artist: str,
        title: str,
    ) -> MatchResult:
        """在候选歌曲中寻找最佳匹配。

        Args:
            songs: Subsonic ``search3`` 返回的歌曲字典列表
            artist: 播放器解析出的歌手
            title: 播放器解析出的歌名

        Returns:
            MatchResult；没有候选时返回 ``(False, None, 0.0)``。
        """
        best_score = 0.0
        best_song: Optional[Dict[str, Any]] = None

        normalized_artist = self.normalize_text(artist)
        normalized_title = self.normalize_text(title)

        for song in songs:
            candidate_artist = song.get("artist", "")
            candidate_title = song.get("title", "")

            artist_similarity = self.calculate_similarity(
                normalized_artist, self.normalize_text(candidate_artist)
            )
            title_similarity = self.calculate_similarity(
                normalized_title, self.normalize_text(candidate_title)
            )
            overall = (
                artist_similarity * self.artist_weight
                + title_similarity * self.title_weight
            )

            logger.debug(
                "候选: %s - %s | 艺人 %.3f | 歌名 %.3f | 综合 %.3f",
                candidate_artist,
                candidate_title,
                artist_similarity,
                title_similarity,
                overall,
            )

            if overall > best_score:
                best_score = overall
                best_song = song

        matched = best_song is not None and best_score >= self.threshold
        if matched:
            logger.info(
                "匹配成功: %s - %s (评分 %.3f)",
                best_song.get("artist", ""),
                best_song.get("title", ""),
                best_score,
            )
        else:
            logger.info(
                "未命中: %s - %s (最高评分 %.3f, 阈值 %.2f)",
                artist,
                title,
                best_score,
                self.threshold,
            )

        return MatchResult(matched=matched, song=best_song, score=best_score)


def make_song_key(artist: str, title: str) -> str:
    """生成用于待补清单去重的稳定键（跨播放器、忽略大小写/标点/版本后缀）。"""
    normalized_artist = SongMatcher.normalize_text(artist)
    normalized_title = SongMatcher.normalize_text(title)
    return f"{normalized_artist}|{normalized_title}"
