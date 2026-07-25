from __future__ import annotations

import unittest

from naver_blog_automation.gemini_key import (
    GeminiKeyValidationError,
    normalize_gemini_api_key,
    validate_gemini_api_key,
)


class _Models:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def list(self, *, config=None):
        if self.fail:
            raise RuntimeError("request failed")
        return iter([object()])


class _Client:
    def __init__(self, *, fail: bool = False) -> None:
        self.models = _Models(fail=fail)


class GeminiKeyValidationTests(unittest.TestCase):
    def test_normalizes_google_key_copy_and_paste_formats(self) -> None:
        self.assertEqual(
            normalize_gemini_api_key(" GEMINI_API_KEY='AIza-example' "),
            "AIza-example",
        )
        self.assertEqual(
            normalize_gemini_api_key("GOOGLE_API_KEY=AIza-example\n"),
            "AIza-example",
        )
        self.assertEqual(
            normalize_gemini_api_key("\ufeffAIza-\u200bexample"),
            "AIza-example",
        )

    def test_validates_with_non_generating_models_request(self) -> None:
        seen_key = ""

        def factory(key: str):
            nonlocal seen_key
            seen_key = key
            return _Client()

        message = validate_gemini_api_key(
            " GEMINI_API_KEY='AIza-test-value' ",
            client_factory=factory,
        )
        self.assertEqual(seen_key, "AIza-test-value")
        self.assertIn("검증 완료", message)
        self.assertIn("Gemini 모델", message)

    def test_rejects_empty_key(self) -> None:
        with self.assertRaises(GeminiKeyValidationError):
            validate_gemini_api_key("", client_factory=lambda _key: _Client())

    def test_wraps_validation_failure_without_exposing_key(self) -> None:
        with self.assertRaises(GeminiKeyValidationError) as context:
            validate_gemini_api_key(
                "AIza-secret-value",
                client_factory=lambda _key: _Client(fail=True),
            )
        self.assertNotIn("AIza-secret-value", str(context.exception))


if __name__ == "__main__":
    unittest.main()
