from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from naver_blog_automation.settings import (
    AppSettings,
    DEFAULT_IMAGE_PROMPT,
    DEFAULT_WRITING_PROMPT,
    build_blog_write_url,
)


class SettingsTests(unittest.TestCase):
    def test_free_tier_gemini_defaults_are_safe(self) -> None:
        settings = AppSettings()
        self.assertEqual(settings.text_model, "gemini-3.5-flash")
        self.assertEqual(settings.image_model, "")
        self.assertEqual(settings.gemini_min_request_interval_seconds, 12.5)

    def test_blog_write_url_is_derived_from_blog_id(self) -> None:
        self.assertEqual(
            build_blog_write_url("my_blog"),
            "https://blog.naver.com/my_blog?Redirect=Write",
        )
        self.assertEqual(build_blog_write_url(""), "")

    def test_posting_yaml_matches_blog_id_without_password(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = AppSettings(
                project_root=root,
                output_dir=root / "output",
                browser_profile_dir=root / "profile",
                selector_path=root / "selectors.yaml",
                sample_property_path=root / "sample.json",
                naver_login_id="login_user",
                blog_id="sample_blog",
                esiljang_login_id="office_user",
            )
            target = settings.save_posting_config()
            saved = target.read_text(encoding="utf-8")

            self.assertIn("blog_id: sample_blog", saved)
            self.assertIn("login_id: login_user", saved)
            self.assertIn("account_source: user_input", saved)
            self.assertIn(
                "blog_write_url: https://blog.naver.com/sample_blog?Redirect=Write",
                saved,
            )
            self.assertIn("password_storage: os_keyring", saved)
            self.assertIn(
                "credential_service: naver-blog-automation",
                saved,
            )
            self.assertIn("login_id: office_user", saved)
            self.assertIn("credential_service: esiljang-automation", saved)
            self.assertIn("status: credentials_only_not_connected", saved)
            self.assertNotIn("password:", saved)

    def test_enrichment_api_keys_are_saved_to_gitignored_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = AppSettings(
                project_root=root,
                output_dir=root / "output",
                browser_profile_dir=root / "profile",
                selector_path=root / "selectors.yaml",
                sample_property_path=root / "sample.json",
            )
            settings.save_enrichment_api_keys(
                kakao_rest_api_key="kakao-test",
                kakao_javascript_key="javascript-test",
                data_go_kr_service_key="public-test",
            )

            contents = (root / ".env").read_text(encoding="utf-8")
            self.assertIn("KAKAO_REST_API_KEY='kakao-test'", contents)
            self.assertIn(
                "KAKAO_JAVASCRIPT_KEY='javascript-test'",
                contents,
            )
            self.assertIn("DATA_GO_KR_SERVICE_KEY='public-test'", contents)
            self.assertEqual(
                settings.public_dict()["kakao_rest_api_key"],
                "***",
            )
            self.assertEqual(
                settings.public_dict()["kakao_javascript_key"],
                "***",
            )
            self.assertEqual(
                settings.public_dict()["data_go_kr_service_key"],
                "***",
            )

    def test_default_writing_prompt_is_automation_safe_and_complete(self) -> None:
        self.assertIn("네이버 글쓰기 SEO 빌더", DEFAULT_WRITING_PROMPT)
        self.assertIn("3,000자 이상", DEFAULT_WRITING_PROMPT)
        self.assertIn("FAQ 섹션", DEFAULT_WRITING_PROMPT)
        self.assertIn("최종 해시태그", DEFAULT_WRITING_PROMPT)
        self.assertIn("단계별 승인을 요구하거나 질문하지 않습니다", DEFAULT_WRITING_PROMPT)
        self.assertIn("실제 경험처럼 허위 서술하지 않습니다", DEFAULT_WRITING_PROMPT)

    def test_custom_writing_prompt_is_saved_with_user_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = AppSettings(
                project_root=root,
                output_dir=root / "output",
                browser_profile_dir=root / "profile",
                selector_path=root / "selectors.yaml",
                sample_property_path=root / "sample.json",
                writing_prompt="사용자 지정 SEO 프롬프트",
            )
            settings.save_user_preferences()

            saved = (root / "config" / "user_settings.json").read_text(
                encoding="utf-8"
            )
            self.assertIn("사용자 지정 SEO 프롬프트", saved)
            self.assertIn('"account_source": "user_input"', saved)

    def test_prompt_environment_file_has_highest_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prompt_path = Path(temp_dir) / "image.txt"
            prompt_path.write_text("환경 파일 이미지 프롬프트", encoding="utf-8")
            with patch.dict(
                os.environ,
                {"IMAGE_GENERATION_PROMPT_FILE": str(prompt_path)},
                clear=False,
            ):
                settings = AppSettings.load()
            self.assertEqual(
                settings.image_prompt,
                "환경 파일 이미지 프롬프트",
            )
        self.assertIn("배경색", DEFAULT_IMAGE_PROMPT)

    def test_verified_gemini_key_is_saved_to_gitignored_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = AppSettings(
                project_root=root,
                output_dir=root / "output",
                browser_profile_dir=root / "profile",
                selector_path=root / "selectors.yaml",
                sample_property_path=root / "sample.json",
            )
            settings.save_gemini_api_key("AIza-test-saved")

            env_path = root / ".env"
            contents = env_path.read_text(encoding="utf-8")
            self.assertIn("GEMINI_API_KEY='AIza-test-saved'", contents)
            self.assertEqual(settings.gemini_api_key, "AIza-test-saved")
            if os.name != "nt":
                self.assertEqual(env_path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
