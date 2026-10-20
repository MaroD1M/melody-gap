# -*- coding: utf-8 -*-
"""待补清单的本地持久化。

清单只保存“确实不在曲库”的歌曲。查询失败（unknown）不会进入这里，避免
网络故障污染待补列表。所有写操作使用同一把锁，并采用临时文件 + 替换的
方式落盘，防止程序异常退出时留下半个 JSON 文件。
"""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.constants import (
    MISSING_STATUS_LABELS,
    MISSING_STATUS_PENDING,
)
from app.models import MissingSong, PlayRecord
from app.services.matcher import make_song_key

logger = logging.getLogger(__name__)


class MissingRepository:
    """待补歌曲仓库（线程安全）。

    Args:
        path: JSON 文件路径；默认由调用方传入 ``get_app_dir()`` 下的文件。
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._entries: Dict[str, MissingSong] = {}
        self.load()

    # ---------- 持久化 ----------

    def load(self) -> None:
        """从磁盘加载；文件不存在或损坏时从空清单开始。"""
        with self._lock:
            self._entries = {}
            if not self.path.exists():
                return

            try:
                with self.path.open("r", encoding="utf-8") as fp:
                    data = json.load(fp)
            except (OSError, ValueError) as exc:
                logger.exception("读取待补清单失败，将使用空清单: %s", exc)
                self._backup_corrupt_locked()
                return

            raw_entries = data.get("songs", []) if isinstance(data, dict) else data
            if not isinstance(raw_entries, list):
                logger.warning("待补清单格式不正确，将使用空清单")
                self._backup_corrupt_locked()
                return

            for raw in raw_entries:
                if not isinstance(raw, dict):
                    continue
                entry = MissingSong.from_dict(raw)
                if not entry.title or not entry.artist:
                    continue
                if not entry.key:
                    entry.key = make_song_key(entry.artist, entry.title)
                if entry.status not in MISSING_STATUS_LABELS:
                    entry.status = MISSING_STATUS_PENDING
                self._entries[entry.key] = entry

            logger.info("待补清单已加载: %d 首", len(self._entries))

    def _backup_corrupt_locked(self) -> None:
        if not self.path.exists():
            return
        suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = self.path.with_name(f"{self.path.stem}.corrupt_{suffix}{self.path.suffix}")
        try:
            self.path.replace(backup)
            logger.warning("损坏的待补清单已备份到: %s", backup)
        except OSError:
            logger.exception("备份损坏的待补清单失败")

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "songs": [
                entry.to_dict()
                for entry in sorted(
                    self._entries.values(),
                    key=lambda item: item.first_seen,
                )
            ],
        }
        temp_path = self.path.with_name(f"{self.path.name}.tmp")
        with temp_path.open("w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2)
        temp_path.replace(self.path)

    # ---------- 查询 ----------

    def snapshot(self) -> List[MissingSong]:
        """返回当前清单快照（副本），供 UI 安全遍历。"""
        with self._lock:
            return [MissingSong.from_dict(entry.to_dict()) for entry in self._entries.values()]

    def get(self, key: str) -> Optional[MissingSong]:
        with self._lock:
            entry = self._entries.get(key)
            return MissingSong.from_dict(entry.to_dict()) if entry else None

    def count_pending(self) -> int:
        with self._lock:
            return sum(1 for entry in self._entries.values() if entry.is_pending)

    # ---------- 写入 ----------

    def add_missing(self, record: PlayRecord) -> Tuple[Optional[MissingSong], bool]:
        """记录一首缺失歌曲。

        Returns:
            ``(entry, created)``；``created`` 表示本次是否新建。查询失败
            （``in_library is None``）或已在库时不写入。
        """
        if record.in_library is not False:
            return None, False

        key = make_song_key(record.artist, record.title)
        with self._lock:
            existing = self._entries.get(key)
            if existing is not None:
                existing.last_seen = record.timestamp
                existing.play_count += 1
                self._save_locked()
                return MissingSong.from_dict(existing.to_dict()), False

            entry = MissingSong(
                key=key,
                title=record.title,
                artist=record.artist,
                player=record.player,
                first_seen=record.timestamp,
                last_seen=record.timestamp,
            )
            self._entries[key] = entry
            self._save_locked()
            return MissingSong.from_dict(entry.to_dict()), True

    def resolve_song(self, artist: str, title: str) -> bool:
        """歌曲已在曲库时从待补清单移除。"""
        return self.remove_key(make_song_key(artist, title))

    def remove_key(self, key: str) -> bool:
        with self._lock:
            if key not in self._entries:
                return False
            del self._entries[key]
            self._save_locked()
            return True

    def set_status(self, key: str, status: str) -> bool:
        if status not in MISSING_STATUS_LABELS:
            raise ValueError(f"未知的待补状态: {status}")
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return False
            entry.status = status
            self._save_locked()
            return True

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._save_locked()
