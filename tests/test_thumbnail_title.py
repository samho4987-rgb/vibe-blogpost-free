from __future__ import annotations

import unittest

from naver_blog_automation.models import PropertyInfo, thumbnail_title


def _info(payload: dict) -> PropertyInfo:
    return PropertyInfo.from_payload("100", payload)


# 대표 이미지 제목 금지값: 이 값들이 이미지에 인쇄되면 안 된다.
FORBIDDEN_TITLES = {"", "정보 없음", "-"}


class ThumbnailTitleCategoryTests(unittest.TestCase):
    """카테고리별 썸네일 제목 규칙 검증.

    기준:
    R1 금지값 — '정보 없음'·빈 값·'null'·단독 'N동' 금지
    R2 카테고리 적합성 — 아파트=단지명 / 빌라=건물명(동 제거) /
       명칭 없는 유형=지역+유형
    R5 사실성 — 대체 제목은 수집된 지역·유형만 조합(수식어 없음)
    """

    def assert_title(self, payload: dict, expected: str) -> None:
        title = thumbnail_title(_info(payload))
        self.assertEqual(title, expected)
        self.assertNotIn(title, FORBIDDEN_TITLES)
        self.assertNotRegex(title, r"^\d+동$")
        self.assertNotRegex(title, r"(?i)(?<![\w가-힣])null(?![\w가-힣])")

    def test_apartment_uses_complex_name(self) -> None:
        self.assert_title(
            {
                "realEstateTypeName": "아파트",
                "aptName": "e편한세상오션테라스4단지",
                "articleName": "e편한세상오션테라스 403동",
                "cortarName": "부산 기장군 일광읍",
            },
            "e편한세상오션테라스4단지",
        )

    def test_officetel_uses_complex_name(self) -> None:
        self.assert_title(
            {
                "realEstateTypeName": "오피스텔",
                "complexName": "일광타워오피스텔",
                "articleName": "일광타워 오피스텔",
                "cortarName": "부산 기장군 일광읍",
            },
            "일광타워오피스텔",
        )

    def test_villa_with_dong_only_building_name(self) -> None:
        # 실데이터 결함: buildingName에 '1동'만 오는 경우 → 광고 제목에서 복구
        self.assert_title(
            {
                "realEstateTypeName": "빌라",
                "buildingName": "1동",
                "articleName": "진주빌라 1동",
                "cortarName": "부산 기장군 일광읍",
            },
            "진주빌라",
        )

    def test_villa_name_strips_trailing_dong(self) -> None:
        self.assert_title(
            {
                "realEstateTypeName": "연립",
                "buildingName": "해운대그랜드맨션 2동",
                "cortarName": "부산 해운대구 우동",
            },
            "해운대그랜드맨션",
        )

    def test_villa_null_token_cleaned(self) -> None:
        self.assert_title(
            {
                "realEstateTypeName": "빌라",
                "articleName": "null 1동",
                "buildingName": "진주빌라",
                "cortarName": "부산 기장군 일광읍",
            },
            "진주빌라",
        )

    def test_dasedae_with_only_dong_falls_back_to_region_type(self) -> None:
        self.assert_title(
            {
                "realEstateTypeName": "다세대",
                "buildingName": "3동",
                "articleName": "3동",
                "cortarName": "부산 기장군 정관읍",
            },
            "정관읍 다세대",
        )

    def test_dandok_type_only_becomes_region_type(self) -> None:
        # 광고 제목이 유형명 반복('단독/다가구')이면 지역+유형으로
        self.assert_title(
            {
                "realEstateTypeName": "단독/다가구",
                "articleName": "단독/다가구",
                "cortarName": "부산 기장군 장안읍",
            },
            "장안읍 단독·다가구",
        )

    def test_oneroom_type_only_becomes_region_type(self) -> None:
        self.assert_title(
            {
                "realEstateTypeName": "원룸",
                "articleName": "원룸",
                "cortarName": "부산 기장군 기장읍",
            },
            "기장읍 원룸",
        )

    def test_store_keeps_meaningful_listing_title(self) -> None:
        self.assert_title(
            {
                "realEstateTypeName": "상가",
                "articleName": "1층 코너 상가",
                "cortarName": "부산 기장군 기장읍",
            },
            "1층 코너 상가",
        )

    def test_land_keeps_meaningful_listing_title(self) -> None:
        self.assert_title(
            {
                "realEstateTypeName": "토지",
                "articleName": "계획관리 토지",
                "cortarName": "부산 기장군 철마면",
            },
            "계획관리 토지",
        )

    def test_countryside_house_keeps_listing_title(self) -> None:
        self.assert_title(
            {
                "realEstateTypeName": "전원주택",
                "articleName": "일광 바다뷰 전원주택",
                "cortarName": "부산 기장군 일광읍",
            },
            "일광 바다뷰 전원주택",
        )

    def test_no_name_at_all_never_prints_missing_info(self) -> None:
        self.assert_title(
            {
                "realEstateTypeName": "아파트",
                "cortarName": "부산 기장군 일광읍",
            },
            "일광읍 아파트",
        )

    def test_nothing_collected_uses_final_fallback(self) -> None:
        title = thumbnail_title(_info({}))
        self.assertEqual(title, "매물 정보 확인")


if __name__ == "__main__":
    unittest.main()
