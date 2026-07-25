"""BYO-AI 방식용 프롬프트 생성기.

앱은 기초자료로 (1) 블로그 글 작성 프롬프트와 (2) 이미지 생성 프롬프트를 만들어
사용자에게 제공한다. 사용자는 각자 쓰는 AI(제미나이·챗GPT 등)에 붙여넣어 결과를
받고, 완성 텍스트와 이미지를 다시 앱에 넣어 포스팅한다.

핵심 원칙:
- 이미지는 실제 매물을 재현하지 않는다(표시·광고법 허위광고 방지).
  썸네일은 텍스트가 지배하는 커버 그래픽, 본문 이미지는 내용 연상 개념/무드 이미지.
- 블로그 글은 코중사 포맷을 따르되 검색 노출(SEO)에 유리하게, 규정 안전 문구를 포함.
"""

from __future__ import annotations

import json
import re

from .content_writer import (
    MANDATORY_INQUIRY_TEXT,
    MANDATORY_TRANSACTION_NOTICE,
)
from .models import PropertyInfo


# 본문 이미지 개념 → 프롬프트(특정 매물·장소 재현 금지, 무드/개념).
_COMMON_PHOTO_STYLE = (
    "Editorial lifestyle concept photography, photorealistic but generic (NOT a "
    "specific real place). Sony A7R V full-frame, natural soft daylight, shallow "
    "depth of field, true-to-life color, warm inviting premium mood. "
    "No readable signage or brand text, no identifiable faces, no logos, no watermarks."
)

_CONCEPT_IMAGE_PROMPTS: dict[str, str] = {
    "교통": (
        "한국 도심의 편리한 대중교통·상권을 연상시키는 장면(밝은 지하철/버스 정류장 또는 "
        "활기찬 상점가), 일상적 이동 편의의 느낌. " + _COMMON_PHOTO_STYLE
    ),
    "학군": (
        "안전하고 교육 친화적인 동네를 연상시키는 장면(아침 햇살의 가로수 통학길, "
        "멀리 흐릿한 학생들 - 얼굴 식별 불가), 안심되는 분위기. " + _COMMON_PHOTO_STYLE
    ),
    "생활": (
        "동네를 여유롭게 즐기는 일상(아늑한 카페 거리 또는 공원·해변 산책, 골든아워), "
        "편안한 생활의 느낌. " + _COMMON_PHOTO_STYLE
    ),
    "개발": (
        "도시의 성장과 활기를 연상시키는 일반적인 도시 스카이라인(특정 개발지 재현 금지), "
        "미래 가치의 느낌. " + _COMMON_PHOTO_STYLE
    ),
    "주거": (
        "따뜻한 주거 라이프스타일 무드(밝고 아늑한 거실 분위기, 특정 집 아님). "
        + _COMMON_PHOTO_STYLE
    ),
}

BODY_IMAGE_CAPTION = "이해를 돕기 위한 연출 이미지이며, 실제 매물과 무관합니다."


def _region_label(address: str) -> str:
    parts = [part for part in address.split() if part and part != "정보 없음"]
    if len(parts) >= 3 and parts[0].endswith(("시", "도")):
        return " ".join(parts[1:3])
    if len(parts) >= 2:
        return " ".join(parts[:2])
    return parts[0] if parts else "지역"


def _dong(address: str) -> str:
    match = re.search(r"([가-힣]+동)", address)
    return match.group(1) if match else ""


def _gu(address: str) -> str:
    match = re.search(r"([가-힣]+구)", address)
    return match.group(1) if match else ""


def _pyeong_label(area: str) -> str:
    supply = re.search(r"공급\s*([0-9]+(?:\.[0-9]+)?)\s*㎡", area)
    any_area = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*㎡", area)
    match = supply or any_area
    if not match:
        return "면적 확인"
    pyeong = max(1, round(float(match.group(1)) / 3.3058))
    return f"{pyeong}평"


def _has(value: str) -> bool:
    text = str(value or "").strip()
    return bool(text) and text not in {"정보 없음", "-", ""}


def select_body_image_concepts(research: str) -> list[str]:
    """조사 자료에서 강조 가능한 3개 개념을 고른다(관련 섹션이 있는 것 우선)."""
    order: list[tuple[str, str]] = [
        ("교통", "## 🚇 교통"),
        ("학군", "## 🎓 학군"),
        ("생활", "## 🛒 생활 편의"),
        ("개발", "개발계획"),
    ]
    picked = [key for key, marker in order if marker in research]
    for key in ("교통", "학군", "생활", "주거"):
        if len(picked) >= 3:
            break
        if key not in picked:
            picked.append(key)
    return picked[:3]


def _clean_pyeong(area: str) -> str:
    label = _pyeong_label(area)
    return label if label.endswith("평") and "확인" not in label else ""


def build_hashtags(property_info: PropertyInfo, *, limit: int = 15) -> list[str]:
    """매물 데이터에서 검색 노출용 해시태그(공백 없는 토큰)를 미리 생성한다."""
    address = property_info.address or ""
    building = property_info.complex_name or property_info.name
    region_parts = [
        part for part in address.split() if part and part != "정보 없음"
    ]
    city = region_parts[0] if region_parts and region_parts[0].endswith(
        ("시", "도")
    ) else ""
    gu = _gu(address)
    dong = _dong(address)
    pyeong = _clean_pyeong(property_info.area)
    trade = property_info.trade_type if _has(property_info.trade_type) else ""
    ptype = property_info.property_type if _has(
        property_info.property_type
    ) else ""

    tags: list[str] = []

    def add(*words: str) -> None:
        token = "".join(
            str(word).replace(" ", "") for word in words if _has(str(word))
        )
        if token and token not in tags:
            tags.append(token)

    add(building)
    add(dong)
    add(gu)
    add(city)
    add(dong, ptype)
    add(dong, trade)
    add(building, trade)
    add(building, pyeong)
    add(gu, trade)
    add(gu, ptype)
    add(ptype, trade)
    add(dong, ptype, trade)
    add(building, ptype)
    add(pyeong, trade)
    add(dong, "부동산")
    add(gu, "부동산")
    add(city, ptype)
    return tags[:limit]


def build_image_prompts(property_info: PropertyInfo, research: str = "") -> dict:
    """썸네일 1 + 본문 개념 이미지 3을 담은 구조를 반환(JSON 직렬화 가능)."""
    building = property_info.complex_name or property_info.name
    region = _region_label(property_info.address)
    pyeong = _pyeong_label(property_info.area)
    price_line = " ".join(
        part for part in (property_info.trade_type, property_info.price)
        if _has(part)
    )

    thumbnail = {
        "task": "korean_real_estate_blog_thumbnail",
        "aspect_ratio": "1:1",
        "prompt": (
            f"Premium Korean apartment blog cover graphic for '{building}' in {region}. "
            "Background: a general, tasteful premium-apartment mood or clean abstract "
            "architectural graphic (do NOT depict a specific real building). "
            "Sony A7R V look, golden-hour warm light, natural HDR, editorial premium mood. "
            "Center a semi-transparent dark-navy rounded card with a thin gold frame; "
            "render the Korean text EXACTLY and legibly: "
            f"small top 'Modern & Premium', large title '{building}', "
            f"middle '{price_line}', bottom pill '{pyeong}'. "
            "No people, no logos, no watermarks, no extra or garbled text."
        ),
        "text_overlay": {
            "top": "Modern & Premium",
            "title": building,
            "price": price_line,
            "badge": pyeong,
        },
        "negatives": "specific real building, garbled Korean, extra logos/watermarks, people",
    }

    concepts = select_body_image_concepts(research)
    body_images = [
        {
            "slot": f"본문{i + 1}_{concept}",
            "concept": concept,
            "caption": BODY_IMAGE_CAPTION,
            "prompt": _CONCEPT_IMAGE_PROMPTS.get(concept, _CONCEPT_IMAGE_PROMPTS["주거"]),
        }
        for i, concept in enumerate(concepts)
    ]
    # 매물명(건물명)을 최상단에 두고, 이미지 상단에 함께 표기하도록 요청한다.
    return {
        "매물명": building,
        "요청": (
            f"생성하는 이미지(특히 썸네일) 최상단에 매물명 '{building}'을 "
            "한글로 또렷하게 표기해 주세요."
        ),
        "thumbnail": thumbnail,
        "body_images": body_images,
    }


def build_image_prompt_text(property_info: PropertyInfo, research: str = "") -> str:
    """사용자가 복사해 붙여넣기 좋은 JSON 텍스트."""
    return json.dumps(
        build_image_prompts(property_info, research),
        ensure_ascii=False,
        indent=2,
    )


def build_blog_prompt(
    property_info: PropertyInfo,
    research: str,
    *,
    office_name: str = "",
    writing_prompt: str = "",
) -> str:
    """사용자가 텍스트 AI에 붙여넣을 블로그 글 작성 프롬프트."""
    region = _region_label(property_info.address)
    dong = _dong(property_info.address) or region
    gu = _gu(property_info.address)
    pyeong = _pyeong_label(property_info.area)
    office = office_name.strip() or "○○공인중개사"
    extra = writing_prompt.strip()

    sections = [
        "당신은 대한민국 공인중개사의 네이버 블로그 매물광고 작성 도우미입니다.",
        "아래 [확정 데이터]와 [조사 메모]만 사용하고, 없는 정보는 지어내지 마세요.",
        "시세 상승·수익 보장·확정되지 않은 호재 단정은 금지합니다(부동산광고규정 준수).",
        "확인된 공식 자료(건축물대장 표제부·카카오 입지 등)는 신뢰할 수 있는 정보이므로 "
        "'일치하지 않을 수 있다'는 식으로 불필요하게 부정하지 말고 그대로 활용하세요. "
        "개별 호수의 권리관계만 계약 전 등기·중개대상물 확인설명서로 확인하도록 안내합니다.",
        "",
        "[확정 데이터]",
        property_info.summary(),
        "",
        "[조사 메모(공식 API·웹검색 정리)]",
        research.strip() or "추가 조사 메모 없음",
        "",
        "[검색 노출(SEO) 규칙 — 가장 중요]",
        f"1. 제목: \"{region} {property_info.complex_name or property_info.name} {pyeong} "
        f"{property_info.trade_type} | (핵심특징)\" — 지역·단지·평형·거래유형을 앞쪽에.",
        f"2. 첫 문단 2줄 안에 \"{region} {property_info.complex_name or property_info.name} "
        f"{property_info.trade_type}\"를 자연스럽게 넣기.",
        f"3. 본문에서 핵심 키워드를 자연스럽게 반복: \"{dong}\", "
        f"\"{property_info.complex_name or property_info.name}\", \"{pyeong}\", "
        f"\"{property_info.trade_type}\" (각 2~3회, 스터핑 금지).",
        f"4. 롱테일 키워드를 문맥에 녹이기: \"{dong} 아파트 {property_info.trade_type}\", "
        + (f"\"{gu} {property_info.trade_type}\", " if gu else "")
        + f"\"{property_info.complex_name or property_info.name} {pyeong}\".",
        "5. 개발호재/학군/교통 소제목에는 실제 지역·시설 고유명사를 포함.",
        "6. 마지막에 해시태그 10~15개: 지역/구/동/단지명/평형/거래유형/생활권 조합.",
        "",
        "[모바일 가독성]",
        "- 한 문단 2~3줄, 문단 사이 빈 줄, 핵심 키워드 **굵게**, 이모지는 문두에만.",
        "- 거리값은 '직선거리'로 명시, 도보시간으로 바꾸지 않기. 700~1,200자.",
    ]
    if extra:
        sections += ["", "[사용자 지정 글 작성 기준]", extra]
    sections += [
        "",
        "[출력 구조 — 아래 뼈대를 그대로 유지, [ ] 플레이스홀더 절대 삭제 금지]",
        "# (제목)",
        "[THUMBNAIL_IMAGE]",
        f"안녕하세요, **{office}**입니다.",
        "## 📍 매물 소개",
        "## ✨ 매물 특징",
        "## 🏢 단지정보",
        "[TABLE_COMPLEX]",
        "## 📊 매물 상세 정보",
        "[TABLE_SUMMARY]",
        "[TABLE_DETAIL]",
        "## ⚠️ 매물 거래상태 확인 안내",
        MANDATORY_TRANSACTION_NOTICE,
        "## 🚀 개발 호재 및 미래 가치",
        "## 🏫 주변 학군 (초품아 & 학원가)",
        "## 🚇 교통 및 편의시설",
        "## 🏠 중개사무소정보",
        "[TABLE_REALTOR]",
        "## 📞 문의 안내",
        f"(아래 문구를 글자 그대로 포함) {MANDATORY_INQUIRY_TEXT}",
        "해시태그: #... (10~15개)",
    ]
    return "\n".join(sections).strip()
