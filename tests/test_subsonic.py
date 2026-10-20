# -*- coding: utf-8 -*-
"""Subsonic 客户端测试（本地假服务器，不访问外网）。

若未安装运行期依赖 requests，则整个测试类跳过。
"""

import hashlib
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

try:
    from app.services.subsonic import (
        SubsonicClient,
        SubsonicError,
        normalize_server_url,
    )

    HAS_REQUESTS = True
except ImportError:  # pragma: no cover - 仅用于未安装依赖的环境
    HAS_REQUESTS = False


SONG_A = {"id": "1", "title": "晴天", "artist": "周杰伦", "album": "叶惠美"}
SONG_B = {"id": "2", "title": "稻香", "artist": "周杰伦", "album": "魔杰座"}
SONG_C = {"id": "3", "title": "晴天 (Live)", "artist": "周杰伦", "album": "演唱会"}
SONG_D = {"id": "4", "title": "七里香", "artist": "周杰伦", "album": "七里香"}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler API)
        parsed = urlparse(self.path)
        params = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        self.server.requests.append((parsed.path, params))

        if self.server.mode == "search3_unsupported" and parsed.path.endswith("/search3"):
            payload = {
                "subsonic-response": {
                    "status": "failed",
                    "version": "1.16.1",
                    "error": {"code": 70, "message": "Search not supported"},
                }
            }
        elif self.server.mode == "error":
            payload = {
                "subsonic-response": {
                    "status": "failed",
                    "version": "1.16.1",
                    "error": {"code": 40, "message": "Wrong username or password"},
                }
            }
        else:
            query = params.get("query", "")
            songs = self.server.responses.get(query, [])
            # 模拟 Subsonic 单条结果返回 dict 的行为
            song_value = songs[0] if len(songs) == 1 else songs
            result_key = (
                "searchResult2" if parsed.path.endswith("/search2") else "searchResult3"
            )
            payload = {
                "subsonic-response": {
                    "status": "ok",
                    "version": "1.16.1",
                    result_key: {"song": song_value},
                }
            }

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # 静默测试输出
        pass


@unittest.skipUnless(HAS_REQUESTS, "需要安装 requests")
class TestSubsonicClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.server.daemon_threads = True
        cls.server.requests = []
        cls.server.responses = {}
        cls.server.mode = "ok"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}/"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.server.requests.clear()
        self.server.mode = "ok"
        self.server.responses = {
            "周杰伦 晴天": [SONG_A, SONG_B],
            "晴天": [SONG_A, SONG_C],
            "周杰伦": [SONG_B, SONG_D],
        }
        self.client = SubsonicClient(self.base_url, "demo", "secret")
        # 测试环境可能配置了 HTTP_PROXY，强制本地请求不走代理
        self.client.session.trust_env = False

    def test_normalize_server_url(self):
        self.assertEqual(
            normalize_server_url(" https://music.example.com/rest/search3/?x=1 "),
            "https://music.example.com",
        )
        self.assertEqual(
            normalize_server_url("https://music.example.com/sub/rest/ping"),
            "https://music.example.com/sub",
        )
        self.assertEqual(normalize_server_url(""), "")

    def test_ping_returns_server_info(self):
        info = self.client.ping()
        self.assertEqual(info["api_version"], "1.16.1")

    def test_token_authentication(self):
        self.client.search_song("周杰伦", "晴天")
        self.assertTrue(self.server.requests)
        _path, params = self.server.requests[0]
        expected = hashlib.md5(("secret" + params["s"]).encode("utf-8")).hexdigest()
        self.assertEqual(params["t"], expected)
        self.assertEqual(params["u"], "demo")
        self.assertEqual(params["f"], "json")
        self.assertNotIn("p", params)  # 不应发送明文密码

    def test_search_deduplicates_by_song_id(self):
        songs = self.client.search_song("周杰伦", "晴天")
        self.assertEqual([song["id"] for song in songs], ["1", "2", "3", "4"])
        self.assertEqual(len(self.server.requests), 3)  # 三种查询策略

    def test_search_handles_single_song_dict(self):
        self.server.responses = {"晴天": [SONG_A]}
        songs = self.client.search_song("未知歌手", "晴天")
        self.assertEqual(len(songs), 1)
        self.assertEqual(songs[0]["id"], "1")

    def test_find_exact_match(self):
        self.assertTrue(self.client.find_exact_match("周杰伦", "晴天"))

    def test_find_exact_match_early_stop(self):
        self.assertTrue(self.client.find_exact_match("周杰伦", "晴天"))
        self.assertEqual(len(self.server.requests), 1)

    def test_search3_falls_back_to_search2(self):
        self.server.mode = "search3_unsupported"
        self.server.responses = {"周杰伦 晴天": [SONG_A]}
        self.assertTrue(self.client.find_exact_match("周杰伦", "晴天"))
        paths = [path for path, _params in self.server.requests]
        self.assertEqual(paths[:2], ["/rest/search3", "/rest/search2"])

    def test_find_exact_match_propagates_error(self):
        self.server.mode = "error"
        with self.assertRaises(SubsonicError):
            self.client.find_exact_match("周杰伦", "晴天")

    def test_find_exact_match_negative(self):
        self.server.responses = {"周杰伦 晴天": [SONG_D]}
        self.assertFalse(self.client.find_exact_match("周杰伦", "晴天"))

    def test_api_error_raises(self):
        self.server.mode = "error"
        with self.assertRaises(SubsonicError) as ctx:
            self.client._make_request("ping")
        self.assertIn("用户名或密码错误", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
