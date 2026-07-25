from __future__ import annotations

import unittest

from app import BlogAutomationApp


class _Root:
    def __init__(self, clipboard: str) -> None:
        self.clipboard = clipboard

    def clipboard_get(self) -> str:
        return self.clipboard


class _Entry:
    def __init__(self, value: str = "") -> None:
        self.value = value
        self.cursor = None
        self.focused = False

    def delete(self, _start, _end) -> None:
        self.value = ""

    def insert(self, _index, value: str) -> None:
        self.value = value

    def icursor(self, index) -> None:
        self.cursor = index

    def focus_set(self) -> None:
        self.focused = True


class ArticlePasteTests(unittest.TestCase):
    def test_pastes_plain_article_number(self) -> None:
        app = BlogAutomationApp.__new__(BlogAutomationApp)
        app.root = _Root("2634925140")
        app.article_entry = _Entry("old")

        result = app._paste_article_no()

        self.assertEqual(app.article_entry.value, "2634925140")
        self.assertEqual(app.article_entry.cursor, "end")
        self.assertTrue(app.article_entry.focused)
        self.assertEqual(result, "break")

    def test_extracts_article_number_from_naver_url(self) -> None:
        app = BlogAutomationApp.__new__(BlogAutomationApp)
        app.root = _Root(
            "https://new.land.naver.com/api/articles/2634925140"
        )
        app.article_entry = _Entry()

        app._paste_article_no()

        self.assertEqual(app.article_entry.value, "2634925140")


if __name__ == "__main__":
    unittest.main()
