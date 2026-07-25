from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from naver_blog_automation.property_fetcher import (
    PropertyFetchError,
    PropertyFetcher,
    parse_curl_command,
)
from naver_blog_automation.models import PropertyInfo


class _VisiblePage:
    def goto(self, *_args, **_kwargs) -> None:
        return None

    def wait_for_function(self, *_args, **_kwargs) -> None:
        return None

    def locator(self, _selector: str):
        return self

    def inner_text(self, **_kwargs) -> str:
        return "화면 텍스트"


class _VisibleBrowser:
    def __init__(self) -> None:
        self.page = _VisiblePage()
        self.closed = False

    def new_page(self, **_kwargs):
        return self.page

    def close(self) -> None:
        self.closed = True


class _VisibleChromium:
    def __init__(self, browser: _VisibleBrowser) -> None:
        self.browser = browser
        self.launch_options: dict[str, object] = {}

    def launch(self, **kwargs):
        self.launch_options = kwargs
        return self.browser


class _VisiblePlaywrightManager:
    def __init__(self, chromium: _VisibleChromium) -> None:
        self.chromium = chromium

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


class CurlParserTests(unittest.TestCase):
    def test_parses_get_headers_and_cookie_without_shell_execution(self) -> None:
        command = (
            "curl 'https://new.land.naver.com/api/articles/{article_no}' "
            "-H 'accept: application/json' "
            "-H 'referer: https://new.land.naver.com/' "
            "-b 'NID_AUT=example'"
        )
        parsed = parse_curl_command(command, "123456")
        self.assertEqual(parsed.method, "GET")
        self.assertEqual(
            parsed.url,
            "https://new.land.naver.com/api/articles/123456",
        )
        self.assertEqual(parsed.headers["accept"], "application/json")
        self.assertEqual(parsed.headers["Cookie"], "NID_AUT=example")

    def test_parses_post_body(self) -> None:
        parsed = parse_curl_command(
            "curl -X POST https://example.com/api -d '{\"id\": 1}'",
            "1",
        )
        self.assertEqual(parsed.method, "POST")
        self.assertEqual(parsed.data, '{"id": 1}')

    def test_rejects_non_http_url(self) -> None:
        with self.assertRaises(PropertyFetchError):
            parse_curl_command("curl file:///etc/passwd", "1")


class SessionRequestTests(unittest.TestCase):
    def setUp(self) -> None:
        PropertyFetcher._rate_limited_until = 0.0

    def test_cookies_from_article_page_are_sent_to_api(self) -> None:
        seen_cookie = ""

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal seen_cookie
            if request.url.path.startswith("/articles/"):
                return httpx.Response(
                    200,
                    headers=[
                        ("set-cookie", "PROP_TEST_KEY=key-1; Path=/; Domain=.naver.com"),
                        ("set-cookie", "PROP_TEST_ID=id-1; Path=/; Domain=.naver.com"),
                    ],
                    text="<html></html>",
                )
            seen_cookie = request.headers.get("cookie", "")
            return httpx.Response(
                200,
                json={"articleName": "테스트 매물", "tradeTypeName": "매매"},
            )

        fetcher = PropertyFetcher(transport=httpx.MockTransport(handler))
        result = fetcher.fetch("2634925140")
        self.assertEqual(result.name, "테스트 매물")
        self.assertIn("PROP_TEST_KEY=key-1", seen_cookie)
        self.assertIn("PROP_TEST_ID=id-1", seen_cookie)
        self.assertEqual(
            fetcher.session_cookie_names,
            ("PROP_TEST_ID", "PROP_TEST_KEY"),
        )

    def test_429_waits_refreshes_cookie_once_and_retries_once(self) -> None:
        article_visits = 0
        api_visits = 0
        api_cookies: list[str] = []
        sleeps: list[float] = []

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal article_visits, api_visits
            if request.url.path.startswith("/articles/"):
                article_visits += 1
                return httpx.Response(
                    200,
                    headers={
                        "set-cookie": (
                            f"PROP_TEST_ID=session-{article_visits}; "
                            "Path=/; Domain=.naver.com"
                        )
                    },
                    text="<html></html>",
                )
            api_visits += 1
            api_cookies.append(request.headers.get("cookie", ""))
            if api_visits == 1:
                return httpx.Response(
                    429,
                    headers=[
                        ("Retry-After", "0"),
                        (
                            "set-cookie",
                            "PROP_TEST_KEY=refreshed-key; Path=/; Domain=.naver.com",
                        ),
                    ],
                )
            return httpx.Response(
                200,
                json={"articleName": "재시도 성공", "tradeTypeName": "매매"},
            )

        fetcher = PropertyFetcher(
            transport=httpx.MockTransport(handler),
            sleep=sleeps.append,
        )
        result = fetcher.fetch("2634925140")
        self.assertEqual(result.name, "재시도 성공")
        self.assertEqual(article_visits, 1)
        self.assertEqual(api_visits, 2)
        self.assertEqual(sleeps, [0.0])
        self.assertIn("session-1", api_cookies[0])
        self.assertIn("session-1", api_cookies[1])
        self.assertIn("PROP_TEST_KEY=refreshed-key", api_cookies[1])

    def test_403_clears_and_primes_new_page_session_once(self) -> None:
        article_visits = 0
        api_visits = 0
        api_cookies: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal article_visits, api_visits
            if request.url.path.startswith("/articles/"):
                article_visits += 1
                return httpx.Response(
                    200,
                    headers={
                        "set-cookie": (
                            f"PROP_TEST_ID=session-{article_visits}; "
                            "Path=/; Domain=.naver.com"
                        )
                    },
                    text="<html></html>",
                )
            api_visits += 1
            api_cookies.append(request.headers.get("cookie", ""))
            if api_visits == 1:
                return httpx.Response(403)
            return httpx.Response(
                200,
                json={"articleName": "세션 갱신 성공", "tradeTypeName": "매매"},
            )

        fetcher = PropertyFetcher(transport=httpx.MockTransport(handler))
        result = fetcher.fetch("2634925140")
        self.assertEqual(result.name, "세션 갱신 성공")
        self.assertEqual(article_visits, 2)
        self.assertEqual(api_visits, 2)
        self.assertIn("session-1", api_cookies[0])
        self.assertIn("session-2", api_cookies[1])
        self.assertNotIn("session-1", api_cookies[1])

    def test_long_retry_after_stops_without_second_api_call(self) -> None:
        api_visits = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal api_visits
            if request.url.path.startswith("/articles/"):
                return httpx.Response(200, text="<html></html>")
            api_visits += 1
            return httpx.Response(429, headers={"Retry-After": "120"})

        fetcher = PropertyFetcher(transport=httpx.MockTransport(handler))
        with self.assertRaises(PropertyFetchError) as context:
            fetcher.fetch("2634925140")
        self.assertEqual(api_visits, 1)
        self.assertIn("HTTP 429", str(context.exception))


class VisiblePageParserTests(unittest.TestCase):
    def test_browser_fallback_is_hidden_during_preview(self) -> None:
        browser = _VisibleBrowser()
        chromium = _VisibleChromium(browser)
        manager = _VisiblePlaywrightManager(chromium)
        expected = PropertyInfo(
            article_no="123",
            name="테스트",
            property_type="아파트",
            trade_type="매매",
            price="1억",
            address="서울",
            area="84㎡",
            floor="1/10층",
            rooms="3",
            direction="남향",
            description="테스트",
        )
        fetcher = PropertyFetcher(browser_channel="chrome")
        with (
            patch(
                "playwright.sync_api.sync_playwright",
                return_value=manager,
            ),
            patch.object(
                fetcher,
                "_property_from_visible_text",
                return_value=expected,
            ),
        ):
            result = fetcher._fetch_visible_page("123")

        self.assertIs(result, expected)
        # 네이버가 headless를 막으므로 화면 밖에 배치한 일반 창으로 빠르게 수집한다.
        self.assertIs(chromium.launch_options["headless"], False)
        self.assertIn(
            "--window-position=-10000,-10000",
            chromium.launch_options["args"],
        )
        self.assertTrue(browser.closed)

    def test_extracts_selected_article_details_without_storing_page_text(self) -> None:
        text = """
지역 선택
부산시
수영구
광안동
집주인확인매물 26.06.29.
광안삼정그린코아 101동고층
전세5억(1,038만원/3.3㎡)
평당가 도움말
허위매물신고인쇄
아파트남동향역까지 8분공급/전용 면적:159.2㎡/127.84㎡
매물정보시세/실거래가동호수/공시가격학군정보
평
매물 정보
매물특징\t광안대교조망굿 올수리됨 빠른입주 선호라인
공급/전용면적\t159.2㎡/127.84㎡(전용률80%)
해당층/총층\t고/24층\t방수/욕실수\t4/2개
관리비\t25만원
방향\t남동향(거실 기준)
입주가능일\t즉시입주 협의가능
매물번호\t2634925140
매물설명\t
광안대교조망굿 올수리됨 빠른입주 선호라인
"""
        result = PropertyFetcher._property_from_visible_text(
            "2634925140",
            text,
            "https://fin.land.naver.com/articles/2634925140",
        )
        self.assertEqual(result.name, "광안삼정그린코아 101동")
        self.assertEqual(result.property_type, "아파트")
        self.assertEqual(result.trade_type, "전세")
        self.assertEqual(result.price, "5억")
        self.assertEqual(result.address, "부산시 수영구 광안동")
        self.assertEqual(result.area, "159.2㎡/127.84㎡(전용률80%)")
        self.assertEqual(result.floor, "고/24층")
        self.assertEqual(result.rooms, "4/2개")
        self.assertEqual(result.direction, "남동향(거실 기준)")
        self.assertNotIn("visible_text", result.raw)

    def test_extracts_current_fin_land_line_based_layout(self) -> None:
        text = """
광안삼정그린코아 101동
창닫기
광안삼정그린코아 101동
전세 5억
1,038만원/3.3㎡
아파트159A㎡ (전용127A)고/24층남동향
광안대교조망굿 올수리됨 빠른입주 선호라인
기본 정보
전세가
5억원
공급면적
159.2㎡
전용면적
127.84㎡ (전용률 80%)
해당층/총층
고/24층
방수/욕실수
4/2개
향
(거실 기준) 남동향
입주가능일
즉시입주 협의 가능
매물번호
2634925140
매물소개
광안대교조망굿 올수리됨 빠른입주 선호라인
위치
부산시 수영구 광안동 172-1
"""
        result = PropertyFetcher._property_from_visible_text(
            "2634925140",
            text,
        )
        self.assertEqual(result.name, "광안삼정그린코아 101동")
        self.assertEqual(result.trade_type, "전세")
        self.assertEqual(result.price, "5억")
        self.assertEqual(result.address, "부산시 수영구 광안동 172-1")
        self.assertEqual(
            result.area,
            "공급 159.2㎡ / 전용 127.84㎡ (전용률 80%)",
        )
        self.assertEqual(result.description, "광안대교조망굿 올수리됨 빠른입주 선호라인")


if __name__ == "__main__":
    unittest.main()
