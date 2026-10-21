# -*- coding: utf-8 -*-
"""歌曲播放监控核心。

职责边界
--------
* 启动/停止后台监控线程；
* 轮询 SMTC/窗口标题，解析新歌曲；
* 调用 Subsonic 查询是否在曲库；
* 按播放器维护当前歌曲（支持 QQ 音乐 + 网易云同时播放）；
* 维护播放历史（线程安全）并发出事件回调。

**本模块不接触任何 Tkinter 对象。** 新记录通过 ``on_record`` 回调交给 UI 层，
由 UI 层放入线程安全队列、在主线程消费后再弹通知，避免旧版“监控线程直接
创建/销毁 Tk 窗口”导致的崩溃。
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from app.config_manager import ConfigManager
from app.constants import (
    MONITOR_INTERVAL_SECONDS,
    MONITOR_STOP_TIMEOUT,
    PLAYER_STATE_RESET_SECONDS,
    PLAYBACK_SOURCE_SMTC,
    PLAYBACK_SOURCE_WINDOW,
    PLAYBACK_STATUS_PLAYING,
    PLAYBACK_STATUS_UNKNOWN,
    SUPPORTED_PLAYERS,
    UNKNOWN_RETRY_MAX,
    UNKNOWN_RETRY_SECONDS,
)
from app.models import PlaybackCandidate, PlayRecord, SongInfo
from app.services.playback_detector import HybridPlaybackDetector
from app.services.subsonic import SubsonicClient, SubsonicError
from app.services.title_parser import parse_title

logger = logging.getLogger(__name__)

# 新播放记录事件：(record, song)
RecordCallback = Callable[[PlayRecord, SongInfo], None]


@dataclass
class _UnknownRetry:
    count: int = 0
    next_at: float = 0.0


class MusicMonitor:
    """音乐播放监控器。

    Args:
        config_manager: 配置管理器（读取 Subsonic 连接信息）
        on_record: 新记录回调，在**监控线程**中调用；UI 层需自行切回主线程
        detector: 播放检测器（可注入假实现做测试）
        subsonic_factory: Subsonic 客户端工厂（可注入假实现做测试）
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        on_record: Optional[RecordCallback] = None,
        detector: Optional[object] = None,
        subsonic_factory: Callable[..., SubsonicClient] = SubsonicClient,
    ) -> None:
        self.config_manager = config_manager
        self.on_record = on_record
        self.detector = detector or HybridPlaybackDetector()
        self._subsonic_factory = subsonic_factory

        self.running = False
        # 每次 start 使用独立的 Event，避免“停止超时后立刻再启动”时
        # clear 掉旧线程正在等待的事件，导致两个监控线程并存。
        self._stop_event = threading.Event()
        self._lifecycle_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

        self._history: List[PlayRecord] = []
        self._history_lock = threading.Lock()
        self._current_songs: Dict[str, SongInfo] = {}
        self._current_records: Dict[str, PlayRecord] = {}
        self._current_sources: Dict[str, str] = {}
        self._last_keys: Dict[str, Tuple[str, str]] = {}
        self._last_records: Dict[str, PlayRecord] = {}
        self._missing_since: Dict[str, float] = {}

        self._result_cache: Dict[Tuple[str, str], bool] = {}
        self._cache_lock = threading.Lock()
        self._last_query_error: Optional[str] = None
        self._query_ok = False
        self._unknown_retries: Dict[str, _UnknownRetry] = {}
        self._retry_interval = UNKNOWN_RETRY_SECONDS
        self._retry_max = UNKNOWN_RETRY_MAX

        self.subsonic: Optional[SubsonicClient] = None
        self._setup_subsonic()

    # ---------- 配置 ----------

    def _setup_subsonic(self) -> None:
        """根据配置创建/重建 Subsonic 客户端。"""
        if not self.config_manager.is_subsonic_configured():
            logger.warning("Subsonic 配置不完整，请在设置中填写服务器信息")
            self.subsonic = None
            return

        config = self.config_manager.get_subsonic_config()
        try:
            self.subsonic = self._subsonic_factory(
                server_url=config["server_url"],
                username=config["username"],
                password=config["password"],
                verify_ssl=config.get("verify_ssl", "1") != "0",
            )
            logger.info("Subsonic 客户端已初始化: %s", config["server_url"])
        except Exception as exc:
            logger.exception("初始化 Subsonic 客户端失败: %s", exc)
            self.subsonic = None

    def reload_config(self) -> None:
        """配置变更后调用：重建客户端并清空标题去重缓存。

        清空 ``_last_keys`` 是有意为之：用户刚改完服务器配置时，希望当前
        正在播放的歌曲能立即重新查询一次。
        """
        self._setup_subsonic()
        # 重新绑定而不是 clear()：监控线程可能正在读取旧字典，避免竞态
        self._last_keys = {}
        with self._cache_lock:
            self._result_cache = {}
        with self._history_lock:
            self._last_query_error = None
            self._query_ok = False
        self._reset_unknown_retry()

    # ---------- 历史记录 ----------

    @property
    def play_history(self) -> List[PlayRecord]:
        """返回历史记录快照（副本，UI 可安全遍历）。"""
        with self._history_lock:
            return list(self._history)

    @property
    def last_query_error(self) -> Optional[str]:
        """最近一次曲库查询失败的原因；成功后清空。"""
        with self._history_lock:
            return self._last_query_error

    @property
    def query_ok(self) -> bool:
        """本次运行是否至少成功完成过一次曲库查询。"""
        with self._history_lock:
            return self._query_ok

    def _set_query_state(self, ok: bool, error: Optional[str] = None) -> None:
        with self._history_lock:
            self._query_ok = ok
            self._last_query_error = error

    def _reset_unknown_retry(self, player: Optional[str] = None) -> None:
        if player is None:
            self._unknown_retries.clear()
        else:
            self._unknown_retries.pop(player, None)

    def _schedule_unknown_retry(self, player: str) -> None:
        self._unknown_retries[player] = _UnknownRetry(
            count=0,
            next_at=time.monotonic() + self._retry_interval,
        )

    def clear_history(self) -> None:
        """清空播放历史。"""
        with self._history_lock:
            self._history.clear()
        logger.info("播放历史已清空")

    @staticmethod
    def _ordered_players(players: List[str]) -> List[str]:
        order = list(SUPPORTED_PLAYERS)
        return sorted(
            players,
            key=lambda key: (order.index(key) if key in order else len(order), key),
        )

    def _ordered_current_players_locked(self) -> List[str]:
        return self._ordered_players(list(self._current_songs))

    @property
    def current_songs(self) -> Dict[str, SongInfo]:
        """按播放器返回当前歌曲快照（双播放器并列展示使用）。"""
        with self._history_lock:
            return {
                player: self._current_songs[player]
                for player in self._ordered_current_players_locked()
            }

    @property
    def current_records(self) -> Dict[str, PlayRecord]:
        """按播放器返回当前歌曲的查询结果快照。"""
        with self._history_lock:
            return {
                player: self._current_records[player]
                for player in self._ordered_current_players_locked()
                if player in self._current_records
            }

    @property
    def current_sources(self) -> Dict[str, str]:
        """按播放器返回检测来源（``smtc`` / ``window``）。"""
        with self._history_lock:
            return {
                player: self._current_sources.get(player, PLAYBACK_SOURCE_WINDOW)
                for player in self._ordered_current_players_locked()
            }

    @property
    def current_song(self) -> Optional[SongInfo]:
        """兼容旧接口：返回顺序最靠前的当前歌曲。"""
        with self._history_lock:
            players = self._ordered_current_players_locked()
            return self._current_songs[players[0]] if players else None

    @property
    def current_record(self) -> Optional[PlayRecord]:
        """兼容旧接口：返回顺序最靠前当前歌曲的查询结果。"""
        with self._history_lock:
            players = self._ordered_current_players_locked()
            if not players:
                return None
            return self._current_records.get(players[0])

    def update_current_result(
        self,
        artist: str,
        title: str,
        in_library: Optional[bool],
        player: Optional[str] = None,
    ) -> bool:
        """核验结果返回后，若仍是当前歌曲则同步更新当前卡片/历史记录。

        ``player`` 用于双播放器同时播放同一首歌时精确更新对应播放器；旧调用
        不传 ``player`` 时仍按原逻辑匹配所有同名当前歌曲。
        """
        with self._history_lock:
            players = (
                [player]
                if player is not None
                else self._ordered_current_players_locked()
            )
            updated = False
            for player_key in players:
                song = self._current_songs.get(player_key)
                record = self._current_records.get(player_key)
                if song is None or record is None:
                    continue
                if song.artist != artist or song.title != title:
                    continue
                record.in_library = in_library
                updated = True
            return updated

    # ---------- 轮询逻辑 ----------

    def _check_library(self, song: SongInfo) -> Optional[bool]:
        """查询曲库并缓存确定结果。

        Returns:
            True/False 表示在库/不在库；None 表示未配置服务器或查询失败。
        """
        if self.subsonic is None:
            self._set_query_state(False, "服务器尚未配置")
            return None

        cache_key = (song.artist, song.title)
        with self._cache_lock:
            cached = self._result_cache.get(cache_key)
        if cached is not None:
            logger.debug("曲库缓存命中: %s", song.display_text)
            self._set_query_state(True, None)
            return cached

        try:
            result = self.subsonic.find_exact_match(song.artist, song.title)
        except SubsonicError as exc:
            logger.warning("曲库查询失败: %s", exc)
            self._set_query_state(False, str(exc))
            return None
        except Exception as exc:
            logger.exception("曲库查询异常")
            self._set_query_state(False, f"查询异常: {exc}")
            return None

        with self._cache_lock:
            self._result_cache[cache_key] = result
        self._set_query_state(True, None)
        return result

    def recheck_song(self, song: SongInfo) -> Optional[bool]:
        """跳过缓存重新核验一首歌，供待补清单的“核验”功能使用。"""
        if self.subsonic is None:
            self._set_query_state(False, "服务器尚未配置")
            return None
        try:
            result = self.subsonic.find_exact_match(song.artist, song.title)
        except SubsonicError as exc:
            logger.warning("核验失败: %s", exc)
            self._set_query_state(False, str(exc))
            return None
        except Exception as exc:
            logger.exception("核验异常")
            self._set_query_state(False, f"查询异常: {exc}")
            return None

        with self._cache_lock:
            self._result_cache[(song.artist, song.title)] = result
        self._set_query_state(True, None)
        return result

    def _detect_candidates(self) -> List[PlaybackCandidate]:
        """读取检测器结果，并兼容旧的单播放器 ``get_current_playing``。"""
        get_playings = getattr(self.detector, "get_current_playings", None)
        if callable(get_playings):
            return list(get_playings())

        get_playing = getattr(self.detector, "get_current_playing", None)
        if not callable(get_playing):
            return []
        playing = get_playing()
        if not playing:
            return []

        player_key, full_title = playing
        song = parse_title(full_title, player_key)
        if song is None:
            return []
        return [
            PlaybackCandidate(
                song=song,
                source=PLAYBACK_SOURCE_WINDOW,
                playback_status=PLAYBACK_STATUS_UNKNOWN,
                full_title=full_title,
            )
        ]

    def _select_candidates(
        self, candidates: List[PlaybackCandidate]
    ) -> Dict[str, PlaybackCandidate]:
        """按播放器去重，优先保留正在播放且来自 SMTC 的候选。"""
        selected: Dict[str, PlaybackCandidate] = {}
        for candidate in candidates:
            if not candidate.title or not candidate.player:
                continue
            previous = selected.get(candidate.player)
            if previous is None:
                selected[candidate.player] = candidate
                continue
            score = (
                candidate.playback_status == PLAYBACK_STATUS_PLAYING,
                candidate.source == PLAYBACK_SOURCE_SMTC,
            )
            previous_score = (
                previous.playback_status == PLAYBACK_STATUS_PLAYING,
                previous.source == PLAYBACK_SOURCE_SMTC,
            )
            if score > previous_score:
                selected[candidate.player] = candidate
        return selected

    def _clear_inactive_players(self, active_players: set) -> None:
        """隐藏已消失播放器，并在短暂漏检后恢复原记录。

        播放器消失超过 ``PLAYER_STATE_RESET_SECONDS`` 后清空标题去重和记录
        恢复缓存，使之后重新播放同一首歌仍会生成新的播放记录。
        """
        now = time.monotonic()
        with self._history_lock:
            for player_key in active_players:
                self._missing_since.pop(player_key, None)

            tracked = set(self._current_songs) | set(self._last_keys)
            for player_key in tracked - active_players:
                self._current_songs.pop(player_key, None)
                self._current_records.pop(player_key, None)
                self._current_sources.pop(player_key, None)

                missing_since = self._missing_since.setdefault(player_key, now)
                if now - missing_since >= PLAYER_STATE_RESET_SECONDS:
                    self._last_keys.pop(player_key, None)
                    self._last_records.pop(player_key, None)
                    self._unknown_retries.pop(player_key, None)


    def _poll_once(self) -> None:
        """执行一次检测，分别更新每个正在播放的播放器。"""
        candidates = self._select_candidates(self._detect_candidates())
        if not candidates:
            self._clear_inactive_players(set())
            return

        for player_key, candidate in candidates.items():
            self._process_candidate(player_key, candidate)

        self._clear_inactive_players(set(candidates))

    def _process_candidate(
        self, player_key: str, candidate: PlaybackCandidate
    ) -> None:
        song = candidate.song
        song_key = (song.artist, song.title)
        full_title = candidate.full_title or f"{song.title} - {song.artist}"
        if song_key == self._last_keys.get(player_key):
            # 同一首歌可能因一次掉帧/隐藏窗口不可见而被短暂清空，也可能在
            # SMTC 与窗口回退之间切换来源；这些情况恢复状态但不重复写历史。
            with self._history_lock:
                self._current_songs[player_key] = song
                self._current_sources[player_key] = candidate.source
                if player_key not in self._current_records:
                    previous_record = self._last_records.get(player_key)
                    if previous_record is not None:
                        self._current_records[player_key] = previous_record
            self._retry_unknown_if_due(player_key)
            return

        with self._history_lock:
            self._current_songs[player_key] = song
            self._current_records.pop(player_key, None)
            self._current_sources[player_key] = candidate.source
        self._reset_unknown_retry(player_key)

        in_library = self._check_library(song)
        record = PlayRecord.create(
            song=song,
            in_library=in_library,
            full_title=full_title,
        )

        with self._history_lock:
            self._history.append(record)
            self._current_songs[player_key] = song
            self._current_records[player_key] = record
            self._current_sources[player_key] = candidate.source
            self._last_records[player_key] = record

        # 记录完成后再更新去重键，避免解析失败时漏记
        self._last_keys[player_key] = song_key

        if in_library is None:
            status_text = "曲库状态未知"
            self._schedule_unknown_retry(player_key)
        elif in_library:
            status_text = "在曲库"
        else:
            status_text = "不在曲库"
        logger.info(
            "检测到新歌曲 [%s] %s | %s",
            SUPPORTED_PLAYERS.get(player_key, {}).get("display_name", player_key),
            song.display_text,
            status_text,
        )

        self._emit_record(record, song)

    def _retry_unknown_if_due(self, player_key: str) -> None:
        """某个播放器查询失败时，隔一段时间自动重试。

        重试不会新增播放记录，只更新原记录的三态；成功后重新触发 on_record，
        让待补清单/通知得到更新。避免一次瞬时网络错误把歌曲永久标成“未知”。
        每个播放器独立计数，避免一个播放器拖住另一个。
        """
        retry = self._unknown_retries.get(player_key)
        if retry is None or retry.count >= self._retry_max:
            return
        if time.monotonic() < retry.next_at:
            return

        with self._history_lock:
            record = self._current_records.get(player_key)
            song = self._current_songs.get(player_key)
            if record is None or song is None or record.in_library is not None:
                return

        retry.count += 1
        retry.next_at = time.monotonic() + self._retry_interval
        logger.info(
            "重试曲库查询 [%s] (%d/%d): %s",
            player_key,
            retry.count,
            self._retry_max,
            song.display_text,
        )
        result = self._check_library(song)
        if result is None:
            return

        with self._history_lock:
            if self._current_records.get(player_key) is not record:
                return
            record.in_library = result

        self._reset_unknown_retry(player_key)
        logger.info(
            "重试成功: %s | %s",
            song.display_text,
            "在曲库" if result else "不在曲库",
        )
        self._emit_record(record, song)

    def _emit_record(self, record: PlayRecord, song: SongInfo) -> None:
        if self.on_record is None:
            return
        try:
            self.on_record(record, song)
        except Exception:
            logger.exception("记录回调执行失败")

    def _loop(self, stop_event: threading.Event) -> None:
        """监控线程主循环。

        Args:
            stop_event: 本次运行专属的停止事件（不是 self._stop_event，
                防止后续 start 覆盖）。
        """
        logger.info("监控线程已启动")
        while not stop_event.is_set():
            try:
                self._poll_once()
            except Exception:
                logger.exception("监控轮询异常，5 秒后重试")
                stop_event.wait(5)
                continue
            # 使用 wait 而不是 sleep，停止时能立即退出
            stop_event.wait(MONITOR_INTERVAL_SECONDS)
        logger.info("监控线程已停止")

    # ---------- 生命周期 ----------

    def start(self) -> None:
        """启动检测器与监控线程（幂等）。"""
        with self._lifecycle_lock:
            if self.running:
                return
            starter = getattr(self.detector, "start", None)
            if callable(starter):
                try:
                    starter()
                except Exception:
                    logger.exception("启动播放检测器失败，继续使用窗口回退")
            self._stop_event = threading.Event()
            self.running = True
            self._thread = threading.Thread(
                target=self._loop,
                args=(self._stop_event,),
                name="MusicMonitor",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """停止监控线程/检测器并等待其退出。"""
        with self._lifecycle_lock:
            if not self.running:
                return

            logger.info("正在停止监控...")
            self.running = False
            self._stop_event.set()

            if self._thread is not None and self._thread.is_alive():
                self._thread.join(timeout=MONITOR_STOP_TIMEOUT)
                if self._thread.is_alive():
                    logger.warning("监控线程未在 %.0f 秒内退出", MONITOR_STOP_TIMEOUT)
            self._thread = None

            stopper = getattr(self.detector, "stop", None)
            if callable(stopper):
                try:
                    stopper()
                except Exception:
                    logger.exception("停止播放检测器失败")
            logger.info("监控已停止")
