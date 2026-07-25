from __future__ import annotations

import json
import unittest

from naver_blog_automation.content_writer import MANDATORY_TRANSACTION_NOTICE
from naver_blog_automation.models import PropertyInfo
from naver_blog_automation.prompt_builder import (
    BODY_IMAGE_CAPTION,
    build_blog_prompt,
    build_image_prompt_text,
    build_image_prompts,
    select_body_image_concepts,
)


def _property() -> PropertyInfo:
    return PropertyInfo(
        article_no="2634925140",
        name="광안삼정그린코아",
        property_type="아파트",
        trade_type="전세",
        price="5억",
        address="부산시 수영구 광안동 172-1",
        area="공급 159.2㎡ / 전용 127.84㎡",
        floor="고/24층",
        rooms="4",
        direction="남동향",
        description="광안대교 조망 올수리",
        features=["광안대교조망", "올수리"],
        complex_name="광안삼정그린코아",
    )


class ImagePromptTests(unittest.TestCase):
    def test_thumbnail_overlay_uses_real_values(self) -> None:
        prompts = build_image_prompts(_property(), research="")
        overlay = prompts["thumbnail"]["text_overlay"]
        self.assertEqual(overlay["title"], "광안삼정그린코아")
        self.assertEqual(overlay["price"], "전세 5억")
        self.assertEqual(overlay["badge"], "48평")

    def test_body_images_are_concept_not_property_with_caption(self) -> None:
        research = "## 🚇 교통\nx\n## 🎓 학군\ny\n## 🛒 생활 편의\nz"
        prompts = build_image_prompts(_property(), research)
        body = prompts["body_images"]
        self.assertEqual(len(body), 3)
        self.assertEqual([b["concept"] for b in body], ["교통", "학군", "생활"])
        for item in body:
            self.assertEqual(item["caption"], BODY_IMAGE_CAPTION)
            # 개념 이미지는 특정 매물/건물을 재현하지 않음(무드/개념 지시 포함)
            self.assertIn("NOT a", item["prompt"])
            self.assertIn("no identifiable faces", item["prompt"])

    def test_body_concepts_fall_back_when_sections_missing(self) -> None:
        concepts = select_body_image_concepts(research="")
        self.assertEqual(len(concepts), 3)

    def test_image_prompt_text_is_valid_json(self) -> None:
        text = build_image_prompt_text(_property(), research="")
        data = json.loads(text)
        self.assertIn("thumbnail", data)
        self.assertEqual(len(data["body_images"]), 3)


class BlogPromptTests(unittest.TestCase):
    def test_blog_prompt_has_seo_rules_and_mandatory_texts(self) -> None:
        prompt = build_blog_prompt(
            _property(),
            research="## 🚇 교통\n광안역 505m",
            office_name="그린코아 공인중개사",
        )
        self.assertIn("검색 노출(SEO) 규칙", prompt)
        self.assertIn("48평", prompt)
        self.assertIn("광안동", prompt)
        self.assertIn(MANDATORY_TRANSACTION_NOTICE, prompt)
        self.assertIn("그린코아 공인중개사", prompt)
        # 포맷 뼈대(플레이스홀더) 포함
        for placeholder in ("[THUMBNAIL_IMAGE]", "[TABLE_COMPLEX]", "[TABLE_REALTOR]"):
            self.assertIn(placeholder, prompt)


if __name__ == "__main__":
    unittest.main()
