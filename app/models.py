# -*- coding: utf-8 -*-
"""领域数据模型。

UI、监控、导出等模块统一使用这里的数据结构，避免在模块之间传递裸 dict。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from app.constants import (
    MISSING_STATUS_LABELS,
    MISSING_STATUS_PENDING,
    player_display_name,
    player_short_name,
)


@dataclass(frozen=True)
class SongInfo:
    """从播放器窗口标题解析出的歌曲信息（不可变值对象）。

    Attributes:
        title: 歌曲名
        artist: 歌手名
        player: 播放器标识（``qq`` / ``netease``）
    """

    title: str
    artist: str
    player: str

    @property
    def player_name(self) -> str:
        return player_display_name(self.player)

    @property
    def player_short_name(self) -> str:
        return player_short_name(self.player)

    @property
    def display_text(self) -> str:
        """用于日志/调试的单行展示文本。"""
        return f"[{self.player_name}] {self.title} - {self.artist}"


@dataclass
class PlayRecord:
    """一条播放记录。

    Attributes:
        timestamp: 检测时间，格式 ``YYYY-MM-DD HH:MM:SS``
        title: 歌曲名
        artist: 歌手名
        in_library: 是否在 Subsonic 曲库中；``None`` 表示未配置或查询失败
        full_title: 原始窗口标题（排障用）
        player: 播放器标识
    """

    timestamp: str
    title: str
    artist: str
    in_library: Optional[bool]
    full_title: str
    player: str

    # ---------- 派生展示字段 ----------

    @property
    def status_key(self) -> str:
        if self.in_library is None:
            return "unknown"
        return "in_library" if self.in_library else "not_in_library"

    @property
    def status_text(self) -> str:
        if self.in_library is None:
            return "未知"
        return "在曲库" if self.in_library else "不在库"

    @property
    def is_missing(self) -> bool:
        return self.in_library is False

    @property
    def is_unknown(self) -> bool:
        return self.in_library is None

    @property
    def player_name(self) -> str:
        return player_display_name(self.player)

    @property
    def player_short_name(self) -> str:
        return player_short_name(self.player)

    # ---------- 构造 / 导出 ----------

    @classmethod
    def create(
        cls,
        song: SongInfo,
        in_library: Optional[bool],
        full_title: str,
        timestamp: Optional[str] = None,
    ) -> "PlayRecord":
        """由 SongInfo 构造播放记录，统一时间格式。"""
        return cls(
            timestamp=timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            title=song.title,
            artist=song.artist,
            in_library=in_library,
            full_title=full_title,
            player=song.player,
        )

    def csv_row(self) -> Dict[str, Any]:
        """返回 CSV 导出的字段字典（顺序由 UI 决定）。

        使用 csv 模块写文件，字段中即使包含逗号/换行也不会破坏格式。
        """
        if self.in_library is None:
            in_library_text = "未知"
        else:
            in_library_text = "是" if self.in_library else "否"
        return {
            "播放时间": self.timestamp,
            "歌曲名称": self.title,
            "歌手": self.artist,
            "播放器": self.player_name,
            "在曲库中": in_library_text,
        }


@dataclass
class MissingSong:
    """待补清单中的一首歌。

    ``key`` 由标准化后的歌手/歌名生成，用于跨播放器去重；其余字段保留展示
    原文，避免把用户看到的歌名改成标准化结果。
    """

    key: str
    title: str
    artist: str
    player: str
    first_seen: str
    last_seen: str
    play_count: int = 1
    status: str = MISSING_STATUS_PENDING

    @property
    def player_name(self) -> str:
        return player_display_name(self.player)

    @property
    def player_short_name(self) -> str:
        return player_short_name(self.player)

    @property
    def status_text(self) -> str:
        return MISSING_STATUS_LABELS.get(self.status, self.status)

    @property
    def is_pending(self) -> bool:
        return self.status == MISSING_STATUS_PENDING

    @property
    def copy_text(self) -> str:
        return f"{self.title} - {self.artist}"

    @property
    def search_query(self) -> str:
        return f"{self.title} {self.artist}".strip()

    def csv_row(self) -> Dict[str, Any]:
        return {
            "歌曲名称": self.title,
            "歌手": self.artist,
            "播放器": self.player_name,
            "首次发现": self.first_seen,
            "最后发现": self.last_seen,
            "发现次数": self.play_count,
            "状态": self.status_text,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "artist": self.artist,
            "player": self.player,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "play_count": self.play_count,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MissingSong":
        """从 JSON 字典恢复；缺失/非法字段使用安全默认值。"""
        try:
            play_count = int(data.get("play_count", 1) or 1)
        except (TypeError, ValueError):
            play_count = 1
        return cls(
            key=str(data.get("key", "")),
            title=str(data.get("title", "")),
            artist=str(data.get("artist", "")),
            player=str(data.get("player", "")),
            first_seen=str(data.get("first_seen", "")),
            last_seen=str(data.get("last_seen", "")),
            play_count=max(1, play_count),
            status=str(data.get("status", MISSING_STATUS_PENDING)),
        )
