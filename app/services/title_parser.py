# -*- coding: utf-8 -*-
"""播放器窗口标题解析（纯函数，无平台依赖）。

QQ 音乐 / 网易云音乐的窗口标题通常形如::

    晴天 - 周杰伦
    晴天 — 周杰伦
    晴天 | 周杰伦

不同版本/皮肤可能使用不同分隔符，因此这里按 TITLE_SEPARATORS 依次尝试。

设计说明：
* 本模块只处理字符串，不调用 Win32 API，因此可以在任意平台单元测试。
* 返回不可变的 ``SongInfo``，避免调用方意外修改解析结果。
"""

import logging
import re
from typing import List, Optional, Sequence

from app.constants import (
    EXCLUDED_TITLE_KEYWORDS,
    PLAYER_EXCLUDED_KEYWORDS,
    PLAYER_TITLE_SUFFIXES,
    TITLE_PATTERNS,
    TITLE_SEPARATORS,
)
from app.models import SongInfo

logger = logging.getLogger(__name__)

# 预编译：按分隔符切段，用于判断功能页标题
_SEGMENT_SPLIT_RE = re.compile(r"\s*[-—–|]\s*")
_EXCLUDED_KEYWORDS_LOWER = {keyword.lower() for keyword in EXCLUDED_TITLE_KEYWORDS}


def clean_window_title(title: str, player_key: str) -> str:
    """剥离标题末尾的播放器应用名。

    某些版本会把应用名追加在标题末尾::

        "晴天 - 周杰伦 - 网易云音乐" -> "晴天 - 周杰伦"

    旧版用“标题包含播放器名就丢弃”的做法，会把这类正常播放标题一并过滤掉。
    """
    cleaned = title.strip()
    suffixes = sorted(
        PLAYER_TITLE_SUFFIXES.get(player_key, ()), key=len, reverse=True
    )
    for suffix in suffixes:
        pattern = re.compile(
            r"\s*[-—–|]\s*" + re.escape(suffix) + r"\s*$", re.IGNORECASE
        )
        cleaned = pattern.sub("", cleaned).strip()
    return cleaned


def is_valid_song_title(title: str, player_key: str) -> bool:
    """判断窗口标题是否像“正在播放的歌曲”。

    判定顺序：
    1. 剥离末尾应用名；
    2. 必须包含歌曲分隔符；
    3. 仍包含播放器应用名 -> 功能页，排除；
    4. 任一分隔段与功能页关键词完全相等 -> 排除。

    第 4 步使用“完全相等”而不是子串匹配，避免误杀《我的天空》《发现》
    这类包含常见词的合法歌名。

    Args:
        title: 窗口标题原文
        player_key: 播放器标识
    """
    if not title:
        return False

    cleaned = clean_window_title(title, player_key)
    if not any(separator in cleaned for separator in TITLE_SEPARATORS):
        return False

    lowered = cleaned.lower()
    for keyword in PLAYER_EXCLUDED_KEYWORDS.get(player_key, ()):
        if keyword.lower() in lowered:
            return False

    segments = [
        segment.strip().lower()
        for segment in _SEGMENT_SPLIT_RE.split(cleaned)
        if segment.strip()
    ]
    if any(segment in _EXCLUDED_KEYWORDS_LOWER for segment in segments):
        return False

    return True


def parse_title(title: str, player_key: str) -> Optional[SongInfo]:
    """把窗口标题解析为 ``SongInfo``。

    当前两个播放器均采用“歌名 - 歌手”的顺序。若未来出现相反顺序的播放器，
    在这里增加分支即可（保持函数签名不变）。

    Returns:
        解析成功返回 SongInfo；失败返回 None。
    """
    if not title:
        return None

    cleaned = clean_window_title(title, player_key)
    for pattern in TITLE_PATTERNS:
        match = re.match(pattern, cleaned)
        if not match:
            continue

        song_title = match.group(1).strip()
        artist = match.group(2).strip()
        if not song_title or not artist:
            continue

        return SongInfo(title=song_title, artist=artist, player=player_key)

    return None


def select_best_title(titles: Sequence[str]) -> Optional[str]:
    """当同一播放器存在多个可见窗口标题时，选出最可能是歌曲的那个。

    评分规则：
    * 长度 10~100 字符：+10；5~10 或 100~150：+5（过短/过长都不可靠）
    * 含 " - "：+15；含破折号：+12；含 " | "：+8
    * 含方括号：-3；含成对圆括号：-2（通常是歌词/提示窗口）

    该函数不再需要 player_key 参数（旧版参数未使用，已移除）。
    """
    if not titles:
        return None
    if len(titles) == 1:
        return titles[0]

    scored: List[tuple] = []
    for title in titles:
        score = 0
        length = len(title)

        if 10 <= length <= 100:
            score += 10
        elif 5 <= length < 10 or 100 < length <= 150:
            score += 5

        if " - " in title:
            score += 15
        elif " — " in title or " – " in title:
            score += 12
        elif " | " in title:
            score += 8

        if "[" in title or "]" in title:
            score -= 3
        if "(" in title and ")" in title:
            score -= 2

        scored.append((score, title))

    return max(scored, key=lambda item: item[0])[1]
