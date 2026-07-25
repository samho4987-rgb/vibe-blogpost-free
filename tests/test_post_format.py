from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from naver_blog_automation.models import PropertyInfo
from naver_blog_automation.naver_blog import NaverBlogPoster
from naver_blog_automation.post_format import build_property_tables


class PostFormatTests(unittest.TestCase):
    def test_tables_escape_html_and_skip_zero_building_fields(self) -> None:
        property_info = PropertyInfo(
            article_no="123",
            name="테스트 <아파트>",
            property_type="아파트",
            trade_type="매매",
            price="10억",
            address="서울",
            area="전용 84㎡",
            floor="10층",
            rooms="3",
            direction="남향",
            description="확인 & 협의",
        )
        tables = build_property_tables(
            property_info,
            {"building": {"fields": {"세대수": "0", "주용도": "공동주택"}}},
        )
        self.assertEqual(
            set(tables),
            {
                "[TABLE_COMPLEX]",
                "[TABLE_SUMMARY]",
                "[TABLE_DETAIL]",
                "[TABLE_REALTOR]",
            },
        )
        complex_html = tables["[TABLE_COMPLEX]"].html
        self.assertIn("테스트 &lt;아파트&gt;", complex_html)
        self.assertIn("공동주택", complex_html)
        self.assertNotIn(">0<", complex_html)
        self.assertIn("확인 &amp; 협의", tables["[TABLE_DETAIL]"].html)

    def test_markdown_placeholders_become_html_tables_and_headings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            selector_path = root / "selectors.yaml"
            selector_path.write_text("editor: {}\n", encoding="utf-8")
            poster = NaverBlogPoster(
                profile_dir=root / "profile",
                selector_path=selector_path,
            )
            block = build_property_tables(
                PropertyInfo(
                    article_no="1",
                    name="단지",
                    property_type="아파트",
                    trade_type="매매",
                    price="1억",
                    address="서울",
                    area="전용 59㎡",
                    floor="3층",
                    rooms="2",
                    direction="남향",
                    description="설명",
                )
            )
            html, plain = poster._markdown_html(
                "# 제목\n\n## 🏢 단지 정보\n\n[TABLE_COMPLEX]\n\n"
                "**핵심** 설명",
                block,
            )
        self.assertIn("<h2", html)
        self.assertIn("<table", html)
        self.assertIn("<strong>핵심</strong>", html)
        self.assertNotIn("[TABLE_COMPLEX]", plain)


if __name__ == "__main__":
    unittest.main()
