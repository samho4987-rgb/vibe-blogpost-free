from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import httpx

from naver_blog_automation.enrichment import (
    BUILDING_REGISTER_URL,
    KAKAO_ADDRESS_URL,
    KAKAO_CATEGORY_URL,
    KAKAO_STATIC_MAP_URL,
    EnrichmentResult,
    PropertyDataEnricher,
)
from naver_blog_automation.models import PropertyInfo


def _property() -> PropertyInfo:
    return PropertyInfo(
        article_no="123",
        name="테스트아파트",
        property_type="아파트",
        trade_type="매매",
        price="10억",
        address="서울 강남구 테스트로 10",
        area="공급 109.2㎡ / 전용 84.9㎡",
        floor="10/20층",
        rooms="3/2개",
        direction="남향",
        description="테스트",
    )


class EnrichmentTests(unittest.TestCase):
    def test_static_map_uses_property_and_nearby_markers(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            self.assertTrue(str(request.url).startswith(KAKAO_STATIC_MAP_URL))
            return httpx.Response(
                200,
                content=b"fake-png",
                headers={"content-type": "image/png"},
            )

        enrichment = EnrichmentResult(
            address={"longitude": "127.1", "latitude": "37.5"},
            nearby={
                "학교": [
                    {
                        "name": "테스트학교",
                        "longitude": "127.11",
                        "latitude": "37.51",
                    }
                ]
            },
        )
        enricher = PropertyDataEnricher(
            kakao_rest_api_key="kakao-secret",
            transport=httpx.MockTransport(handler),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "map.png"
            result = enricher.create_static_map(enrichment, target)

            self.assertEqual(result, target)
            self.assertEqual(target.read_bytes(), b"fake-png")
        self.assertEqual(
            requests[0].headers["Authorization"],
            "KakaoAK kakao-secret",
        )
        params = list(requests[0].url.params.multi_items())
        self.assertIn(("center", "127.1,37.5"), params)
        self.assertIn(("lv", "4"), params)
        markers = [value for key, value in params if key == "markers"]
        self.assertEqual(len(markers), 2)

    def test_area_analysis_works_without_api_keys(self) -> None:
        result = PropertyDataEnricher().enrich(_property())

        self.assertEqual(result.area["supply_m2"], 109.2)
        self.assertEqual(result.area["exclusive_m2"], 84.9)
        self.assertAlmostEqual(result.area["exclusive_ratio"], 77.747, places=2)
        markdown = result.to_markdown()
        self.assertIn("## 📐 면적 분석", markdown)
        self.assertIn("전용률", markdown)

    def test_kakao_and_building_register_enrich_property(self) -> None:
        seen_building_params: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url).startswith(KAKAO_ADDRESS_URL):
                self.assertEqual(
                    request.headers["Authorization"],
                    "KakaoAK kakao-secret",
                )
                return httpx.Response(
                    200,
                    json={
                        "documents": [
                            {
                                "address_name": "서울 강남구 역삼동 123-4",
                                "x": "127.1",
                                "y": "37.5",
                                "address": {
                                    "address_name": "서울 강남구 역삼동 123-4",
                                    "b_code": "1168010100",
                                    "mountain_yn": "N",
                                    "main_address_no": "123",
                                    "sub_address_no": "4",
                                    "x": "127.1",
                                    "y": "37.5",
                                },
                                "road_address": {
                                    "address_name": "서울 강남구 테스트로 10",
                                },
                            }
                        ]
                    },
                )
            if str(request.url).startswith(KAKAO_CATEGORY_URL):
                code = request.url.params["category_group_code"]
                return httpx.Response(
                    200,
                    json={
                        "documents": [
                            {
                                "place_name": f"시설-{code}",
                                "distance": "350",
                                "category_name": "테스트",
                                "road_address_name": "서울 테스트로",
                                "place_url": "https://place.map.kakao.com/1",
                            }
                        ]
                    },
                )
            if str(request.url).startswith(BUILDING_REGISTER_URL):
                seen_building_params.update(dict(request.url.params))
                return httpx.Response(
                    200,
                    json={
                        "response": {
                            "header": {
                                "resultCode": "00",
                                "resultMsg": "NORMAL SERVICE",
                            },
                            "body": {
                                "items": {
                                    "item": [
                                        {
                                            "bldNm": "테스트아파트",
                                            "dongNm": "101동",
                                            "mainPurpsCdNm": "공동주택",
                                            "useAprDay": "20200115",
                                            "grndFlrCnt": "20",
                                            "ugrndFlrCnt": "0",
                                            "hhldCnt": "100",
                                            "totPkngCnt": "120",
                                            "emgenUseElvtCnt": 0,
                                            "totArea": "12345.6",
                                        }
                                    ]
                                }
                            },
                        }
                    },
                )
            return httpx.Response(404)

        result = PropertyDataEnricher(
            kakao_rest_api_key="kakao-secret",
            data_go_kr_service_key="public-secret",
            transport=httpx.MockTransport(handler),
        ).enrich(_property())

        self.assertEqual(result.address["legal_code"], "1168010100")
        self.assertIn("/link/roadview/37.5,127.1", result.address["roadview_url"])
        self.assertEqual(result.nearby["지하철역"][0]["distance_m"], 350.0)
        self.assertEqual(result.building["fields"]["건물명"], "테스트아파트")
        self.assertNotIn("지하층수", result.building["fields"])
        self.assertNotIn("비상용 엘리베이터", result.building["fields"])
        self.assertEqual(seen_building_params["sigunguCd"], "11680")
        self.assertEqual(seen_building_params["bjdongCd"], "10100")
        self.assertEqual(seen_building_params["bun"], "0123")
        self.assertEqual(seen_building_params["ji"], "0004")
        serialized = json.dumps(result.to_dict(), ensure_ascii=False)
        self.assertNotIn("kakao-secret", serialized)
        self.assertNotIn("public-secret", serialized)
        markdown = result.to_markdown()
        self.assertIn("## 📍 입지 분석", markdown)
        self.assertIn("직선거리", markdown)
        self.assertIn("## 🚇 교통", markdown)
        self.assertIn("## 🎓 학군", markdown)
        self.assertIn("## 🛒 생활 편의", markdown)
        self.assertIn("## 🏗 건축물대장 확인", markdown)

    def test_invalid_kakao_key_returns_warning_without_raising(self) -> None:
        result = PropertyDataEnricher(
            kakao_rest_api_key="invalid",
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(401, json={"msg": "Unauthorized"})
            ),
        ).enrich(_property())

        self.assertTrue(result.warnings)
        self.assertIn("REST API 키 인증", result.warnings[0])


if __name__ == "__main__":
    unittest.main()
