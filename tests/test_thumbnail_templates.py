from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from naver_blog_automation.body_cards import create_body_cards
from naver_blog_automation.models import PropertyInfo
from naver_blog_automation.thumbnail import (
    TEMPLATE_LABELS,
    TEMPLATE_PALETTES,
    apply_template_to_prompt,
    create_demo_thumbnail,
    parse_template,
    template_colors,
)


def _sample_property() -> PropertyInfo:
    return PropertyInfo(
        article_no="2412345678",
        name="일광 신축 아파트",
        property_type="아파트",
        trade_type="전세",
        price="3억 5,000",
        address="부산 기장군 일광읍",
        area="공급 84㎡ / 전용 59.8㎡",
        floor="7/15층",
        rooms="3",
        direction="남동향",
        description="테스트",
        features=["역세권", "신축", "주차 여유"],
    )


class TemplateParsingTests(unittest.TestCase):
    def test_default_template_is_classic(self) -> None:
        self.assertEqual(parse_template(""), "classic")
        self.assertEqual(parse_template("색상만 적은 프롬프트"), "classic")

    def test_korean_and_english_aliases(self) -> None:
        self.assertEqual(parse_template("템플릿: 모던"), "modern")
        self.assertEqual(parse_template("템플릿: bold"), "bold")
        self.assertEqual(parse_template("템플릿: 사진"), "photo")

    def test_unknown_template_falls_back_to_classic(self) -> None:
        self.assertEqual(parse_template("템플릿: 없는이름"), "classic")

    def test_prompt_color_overrides_template_palette(self) -> None:
        colors = template_colors("modern", "배경색: #123456")
        self.assertEqual(colors["배경색"], "#123456")
        self.assertEqual(
            colors["구분선 색상"],
            TEMPLATE_PALETTES["modern"]["구분선 색상"],
        )

    def test_apply_template_to_prompt_updates_line_and_colors(self) -> None:
        prompt = "제목\n\n템플릿: 클래식\n배경색: #10283D"
        updated = apply_template_to_prompt(prompt, "bold")
        self.assertIn("템플릿: 볼드", updated)
        self.assertIn(f"배경색: {TEMPLATE_PALETTES['bold']['배경색']}", updated)

    def test_apply_template_inserts_line_when_missing(self) -> None:
        updated = apply_template_to_prompt("제목만 있는 프롬프트", "modern")
        self.assertIn("템플릿: 모던", updated)


class TemplateRenderTests(unittest.TestCase):
    def test_every_template_renders_png(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            for key, label in TEMPLATE_LABELS.items():
                target = Path(temp_dir) / f"thumb_{key}.png"
                created = create_demo_thumbnail(
                    target,
                    "일광 신축 아파트",
                    "부산 기장군 일광읍",
                    "전세 · 3억 5,000 · 18평",
                    design_prompt=f"템플릿: {label}",
                )
                self.assertTrue(created.exists())
                # 대체본(글자 없는 PNG)이 아니라 실제 렌더링이면 에러 파일이 없어야 한다.
                self.assertFalse(
                    (created.parent / "_thumbnail_error.txt").exists(),
                    f"{key} 템플릿 렌더링 실패",
                )
                self.assertGreater(created.stat().st_size, 2048)

    def test_explicit_template_argument_wins_over_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "thumb.png"
            created = create_demo_thumbnail(
                target,
                "테스트 매물",
                "서울 강동구",
                "매매 · 9억",
                design_prompt="템플릿: 클래식",
                template="modern",
            )
            self.assertTrue(created.exists())


class BodyCardTests(unittest.TestCase):
    def test_creates_three_cards_with_full_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cards = create_body_cards(
                Path(temp_dir),
                _sample_property(),
                nearby={
                    "지하철역": [{"name": "일광역", "distance_m": 500}],
                    "학교": [{"name": "일광초등학교", "distance_m": 380}],
                },
                design_prompt="템플릿: 클래식",
            )
            self.assertEqual(len(cards), 3)
            for card in cards:
                self.assertTrue(card.exists())
                self.assertGreater(card.stat().st_size, 2048)

    def test_skips_nearby_card_without_nearby_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cards = create_body_cards(
                Path(temp_dir),
                _sample_property(),
                nearby={},
                design_prompt="템플릿: 모던",
            )
            names = [card.name for card in cards]
            self.assertEqual(len(cards), 2)
            self.assertFalse(any("입지" in name for name in names))

    def test_generic_checklist_when_no_features(self) -> None:
        info = _sample_property()
        info.features = []
        with tempfile.TemporaryDirectory() as temp_dir:
            cards = create_body_cards(Path(temp_dir), info, nearby={})
            names = [card.name for card in cards]
            self.assertTrue(any("체크포인트" in name for name in names))


class ColorPresetTests(unittest.TestCase):
    def test_preset_replaces_existing_color_lines(self) -> None:
        from naver_blog_automation.thumbnail import (
            COLOR_PRESETS,
            apply_color_preset_to_prompt,
        )

        prompt = "제목\n\n템플릿: 클래식\n배경색: #10283D\n구분선 색상: #D6A546"
        updated = apply_color_preset_to_prompt(prompt, "버건디")
        self.assertIn(f"배경색: {COLOR_PRESETS['버건디']['배경색']}", updated)
        # 없던 색상 줄도 추가되어 프롬프트와 결과가 일치한다.
        self.assertIn(
            f"단지명 색상: {COLOR_PRESETS['버건디']['단지명 색상']}", updated
        )

    def test_unknown_preset_returns_prompt_unchanged(self) -> None:
        from naver_blog_automation.thumbnail import apply_color_preset_to_prompt

        prompt = "제목\n배경색: #10283D"
        self.assertEqual(apply_color_preset_to_prompt(prompt, "없는프리셋"), prompt)

    def test_light_preset_renders_all_templates(self) -> None:
        import tempfile
        from naver_blog_automation.thumbnail import apply_color_preset_to_prompt

        base = "로컬 썸네일\n\n템플릿: 클래식\n배경색: #10283D"
        prompt = apply_color_preset_to_prompt(base, "웜샌드")
        with tempfile.TemporaryDirectory() as temp_dir:
            for key, label in TEMPLATE_LABELS.items():
                target = Path(temp_dir) / f"thumb_{key}.png"
                created = create_demo_thumbnail(
                    target,
                    "일광 신축 아파트",
                    "부산 기장군 일광읍",
                    "전세 · 3억 5,000 · 18평",
                    design_prompt=apply_template_to_prompt(prompt, key),
                    brand_name="브리즈부동산중개",
                    brand_contact="051-000-0000",
                )
                self.assertTrue(created.exists())
                self.assertFalse(
                    (created.parent / "_thumbnail_error.txt").exists(),
                    f"{key} 템플릿 + 웜샌드 프리셋 렌더링 실패",
                )


if __name__ == "__main__":
    unittest.main()
