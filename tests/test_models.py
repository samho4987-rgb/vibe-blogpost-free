from __future__ import annotations

import unittest

from naver_blog_automation.models import PropertyInfo


class PropertyInfoTests(unittest.TestCase):
    def test_maps_nested_naver_like_payload(self) -> None:
        payload = {
            "article": {
                "articleName": "테스트 아파트",
                "realEstateTypeName": "아파트",
                "tradeTypeName": "전세",
                "dealOrWarrantPrc": "5억",
                "area1": 109,
                "area2": 84,
                "floorInfo": "10/20층",
            },
            "location": {"cityName": "서울", "roadAddress": "테스트로 1"},
            "articleDescription": "채광이 좋습니다.",
        }
        info = PropertyInfo.from_payload("100", payload)
        self.assertEqual(info.name, "테스트 아파트")
        self.assertEqual(info.trade_type, "전세")
        self.assertEqual(info.address, "서울 테스트로 1")
        self.assertEqual(info.area, "공급 109㎡ / 전용 84㎡")


if __name__ == "__main__":
    unittest.main()
