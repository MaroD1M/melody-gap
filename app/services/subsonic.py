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
from urllib.parse import urlsplit, urlunsplit

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


def normalize_server_url(server_url: str) -> str:
    """把用户填写的服务器地址规范为 API 根地址。

    - 去掉首尾空白与末尾斜杠；
    - 如果误填了 ``/rest``、``/rest/ping`` 等 API 路径，自动去掉；
    - 保留协议、主机、端口和反向代理子路径。

    返回不带末尾斜杠的地址；空输入返回空字符串。
    """
    url = (server_url or "").strip().rstrip("/")
    if not url:
        return ""

    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    lowered = path.lower()
    for suffix in ("/rest/search3", "/rest/search2", "/rest/ping", "/rest"):
        if lowered.endswith(suffix):
            path = path[: -len(suffix)].rstrip("/")
            break
    return urlunsplit((parts.scheme, parts.netloc, path, "", "")).rstrip("/")


class SubsonicError(Exception):
    """Subsonic 请求/协议错误（带用户可读中文消息与可选错误码）。"""

    def __init__(self, message: str, code: int = 0) -> None:
        super().__init__(message)
        self.code = code


class SubsonicClient:
    """Subsonic API 客户端。

    Args:
        server_url: 服务器根地址，如 ``https://music.example.com:4533/``
        username: 用户名
        password: 密码
        client_name: 客户端标识（写入服务器日志）
        timeout: 单次请求超时（秒）
        matcher: 匹配器实例，默认使用标准参数
        verify_ssl: 是否校验 HTTPS 证书；仅自签名服务器才建议关闭
    """

    def __init__(
        self,
        server_url: str,
        username: str,
        password: str,
        client_name: str = SUBSONIC_CLIENT_NAME,
        timeout: int = SUBSONIC_REQUEST_TIMEOUT,
        matcher: Optional[SongMatcher] = None,
        verify_ssl: bool = True,
    ) -> None:
        self.server_url = normalize_server_url(server_url)
        self.username = username
        self.password = password
        self.client_name = client_name
        self.timeout = timeout
        self.matcher = matcher or SongMatcher()
        self.api_version = SUBSONIC_API_VERSION
        self.verify_ssl = verify_ssl
        if not verify_ssl:
            try:
                import urllib3

                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            except Exception:  # pragma: no cover - 仅影响警告展示
                pass

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

        response = None
        for attempt in range(2):
            try:
                response = self.session.get(
                    url,
                    params=request_params,
                    timeout=request_timeout,
                    verify=self.verify_ssl,
                )
                response.raise_for_status()
                break
            except requests.exceptions.SSLError as exc:
                raise SubsonicError(
                    "HTTPS 证书校验失败，请检查证书，或在设置中关闭证书校验",
                    code=-2,
                ) from exc
            except requests.exceptions.Timeout as exc:
                if attempt == 0:
                    logger.debug("请求超时，重试一次: %s", endpoint)
                    continue
                raise SubsonicError(
                    "连接超时，请检查服务器地址和网络连接", code=-1
                ) from exc
            except requests.exceptions.ConnectionError as exc:
                if attempt == 0:
                    logger.debug("连接失败，重试一次: %s", endpoint)
                    continue
                raise SubsonicError(
                    "连接失败，请检查服务器地址是否正确", code=-2
                ) from exc
            except requests.exceptions.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                if status == 401:
                    raise SubsonicError("认证失败，请检查用户名和密码", code=401) from exc
                if status == 404:
                    raise SubsonicError(
                        "服务器地址不存在或路径错误", code=404
                    ) from exc
                raise SubsonicError(f"HTTP 错误 {status}", code=status) from exc
            except requests.exceptions.RequestException as exc:
                raise SubsonicError(f"网络请求失败: {exc}", code=-3) from exc

        if response is None:  # pragma: no cover - 防御性分支
            raise SubsonicError("网络请求失败", code=-3)

        try:
            data = response.json()
        except ValueError as exc:
            raise SubsonicError(
                "服务器响应格式错误，请检查服务器地址", code=-4
            ) from exc

        if not isinstance(data, dict):
            raise SubsonicError("服务器响应格式错误，请检查服务器地址", code=-4)

        payload = data.get("subsonic-response") or {}
        if not isinstance(payload, dict):
            raise SubsonicError("服务器响应格式错误，请检查服务器地址", code=-4)
        if payload.get("status") != "ok":
            error = payload.get("error") or {}
            code = int(error.get("code", 0) or 0)
            message = error.get("message", "未知错误")
            if code == 40:
                raise SubsonicError("用户名或密码错误", code=code)
            if code == 50:
                raise SubsonicError("用户未授权访问此资源", code=code)
            raise SubsonicError(f"API 错误 ({code}): {message}", code=code)

        return payload

    # ---------- 连接测试 ----------

    def ping(self) -> Dict[str, str]:
        """执行 ``ping`` 并返回服务器信息，供设置窗口“测试连接”使用。"""
        payload = self._make_request("ping")
        return {
            "type": str(payload.get("type") or ""),
            "server_version": str(payload.get("serverVersion") or ""),
            "api_version": str(payload.get("version") or ""),
        }

    # ---------- 搜索 ----------

    @staticmethod
    def _extract_songs(payload: Dict[str, Any], result_key: str) -> List[Dict[str, Any]]:
        """从 search2/search3 响应中提取歌曲列表。"""
        songs = (payload.get(result_key) or {}).get("song", [])
        # Subsonic 在只有一首结果时可能返回 dict 而不是 list
        if isinstance(songs, dict):
            return [songs]
        return list(songs or [])

    def _search_endpoint(
        self,
        endpoint: str,
        result_key: str,
        query: str,
        song_count: int,
    ) -> List[Dict[str, Any]]:
        payload = self._make_request(
            endpoint,
            {
                "query": query.strip(),
                "songCount": song_count,
                "artistCount": 0,
                "albumCount": 0,
            },
        )
        return self._extract_songs(payload, result_key)

    def _search(self, query: str, song_count: int) -> List[Dict[str, Any]]:
        """执行一次搜索，返回歌曲列表。

        优先 ``search3``；若服务器返回“未知错误/未找到/参数不支持”等错误，
        自动回退到更老的 ``search2``。认证、网络等错误不会回退，直接抛出。
        """
        if not query.strip():
            return []

        try:
            return self._search_endpoint(
                "search3", "searchResult3", query, song_count
            )
        except SubsonicError as exc:
            if exc.code not in (0, 10, 70):
                raise
            logger.info("search3 不可用，尝试 search2: %s", exc)
            return self._search_endpoint(
                "search2", "searchResult2", query, song_count
            )

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
