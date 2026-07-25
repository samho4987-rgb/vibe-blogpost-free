from __future__ import annotations

import re
from pathlib import Path

from .models import BlogContent


REQUIRED_PLACEHOLDERS = (
    "[THUMBNAIL_IMAGE]",
    "[TABLE_COMPLEX]",
    "[TABLE_SUMMARY]",
    "[TABLE_DETAIL]",
    "[TABLE_REALTOR]",
)

TRANSACTION_NOTICE_HEADING = "## ⚠️ 매물 거래상태 확인 안내"
MANDATORY_TRANSACTION_NOTICE = (
    "공인중개사법 제18조의2에 의거하여 위 매물은 실거래 매물임을 확인하였으나 "
    "포스팅을 열람하는 시점에서는 거래완료가 되었을 수 있으니 부동산으로 거래가 "
    "가능한 매물인지 꼭 확인부탁드립니다.~!!!"
)

INQUIRY_HEADING = "## 📞 문의 안내"
INQUIRY_INTRO = (
    "궁금한 점이 있거나 직접 집 보기를 원하신다면 언제든 편하게 연락해 주세요."
)
MANDATORY_INQUIRY_TEXT = (
    "본 매물 외에도 인근 지역의 다양한 매물을 다량 확보하고 있으니, "
    "편하게 문의 주시면 조건에 맞는 원하시는 매물을 친절하게 안내해 드리겠습니다"
)
# 두 문의 문구를 정해진 순서(확보 안내 → 연락 안내)로 한 문단에 붙여서 쓴다.
INQUIRY_BLOCK = f"{MANDATORY_INQUIRY_TEXT}. {INQUIRY_INTRO}"
_INQUIRY_SECTION_PATTERN = re.compile(
    r"(?ms)^##\s*📞\s*문의 안내\s*\n+(.*?)(?=^##\s|\Z)"
)
# 붙여넣은 본문에 이미 들어 있을 수 있는 '거래상태 확인 안내' 섹션(제목~다음 ## 전까지).
_TRANSACTION_SECTION_PATTERN = re.compile(
    r"(?ms)^##[^\n]*거래상태 확인 안내[^\n]*\n+.*?(?=^##\s|\Z)"
)
# 표는 프로그램이 별도 삽입하므로, 외부 AI가 만든 표 섹션 제목(내용 없이 뜨는 제목)은
# 제거한다. 제거하지 않으면 '단지정보/매물 상세 정보/중개사무소 정보' 제목이 표 없이
# 본문 중간에 떠 보이고, 프로그램이 만든 같은 섹션과 중복된다.
_DUPLICATE_SECTION_PATTERNS = (
    re.compile(r"(?ms)^##[^\n]*단지\s*정보.*?(?=^##\s|\Z)"),
    re.compile(r"(?ms)^##[^\n]*매물\s*상세\s*정보.*?(?=^##\s|\Z)"),
    re.compile(r"(?ms)^##[^\n]*중개\s*사무소.*?(?=^##\s|\Z)"),
)


def _strip_duplicate_table_sections(body: str) -> str:
    """외부 AI 본문에 있는 표 섹션 제목(단지정보·매물 상세 정보·중개사무소)을 제거한다."""
    cleaned = body
    for pattern in _DUPLICATE_SECTION_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    return cleaned.strip()


# AI가 본문에 넣곤 하는 '썸네일 기획 아이디어 … 대표 이미지로 추천해 드립니다.' 안내문.
_THUMBNAIL_IDEA_PATTERN = re.compile(
    r"(?s)\*{0,2}\(?\s*썸네일\s*기획.*?추천[^)]*\)?\*{0,2}"
)


def _strip_thumbnail_idea(body: str) -> str:
    """본문에 섞여 들어온 '썸네일 기획 아이디어…추천' 안내 문구를 제거한다."""
    return _THUMBNAIL_IDEA_PATTERN.sub("", body).strip()


def _strip_transaction_notice(body: str) -> str:
    """본문에 이미 있는 거래상태 확인 고지(섹션·문구)를 제거한다.

    프롬프트가 외부 AI에게 고지문을 넣도록 안내하지만, 앱이 포스팅 시 고지문을
    한 번 더 붙이므로 중복(2회)이 생겨 검증에 실패한다. 여기서 미리 걷어내면
    render_blog_markdown이 항상 정확히 한 번만 넣게 된다.
    """
    cleaned = _TRANSACTION_SECTION_PATTERN.sub("", body)
    cleaned = cleaned.replace(MANDATORY_TRANSACTION_NOTICE, "")
    return cleaned.strip()


def ensure_inquiry_section(body: str) -> str:
    """문의 섹션과 필수 안내 문구가 AI 응답에서 빠져도 자동 보완한다."""
    cleaned = body.strip()
    match = _INQUIRY_SECTION_PATTERN.search(cleaned)
    if not match:
        return (
            f"{cleaned}\n\n\n{INQUIRY_HEADING}\n\n{INQUIRY_BLOCK}"
        ).strip()

    # 기존 섹션에서 필수 문구를 걷어내고, 정해진 순서로 붙인 한 문단을 맨 뒤에 다시 넣는다.
    section = match.group(1).strip()
    for token in (
        f"{MANDATORY_INQUIRY_TEXT}.",
        MANDATORY_INQUIRY_TEXT,
        INQUIRY_INTRO,
    ):
        section = section.replace(token, "")
    # 문구 제거 후 남은 외톨이 구두점·과도한 공백을 정리한다.
    section = re.sub(r"(?m)^[\s.·•]+$", "", section)
    section = re.sub(r"\n{3,}", "\n\n", section).strip()

    replacement = f"{INQUIRY_HEADING}\n\n"
    if section:
        replacement += f"{section}\n\n"
    replacement += INQUIRY_BLOCK
    return (
        cleaned[: match.start()]
        + replacement
        + cleaned[match.end() :]
    ).strip()


def _extract_inquiry_section(body: str) -> tuple[str, str]:
    ensured = ensure_inquiry_section(body)
    match = _INQUIRY_SECTION_PATTERN.search(ensured)
    if not match:
        raise ValueError("문의 안내 섹션을 구성하지 못했습니다.")
    main_body = (ensured[: match.start()] + ensured[match.end() :]).strip()
    return main_body, match.group(1).strip()


def _clean_body(body: str) -> str:
    """AI 본문에 실수로 들어간 고정 플레이스홀더와 과도한 공백을 정리한다."""
    cleaned = body.strip()
    for placeholder in REQUIRED_PLACEHOLDERS:
        cleaned = cleaned.replace(placeholder, "")
    blocks = [
        block.strip()
        for block in re.split(r"\n[ \t]*\n+", cleaned)
        if block.strip()
    ]
    # 모바일에서 문단 경계가 충분히 보이도록 빈 줄을 두 줄 둔다.
    return "\n\n\n".join(blocks)


def render_blog_markdown(content: BlogContent, *, realtor_footer: bool = True) -> str:
    """post_blog.py가 읽을 수 있는 고정 구조의 네이버 블로그 원고를 만든다.

    realtor_footer=True(기본)면 본문에 중개사무소 정보 표를 넣고,
    False면 블로그에서 중개사무소 정보 표기를 생략한다.
    """
    hashtags = " ".join(
        f"#{tag.lstrip('#').replace(' ', '')}"
        for tag in content.hashtags
        if tag.strip()
    )
    main_body, inquiry_body = _extract_inquiry_section(content.body)
    # 본문에 이미 들어간 거래상태 고지문을 제거해 중복 삽입을 막는다.
    main_body = _strip_transaction_notice(main_body)
    # 표 섹션 제목 중복(단지정보·매물 상세 정보·중개사무소)도 제거한다.
    main_body = _strip_duplicate_table_sections(main_body)
    # '썸네일 기획 아이디어…' 안내 문구도 제거한다.
    main_body = _strip_thumbnail_idea(main_body)
    # 문의 섹션 밖에 남은 필수 문의 문구 중복도 제거(동일한 '정확히 한 번' 오류 방지).
    main_body = main_body.replace(MANDATORY_INQUIRY_TEXT, "").strip()
    body = _clean_body(main_body)
    inquiry = _clean_body(inquiry_body)
    parts = [
        f"# {content.title.strip()}",
        "[THUMBNAIL_IMAGE]",
        body,
        "## 🏢 단지 정보",
        "[TABLE_COMPLEX]",
        "---",
        "## 📊 매물 상세 정보",
        "[TABLE_SUMMARY]",
        "[TABLE_DETAIL]",
        TRANSACTION_NOTICE_HEADING,
        MANDATORY_TRANSACTION_NOTICE,
    ]
    if realtor_footer:
        # 중개사무소 정보 표기(기본 ON). 해제하면 블로그에서 생략한다.
        parts.extend([
            "---",
            "## 🏠 중개사무소 정보",
            "[TABLE_REALTOR]",
        ])
    parts.extend([
        "---",
        INQUIRY_HEADING,
        inquiry,
    ])
    if hashtags:
        parts.extend(["---", hashtags])
    markdown = "\n\n\n".join(part for part in parts if part.strip()).strip() + "\n"
    for placeholder in REQUIRED_PLACEHOLDERS:
        if placeholder == "[TABLE_REALTOR]":
            continue  # 중개사무소 표기 여부에 따라 아래에서 따로 검사
        if markdown.count(placeholder) != 1:
            raise ValueError(f"필수 플레이스홀더가 정확히 한 번 필요합니다: {placeholder}")
    expected_realtor = 1 if realtor_footer else 0
    if markdown.count("[TABLE_REALTOR]") != expected_realtor:
        raise ValueError(
            "중개사무소 정보 표기 설정과 원고의 표 자리표시가 일치하지 않습니다."
        )
    if markdown.count(INQUIRY_HEADING) != 1:
        raise ValueError("문의 안내 섹션이 정확히 한 번 필요합니다.")
    if markdown.count(MANDATORY_TRANSACTION_NOTICE) != 1:
        raise ValueError("거래상태 확인 고지 문구가 정확히 한 번 필요합니다.")
    if markdown.count(MANDATORY_INQUIRY_TEXT) != 1:
        raise ValueError("문의 안내 필수 문구가 정확히 한 번 필요합니다.")
    # 소제목 앞의 이모지(🏢📊⚠️🏠📞 등)를 제거한다. 커스텀 섹션 아이콘 이미지를
    # 따로 넣으므로 텍스트 이모지는 오히려 AI티가 나서 뺀다. (검증 이후에 적용)
    markdown = _strip_heading_leading_symbols(markdown)
    return markdown


# 소제목(#~######) 바로 뒤에 오는 이모지·픽토그램·기호를 지운다.
_HEADING_LEADING_SYMBOLS_RE = re.compile(
    r"^(#{1,6})[ \t]+"
    r"([\U0001F000-\U0001FAFF☀-➿⬀-⯿←-⇿"
    r"️‍⃣㊗㊙〽©®\s]*)"
    r"(.*)$"
)


def _strip_heading_leading_symbols(markdown: str) -> str:
    lines = []
    for line in markdown.split("\n"):
        match = _HEADING_LEADING_SYMBOLS_RE.match(line)
        if match and match.group(3).strip():
            lines.append(f"{match.group(1)} {match.group(3).strip()}")
        else:
            lines.append(line)
    return "\n".join(lines)


def write_blog_file(
    output_dir: Path,
    article_no: str,
    content: BlogContent,
    *,
    realtor_footer: bool = True,
) -> Path:
    """반드시 output/contents/blog_[매물번호].md 형식으로 저장한다."""
    safe_article_no = re.sub(r"[^0-9A-Za-z_-]+", "", article_no.strip())
    if not safe_article_no:
        raise ValueError("블로그 원고 파일에 사용할 매물번호가 없습니다.")
    contents_dir = output_dir / "contents"
    contents_dir.mkdir(parents=True, exist_ok=True)
    target = contents_dir / f"blog_{safe_article_no}.md"
    target.write_text(
        render_blog_markdown(content, realtor_footer=realtor_footer),
        encoding="utf-8",
    )
    return target
