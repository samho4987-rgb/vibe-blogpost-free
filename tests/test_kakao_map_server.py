from __future__ import annotations

import unittest

from naver_blog_automation.kakao_map_server import (
    KakaoMapServer,
    _render_page,
)


class KakaoMapServerTests(unittest.TestCase):
    def test_default_origin_uses_portable_localhost_name(self) -> None:
        self.assertEqual(
            KakaoMapServer().origin,
            "http://localhost:8765",
        )

    def test_dynamic_map_and_roadview_share_one_page(self) -> None:
        page = _render_page(
            {
                "javascript_key": "javascript-test",
                "title": "테스트아파트",
                "address": "서울 테스트로 10",
                "latitude": 37.5,
                "longitude": 127.1,
                "nearby_places": {
                    "학교": [
                        {
                            "name": "테스트학교",
                            "distance_m": 300,
                            "latitude": "37.51",
                            "longitude": "127.11",
                            "road_address": "서울 학교로",
                        }
                    ]
                },
            }
        )

        self.assertIn('id="map"', page)
        self.assertIn('id="roadview"', page)
        self.assertIn("showMap", page)
        self.assertIn("showRoadview", page)
        self.assertIn("getNearestPanoId", page)
        self.assertIn("테스트학교", page)
        self.assertIn("appkey=javascript-test", page)

    def test_embedded_page_hides_browser_only_chrome_and_exposes_controls(
        self,
    ) -> None:
        page = _render_page(
            {
                "javascript_key": "javascript-test",
                "title": "테스트",
                "address": "서울",
                "latitude": 37.5,
                "longitude": 127.1,
                "nearby_places": {},
            },
            embedded=True,
        )

        self.assertIn('<body class="embedded">', page)
        self.assertIn("window.showMap = showMap", page)
        self.assertIn("window.showRoadview = showRoadview", page)
        self.assertIn("window.zoomMap", page)


if __name__ == "__main__":
    unittest.main()
