# -*- coding: utf-8 -*-

import unittest


class FakeEntry:
    def __init__(self, value):
        self.value = value
        self.focused = False

    def get(self):
        return self.value

    def focus_set(self):
        self.focused = True


class FakeLabel:
    def __init__(self):
        self.text = ""
        self.color = ""

    def config(self, text=None, fg=None):
        if text is not None:
            self.text = text
        if fg is not None:
            self.color = fg


class FakeVar:
    def __init__(self, value=True):
        self.value = value

    def get(self):
        return self.value


class TestSettingsServerForm(unittest.TestCase):
    def _window(self):
        try:
            from app.ui.settings_window import SettingsWindow
        except Exception as exc:
            self.skipTest(f"Tk 不可用: {exc}")

        window = SettingsWindow.__new__(SettingsWindow)
        window.window = object()
        window.verify_ssl_var = FakeVar()
        window.test_status_label = FakeLabel()
        return window

    def test_password_whitespace_is_preserved(self):
        window = self._window()
        window.server_entry = FakeEntry(" HTTPS://music.example.com:4533/rest ")
        window.username_entry = FakeEntry("demo")
        window.password_entry = FakeEntry(" pass word ")

        data = window._read_server_form()

        self.assertEqual(data[0], "https://music.example.com:4533/")
        self.assertEqual(data[1], "demo")
        self.assertEqual(data[2], " pass word ")
        self.assertTrue(data[3])

    def test_missing_server_shows_inline_error_and_focuses_field(self):
        window = self._window()
        window.server_entry = FakeEntry("")
        window.username_entry = FakeEntry("demo")
        window.password_entry = FakeEntry("secret")

        data = window._read_server_form()

        self.assertIsNone(data)
        self.assertEqual(window.test_status_label.text, "请填写服务器地址")
        self.assertTrue(window.server_entry.focused)


if __name__ == "__main__":
    unittest.main()
