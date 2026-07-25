from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from naver_blog_automation.ai_agent import AIQuotaExceededError, ContentAgent
from naver_blog_automation.content_writer import (
    INQUIRY_HEADING,
    MANDATORY_INQUIRY_TEXT,
)
from naver_blog_automation.enrichment import EnrichmentResult
from naver_blog_automation.settings import AppSettings
from naver_blog_automation.workflow import BlogAutomationWorkflow
from naver_blog_automation.models import PropertyInfo


class OfflineWorkflowTests(unittest.TestCase):
    def test_real_property_preview_fetches_data_without_gemini(self) -> None:
        base = AppSettings.load()
        property_info = PropertyInfo(
            article_no="9876543210",
            name="실제 데이터 아파트",
            property_type="아파트",
            trade_type="매매",
            price="9억",
            address="서울시 강동구 강일동",
            area="공급 109㎡ / 전용 84㎡",
            floor="12/25층",
            rooms="3",
            direction="남향",
            description="수집된 실제 매물 설명",
            features=["채광 좋음", "입주 협의"],
            source="네이버부동산 수집 데이터",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = replace(
                base,
                output_dir=Path(temp_dir) / "output",
                browser_profile_dir=Path(temp_dir) / "profile",
                gemini_api_key="",
                kakao_rest_api_key="",
                data_go_kr_service_key="",
            )
            workflow = BlogAutomationWorkflow(settings)
            workflow.fetcher.fetch = Mock(return_value=property_info)

            class _MapEnricher:
                @staticmethod
                def enrich(_property_info):
                    return EnrichmentResult(
                        address={
                            "latitude": "37.5",
                            "longitude": "127.1",
                            "map_url": (
                                "https://map.kakao.com/link/map/"
                                "test,37.5,127.1"
                            ),
                            "roadview_url": (
                                "https://map.kakao.com/link/roadview/"
                                "37.5,127.1"
                            ),
                        },
                        nearby={
                            "학교": [
                                {
                                    "name": "테스트학교",
                                    "distance_m": 300.0,
                                    "road_address": "서울 테스트로",
                                    "longitude": "127.11",
                                    "latitude": "37.51",
                                }
                            ]
                        },
                    )

            workflow.enricher = _MapEnricher()

            with patch.object(
                ContentAgent,
                "_client",
                side_effect=AssertionError("Gemini must not be called"),
            ):
                preview = workflow.preview(
                    article_no="9876543210",
                    sample=False,
                )

            workflow.fetcher.fetch.assert_called_once_with("9876543210", "")
            self.assertEqual(preview.property_info.name, "실제 데이터 아파트")
            self.assertTrue(preview.preview_only)
            self.assertEqual(preview.content.body, "")
            self.assertIsNone(preview.blog_markdown_path)
            self.assertIn("## 수집된 매물정보", preview.research)
            result = workflow.generate_content(preview)
            self.assertIn("**실제 데이터 아파트**", result.content.body)
            self.assertIn("**매매 9억**", result.content.body)
            self.assertIn("## 수집된 매물정보", result.research)
            self.assertIn("수집된 실제 매물 설명", result.research)
            self.assertIn("네이버부동산 수집 데이터", result.research)
            self.assertEqual(result.latitude, "37.5")
            self.assertEqual(result.longitude, "127.1")
            self.assertIn("/link/roadview/", result.roadview_url)
            self.assertIsNone(result.map_image_path)
            self.assertIn("테스트학교", result.content.body)
            self.assertNotIn("카카오맵에서 위치 확인", result.content.body)

    def test_gemini_quota_error_finishes_with_offline_fallback(self) -> None:
        base = AppSettings.load()
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = replace(
                base,
                output_dir=Path(temp_dir) / "output",
                browser_profile_dir=Path(temp_dir) / "profile",
                gemini_api_key="AIza-quota-test",
            )
            messages: list[str] = []
            workflow = BlogAutomationWorkflow(
                settings,
                progress=lambda _step, message: messages.append(message),
            )
            with patch.object(
                ContentAgent,
                "_generate_content",
                side_effect=AIQuotaExceededError("quota"),
            ):
                result = workflow.run(
                    article_no="SAMPLE-QUOTA",
                    sample=True,
                    generate_thumbnail=True,
                )

            self.assertIsNotNone(result.generation_warning)
            self.assertIn("오프라인 초안", result.generation_warning or "")
            self.assertTrue(Path(result.blog_markdown_path or "").exists())
            self.assertTrue(Path(result.thumbnail_path or "").exists())
            self.assertTrue(any("사용량 한도" in message for message in messages))

    def test_sample_workflow_creates_reviewable_artifacts(self) -> None:
        base = AppSettings.load()
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = replace(
                base,
                output_dir=Path(temp_dir) / "output",
                browser_profile_dir=Path(temp_dir) / "profile",
                gemini_api_key="",
            )
            progress: list[int] = []
            result = BlogAutomationWorkflow(
                settings,
                progress=lambda step, _message: progress.append(step),
            ).run(article_no="SAMPLE-001", sample=True)

            run_dir = Path(result.output_dir)
            self.assertTrue(all(step in {1, 2, 3, 4} for step in progress))
            self.assertEqual(progress[0], 1)
            self.assertEqual(progress[-1], 4)
            self.assertTrue((run_dir / "property.json").exists())
            self.assertTrue((run_dir / "enrichment.json").exists())
            self.assertTrue((run_dir / "research.md").exists())
            self.assertTrue((run_dir / "post.md").exists())
            self.assertTrue((run_dir / "thumbnail.png").exists())
            self.assertEqual(
                Path(result.thumbnail_path or ""),
                settings.output_dir
                / "thumbnails"
                / "thumbnail_SAMPLE-001.png",
            )
            blog_path = (
                settings.output_dir
                / "contents"
                / "blog_SAMPLE-001.md"
            )
            self.assertEqual(Path(result.blog_markdown_path or ""), blog_path)
            self.assertTrue(blog_path.exists())
            blog_text = blog_path.read_text(encoding="utf-8")
            self.assertIn("## 면적 분석", blog_text)
            self.assertIn("[THUMBNAIL_IMAGE]", blog_text)
            self.assertIn("[TABLE_COMPLEX]", blog_text)
            self.assertIn("[TABLE_SUMMARY]", blog_text)
            self.assertIn("[TABLE_DETAIL]", blog_text)
            self.assertIn("[TABLE_REALTOR]", blog_text)
            self.assertEqual(blog_text.count("## 문의 안내"), 1)
            self.assertEqual(blog_text.count(MANDATORY_INQUIRY_TEXT), 1)
            self.assertGreater(
                blog_text.index("## 문의 안내"),
                blog_text.index("[TABLE_REALTOR]"),
            )
            payload = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["property_info"]["article_no"], "SAMPLE-001")
            self.assertFalse(payload["draft_saved"])


if __name__ == "__main__":
    unittest.main()
