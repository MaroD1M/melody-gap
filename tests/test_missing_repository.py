# -*- coding: utf-8 -*-
"""待补清单持久化测试。"""

import json
import tempfile
import unittest
from pathlib import Path

from app.models import PlayRecord, SongInfo
from app.services.missing_repository import MissingRepository


def make_record(
    title: str = "晴天",
    artist: str = "周杰伦",
    player: str = "qq",
    in_library=False,
    timestamp: str = "2026-10-20 12:00:00",
) -> PlayRecord:
    song = SongInfo(title=title, artist=artist, player=player)
    return PlayRecord.create(
        song=song,
        in_library=in_library,
        full_title=f"{title} - {artist}",
        timestamp=timestamp,
    )


class TestMissingRepository(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "missing_songs.json"
        self.repo = MissingRepository(self.path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_add_and_deduplicate(self):
        entry, created = self.repo.add_missing(make_record())
        self.assertTrue(created)
        self.assertEqual(entry.play_count, 1)

        entry, created = self.repo.add_missing(
            make_record(
                player="netease",
                timestamp="2026-10-20 12:05:00",
            )
        )
        self.assertFalse(created)
        self.assertEqual(entry.play_count, 2)
        self.assertEqual(entry.last_seen, "2026-10-20 12:05:00")
        self.assertEqual(self.repo.count_pending(), 1)

    def test_only_missing_records_are_added(self):
        self.repo.add_missing(make_record(in_library=True))
        self.repo.add_missing(make_record(in_library=None))
        self.assertEqual(self.repo.snapshot(), [])

    def test_persists_across_reload(self):
        self.repo.add_missing(make_record())
        reloaded = MissingRepository(self.path)
        entries = reloaded.snapshot()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].title, "晴天")
        self.assertEqual(entries[0].status, "pending")

    def test_ignore_and_restore(self):
        entry, _ = self.repo.add_missing(make_record())
        self.assertTrue(self.repo.set_status(entry.key, "ignored"))
        self.assertEqual(self.repo.count_pending(), 0)
        self.assertEqual(self.repo.get(entry.key).status, "ignored")

        self.repo.set_status(entry.key, "pending")
        self.assertEqual(self.repo.count_pending(), 1)

    def test_resolve_song(self):
        entry, _ = self.repo.add_missing(make_record())
        self.assertTrue(self.repo.resolve_song("周杰伦", "晴天"))
        self.assertIsNone(self.repo.get(entry.key))
        self.assertFalse(self.repo.resolve_song("周杰伦", "晴天"))

    def test_remove_and_clear(self):
        entry, _ = self.repo.add_missing(make_record())
        self.assertTrue(self.repo.remove_key(entry.key))
        self.assertEqual(self.repo.snapshot(), [])

        self.repo.add_missing(make_record())
        self.repo.clear()
        self.assertEqual(self.repo.snapshot(), [])

    def test_corrupt_file_is_backed_up(self):
        self.path.write_text("{not valid json", encoding="utf-8")
        repo = MissingRepository(self.path)
        self.assertEqual(repo.snapshot(), [])

        backups = list(self.path.parent.glob("missing_songs.corrupt_*.json"))
        self.assertEqual(len(backups), 1)
        self.assertFalse(self.path.exists())

    def test_invalid_play_count_is_normalized(self):
        payload = {
            "songs": [
                {
                    "key": "周杰伦|晴天",
                    "title": "晴天",
                    "artist": "周杰伦",
                    "player": "qq",
                    "first_seen": "2026-10-20 12:00:00",
                    "last_seen": "2026-10-20 12:00:00",
                    "play_count": "not-a-number",
                    "status": "pending",
                }
            ]
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        repo = MissingRepository(self.path)
        self.assertEqual(repo.snapshot()[0].play_count, 1)

    def test_unknown_status_is_normalized(self):
        payload = {
            "songs": [
                {
                    "key": "周杰伦|晴天",
                    "title": "晴天",
                    "artist": "周杰伦",
                    "player": "qq",
                    "first_seen": "2026-10-20 12:00:00",
                    "last_seen": "2026-10-20 12:00:00",
                    "play_count": 1,
                    "status": "bad-status",
                }
            ]
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        repo = MissingRepository(self.path)
        self.assertEqual(repo.snapshot()[0].status, "pending")


if __name__ == "__main__":
    unittest.main()
