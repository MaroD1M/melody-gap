# -*- coding: utf-8 -*-
"""提醒策略测试。"""

import unittest
from datetime import datetime, timedelta

from app.services.reminder import should_notify

NOW = datetime(2026, 10, 20, 12, 0, 0)


class TestReminderPolicy(unittest.TestCase):
    def test_new_missing_only_notifies_new(self):
        self.assertTrue(should_notify("new_missing", False, True, None, NOW, 10))
        self.assertFalse(should_notify("new_missing", False, False, None, NOW, 10))
        self.assertFalse(should_notify("new_missing", True, True, None, NOW, 10))

    def test_missing_mode_respects_cooldown(self):
        last = NOW - timedelta(minutes=5)
        self.assertFalse(should_notify("missing", False, False, last, NOW, 10))
        self.assertTrue(should_notify("missing", False, False, last, NOW, 0))
        self.assertTrue(
            should_notify("missing", False, False, NOW - timedelta(minutes=11), NOW, 10)
        )

    def test_all_mode_notifies_in_library(self):
        self.assertTrue(should_notify("all", True, False, None, NOW, 10))
        self.assertFalse(should_notify("all", None, False, None, NOW, 10))

    def test_off_mode_never_notifies(self):
        self.assertFalse(should_notify("off", False, True, None, NOW, 10))

    def test_unknown_never_notifies(self):
        self.assertFalse(should_notify("new_missing", None, False, None, NOW, 10))

    def test_invalid_mode_falls_back_to_new_missing(self):
        self.assertTrue(should_notify("bad", False, True, None, NOW, 10))
        self.assertFalse(should_notify("bad", False, False, None, NOW, 10))


if __name__ == "__main__":
    unittest.main()
