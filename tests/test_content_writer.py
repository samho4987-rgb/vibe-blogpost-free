from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from naver_blog_automation.content_writer import (
    INQUIRY_HEADING,
    MANDATORY_INQUIRY_TEXT,
    MANDATORY_TRANSACTION_NOTICE,
    REQUIRED_PLACEHOLDERS,
    render_blog_markdown,
    write_blog_file,
)
from naver_blog_automation.models import BlogContent


def _content() -> BlogContent:
    return BlogContent(
        title="수영구 광안동 테스트아파트 34평 전세 | 남향 고층 매물",
        body=(
            "짧은 소개입니다.\n\n"
            "## ✨ 이 매물의 장점\n\n"
            "- **남향**입니다.\n"
            "- **고층**입니다."
        ),
        hashtags=["광안동아파트", "부산전세"],
        image_prompt="아파트 외관",
    )


class ContentWriterTests(unittest.TestCase):
    def test_renders_required_post_blog_placeholders_once_in_order(self) -> None:
        markdown = render_blog_markdown(_content())
        self.assertTrue(markdown.startswith("# 수영구 광안동"))
        positions = [markdown.index(item) for item in REQUIRED_PLACEHOLDERS]
        self.assertEqual(positions, sorted(positions))
        for placeholder in REQUIRED_PLACEHOLDERS:
            self.assertEqual(markdown.count(placeholder), 1)
        self.assertIn("## 단지 정보", markdown)
        self.assertIn("## 매물 상세 정보", markdown)
        self.assertIn("## 중개사무소 정보", markdown)
        self.assertEqual(markdown.count("## 문의 안내"), 1)
        self.assertEqual(markdown.count(MANDATORY_INQUIRY_TEXT), 1)
        self.assertGreater(
            markdown.index("## 문의 안내"),
            markdown.index("[TABLE_REALTOR]"),
        )
        # 표시·광고법 거래상태 고지: 정확히 1회, 매물 상세([TABLE_DETAIL]) 아래·중개사표 위
        self.assertEqual(markdown.count(MANDATORY_TRANSACTION_NOTICE), 1)
        self.assertGreater(
            markdown.index(MANDATORY_TRANSACTION_NOTICE),
            markdown.index("[TABLE_DETAIL]"),
        )
        self.assertLess(
            markdown.index(MANDATORY_TRANSACTION_NOTICE),
            markdown.index("[TABLE_REALTOR]"),
        )

    def test_moves_existing_inquiry_to_end_without_duplicating_required_copy(self) -> None:
        content = _content()
        content.body += (
            "\n\n## 📞 문의 안내\n\n"
            "직접 집 보기를 원하시면 연락해 주세요.\n\n"
            f"{MANDATORY_INQUIRY_TEXT}"
        )
        markdown = render_blog_markdown(content)
        self.assertEqual(markdown.count("## 문의 안내"), 1)
        self.assertEqual(markdown.count(MANDATORY_INQUIRY_TEXT), 1)
        self.assertGreater(
            markdown.index("## 문의 안내"),
            markdown.index("[TABLE_REALTOR]"),
        )

    def test_writes_mandatory_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = write_blog_file(
                Path(temp_dir),
                "2610279820",
                _content(),
            )
            self.assertEqual(
                target,
                Path(temp_dir) / "contents" / "blog_2610279820.md",
            )
            self.assertTrue(target.exists())


if __name__ == "__main__":
    unittest.main()
