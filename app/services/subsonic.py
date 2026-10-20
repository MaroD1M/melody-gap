# -*- coding: utf-8 -*-
"""Subsonic / Navidrome API 客户端。

认证机制（Subsonic API 1.16.1）
--------------------------------
每次请求生成随机 salt，并计算::

    token = MD5(password + salt)

请求参数包含 ``u``(用户名)、``t``(token)、``s``(salt)、``v``(API 版本)、
``c``(客户端名)、``f=json``。密码本身不会出现在 URL 中。

搜索策略
--------
``search3`` 分三次调用，最后按歌曲 id 去重：

1. ``artist + title``：最精确，优先命中；
2. 仅 ``title``：应对歌手名带后缀/翻译的情况；
3. 仅 ``artist``：应对歌名带版本后缀的情况。

匹配由 :class:`app.services.matcher.SongMatcher` 完成。
"""

import hashlib
import logging
import secrets
import string
from typing import Any, Dict, List, Optional

import requests

from app.constants import (
    EARLY_STOP_SCORE,
    SUBSONIC_API_VERSION,
    SUBSONIC_CLIENT_NAME,
    SUBSONIC_REQUEST_TIMEOUT,
    SUBSONIC_SONG_COUNT_FULL,
    SUBSONIC_SONG_COUNT_SINGLE,
)
from app.services.matcher import MatchResult, SongMatcher

logger = logging.getLogger(__name__)


class SubsonicError(Exception):
    """Subsonic 请求/协议错误（带用户可读中文消息）。"""


class SubsonicClient:
    """Subsonic API 客户端。

    Args:
        server_url: 服务器根地址，如 ``https://music.example.com:4533/``
        username: 用户名
        password: 密码
        client_name: 客户端标识（写入服务器日志）
        timeout: 单次请求超时（秒）
        matcher: 匹配器实例，默认使用标准参数
    """

    def __init__(
        self,
        server_url: str,
        username: str,
        password: str,
        client_name: str = SUBSONIC_CLIENT_NAME,
        timeout: int = SUBSONIC_REQUEST_TIMEOUT,
        matcher: Optional[SongMatcher] = None,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.username = username
        self.password = password
        self.client_name = client_name
        self.timeout = timeout
        self.matcher = matcher or SongMatcher()
        self.api_version = SUBSONIC_API_VERSION

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": f"{client_name}/{self.api_version}",
                "Accept": "application/json",
            }
        )

    # ---------- 认证 ----------

    def _generate_token(self) -> Dict[str, str]:
        """生成随机 salt 与对应的 MD5 token。"""
        salt = "".join(
            secrets.choice(string.ascii_letters + string.digits) for _ in range(6)
        )
        token = hashlib.md5((self.password + salt).encode("utf-8")).hexdigest()
        return {"t": token, "s": salt}

    # ---------- 请求 ----------

    def _make_request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """发起 API 请求并返回 ``subsonic-response`` 字典。

        Raises:
            SubsonicError: 网络错误、HTTP 错误、协议错误或认证失败。
        """
        request_params: Dict[str, Any] = {
            "u": self.username,
            "v": self.api_version,
            "c": self.client_name,
            "f": "json",
            **self._generate_token(),
            **(params or {}),
        }
        url = f"{self.server_url}/rest/{endpoint}"
        request_timeout = self.timeout if timeout is None else timeout

        try:
            response = self.session.get(url, params=request_params, timeout=request_timeout)
            response.raise_for_status()
        except requests.exceptions.Timeout as exc:
            raise SubsonicError("连接超时，请检查服务器地址和网络连接") from exc
        except requests.exceptions.ConnectionError as exc:
            raise SubsonicError("连接失败，请检查服务器地址是否正确") from exc
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            if status == 401:
                raise SubsonicError("认证失败，请检查用户名和密码") from exc
            if status == 404:
                raise SubsonicError("服务器地址不存在或路径错误") from exc
            raise SubsonicError(f"HTTP 错误 {status}") from exc
        except requests.exceptions.RequestException as exc:
            raise SubsonicError(f"网络请求失败: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise SubsonicError("服务器响应格式错误，请检查服务器地址") from exc

        if not isinstance(data, dict):
            raise SubsonicError("服务器响应格式错误，请检查服务器地址")

        payload = data.get("subsonic-response") or {}
        if payload.get("status") != "ok":
            error = payload.get("error") or {}
            code = error.get("code", 0)
            message = error.get("message", "未知错误")
            if code == 40:
                raise SubsonicError("用户名或密码错误")
            if code == 50:
                raise SubsonicError("用户未授权访问此资源")
            raise SubsonicError(f"API 错误 ({code}): {message}")

        return payload

    # ---------- 搜索 ----------

    def _search(self, query: str, song_count: int) -> List[Dict[str, Any]]:
        """执行一次 search3，返回歌曲列表。

        错误不再吞掉：上层需要区分“确实不在库”和“查询失败/未配置”。
        部分策略失败时由 :meth:`match_song` 决定是否继续。
        """
        if not query.strip():
            return []

        payload = self._make_request(
            "search3",
            {
                "query": query.strip(),
                "songCount": song_count,
                "artistCount": 0,
                "albumCount": 0,
            },
        )

        songs = (payload.get("searchResult3") or {}).get("song", [])
        # Subsonic 在只有一首结果时可能返回 dict 而不是 list
        if isinstance(songs, dict):
            return [songs]
        return list(songs or [])

    @staticmethod
    def _merge_unique(
        unique: Dict[str, Dict[str, Any]], songs: List[Dict[str, Any]]
    ) -> None:
        for song in songs:
            song_id = song.get("id")
            if song_id and song_id not in unique:
                unique[song_id] = song

    def _search_queries(self, artist: str, title: str):
        return (
            (f"{artist} {title}".strip(), SUBSONIC_SONG_COUNT_FULL),
            (title, SUBSONIC_SONG_COUNT_SINGLE),
            (artist, SUBSONIC_SONG_COUNT_SINGLE),
        )

    def search_song(self, artist: str, title: str) -> List[Dict[str, Any]]:
        """按三种策略搜索并去重，返回候选歌曲列表。

        任一策略失败不会中断其余策略；若所有策略都失败，则抛出最后一个
        :class:`SubsonicError`，让上层标记为“未知”而不是“不在库”。
        """
        unique: Dict[str, Dict[str, Any]] = {}
        last_error: Optional[SubsonicError] = None

        for query, song_count in self._search_queries(artist, title):
            try:
                self._merge_unique(unique, self._search(query, song_count))
            except SubsonicError as exc:
                logger.warning("搜索失败 [%s]: %s", query, exc)
                last_error = exc

        if not unique and last_error is not None:
            raise last_error

        logger.debug("搜索 \"%s - %s\" 去重后候选 %d 首", artist, title, len(unique))
        return list(unique.values())

    # ---------- 对外匹配接口 ----------

    def match_song(self, artist: str, title: str) -> MatchResult:
        """搜索并返回结构化匹配结果。

        首个“歌手+歌名”查询达到 ``EARLY_STOP_SCORE`` 时直接返回，省掉两次
        兜底搜索；若某个策略失败且最终没有命中，则抛出错误，避免把网络故障
        误判为“不在库”。
        """
        unique: Dict[str, Dict[str, Any]] = {}
        last_error: Optional[SubsonicError] = None
        result = MatchResult(matched=False, song=None, score=0.0)

        for query, song_count in self._search_queries(artist, title):
            try:
                self._merge_unique(unique, self._search(query, song_count))
            except SubsonicError as exc:
                logger.warning("搜索失败 [%s]: %s", query, exc)
                last_error = exc
                continue

            result = self.matcher.find_best_match(unique.values(), artist, title)
            if result.matched and result.score >= EARLY_STOP_SCORE:
                logger.debug(
                    "提前命中 \"%s - %s\"（评分 %.3f），跳过后续搜索",
                    artist,
                    title,
                    result.score,
                )
                return result

        if not result.matched and last_error is not None:
            raise last_error
        return result

    def find_exact_match(self, artist: str, title: str) -> bool:
        """兼容旧接口：是否在曲库中找到足够相似的歌曲。"""
        return self.match_song(artist, title).matched
