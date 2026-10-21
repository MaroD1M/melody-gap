# -*- coding: utf-8 -*-
"""Windows SMTC（系统媒体会话）播放检测。

通过 ``Windows.Media.Control`` 读取系统媒体会话，不依赖播放器窗口是否可见。
因此关闭主窗口、退到托盘、只显示悬浮歌词时，只要播放器注册了 SMTC，仍能
拿到歌曲信息。

线程模型
--------
``SmtcDetector`` 在独立 daemon 线程中运行 asyncio 事件循环，定期刷新一份
不可变快照。监控线程只读取快照，WinRT 对象不会跨线程传递。

平台/依赖
---------
* 只在 Windows 上启用；
* WinRT 依赖使用懒加载，缺失时自动降级为窗口标题检测；
* 所有异步调用都有超时，避免 WinRT 偶发挂起拖死监控线程。
"""

import asyncio
import logging
import os
import threading
import time
from typing import Dict, List, Optional, Tuple

from app.constants import (
    PLAYBACK_SOURCE_SMTC,
    PLAYBACK_STATUS_PAUSED,
    PLAYBACK_STATUS_PLAYING,
    PLAYBACK_STATUS_STOPPED,
    PLAYBACK_STATUS_UNKNOWN,
    SMTC_METADATA_TIMEOUT_SECONDS,
    SMTC_POLL_INTERVAL_SECONDS,
    SMTC_REQUEST_TIMEOUT_SECONDS,
    SUPPORTED_PLAYERS,
)
from app.models import PlaybackCandidate, SongInfo
from app.services.title_parser import parse_title

logger = logging.getLogger(__name__)

# SMTC 播放状态枚举的数值映射（Windows.Media.Control）。
_STATUS_BY_VALUE = {
    3: PLAYBACK_STATUS_STOPPED,
    4: PLAYBACK_STATUS_PLAYING,
    5: PLAYBACK_STATUS_PAUSED,
}
_STATUS_PRIORITY = {
    PLAYBACK_STATUS_PLAYING: 3,
    PLAYBACK_STATUS_PAUSED: 2,
    PLAYBACK_STATUS_STOPPED: 1,
    PLAYBACK_STATUS_UNKNOWN: 0,
}


def normalize_playback_status(value: object) -> str:
    """把 WinRT 播放状态枚举统一为小写字符串。"""
    if value is None:
        return PLAYBACK_STATUS_UNKNOWN

    text = str(value).lower()
    if "playing" in text:
        return PLAYBACK_STATUS_PLAYING
    if "paused" in text:
        return PLAYBACK_STATUS_PAUSED
    if "stopped" in text or "closed" in text:
        return PLAYBACK_STATUS_STOPPED

    try:
        return _STATUS_BY_VALUE.get(int(value), PLAYBACK_STATUS_UNKNOWN)
    except (TypeError, ValueError):
        return PLAYBACK_STATUS_UNKNOWN


def match_player_by_app_id(
    app_id: str,
    players: Optional[Dict[str, Dict[str, object]]] = None,
) -> Optional[str]:
    """把 SMTC 的 AppUserModelId 映射到项目内的播放器标识。"""
    lowered = (app_id or "").strip().lower()
    if not lowered:
        return None

    players = players or SUPPORTED_PLAYERS
    for player_key, info in players.items():
        aliases = tuple(str(item).lower() for item in info.get("smtc_app_ids", ()))
        processes = tuple(str(item).lower() for item in info.get("processes", ()))
        for alias in aliases + processes:
            if alias and alias in lowered:
                return player_key
    return None


def _read_attr(obj: object, *names: str) -> object:
    """兼容 pywinrt 不同版本的 snake_case / PascalCase 属性命名。"""
    for name in names:
        try:
            return getattr(obj, name)
        except (AttributeError, TypeError):
            continue
    return None


class SmtcDetector:
    """后台轮询 Windows 媒体会话，输出每个播放器的当前候选。"""

    def __init__(
        self,
        players: Optional[Dict[str, Dict[str, object]]] = None,
        poll_interval: float = SMTC_POLL_INTERVAL_SECONDS,
    ) -> None:
        self.players = players or SUPPORTED_PLAYERS
        self.poll_interval = max(0.5, float(poll_interval))
        self._lock = threading.Lock()
        self._snapshot: Tuple[PlaybackCandidate, ...] = ()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._started = False
        self._available = False
        self._last_error: Optional[str] = None

    @property
    def platform_supported(self) -> bool:
        return os.name == "nt"

    @property
    def available(self) -> bool:
        """最近一次成功读取到 SMTC 管理器时为 True。"""
        with self._lock:
            return self._available

    @property
    def last_error(self) -> Optional[str]:
        with self._lock:
            return self._last_error

    def start(self) -> bool:
        """启动后台轮询线程；非 Windows 或依赖缺失时返回 False。"""
        if not self.platform_supported:
            return False
        with self._lock:
            if self._started:
                return self._available
            self._stop_event = threading.Event()
            self._started = True
            self._thread = threading.Thread(
                target=self._run,
                name="SmtcDetector",
                daemon=True,
            )
            self._thread.start()
        logger.info("SMTC 检测线程已启动")
        return True

    def stop(self) -> None:
        """停止后台线程（幂等）。"""
        self._stop_event.set()
        with self._lock:
            thread = self._thread
            self._thread = None
            self._started = False
            self._available = False
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
            if thread.is_alive():
                logger.warning("SMTC 检测线程未在 5 秒内退出")
        with self._lock:
            self._snapshot = ()
        logger.info("SMTC 检测线程已停止")

    def snapshot(self) -> List[PlaybackCandidate]:
        """返回当前快照（副本）。"""
        with self._lock:
            return list(self._snapshot)

    # ---------- 后台线程 ----------

    def _run(self) -> None:
        try:
            asyncio.run(self._poll_loop())
        except Exception:
            logger.exception("SMTC 检测线程异常退出")

    async def _poll_loop(self) -> None:
        try:
            from winrt.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager,
            )
        except Exception as exc:
            with self._lock:
                self._last_error = f"SMTC 依赖不可用: {exc}"
            logger.warning("无法加载 WinRT SMTC 模块，将回退窗口检测: %s", exc)
            return

        manager = None
        while not self._stop_event.is_set() and manager is None:
            try:
                manager = await asyncio.wait_for(
                    GlobalSystemMediaTransportControlsSessionManager.request_async(),
                    timeout=SMTC_REQUEST_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                with self._lock:
                    self._last_error = f"获取 SMTC 管理器失败: {exc}"
                logger.warning("获取 SMTC 管理器失败，5 秒后重试: %s", exc)
                await self._wait_or_stop(5.0)

        if manager is None:
            return

        with self._lock:
            self._available = True
            self._last_error = None
        logger.info("SMTC 媒体会话管理器已就绪")

        while not self._stop_event.is_set():
            try:
                candidates = await asyncio.wait_for(
                    self._read_sessions(manager),
                    timeout=SMTC_METADATA_TIMEOUT_SECONDS * 2 + 1.0,
                )
            except Exception as exc:
                with self._lock:
                    # 清空陈旧快照，让本轮回退到窗口检测；恢复后会自动切回。
                    self._snapshot = ()
                    self._last_error = f"读取 SMTC 会话失败: {exc}"
                logger.warning("读取 SMTC 会话失败: %s", exc)
            else:
                with self._lock:
                    self._snapshot = tuple(candidates)
                    self._last_error = None
            await self._wait_or_stop(self.poll_interval)

    async def _wait_or_stop(self, seconds: float) -> None:
        """可被 stop 打断的异步等待，避免阻塞事件循环。"""
        deadline = time.monotonic() + seconds
        while not self._stop_event.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            await asyncio.sleep(min(0.2, remaining))

    async def _read_sessions(self, manager: object) -> List[PlaybackCandidate]:
        sessions = _read_attr(manager, "get_sessions", "GetSessions")
        if callable(sessions):
            sessions = sessions()
        if not sessions:
            return []

        best: Dict[str, PlaybackCandidate] = {}
        for session in sessions:
            if self._stop_event.is_set():
                break
            app_id = _read_attr(
                session,
                "source_app_user_model_id",
                "SourceAppUserModelId",
            )
            player_key = match_player_by_app_id(str(app_id or ""), self.players)
            if player_key is None:
                logger.debug("忽略未支持的 SMTC 会话: %s", app_id)
                continue

            try:
                properties = await asyncio.wait_for(
                    session.try_get_media_properties_async(),
                    timeout=SMTC_METADATA_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                logger.debug("读取 SMTC 元数据失败 [%s]: %s", app_id, exc)
                continue

            title = str(_read_attr(properties, "title", "Title") or "").strip()
            artist = str(_read_attr(properties, "artist", "Artist") or "").strip()
            if not title:
                continue

            if not artist:
                parsed = parse_title(title, player_key)
                if parsed is not None:
                    title, artist = parsed.title, parsed.artist

            status = normalize_playback_status(self._get_playback_status(session))
            candidate = PlaybackCandidate(
                song=SongInfo(title=title, artist=artist, player=player_key),
                source=PLAYBACK_SOURCE_SMTC,
                playback_status=status,
                full_title=f"{title} - {artist}".strip(" -"),
            )
            previous = best.get(player_key)
            if previous is None or _STATUS_PRIORITY.get(
                candidate.playback_status, 0
            ) > _STATUS_PRIORITY.get(previous.playback_status, 0):
                best[player_key] = candidate

        return list(best.values())

    @staticmethod
    def _get_playback_status(session: object) -> object:
        getter = _read_attr(session, "get_playback_info", "GetPlaybackInfo")
        if not callable(getter):
            return None
        try:
            info = getter()
        except Exception:
            return None
        return _read_attr(info, "playback_status", "PlaybackStatus")
