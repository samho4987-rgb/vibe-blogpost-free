from __future__ import annotations

import json
import re
import shlex
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from .models import PropertyInfo


class PropertyFetchError(RuntimeError):
    pass


@dataclass(slots=True)
class ParsedCurl:
    method: str = "GET"
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    data: str | None = None


def _apply_article_no(text: str, article_no: str) -> str:
    """cURL에 박힌 특정 매물번호를 조회 대상 번호로 바꾼다.

    붙여넣은 cURL은 복사할 당시의 매물번호(예: /api/articles/2639338153)가
    그대로 들어 있으므로, 그대로 재사용하면 항상 그 매물만 조회된다. 그래서
    다음 세 가지를 조회 대상 번호로 치환해 어느 매물에나 재사용할 수 있게 한다.
      · 리터럴 자리표시자 {article_no}
      · /articles/<숫자> 경로(new.land API·상세 페이지 URL, Referer 포함)
      · articleNo=<숫자> 쿼리 파라미터
    article_no가 비어 있으면 원본을 유지한다."""
    result = text.replace("{article_no}", article_no)
    if not article_no:
        return result
    result = re.sub(r"(/articles/)\d+", lambda m: m.group(1) + article_no, result)
    result = re.sub(r"(articleNo=)\d+", lambda m: m.group(1) + article_no, result)
    return result


def parse_curl_command(command: str, article_no: str) -> ParsedCurl:
    """Copy as cURL 문자열을 셸에서 실행하지 않고 안전하게 요청 정보로 변환한다."""
    cleaned = command.strip().replace("\\\n", " ")
    if not cleaned:
        raise PropertyFetchError("cURL 명령이 비어 있습니다.")

    try:
        tokens = shlex.split(cleaned, posix=True)
    except ValueError as exc:
        raise PropertyFetchError(f"cURL 명령을 읽을 수 없습니다: {exc}") from exc

    parsed = ParsedCurl()
    index = 1 if tokens and tokens[0].lower() in {"curl", "curl.exe"} else 0

    while index < len(tokens):
        token = tokens[index]
        if token in ("-X", "--request") and index + 1 < len(tokens):
            parsed.method = tokens[index + 1].upper()
            index += 2
            continue
        if token in ("-H", "--header") and index + 1 < len(tokens):
            header = tokens[index + 1]
            if ":" in header:
                name, value = header.split(":", 1)
                parsed.headers[name.strip()] = value.strip()
            index += 2
            continue
        if token in ("-b", "--cookie") and index + 1 < len(tokens):
            parsed.headers["Cookie"] = tokens[index + 1]
            index += 2
            continue
        if token in ("-d", "--data", "--data-raw", "--data-binary") and index + 1 < len(tokens):
            parsed.data = tokens[index + 1]
            if parsed.method == "GET":
                parsed.method = "POST"
            index += 2
            continue
        if token.startswith(("http://", "https://")):
            parsed.url = token
        index += 1

    parsed.url = _apply_article_no(parsed.url, article_no)
    # Referer 헤더에 남아 있는 다른 매물번호도 조회 대상 번호로 맞춘다.
    # (Cookie 등 다른 헤더는 건드리지 않는다.)
    if article_no:
        for key in list(parsed.headers):
            if key.lower() == "referer":
                parsed.headers[key] = _apply_article_no(
                    parsed.headers[key], article_no
                )
    scheme = urlparse(parsed.url).scheme
    if scheme not in {"http", "https"}:
        raise PropertyFetchError("cURL 안에서 http(s) 주소를 찾지 못했습니다.")
    return parsed


class PropertyFetcher:
    DEFAULT_URL = "https://new.land.naver.com/api/articles/{article_no}"
    ARTICLE_PAGE_URL = "https://new.land.naver.com/articles/{article_no}"
    VISIBLE_PAGE_URL = "https://fin.land.naver.com/articles/{article_no}"
    MAX_AUTO_RETRY_DELAY_SECONDS = 30.0
    _rate_limited_until = 0.0

    BROWSER_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/138.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    }
    API_HEADERS = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    def __init__(
        self,
        timeout_seconds: int = 20,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        browser_channel: str = "chrome",
        browser_fallback: bool | None = None,
        auto_refresh: bool = False,
        credential_saver: Callable[[str], None] | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.sleep = sleep
        self.browser_channel = browser_channel
        # MockTransport를 쓰는 단위 테스트에서는 실제 브라우저를 열지 않는다.
        self.browser_fallback = transport is None if browser_fallback is None else browser_fallback
        # 자동 갱신도 테스트(MockTransport)에서는 브라우저를 열지 않도록 막는다.
        self.auto_refresh = transport is None and auto_refresh
        self.credential_saver = credential_saver
        self._log = log or (lambda _message: None)
        self.session_cookie_names: tuple[str, ...] = ()

    def load_sample(self, sample_path: Path) -> PropertyInfo:
        payload = json.loads(sample_path.read_text(encoding="utf-8"))
        article_no = str(payload.get("articleNo", "SAMPLE-001"))
        return PropertyInfo.from_payload(article_no, payload, source="내장 샘플 데이터")

    def fetch(self, article_no: str, curl_command: str = "") -> PropertyInfo:
        article_no = article_no.strip()
        if not article_no:
            raise PropertyFetchError("매물번호를 입력해 주세요.")

        now = time.monotonic()
        if now < type(self)._rate_limited_until:
            remaining = max(1, int(type(self)._rate_limited_until - now))
            raise PropertyFetchError(
                f"네이버가 재시도 대기를 요청했습니다. 약 {remaining}초 후 다시 시도해 주세요."
            )

        try:
            return self._attempt(article_no, curl_command)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            fallback_error = ""
            if status in {401, 403, 429}:
                # 1) 자동 갱신: 창 없이 헤드리스로 토큰·쿠키를 새로 발급해 재시도.
                if self.auto_refresh:
                    refreshed = self._auto_refresh_credentials(article_no)
                    if refreshed:
                        try:
                            info = self._attempt(article_no, refreshed)
                        except (
                            httpx.HTTPStatusError,
                            httpx.RequestError,
                            PropertyFetchError,
                        ):
                            info = None
                        if info is not None:
                            if self.credential_saver is not None:
                                try:
                                    self.credential_saver(refreshed)
                                except Exception:
                                    pass
                            self._log("자동 갱신한 인증으로 매물 정보를 가져왔습니다.")
                            return info
                # 2) 마지막 수단: 보이는 브라우저로 상세 화면 스크랩
                #    (사용자가 직접 cURL을 준 경우는 그 값을 존중해 창을 열지 않는다.)
                if not curl_command.strip() and self.browser_fallback:
                    try:
                        return self._fetch_visible_page(article_no)
                    except PropertyFetchError as browser_exc:
                        fallback_error = (
                            "\n현재 네이버페이 부동산 화면에서도 정보를 읽지 못했습니다: "
                            f"{browser_exc}"
                        )
            if status == 429:
                retry_after = self._retry_after_seconds(exc.response)
                detail = (
                    f" 네이버가 약 {int(retry_after)}초의 대기 시간을 지정했습니다."
                    if retry_after > 0
                    else ""
                )
                hint = (
                    "자동 반복 호출은 중단했습니다."
                    f"{detail} 잠시 뒤 다시 시도하거나, 실제 브라우저의 요청을 "
                    "'Copy as cURL'로 복사해 문제 해결·고급 설정에 붙여 넣어 주세요."
                )
            else:
                hint = (
                    "로그인 또는 세션이 필요한 요청일 수 있습니다. 실제 브라우저의 "
                    "해당 요청을 'Copy as cURL'로 복사해 문제 해결·고급 설정에 붙여 넣어 주세요."
                )
            raise PropertyFetchError(
                f"매물정보 요청 실패: HTTP {status} ({exc.response.reason_phrase})"
                f"\n{hint}{fallback_error}"
            ) from exc
        except httpx.RequestError as exc:
            hint = (
                "네트워크 연결을 확인하세요. 기본 요청이 차단되었다면 개발자 도구의 Network에서 "
                "해당 매물 API 요청을 'Copy as cURL'로 복사해 문제 해결·고급 설정에 붙여 넣어 주세요."
            )
            raise PropertyFetchError(f"매물정보 요청 실패: {exc}\n{hint}") from exc

    def _attempt(self, article_no: str, curl_command: str) -> PropertyInfo:
        """단일 httpx 시도: 요청 구성 → 세션 요청 → JSON 파싱(오류는 상위로)."""
        if curl_command.strip():
            request = parse_curl_command(curl_command, article_no)
            source = "네이버부동산 세션(cURL)"
        else:
            request = ParsedCurl(
                method="GET",
                url=self.DEFAULT_URL.format(article_no=article_no),
                headers=dict(self.API_HEADERS),
            )
            source = "네이버부동산 기본 API"
        response = self._request_with_session(article_no, request)
        response.raise_for_status()
        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise PropertyFetchError("매물 API 응답이 JSON 형식이 아닙니다.") from exc
        if not isinstance(payload, dict):
            raise PropertyFetchError("매물 API 응답에서 객체 형태의 정보를 찾지 못했습니다.")
        # 네이버가 200으로 에러 바디를 주는 경우(삭제·만료 매물 등)를 빈 문서로
        # 만들지 않고 명확히 알린다.
        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "매물 정보를 찾을 수 없습니다.").strip()
            raise PropertyFetchError(
                f"네이버에서 매물을 찾지 못했습니다: {message}\n"
                "매물이 삭제·만료되었거나 매물번호가 올바른지 확인해 주세요."
            )
        return PropertyInfo.from_payload(article_no, payload, source=source)

    def _auto_refresh_credentials(self, article_no: str) -> str:
        """헤드리스 브라우저로 네이버 인증(토큰·쿠키)을 새로 발급해 cURL 문자열로 돌려준다.

        실패하면 빈 문자열(다른 폴백으로 넘어감)."""
        self._log("네이버 인증이 만료·차단되어 창 없이 자동으로 갱신합니다…")
        try:
            creds = harvest_naver_credentials(
                article_no,
                browser_channel=self.browser_channel,
                log=self._log,
            )
        except Exception:
            creds = None
        if not creds:
            self._log("자동 갱신에 실패했습니다(헤드리스 차단 가능). 다른 방법으로 시도합니다.")
            return ""
        authorization, cookie_str = creds
        self._log("새 인증 토큰·쿠키를 발급했습니다. 이 값으로 다시 요청합니다.")
        return build_curl_from_credentials(article_no, authorization, cookie_str)

    def _fetch_visible_page(self, article_no: str) -> PropertyInfo:
        """현재 공식 상세 화면에서 핵심 값만 읽는다.

        네이버가 headless 브라우저를 막아 렌더링이 되지 않으므로, 시간을 낭비하지
        않도록 처음부터 화면 밖에 배치한 일반 창으로 한 번만 수집한다(창이 잠깐
        스칠 수 있으나 가장 빠르고 확실하다).
        """
        try:
            from playwright.sync_api import Error as PlaywrightError  # noqa: F401
        except ImportError as exc:
            raise PropertyFetchError(
                "Chrome 화면 대체 수집에 필요한 Playwright가 설치되지 않았습니다."
            ) from exc
        return self._read_visible_page_once(article_no, headless=False)

    def _read_visible_page_once(
        self,
        article_no: str,
        *,
        headless: bool,
    ) -> PropertyInfo:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright

        url = self.VISIBLE_PAGE_URL.format(article_no=article_no)
        browser = None
        try:
            with sync_playwright() as playwright:
                args = [
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                ]
                if not headless:
                    # headful일 때는 창을 화면 밖에 배치해 최대한 보이지 않게 한다.
                    args = [
                        "--window-position=-10000,-10000",
                        "--window-size=1280,900",
                        *args,
                    ]
                launch_options: dict[str, Any] = {"headless": headless, "args": args}
                if self.browser_channel:
                    launch_options["channel"] = self.browser_channel
                try:
                    browser = playwright.chromium.launch(**launch_options)
                except PlaywrightError:
                    if "channel" not in launch_options:
                        raise
                    launch_options.pop("channel", None)
                    browser = playwright.chromium.launch(**launch_options)

                page = browser.new_page(locale="ko-KR")
                page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_function(
                    """articleNo => {
                        const text = document.body?.innerText || "";
                        return text.includes("매물번호") && text.includes(articleNo);
                    }""",
                    arg=article_no,
                    timeout=25_000,
                )
                visible_text = page.locator("body").inner_text(timeout=10_000)
                return self._property_from_visible_text(article_no, visible_text, url)
        except PlaywrightTimeoutError as exc:
            raise PropertyFetchError(
                "현재 상세 화면에서 매물번호가 표시될 때까지 기다렸지만 응답이 없었습니다."
            ) from exc
        except PlaywrightError as exc:
            raise PropertyFetchError(f"Chrome 상세 화면을 열 수 없습니다: {exc}") from exc
        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass

    @staticmethod
    def _property_from_visible_text(
        article_no: str,
        visible_text: str,
        source_url: str = "",
    ) -> PropertyInfo:
        """전체 화면 텍스트 중 선택된 매물 상세 블록만 구조화한다."""
        marker = re.search(
            rf"매물번호\s*\t?\s*{re.escape(article_no)}(?:\s|$)",
            visible_text,
        )
        if marker is None:
            raise PropertyFetchError("공개 상세 화면에서 입력한 매물번호를 찾지 못했습니다.")

        section_start = max(
            visible_text.rfind("매물 정보", 0, marker.start()),
            visible_text.rfind("기본 정보", 0, marker.start()),
        )
        if section_start < 0:
            section_start = max(0, marker.start() - 1_500)
        section = visible_text[section_start : marker.end() + 800]
        prefix = visible_text[max(0, section_start - 1_200) : section_start]

        def field(*labels: str) -> str:
            alternatives = "|".join(re.escape(label) for label in labels)
            match = re.search(
                rf"(?m)(?:^|\t)(?:{alternatives})[ \u00a0]*(?:\t+|\r?\n)"
                rf"[ \u00a0]*([^\t\r\n]+)",
                section,
            )
            return match.group(1).strip() if match else "정보 없음"

        heading_matches = list(
            re.finditer(
                r"(?m)^([^\n\t]+)\n(매매|전세|월세|단기임대)([^\n(]+)",
                prefix,
            )
        )
        if heading_matches:
            heading = heading_matches[-1]
            name = heading.group(1).strip()
            trade_type = heading.group(2).strip()
            price = heading.group(3).strip()
        else:
            name = "정보 없음"
            trade_type = "정보 없음"
            price = "정보 없음"
        name = re.sub(r"(?:저|중|고)층$", "", name).strip()

        property_types = re.findall(
            r"(?m)^(아파트|오피스텔|빌라|주택|원룸|투룸|상가|업무|공장|토지)",
            prefix,
        )
        property_type = property_types[-1] if property_types else "정보 없음"

        region_match = re.search(
            r"지역 선택\s*\n([^\n]+)\n([^\n]+)\n([^\n]+)",
            visible_text,
        )
        address = field("위치")
        if address == "정보 없음" and region_match:
            address = " ".join(part.strip() for part in region_match.groups())

        description = field("매물특징", "매물소개")
        area = field("공급/전용면적")
        if area == "정보 없음":
            supply_area = field("공급면적")
            exclusive_area = field("전용면적")
            area_parts = []
            if supply_area != "정보 없음":
                area_parts.append(f"공급 {supply_area}")
            if exclusive_area != "정보 없음":
                area_parts.append(f"전용 {exclusive_area}")
            area = " / ".join(area_parts) or "정보 없음"
        floor = field("해당층/총층")
        rooms = field("방수/욕실수")
        direction = field("방향", "향")
        available_date = field("입주가능일")
        entrance_type = field("현관구조")
        maintenance_fee = field("관리비")
        heating = field("난방", "난방방식")
        parking = field("주차", "주차대수")
        builder = field("건설사")
        total_units = field("세대수", "총세대수")
        approval_date = field("사용승인일", "사용승인")
        building_use = field("건축물용도", "주용도")
        realtor_name = field("중개사무소", "중개업소")
        realtor_ceo = field("대표자")
        realtor_registration_no = field("개설등록번호", "등록번호")
        realtor_phone = field("대표번호", "전화번호")
        realtor_mobile = field("휴대폰번호", "휴대전화")
        realtor_address = field("중개사무소 소재지", "중개사무소 주소")
        bathroom_match = re.search(r"/\s*([0-9]+)", rooms)
        bathrooms = bathroom_match.group(1) if bathroom_match else ""
        features = [] if description == "정보 없음" else [description]
        raw = {
            "articleNo": article_no,
            "articleName": name,
            "realEstateTypeName": property_type,
            "tradeTypeName": trade_type,
            "price": price,
            "address": address,
            "area": area,
            "floorInfo": floor,
            "roomCount": rooms,
            "direction": direction,
            "articleDescription": description,
            "availableDate": available_date,
            "entranceType": entrance_type,
            "maintenanceFee": maintenance_fee,
            "heating": heating,
            "parking": parking,
            "builder": builder,
            "totalUnits": total_units,
            "approvalDate": approval_date,
            "buildingUse": building_use,
            "sourceUrl": source_url,
        }
        return PropertyInfo(
            article_no=article_no,
            name=name,
            property_type=property_type,
            trade_type=trade_type,
            price=price,
            address=address,
            area=area,
            floor=floor,
            rooms=rooms,
            direction=direction,
            description=description,
            features=features,
            listing_title=name,
            complex_name=re.sub(r"\s+\d+동$", "", name).strip(),
            bathrooms=bathrooms,
            available_date=(
                "" if available_date == "정보 없음" else available_date
            ),
            entrance_type=(
                "" if entrance_type == "정보 없음" else entrance_type
            ),
            maintenance_fee=(
                "" if maintenance_fee == "정보 없음" else maintenance_fee
            ),
            heating="" if heating == "정보 없음" else heating,
            parking="" if parking == "정보 없음" else parking,
            builder="" if builder == "정보 없음" else builder,
            total_units="" if total_units == "정보 없음" else total_units,
            approval_date=(
                "" if approval_date == "정보 없음" else approval_date
            ),
            building_use=(
                "" if building_use == "정보 없음" else building_use
            ),
            realtor_name=(
                "" if realtor_name == "정보 없음" else realtor_name
            ),
            realtor_ceo=(
                "" if realtor_ceo == "정보 없음" else realtor_ceo
            ),
            realtor_registration_no=(
                ""
                if realtor_registration_no == "정보 없음"
                else realtor_registration_no
            ),
            realtor_phone=(
                "" if realtor_phone == "정보 없음" else realtor_phone
            ),
            realtor_mobile=(
                "" if realtor_mobile == "정보 없음" else realtor_mobile
            ),
            realtor_address=(
                "" if realtor_address == "정보 없음" else realtor_address
            ),
            source="네이버페이 부동산 공개 상세 화면",
            raw=raw,
        )

    def _request_with_session(
        self,
        article_no: str,
        request: ParsedCurl,
    ) -> httpx.Response:
        timeout = httpx.Timeout(
            self.timeout_seconds,
            connect=min(10.0, float(self.timeout_seconds)),
        )
        client_options: dict[str, Any] = {
            "headers": self.BROWSER_HEADERS,
            "timeout": timeout,
            "follow_redirects": True,
        }
        if self.transport is not None:
            client_options["transport"] = self.transport

        with httpx.Client(**client_options) as client:
            provided_cookie = request.headers.get("Cookie") or request.headers.get("cookie")
            if not provided_cookie:
                self._prime_session(client, article_no)
            self._remember_cookie_names(client)

            response = client.request(
                request.method,
                request.url,
                headers={
                    **request.headers,
                    "Referer": self.ARTICLE_PAGE_URL.format(article_no=article_no),
                },
                content=request.data,
            )
            self._remember_cookie_names(client)
            if response.status_code not in {401, 403, 429}:
                return response

            delay = self._retry_after_seconds(response)
            if response.status_code == 429:
                # 429 응답의 Set-Cookie(PROP_TEST_* 등)는 Client가 이미 메모리에
                # 병합했다. 이를 지우지 않고 서버가 지정한 시간 이후 한 번만 재사용한다.
                self._remember_cookie_names(client)
                type(self)._rate_limited_until = time.monotonic() + delay
                if delay > self.MAX_AUTO_RETRY_DELAY_SECONDS:
                    return response
                self.sleep(delay)
            else:
                # 401/403은 세션 만료로 보고 상세 페이지에서 한 번만 갱신한다.
                client.cookies.clear()
                self._prime_session(client, article_no)
                self._remember_cookie_names(client)
            retry_response = client.request(
                request.method,
                request.url,
                headers={
                    **request.headers,
                    "Referer": self.ARTICLE_PAGE_URL.format(article_no=article_no),
                },
                content=request.data,
            )
            self._remember_cookie_names(client)
            if retry_response.status_code == 429:
                retry_delay = self._retry_after_seconds(retry_response)
                type(self)._rate_limited_until = time.monotonic() + retry_delay
            return retry_response

    def _prime_session(self, client: httpx.Client, article_no: str) -> None:
        """매물 상세 페이지가 정상적으로 내려주는 세션 쿠키를 메모리에 저장한다."""
        page_url = self.ARTICLE_PAGE_URL.format(article_no=article_no)
        response = client.get(
            page_url,
            headers={
                **self.BROWSER_HEADERS,
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
            },
        )
        # 초기 페이지도 제한되면 API를 추가 호출하지 않는다.
        if response.status_code == 429:
            delay = self._retry_after_seconds(response)
            type(self)._rate_limited_until = time.monotonic() + delay
            response.raise_for_status()
        response.raise_for_status()

    def _remember_cookie_names(self, client: httpx.Client) -> None:
        # 값은 로그/디스크에 남기지 않고 Client의 메모리 쿠키 저장소에만 둔다.
        self.session_cookie_names = tuple(sorted(set(client.cookies.keys())))

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float:
        value = response.headers.get("Retry-After", "").strip()
        if value.isdigit():
            return max(0.0, float(value))
        if value:
            try:
                retry_at = parsedate_to_datetime(value)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                return max(
                    0.0,
                    (retry_at - datetime.now(timezone.utc)).total_seconds(),
                )
            except (TypeError, ValueError, OverflowError):
                pass
        # 헤더가 없을 때의 짧고 제한적인 기본 대기. 무한 재시도는 하지 않는다.
        return 3.0


def harvest_naver_credentials(
    article_no: str,
    *,
    browser_channel: str = "chrome",
    headless: bool = True,
    log: Callable[[str], None] | None = None,
) -> tuple[str, str] | None:
    """헤드리스 브라우저로 네이버 land 페이지를 열어 API 요청의 authorization 토큰과
    세션 쿠키(PROP_TEST_* 등)를 가로채 (authorization, cookie_str)로 돌려준다.

    네이버 토큰은 프론트엔드 자바스크립트가 실행 시점에 생성하므로 httpx만으로는
    만들 수 없다. 그래서 창 없이 브라우저 엔진으로 JS를 한 번 돌려 값을 수확한다.
    Playwright가 없거나 차단·오류가 나면 None(다른 폴백으로 넘어감)."""

    def _say(message: str) -> None:
        if log:
            log(message)

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    url = PropertyFetcher.ARTICLE_PAGE_URL.format(article_no=article_no)
    captured: dict[str, str | None] = {"auth": None}
    cookie_str = ""
    browser = None
    try:
        with sync_playwright() as playwright:
            launch_options: dict[str, Any] = {
                "headless": headless,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-sandbox",
                ],
            }
            if browser_channel:
                launch_options["channel"] = browser_channel
            try:
                browser = playwright.chromium.launch(**launch_options)
            except PlaywrightError:
                launch_options.pop("channel", None)
                browser = playwright.chromium.launch(**launch_options)

            context = browser.new_context(
                user_agent=PropertyFetcher.BROWSER_HEADERS["User-Agent"],
                locale="ko-KR",
                timezone_id="Asia/Seoul",
                viewport={"width": 1280, "height": 900},
            )
            # 자동화 감지 우회(headless로도 통과할 확률을 높인다).
            context.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                "window.chrome={runtime:{}};"
                "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});"
                "Object.defineProperty(navigator,'languages',"
                "{get:()=>['ko-KR','ko','en-US','en']});"
            )
            page = context.new_page()

            def on_request(request: Any) -> None:
                if captured["auth"]:
                    return
                if "/api/" in request.url:
                    value = request.headers.get("authorization")
                    if value and value.lower().startswith("bearer "):
                        captured["auth"] = value

            page.on("request", on_request)
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)

            # 페이지의 API 호출(=토큰)이 발생할 시간을 준다.
            waited = 0
            while waited < 15_000 and not captured["auth"]:
                page.wait_for_timeout(500)
                waited += 500

            cookies = context.cookies()
            cookie_str = "; ".join(
                f"{cookie['name']}={cookie['value']}"
                for cookie in cookies
                if cookie.get("name")
            )
    except Exception:
        return None
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass

    authorization = captured["auth"]
    if not authorization or not cookie_str:
        return None
    return authorization, cookie_str


def build_curl_from_credentials(
    article_no: str, authorization: str, cookie_str: str
) -> str:
    """자동 갱신으로 얻은 토큰·쿠키를 재사용 가능한 cURL 문자열로 만든다.

    URL은 {article_no} 자리표시자를 써서(parse 단계에서 실제 번호로 치환) 어느
    매물에나 재사용된다."""
    url = PropertyFetcher.DEFAULT_URL.format(article_no="{article_no}")
    user_agent = PropertyFetcher.BROWSER_HEADERS["User-Agent"]
    parts = [
        f"curl '{url}'",
        f"-H 'authorization: {authorization}'",
        "-H 'accept: application/json, text/plain, */*'",
        "-H 'accept-language: ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7'",
        f"-H 'user-agent: {user_agent}'",
        f"-b '{cookie_str}'",
    ]
    return " ".join(parts)
