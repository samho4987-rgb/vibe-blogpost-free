from __future__ import annotations

import unittest

from app import (
    ACTION_LABELS,
    API_KEY_PASTE_LABEL,
    ARTICLE_PASTE_LABEL,
    BUILDING_API_KEY_URL,
    ENVIRONMENT_TAB_LABEL,
    GEMINI_API_KEY_URL,
    GEMINI_USAGE_URL,
    KAKAO_API_KEY_URL,
    WRITING_PROMPT_RESET_LABEL,
    WRITING_PROMPT_SAVE_LABEL,
    WRITING_PROMPT_TAB_LABEL,
    resolve_blog_id,
)


class UICopyTests(unittest.TestCase):
    def test_blank_blog_id_uses_login_id_without_hardcoded_account(self) -> None:
        self.assertEqual(resolve_blog_id("personal-id", ""), "personal-id")
        self.assertEqual(
            resolve_blog_id("login-id", "different-blog-id"),
            "different-blog-id",
        )

    def test_enrichment_key_links_are_official(self) -> None:
        self.assertEqual(
            KAKAO_API_KEY_URL,
            "https://developers.kakao.com/console/app",
        )
        self.assertEqual(
            BUILDING_API_KEY_URL,
            "https://www.data.go.kr/data/15134735/openapi.do",
        )

    def test_article_number_has_visible_paste_button(self) -> None:
        self.assertEqual(ARTICLE_PASTE_LABEL, "붙여넣기")

    def test_writing_prompt_has_edit_save_and_reset_controls(self) -> None:
        self.assertEqual(WRITING_PROMPT_TAB_LABEL, "기본 글 작성 프롬프트")
        self.assertEqual(WRITING_PROMPT_SAVE_LABEL, "프롬프트 저장")
        self.assertEqual(WRITING_PROMPT_RESET_LABEL, "기본값 복원")
        self.assertEqual(ENVIRONMENT_TAB_LABEL, "환경설정")

    def test_api_key_paste_button_has_clear_label(self) -> None:
        self.assertEqual(API_KEY_PASTE_LABEL, "클립보드 붙여넣기")

    def test_google_ai_studio_key_link_is_official_page(self) -> None:
        self.assertEqual(
            GEMINI_API_KEY_URL,
            "https://aistudio.google.com/app/apikey",
        )
        self.assertEqual(
            GEMINI_USAGE_URL,
            "https://aistudio.google.com/rate-limit",
        )

    def test_main_actions_are_numbered_in_execution_order(self) -> None:
        self.assertEqual(
            ACTION_LABELS,
            (
                "1. 매물 조사하기",
                "2. AI로 자동 글쓰기",
                "3. 블로그로 포스팅",
                "4. (선택) 프롬프트 생성",
                "5. (선택) 결과 붙여넣기",
            ),
        )


if __name__ == "__main__":
    unittest.main()
