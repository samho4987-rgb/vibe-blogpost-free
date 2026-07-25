from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from naver_blog_automation.ai_agent import (
    AIQuotaExceededError,
    AIServiceUnavailableError,
    ContentAgent,
    gemini_retry_delay_seconds,
    is_gemini_quota_error,
    is_gemini_transient_error,
    is_non_retryable_gemini_quota,
)
from naver_blog_automation.content_writer import (
    INQUIRY_HEADING,
    MANDATORY_INQUIRY_TEXT,
)
from naver_blog_automation.models import PropertyInfo


def _property() -> PropertyInfo:
    return PropertyInfo(
        article_no="123",
        name="테스트 아파트",
        property_type="아파트",
        trade_type="전세",
        price="5억",
        address="부산시 수영구",
        area="공급 100㎡ / 전용 84㎡",
        floor="고/20층",
        rooms="3/2개",
        direction="남향",
        description="테스트 매물",
    )


class _Models:
    def __init__(self, response) -> None:
        self.response = response
        self.calls: list[dict] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class _Client:
    def __init__(self, response) -> None:
        self.models = _Models(response)
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _agent() -> ContentAgent:
    return ContentAgent(
        api_key="AIza-test",
        text_model="gemini-3.5-flash",
        image_model="gemini-3.1-flash-image",
        tone_guide="친절한 존댓말",
        writing_prompt="사용자가 수정한 SEO 작성 기준",
        min_request_interval_seconds=0,
    )


class GeminiContentAgentTests(unittest.TestCase):
    def test_recognizes_resource_exhausted_and_retry_info(self) -> None:
        error = SimpleNamespace(
            code=429,
            status="RESOURCE_EXHAUSTED",
            message="quota",
            details={
                "error": {
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.RetryInfo",
                            "retryDelay": "2.5s",
                        }
                    ]
                }
            },
        )
        self.assertTrue(is_gemini_quota_error(error))
        self.assertEqual(gemini_retry_delay_seconds(error), 2.5)

    def test_quota_without_retry_info_becomes_friendly_error(self) -> None:
        class QuotaError(Exception):
            code = 429
            status = "RESOURCE_EXHAUSTED"
            message = "check your plan and billing details"
            details = {"error": {"details": []}}

        error = QuotaError("quota")
        client = _Client(SimpleNamespace())
        client.models.generate_content = lambda **_kwargs: (_ for _ in ()).throw(error)
        agent = _agent()

        with self.assertRaisesRegex(
            AIQuotaExceededError,
            "Google Gemini API 사용량 한도",
        ):
            agent._generate_content(client, model="test", contents="test")
        self.assertTrue(is_non_retryable_gemini_quota(error))

    def test_recognizes_503_high_demand_as_transient(self) -> None:
        class Unavailable(Exception):
            code = 503
            status = "UNAVAILABLE"
            message = (
                "This model is currently experiencing high demand. "
                "Spikes in demand are usually temporary. Please try again later."
            )

        error = Unavailable("503 UNAVAILABLE")
        self.assertTrue(is_gemini_transient_error(error))
        self.assertFalse(is_gemini_quota_error(error))

    def test_transient_503_retries_then_service_unavailable(self) -> None:
        class Unavailable(Exception):
            code = 503
            status = "UNAVAILABLE"
            message = "This model is currently experiencing high demand."

        class BusyModels:
            def __init__(self) -> None:
                self.calls = 0

            def generate_content(self, **_kwargs):
                self.calls += 1
                raise Unavailable("busy")

        models = BusyModels()
        client = SimpleNamespace(models=models)
        agent = _agent()
        with patch("naver_blog_automation.ai_agent.time.sleep"):
            with self.assertRaises(AIServiceUnavailableError):
                agent._generate_content(client, model="test", contents="test")
        # 최초 1회 + 재시도 2회 = 총 3회 시도 후 친절한 오류로 전환
        self.assertEqual(models.calls, 3)

    def test_short_retry_info_retries_only_once(self) -> None:
        class QuotaError(Exception):
            code = 429
            status = "RESOURCE_EXHAUSTED"
            message = "temporary quota"
            details = {
                "error": {
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.RetryInfo",
                            "retryDelay": "0s",
                        }
                    ]
                }
            }

        class RetryModels:
            def __init__(self) -> None:
                self.calls = 0

            def generate_content(self, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise QuotaError("temporary quota")
                return "retried"

        models = RetryModels()
        client = SimpleNamespace(models=models)
        agent = _agent()
        with patch("naver_blog_automation.ai_agent.time.sleep") as sleep:
            result = agent._generate_content(
                client,
                model="test",
                contents="test",
            )

        self.assertEqual(result, "retried")
        self.assertEqual(models.calls, 2)
        sleep.assert_called_once_with(0.0)

    def test_same_model_requests_are_spaced_for_five_rpm(self) -> None:
        agent = ContentAgent(
            api_key="AIza-test",
            text_model="gemini-3.5-flash",
            image_model="",
            tone_guide="친절한 존댓말",
            min_request_interval_seconds=12.5,
        )
        with (
            patch(
                "naver_blog_automation.ai_agent.time.monotonic",
                side_effect=[100.0, 100.0, 105.0, 112.5],
            ),
            patch("naver_blog_automation.ai_agent.time.sleep") as sleep,
        ):
            agent._wait_for_model_slot("gemini-3.5-flash")
            agent._wait_for_model_slot("gemini-3.5-flash")

        sleep.assert_called_once_with(7.5)

    def test_research_uses_google_search_grounding(self) -> None:
        response = SimpleNamespace(text="조사 결과", candidates=[])
        client = _Client(response)
        agent = _agent()
        with patch.object(agent, "_client", return_value=client):
            result = agent.research(_property())

        self.assertEqual(result, "조사 결과")
        self.assertEqual(client.models.calls[0]["model"], "gemini-3.5-flash")
        self.assertIsNotNone(
            client.models.calls[0]["config"].tools[0].google_search
        )
        self.assertTrue(client.closed)

    def test_free_mode_uses_local_square_thumbnail(self) -> None:
        agent = ContentAgent(
            api_key="AIza-test",
            text_model="gemini-3.5-flash",
            image_model="",
            tone_guide="친절한 존댓말",
            min_request_interval_seconds=0,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "thumbnail.png"
            result = agent.generate_thumbnail(
                SimpleNamespace(image_prompt="아파트", title="제목"),
                _property(),
                target,
            )
            self.assertEqual(result, target)
            with Image.open(target) as image:
                self.assertEqual(image.size, (1080, 1080))
                self.assertEqual(image.format, "PNG")

    def test_write_requests_json_from_gemini(self) -> None:
        response = SimpleNamespace(
            text=(
                '{"title":"제목","body":"본문","hashtags":["태그"],'
                '"image_prompt":"이미지"}'
            )
        )
        client = _Client(response)
        agent = _agent()
        with patch.object(agent, "_client", return_value=client):
            result = agent.write(_property(), "조사")

        self.assertEqual(
            result.title,
            "부산시 수영구 테스트 아파트 30평 전세 | 테스트 매물",
        )
        self.assertTrue(result.body.startswith("본문"))
        self.assertIn(INQUIRY_HEADING, result.body)
        self.assertIn(MANDATORY_INQUIRY_TEXT, result.body)
        self.assertIn(
            MANDATORY_INQUIRY_TEXT,
            client.models.calls[0]["contents"],
        )
        self.assertIn(
            "사용자가 수정한 SEO 작성 기준",
            client.models.calls[0]["contents"],
        )
        self.assertEqual(
            client.models.calls[0]["config"].response_mime_type,
            "application/json",
        )
        self.assertTrue(client.closed)

    def test_write_removes_kakao_links_from_blog_body(self) -> None:
        response = SimpleNamespace(
            text=(
                '{"title":"제목","body":"## 📍 입지 분석\\n\\n입지 설명",'
                '"hashtags":["태그"],"image_prompt":"이미지"}'
            )
        )
        research = (
            "## 📍 입지 분석\n"
            "- [카카오맵에서 위치 확인]"
            "(https://map.kakao.com/link/map/test,37.5,127.1)\n"
            "- [카카오맵 로드뷰 확인]"
            "(https://map.kakao.com/link/roadview/37.5,127.1)"
        )
        client = _Client(response)
        agent = _agent()
        with patch.object(agent, "_client", return_value=client):
            result = agent.write(_property(), research)

        self.assertNotIn("카카오맵에서 위치 확인", result.body)
        self.assertNotIn("카카오맵 로드뷰 확인", result.body)

    def test_thumbnail_writes_gemini_image_as_png(self) -> None:
        buffer = io.BytesIO()
        Image.new("RGB", (8, 8), "blue").save(buffer, format="PNG")
        response = SimpleNamespace(
            parts=[
                SimpleNamespace(
                    inline_data=SimpleNamespace(data=buffer.getvalue())
                )
            ]
        )
        client = _Client(response)
        agent = _agent()
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "thumbnail.png"
            with patch.object(agent, "_client", return_value=client):
                result = agent.generate_thumbnail(
                    SimpleNamespace(image_prompt="아파트"),
                    _property(),
                    target,
                )
            self.assertEqual(result, target)
            with Image.open(target) as image:
                self.assertEqual(image.format, "PNG")
        self.assertEqual(
            client.models.calls[0]["config"].response_modalities,
            ["IMAGE"],
        )
        self.assertTrue(client.closed)


if __name__ == "__main__":
    unittest.main()
