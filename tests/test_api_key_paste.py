from __future__ import annotations

import unittest

from app import BlogAutomationApp


class _Root:
    def clipboard_get(self) -> str:
        return "GEMINI_API_KEY='AIza-test-value'"


class _Entry:
    def __init__(self) -> None:
        self.value = ""
        self.cursor = ""
        self.focused = False

    def delete(self, _start, _end) -> None:
        self.value = ""

    def insert(self, _index, value: str) -> None:
        self.value = value

    def icursor(self, index) -> None:
        self.cursor = index

    def focus_set(self) -> None:
        self.focused = True


class APIKeyPasteTests(unittest.TestCase):
    def test_paste_replaces_entry_without_logging_key(self) -> None:
        app = BlogAutomationApp.__new__(BlogAutomationApp)
        app.root = _Root()
        app.api_key_entry = _Entry()

        result = app._paste_api_key()

        self.assertEqual(result, "break")
        self.assertEqual(
            app.api_key_entry.value,
            "GEMINI_API_KEY='AIza-test-value'",
        )
        self.assertEqual(app.api_key_entry.cursor, "end")
        self.assertTrue(app.api_key_entry.focused)


if __name__ == "__main__":
    unittest.main()
