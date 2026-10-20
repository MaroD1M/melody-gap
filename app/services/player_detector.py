# -*- coding: utf-8 -*-
"""Windows 播放器检测。

检测原理
--------
1. 用 psutil 缓存目标进程（qqmusic.exe / cloudmusic.exe 等）的 PID；
2. 用 Win32 ``EnumWindows`` 枚举所有可见窗口；
3. 通过 ``GetWindowThreadProcessId`` 把窗口归属到进程；
4. 取窗口标题，经 :mod:`app.services.title_parser` 过滤和解析。

性能考虑
--------
* 进程扫描较重，缓存 ``PROCESS_CACHE_TTL_SECONDS`` 秒；
* 窗口枚举只读取标题，开销可接受，每 2 秒一次。

平台限制
--------
本模块只在 Windows 上返回数据；其它平台会记录一次警告并返回 None，
方便在 Linux/macOS 上导入模块、运行单元测试和做静态检查。
"""

import ctypes
import logging
import os
import time
from typing import Dict, List, Optional, Set, Tuple

import psutil

from app.constants import (
    MONITOR_INTERVAL_SECONDS,
    PROCESS_CACHE_TTL_SECONDS,
    SUPPORTED_PLAYERS,
)
from app.services.title_parser import is_valid_song_title, select_best_title

logger = logging.getLogger(__name__)


class PlayerDetector:
    """检测当前正在播放的歌曲。

    该类不启动线程，也不依赖 UI；由 :class:`app.services.monitor.MusicMonitor`
    在监控线程中按固定间隔调用 ``get_current_playing()``。
    """

    def __init__(self, players: Optional[Dict[str, Dict[str, object]]] = None) -> None:
        self.players = players or SUPPORTED_PLAYERS
        self._pid_cache: Dict[str, Set[int]] = {}
        self._cache_updated_at = 0.0
        if not self.platform_supported:
            logger.warning("当前平台不是 Windows，播放器检测不可用")

    @property
    def platform_supported(self) -> bool:
        """当前平台是否支持窗口标题检测。"""
        return os.name == "nt"

    # ---------- 进程缓存 ----------

    def update_process_cache(self, force: bool = False) -> None:
        """刷新播放器进程 PID 缓存。"""
        now = time.monotonic()
        if not force and now - self._cache_updated_at < PROCESS_CACHE_TTL_SECONDS:
            return

        cache: Dict[str, Set[int]] = {}
        try:
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    name = (proc.info.get("name") or "").lower()
                    if not name:
                        continue
                    for player_key, info in self.players.items():
                        process_names = tuple(str(p).lower() for p in info["processes"])
                        if name in process_names:
                            cache.setdefault(player_key, set()).add(proc.info["pid"])
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as exc:  # psutil 在极端情况下可能抛出系统异常
            logger.warning("刷新进程缓存失败: %s", exc)
            return

        self._pid_cache = cache
        self._cache_updated_at = now
        if cache:
            logger.debug(
                "播放器进程: %s",
                {key: sorted(pids) for key, pids in cache.items()},
            )

    # ---------- 窗口枚举 ----------

    def get_window_titles(self, player_key: str) -> List[str]:
        """返回指定播放器（按 PID 归属）的所有有效歌曲窗口标题。"""
        if not self.platform_supported:
            return []

        pids = self._pid_cache.get(player_key)
        if not pids:
            return []

        try:
            user32 = ctypes.windll.user32
        except AttributeError:  # 理论上不会发生，防御性处理
            return []

        titles: List[str] = []
        # HWND / LPARAM 用 c_void_p 表示，跨 32/64 位都安全
        enum_proc_type = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p
        )

        def _callback(hwnd, _lparam):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True

                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True

                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                title = buffer.value

                pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value not in pids:
                    return True

                if is_valid_song_title(title, player_key):
                    titles.append(title)
            except Exception:
                # 单个窗口读取失败不应影响其他窗口
                pass
            return True

        try:
            user32.EnumWindows(enum_proc_type(_callback), 0)
        except Exception as exc:
            logger.warning("枚举窗口失败: %s", exc)

        return titles

    # ---------- 组合查询 ----------

    def get_current_playing(self) -> Optional[Tuple[str, str]]:
        """返回 ``(player_key, window_title)``；没有播放器时返回 None。"""
        if not self.platform_supported:
            return None

        self.update_process_cache()

        for player_key in self.players:
            if player_key not in self._pid_cache:
                continue
            titles = self.get_window_titles(player_key)
            best = select_best_title(titles)
            if best:
                return player_key, best

        return None


# 供调试/手工测试时直接运行：python -m app.services.player_detector
if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.DEBUG)
    detector = PlayerDetector()
    while True:
        playing = detector.get_current_playing()
        print(playing)
        time.sleep(MONITOR_INTERVAL_SECONDS)
