from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from naver_blog_automation.naver_blog import NaverBlogError, NaverBlogPoster


class _Page:
    def __init__(self) -> None:
        self.url = ""
        self.goto_calls: list[str] = []

    def goto(self, url: str, **_kwargs) -> None:
        self.url = url
        self.goto_calls.append(url)


class NaverBlogWriteUrlTests(unittest.TestCase):
    def _poster(self, root: Path, write_url: str = "") -> NaverBlogPoster:
        selector_path = root / "selectors.yaml"
        selector_path.write_text("editor: {}\n", encoding="utf-8")
        return NaverBlogPoster(
            profile_dir=root / "profile",
            selector_path=selector_path,
            write_url=write_url,
        )

    def test_editor_url_always_matches_blog_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            poster = self._poster(
                Path(temp_dir),
                write_url="https://blog.naver.com/wrong?Redirect=Write",
            )
            page = _Page()
            with patch.object(poster, "_wait_for_editor", return_value="scope"):
                result = poster._open_editor(page, "actual_blog")

            self.assertEqual(result, "scope")
            self.assertEqual(
                page.goto_calls,
                ["https://blog.naver.com/actual_blog?Redirect=Write"],
            )

    def test_direct_write_url_is_single_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            poster = self._poster(Path(temp_dir))
            page = _Page()
            with patch.object(
                poster,
                "_wait_for_editor",
                side_effect=[NaverBlogError("not ready"), "scope"],
            ):
                result = poster._open_editor(page, "actual_blog")

            self.assertEqual(result, "scope")
            self.assertEqual(
                page.goto_calls,
                [
                    "https://blog.naver.com/actual_blog?Redirect=Write",
                    "https://blog.naver.com/PostWriteForm.naver?blogId=actual_blog",
                ],
            )


if __name__ == "__main__":
    unittest.main()
