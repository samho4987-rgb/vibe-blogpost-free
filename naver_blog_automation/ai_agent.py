from __future__ import annotations

import io
import json
import random
import re
import threading
import time
from pathlib import Path
from typing import Any

from .content_writer import (
    INQUIRY_HEADING,
    INQUIRY_INTRO,
    MANDATORY_INQUIRY_TEXT,
    ensure_inquiry_section,
)
from .models import BlogContent, PropertyInfo
from .settings import DEFAULT_WRITING_PROMPT
from .thumbnail import create_demo_thumbnail


class AIConfigurationError(RuntimeError):
    pass


class AIQuotaExceededError(AIConfigurationError):
    """Gemini 사용량 한도를 초과해 온라인 생성을 계속할 수 없는 상태."""


class AIServiceUnavailableError(AIConfigurationError):
    """503 UNAVAILABLE 등 Gemini 서버의 일시적 과부하로 생성에 실패한 상태."""


def is_gemini_transient_error(exc: Exception) -> bool:
    """503 UNAVAILABLE, 500 INTERNAL처럼 잠시 후 되는 일시적 서버 오류를 구분한다."""
    code = getattr(exc, "code", None)
    status = str(getattr(exc, "status", "") or "").upper()
    message = str(getattr(exc, "message", "") or exc).upper()
    if code in (500, 502, 503, 504):
        return True
    if status in ("UNAVAILABLE", "INTERNAL", "DEADLINE_EXCEEDED"):
        return True
    markers = (
        "UNAVAILABLE",
        "HIGH DEMAND",
        "OVERLOADED",
        "TRY AGAIN LATER",
        "INTERNAL ERROR",
        "TEMPORARILY",
        "SERVICE UNAVAILABLE",
    )
    return any(marker in message for marker in markers)


def is_gemini_quota_error(exc: Exception) -> bool:
    code = getattr(exc, "code", None)
    status = str(getattr(exc, "status", "") or "").upper()
    message = str(getattr(exc, "message", "") or exc).upper()
    return (
        code == 429
        or status == "RESOURCE_EXHAUSTED"
        or "RESOURCE_EXHAUSTED" in message
    )


def gemini_retry_delay_seconds(exc: Exception) -> float | None:
    """google.rpc.RetryInfo의 짧은 retryDelay만 숫자로 해석한다."""
    payload = getattr(exc, "details", None)
    if not isinstance(payload, dict):
        return None
    error = payload.get("error", payload)
    if not isinstance(error, dict):
        return None
    details = error.get("details", [])
    if not isinstance(details, list):
        return None
    for detail in details:
        if not isinstance(detail, dict):
            continue
        if not str(detail.get("@type", "")).endswith("RetryInfo"):
            continue
        raw_delay = str(detail.get("retryDelay", "")).strip()
        match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)s", raw_delay)
        if match:
            return float(match.group(1))
    return None


def is_non_retryable_gemini_quota(exc: Exception) -> bool:
    """일일·결제·사용 불가 모델처럼 기다려도 바로 회복되지 않는 429를 구분한다."""
    details = getattr(exc, "details", None)
    try:
        detail_text = json.dumps(details, ensure_ascii=False)
    except (TypeError, ValueError):
        detail_text = str(details or "")
    message = " ".join(
        (
            str(getattr(exc, "message", "") or ""),
            str(exc),
            detail_text,
        )
    ).lower()
    hard_limit_markers = (
        "requests per day",
        "request per day",
        "per_day",
        "daily",
        "rpd",
        "billing",
        "plan and billing",
        "spend",
        "limit: 0",
        "quota value: 0",
    )
    return any(marker in message for marker in hard_limit_markers)


def _json_from_text(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    else:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise AIConfigurationError("AI 응답에서 콘텐츠 JSON을 읽지 못했습니다.") from exc
    if not isinstance(parsed, dict):
        raise AIConfigurationError("AI 콘텐츠 응답이 객체 형식이 아닙니다.")
    return parsed


def _region_label(address: str) -> str:
    parts = [part for part in address.split() if part and part != "정보 없음"]
    if len(parts) >= 3 and parts[0].endswith(("시", "도")):
        return " ".join(parts[1:3])
    if len(parts) >= 2:
        return " ".join(parts[:2])
    return parts[0] if parts else "지역"


def _pyeong_label(area: str) -> str:
    supply = re.search(r"공급\s*([0-9]+(?:\.[0-9]+)?)\s*㎡", area)
    any_area = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*㎡", area)
    match = supply or any_area
    if not match:
        return "면적 확인"
    pyeong = max(1, round(float(match.group(1)) / 3.3058))
    return f"{pyeong}평"


def _meaningful(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text) and text not in {
        "정보 없음",
        "-",
        "0",
        "0개",
        "0세대",
        "0대",
    }


def _property_highlights(property_info: PropertyInfo) -> list[str]:
    """수집된 매물정보에서 의미 있는 항목만 골라 장점 불릿을 만든다."""
    bullets: list[str] = []

    structure_bits: list[str] = []
    if _meaningful(property_info.area):
        structure_bits.append(f"**{property_info.area}**")
    if _meaningful(property_info.rooms):
        room_text = property_info.rooms
        if _meaningful(property_info.bathrooms):
            room_text = f"방 {property_info.rooms} · 욕실 {property_info.bathrooms}"
        structure_bits.append(room_text)
    if structure_bits:
        bullets.append(" / ".join(structure_bits) + " 구조")

    place_bits: list[str] = []
    if _meaningful(property_info.floor):
        place_bits.append(f"**{property_info.floor}**")
    if _meaningful(property_info.direction):
        place_bits.append(f"**{property_info.direction}**")
    if place_bits:
        bullets.append(" · ".join(place_bits))

    facility_bits: list[str] = []
    if _meaningful(property_info.heating):
        facility_bits.append(f"난방 {property_info.heating}")
    if _meaningful(property_info.parking):
        facility_bits.append(f"주차 {property_info.parking}")
    if _meaningful(property_info.entrance_type):
        facility_bits.append(f"{property_info.entrance_type} 구조")
    if facility_bits:
        bullets.append(" · ".join(facility_bits))

    complex_bits: list[str] = []
    if _meaningful(property_info.builder):
        complex_bits.append(f"{property_info.builder} 시공")
    if _meaningful(property_info.total_units):
        units = str(property_info.total_units).strip()
        # 세대수 값에 이미 '세대'가 포함된 경우 중복 표기(예: 231세대세대)를 막는다.
        if not units.endswith("세대"):
            units = f"{units}세대"
        complex_bits.append(f"총 {units}")
    if complex_bits:
        bullets.append(" · ".join(complex_bits) + " 단지")

    if _meaningful(property_info.maintenance_fee):
        bullets.append(f"관리비 {property_info.maintenance_fee} (변동 가능, 방문 시 확인)")

    for feature in property_info.features[:4]:
        if _meaningful(feature):
            bullets.append(feature.strip())

    # 중복 제거(순서 유지)
    seen: set[str] = set()
    unique: list[str] = []
    for bullet in bullets:
        key = re.sub(r"\s+", "", bullet)
        if key not in seen:
            seen.add(key)
            unique.append(bullet)
    return unique[:7]


def _recommendation_targets(property_info: PropertyInfo) -> list[str]:
    """확인된 조건에서만 추천 대상을 조심스럽게 도출한다."""
    targets: list[str] = []
    trade = property_info.trade_type
    if "매매" in trade:
        targets.append("실거주하며 장기 보유를 계획하시는 분")
    elif "전세" in trade or "월세" in trade or "임대" in trade:
        targets.append("해당 지역에서 안정적으로 거주하실 분")

    rooms_match = re.search(r"\d+", property_info.rooms or "")
    if rooms_match and int(rooms_match.group()) >= 3:
        targets.append("자녀가 있어 넉넉한 방 구성이 필요한 가족")

    if any(key in (property_info.direction or "") for key in ("남", "동남", "남동", "남서")):
        targets.append("채광과 일조를 중요하게 보시는 분")

    if not targets:
        targets.append("합리적인 조건의 실매물을 찾으시는 분")
    return targets[:3]


def _feature_summary(property_info: PropertyInfo) -> str:
    source = (
        property_info.features[0]
        if property_info.features
        else property_info.description
    )
    cleaned = re.sub(r"\s+", " ", source).strip(" ,.|")
    if not cleaned or cleaned == "정보 없음":
        return "상세 조건 확인 가능한 매물"
    return cleaned[:38].rstrip()


def _format_blog_title(property_info: PropertyInfo, proposed: str = "") -> str:
    feature = proposed.split("|", 1)[1].strip() if "|" in proposed else ""
    if not feature:
        feature = _feature_summary(property_info)
    return (
        f"{_region_label(property_info.address)} {property_info.name} "
        f"{_pyeong_label(property_info.area)} {property_info.trade_type} | {feature}"
    )


def _extract_enrichment_sections(research: str) -> str:
    wanted = (
        "## 📍 입지 분석",
        "## 🚇 교통",
        "## 🎓 학군",
        "## 🛒 생활 편의",
        "## 📐 면적 분석",
        "## 🏗 건축물대장 확인",
    )
    sections: list[str] = []
    for heading in wanted:
        start = research.find(heading)
        if start < 0:
            continue
        next_heading = research.find("\n## ", start + len(heading))
        end = next_heading if next_heading >= 0 else len(research)
        section = research[start:end].strip()
        section = re.sub(
            r"(?m)^-\s*\[카카오맵(?:에서 위치| 로드뷰) 확인\]"
            r"\(https://map\.kakao\.com/link/(?:map|roadview)/[^)\s]+\)\s*$",
            "",
            section,
        )
        section = re.sub(r"\n{3,}", "\n\n", section).strip()
        if section and section != heading:
            sections.append(section)
    return "\n\n".join(sections)


def _merge_verified_enrichment(body: str, research: str) -> str:
    """AI 초안의 사실 섹션을 공식 API에서 만든 문장으로 교체한다."""
    verified = _extract_enrichment_sections(research)
    cleaned = re.sub(
        r"(?m)^-\s*\[카카오맵(?:에서 위치| 로드뷰) 확인\]"
        r"\(https://map\.kakao\.com/link/(?:map|roadview)/[^)\s]+\)\s*$",
        "",
        body,
    )
    if not verified:
        cleaned = re.sub(
            r"(?ms)^##\s*📍\s*입지 분석\s*$\s*(?=^##\s|\Z)",
            "",
            cleaned,
        )
        return re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    for heading in (
        "## 📍 입지 분석",
        "## 🚇 교통",
        "## 🎓 학군",
        "## 🛒 생활 편의",
        "## 📐 면적 분석",
        "## 🏗 건축물대장 확인",
    ):
        cleaned = re.sub(
            rf"(?ms)^{re.escape(heading)}\s*$.*?(?=^##\s|\Z)",
            "",
            cleaned,
        )
    insert_before = re.search(
        r"(?m)^##\s*(?:✅\s*)?계약 전 확인사항\s*$|"
        r"^##\s*📞\s*문의 안내\s*$",
        cleaned,
    )
    if insert_before:
        merged = (
            cleaned[: insert_before.start()].rstrip()
            + "\n\n"
            + verified
            + "\n\n"
            + cleaned[insert_before.start() :].lstrip()
        )
    else:
        merged = f"{cleaned.rstrip()}\n\n{verified}"
    return re.sub(r"\n{3,}", "\n\n", merged).strip()


class ContentAgent:
    def __init__(
        self,
        *,
        api_key: str,
        text_model: str,
        image_model: str,
        tone_guide: str,
        writing_prompt: str = DEFAULT_WRITING_PROMPT,
        phone_number: str = "",
        office_name: str = "",
        min_request_interval_seconds: float = 12.5,
        ai_engine: str = "gemini",
        anthropic_api_key: str = "",
        anthropic_model: str = "claude-sonnet-4-20250514",
    ) -> None:
        self.api_key = api_key.strip()
        self.text_model = text_model
        self.image_model = image_model
        self.tone_guide = tone_guide.strip()
        self.writing_prompt = writing_prompt.strip() or DEFAULT_WRITING_PROMPT
        self.phone_number = phone_number.strip()
        self.office_name = office_name.strip()
        self.ai_engine = (ai_engine or "gemini").strip().lower()
        self.anthropic_api_key = anthropic_api_key.strip()
        self.anthropic_model = (
            anthropic_model or "claude-sonnet-4-20250514"
        ).strip()
        self.min_request_interval_seconds = max(
            0.0,
            float(min_request_interval_seconds),
        )
        self._last_request_started_by_model: dict[str, float] = {}
        self._rate_limit_lock = threading.Lock()

    def _client(self):
        if not self.api_key:
            raise AIConfigurationError("GEMINI_API_KEY가 설정되지 않았습니다.")
        try:
            from google import genai
        except ImportError as exc:
            raise AIConfigurationError(
                "Google Gen AI 패키지가 없습니다. 설치 스크립트를 다시 실행해 주세요."
            ) from exc
        return genai.Client(api_key=self.api_key)

    def offline_copy(self) -> "ContentAgent":
        return ContentAgent(
            api_key="",
            text_model=self.text_model,
            image_model=self.image_model,
            tone_guide=self.tone_guide,
            writing_prompt=self.writing_prompt,
            phone_number=self.phone_number,
            office_name=self.office_name,
            min_request_interval_seconds=self.min_request_interval_seconds,
            ai_engine=self.ai_engine,
            anthropic_api_key="",
            anthropic_model=self.anthropic_model,
        )

    def _wait_for_model_slot(self, model: str) -> None:
        """무료 등급 5 RPM에 맞춰 동일 모델 호출 시작 간격을 보장한다."""
        interval = self.min_request_interval_seconds
        if interval <= 0:
            return
        with self._rate_limit_lock:
            now = time.monotonic()
            previous = self._last_request_started_by_model.get(model)
            if previous is not None:
                remaining = interval - (now - previous)
                if remaining > 0:
                    time.sleep(remaining)
            self._last_request_started_by_model[model] = time.monotonic()

    def _generate_content(self, client: Any, **kwargs):
        model = str(kwargs.get("model", "") or "default")
        last_error: Exception | None = None
        last_kind = "quota"
        max_retries = 2

        for attempt in range(max_retries + 1):
            self._wait_for_model_slot(model)
            try:
                return client.models.generate_content(**kwargs)
            except Exception as exc:
                quota = is_gemini_quota_error(exc)
                transient = is_gemini_transient_error(exc)
                if not quota and not transient:
                    raise
                last_error = exc
                last_kind = "quota" if quota else "transient"
                if attempt >= max_retries:
                    break
                if quota:
                    retry_delay = gemini_retry_delay_seconds(exc)
                    # Google이 RetryInfo를 보냈다면 일반 오류 문구에 billing이 함께
                    # 들어 있어도 명시된 재시도 시간을 우선한다.
                    if retry_delay is None and is_non_retryable_gemini_quota(exc):
                        break
                    if retry_delay is None:
                        retry_delay = min(16.0, 2.0 * (2**attempt))
                        retry_delay += random.uniform(0.0, 0.5)
                else:
                    # 503 UNAVAILABLE 등 일시적 과부하는 짧은 지수 백오프로 재시도한다.
                    retry_delay = min(16.0, 2.0 * (2**attempt)) + random.uniform(0.0, 0.5)
                time.sleep(max(0.0, min(retry_delay, 60.0)))

        if last_kind == "transient":
            raise AIServiceUnavailableError(
                "Google Gemini 서버가 일시적으로 혼잡합니다(503). 잠시 후 다시 "
                "'(선택) AI로 자동 글쓰기'를 눌러 AI 원고를 시도할 수 있습니다."
            ) from last_error
        raise AIQuotaExceededError(
            "Google Gemini API 사용량 한도에 도달했습니다. 무료 등급의 일일 한도, "
            "현재 프로젝트에서 사용할 수 있는 모델, 결제 상태를 AI Studio에서 "
            "확인해 주세요."
        ) from last_error

    @staticmethod
    def _grounding_sources(response: Any) -> list[str]:
        sources: list[str] = []
        seen_uris: set[str] = set()
        for candidate in getattr(response, "candidates", []) or []:
            metadata = getattr(candidate, "grounding_metadata", None)
            for chunk in getattr(metadata, "grounding_chunks", []) or []:
                web = getattr(chunk, "web", None)
                uri = str(getattr(web, "uri", "") or "").strip()
                title = str(getattr(web, "title", "") or "").strip()
                if uri and uri not in seen_uris:
                    seen_uris.add(uri)
                    sources.append(f"{title or 'Google Search 결과'} - {uri}")
        return sources

    def research(
        self,
        property_info: PropertyInfo,
        supplemental_context: str = "",
    ) -> str:
        if not self.api_key:
            base = self._demo_research(property_info)
            return (
                f"{supplemental_context.strip()}\n\n{base}".strip()
                if supplemental_context.strip()
                else base
            )
        client = self._client()
        prompt = f"""
대한민국 부동산 매물 블로그 글을 위한 사실 확인 조사입니다.

매물 기본정보:
{property_info.summary()}

[공식 API 보강 데이터]
{supplemental_context.strip() or "추가 API 데이터 없음"}

단지/건물 주변 교통, 생활편의, 학군, 공원, 공공기관 발표에 근거한 개발계획을
웹에서 조사해 주세요. 매물 주소가 불충분하면 그 사실을 명확히 표시하세요.
현재 확인할 수 없는 내용, 예상 수익, 시세 상승을 추측하지 마세요.
광고문이 아니라 작성자가 검토할 조사 메모로 작성하고 다음 형식을 지키세요.

## 교통
## 생활편의
## 교육·학군
## 개발계획·호재
## 글 작성 전 확인할 점
## 출처

출처에는 실제로 확인한 페이지의 제목과 URL을 적으세요.
""".strip()
        try:
            from google.genai import types

            response = self._generate_content(
                client,
                model=self.text_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )
            text = (response.text or "").strip()
            sources = self._grounding_sources(response)
            if sources:
                text = f"{text}\n\n## Google Search 확인 출처\n" + "\n".join(
                    f"- {source}" for source in sources
                )
            if supplemental_context.strip():
                text = (
                    f"{supplemental_context.strip()}\n\n"
                    "## Gemini Google Search 추가 조사\n\n"
                    f"{text}"
                )
            return text
        finally:
            client.close()

    def write(self, property_info: PropertyInfo, research: str) -> BlogContent:
        # 엔진별 키 확인 → 없으면 오프라인 초안. 있으면 선택 엔진으로 생성.
        if self.ai_engine == "anthropic":
            if not self.anthropic_api_key:
                return self._demo_content(property_info, research)
        elif not self.api_key:
            return self._demo_content(property_info, research)
        prompt = self._build_write_prompt(property_info, research)
        if self.ai_engine == "anthropic":
            raw = self._anthropic_generate(prompt)
        else:
            raw = self._gemini_generate(prompt)
        data = _json_from_text(raw)
        return self._build_content_from_data(data, property_info, research)

    def _build_write_prompt(self, property_info: PropertyInfo, research: str) -> str:
        """'프롬프트(복사)' 탭과 동일한 본문 작성 프롬프트를 기반으로 삼고,
        자동 글쓰기 경로가 쓰는 JSON 출력 형식만 얇게 덧붙인다.

        복사 탭(build_blog_prompt)과 자동 글쓰기가 같은 프롬프트를 쓰게 되어
        SEO·구조·필수 고지가 일치하고, 프롬프트를 한 곳(prompt_builder)에서만
        관리하면 된다. 표·썸네일 자리표시는 render_blog_markdown이 정리하므로
        본문에 남아 있어도 무방하다.
        """
        from .prompt_builder import build_blog_prompt

        phone_line = (
            f"문의 전화는 {self.phone_number}입니다."
            if self.phone_number
            else "전화번호는 제공되지 않았으므로 본문에 임의로 만들지 마세요."
        )
        base = build_blog_prompt(
            property_info,
            research,
            office_name=self.office_name,
            writing_prompt=self.writing_prompt,
        )
        tone = f"\n\n[작성 톤]\n{self.tone_guide}" if self.tone_guide else ""
        adapter = f"""
[출력 형식 — 매우 중요]
{phone_line}
위 지침에 따라 네이버 블로그 원고를 직접 작성한 뒤, 결과를 반드시 아래 JSON 객체
'하나'로만 출력하세요. 코드블록·설명 문장 없이 JSON만 출력합니다.
- "title": 위 제목 규칙에 맞는 제목 한 줄. 맨 앞의 '#' 기호와 제목 표시는 빼고 텍스트만.
- "body": 제목 줄을 제외한 본문 마크다운. 위 [출력 구조]의 소제목·문단을 담되,
  '해시태그:' 줄은 넣지 마세요(해시태그는 아래 배열로만). [THUMBNAIL_IMAGE]나
  [TABLE_...] 자리표시가 남아 있어도 괜찮습니다 — 표와 대표 이미지는 프로그램이
  자동으로 삽입·정리합니다.
- "hashtags": 해시태그 문자열 배열(각 항목은 '#' 없이 단어) 10~15개.
- "image_prompt": 글자 없는 대표 이미지 설명(선택).
과장·허위·확정되지 않은 호재 단정·수익 보장 표현은 금지합니다.
{{
  "title": "제목",
  "body": "줄바꿈을 포함한 본문",
  "hashtags": ["태그1", "태그2"],
  "image_prompt": "사진처럼 자연스러운 부동산 대표 이미지 설명. 이미지 안 글자는 금지"
}}
""".strip()
        return f"{base}{tone}\n\n{adapter}"

    def _gemini_generate(self, prompt: str) -> str:
        client = self._client()
        try:
            from google.genai import types

            response = self._generate_content(
                client,
                model=self.text_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )
            return response.text or ""
        finally:
            client.close()

    def _anthropic_generate(self, prompt: str) -> str:
        """Claude(Anthropic) Messages API를 raw HTTP로 호출한다."""
        import httpx

        try:
            response = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.anthropic_model,
                    "max_tokens": 4000,
                    "system": (
                        "당신은 대한민국 공인중개사의 네이버 블로그 매물광고 작성 "
                        "도우미입니다. 반드시 JSON 객체 하나만 출력하세요."
                    ),
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=60.0,
            )
        except httpx.RequestError as exc:
            raise AIServiceUnavailableError(
                "Claude(Anthropic) 서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요."
            ) from exc
        if response.status_code == 429:
            raise AIQuotaExceededError(
                "Claude(Anthropic) API 사용량 한도에 도달했습니다. 콘솔에서 한도·결제를 "
                "확인해 주세요."
            )
        if response.status_code in (500, 502, 503, 529):
            raise AIServiceUnavailableError(
                "Claude(Anthropic) 서버가 일시적으로 혼잡합니다. 잠시 후 다시 시도해 주세요."
            )
        if response.status_code >= 400:
            try:
                message = response.json().get("error", {}).get("message", "")
            except ValueError:
                message = ""
            raise AIConfigurationError(
                f"Claude(Anthropic) API 오류(HTTP {response.status_code}). {message}".strip()
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise AIConfigurationError(
                "Claude(Anthropic) 응답이 JSON이 아닙니다."
            ) from exc
        text = ""
        for block in payload.get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "text":
                text += str(block.get("text", ""))
        if not text.strip():
            raise AIConfigurationError(
                "Claude(Anthropic) 응답에서 콘텐츠를 읽지 못했습니다."
            )
        return text

    def _build_content_from_data(
        self,
        data: dict[str, Any],
        property_info: PropertyInfo,
        research: str,
    ) -> BlogContent:
        hashtags = data.get("hashtags", [])
        if isinstance(hashtags, str):
            hashtags = [item for item in re.split(r"[,\s#]+", hashtags) if item]
        body = _merge_verified_enrichment(
            str(data.get("body", "")).strip(),
            research,
        )
        return BlogContent(
            title=_format_blog_title(
                property_info,
                str(data.get("title", "")).strip(),
            ),
            body=ensure_inquiry_section(body),
            hashtags=[str(item).lstrip("#").strip() for item in hashtags if str(item).strip()],
            image_prompt=str(data.get("image_prompt", "")).strip()
            or "A clean editorial real-estate exterior photograph, no text, no logos",
        )

    def generate_thumbnail(
        self,
        content: BlogContent,
        property_info: PropertyInfo,
        target: Path,
    ) -> Path:
        if not self.api_key or not self.image_model:
            detail = (
                f"{property_info.trade_type} {property_info.price} · "
                f"{_pyeong_label(property_info.area)}"
            )
            return create_demo_thumbnail(
                target,
                property_info.name,
                property_info.address,
                detail,
            )
        client = self._client()
        prompt = (
            f"{content.image_prompt}\n"
            "Create a tasteful Korean real-estate blog cover image. "
            "Do not include any letters, numbers, watermarks, logos, signs, or UI."
        )
        try:
            from google.genai import types
            from PIL import Image

            response = self._generate_content(
                client,
                model=self.image_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    image_config=types.ImageConfig(aspect_ratio="3:2"),
                ),
            )
            image_bytes: bytes | None = None
            for part in getattr(response, "parts", []) or []:
                inline_data = getattr(part, "inline_data", None)
                data = getattr(inline_data, "data", None)
                if data:
                    image_bytes = data if isinstance(data, bytes) else bytes(data)
                    break
            if not image_bytes:
                raise AIConfigurationError(
                    "Gemini 이미지 모델이 이미지 데이터를 반환하지 않았습니다."
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(io.BytesIO(image_bytes)) as image:
                image.convert("RGB").save(target, format="PNG")
            return target
        finally:
            client.close()

    def _demo_research(self, property_info: PropertyInfo) -> str:
        feature_text = (
            ", ".join(property_info.features)
            if property_info.features
            else "수집된 특징 없음"
        )
        return (
            "## 수집된 매물정보\n"
            f"- 매물번호: {property_info.article_no}\n"
            f"- 매물명: {property_info.name}\n"
            f"- 유형·거래: {property_info.property_type} / {property_info.trade_type}\n"
            f"- 가격: {property_info.price}\n"
            f"- 주소: {property_info.address}\n"
            f"- 면적: {property_info.area}\n"
            f"- 층·방향·방: {property_info.floor} / {property_info.direction} / "
            f"{property_info.rooms}\n"
            f"- 특징: {feature_text}\n"
            f"- 설명: {property_info.description}\n"
            f"- 데이터 출처: {property_info.source}\n\n"
            "## 교통\n"
            f"- 샘플/오프라인 모드입니다. `{property_info.address}` 주변 교통은 직접 확인이 필요합니다.\n\n"
            "## 생활편의\n"
            "- 대형마트, 병원, 공원 등의 실제 거리와 영업 여부를 확인해 주세요.\n\n"
            "## 교육·학군\n"
            "- 학교 배정과 통학구역은 관할 교육청 자료로 확인해 주세요.\n\n"
            "## 개발계획·호재\n"
            "- 확인된 공공기관 출처가 없어 본문에서 확정적으로 언급하지 않습니다.\n\n"
            "## 글 작성 전 확인할 점\n"
            "- 가격, 면적, 층, 입주 가능일, 관리비를 중개대상물 확인설명 자료와 대조하세요.\n\n"
            "## 출처\n"
            "- 오프라인 미리보기이므로 웹 출처가 없습니다."
        )

    def _demo_content(self, property_info: PropertyInfo, research: str) -> BlogContent:
        feature_text = (
            ", ".join(property_info.features)
            if property_info.features
            else "현장 확인 후 안내"
        )
        contact = (
            f"문의: {self.phone_number}"
            if self.phone_number
            else "문의 방법은 블로그 프로필을 확인해 주세요."
        )
        region = _region_label(property_info.address)
        highlights = _property_highlights(property_info)
        if not highlights:
            highlights = [f"**{feature_text}**"]
        highlight_block = "\n".join(f"- {item}" for item in highlights)
        recommend_block = "\n".join(
            f"- {item}" for item in _recommendation_targets(property_info)
        )

        intro = (
            f"안녕하세요. 오늘은 **{region}**에 위치한 "
            f"**{property_info.name}** 매물을 소개해 드립니다."
        )
        deal_line = (
            f"이번 매물은 **{property_info.trade_type} {property_info.price}** 조건으로, "
            "현재 확인된 정보를 중심으로 꼼꼼하게 안내해 드리겠습니다."
        )
        description_block = ""
        if _meaningful(property_info.description):
            description_block = f"\n\n{property_info.description.strip()}"

        body = f"""
{intro}

{deal_line}

## ✨ 이 매물의 장점

{highlight_block}

## 🏠 이런 분께 추천

{recommend_block}{description_block}

## ✅ 계약 전 확인사항

가격, 면적, 관리비, 입주 가능일과 권리관계(등기부·중개대상물 확인설명서)는
계약 전에 반드시 다시 확인해 주세요.

{contact}

{INQUIRY_HEADING}

{INQUIRY_INTRO}

{MANDATORY_INQUIRY_TEXT}
""".strip()
        pyeong = _pyeong_label(property_info.area)
        region_tag = region.replace(" ", "")
        tags = [
            region_tag,
            region_tag + "부동산",
            property_info.name.replace(" ", ""),
            property_info.property_type.replace(" ", ""),
            property_info.trade_type.replace(" ", ""),
            pyeong.replace(" ", "") if pyeong != "면적 확인" else "",
            f"{region_tag}{property_info.trade_type.replace(' ', '')}",
            "부동산상담",
            "매물정보",
            "집구하기",
        ]
        clean_tags: list[str] = []
        seen_tags: set[str] = set()
        for item in tags:
            tag = item.strip()
            if not tag or "정보없음" in tag or tag in seen_tags:
                continue
            seen_tags.add(tag)
            clean_tags.append(tag)
        return BlogContent(
            title=_format_blog_title(property_info),
            body=_merge_verified_enrichment(body, research),
            hashtags=clean_tags,
            image_prompt=(
                "Clean editorial photograph of a modern residential property exterior "
                "in Korea, warm daylight, professional real estate photography, no text"
            ),
        )
