from __future__ import annotations

import struct
import re
import traceback
import zlib
from pathlib import Path


def _load_font(size: int):
    """후보 폰트를 순서대로 시도하고, 로딩에 실패하는 폰트(.ttc 등)는 건너뛴다.

    macOS의 AppleSDGothicNeo.ttc처럼 특정 글꼴 컬렉션이 Pillow/FreeType에서
    로딩 예외를 던지는 경우가 있어, 하나가 실패하면 다음 후보로 넘어간다.
    모두 실패하면 기본 폰트(한글은 깨질 수 있음)라도 반환해 렌더링은 계속한다.
    """
    from PIL import ImageFont

    for path in _font_candidates():
        if not Path(path).exists():
            continue
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _write_thumbnail_error(path: Path, message: str) -> None:
    """썸네일 렌더링 실패 원인을 옆에 남겨 진단할 수 있게 한다(조용한 실패 방지)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        (path.parent / "_thumbnail_error.txt").write_text(message, encoding="utf-8")
    except Exception:
        pass


def _font_candidates() -> list[str]:
    return [
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "C:/Windows/Fonts/malgun.ttf",
        "C:/Windows/Fonts/malgunbd.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansKR-Bold.ttf",
    ]


def _write_plain_png(path: Path, width: int = 1080, height: int = 1080) -> None:
    """Pillow가 없을 때도 사용할 수 있는 1:1 네이비 썸네일 PNG."""
    rows: list[bytes] = []
    for y in range(height):
        ratio = y / max(1, height - 1)
        row = bytearray([0])
        for x in range(width):
            r = int(20 + 32 * ratio)
            g = int(48 + 55 * ratio)
            b = int(72 + 54 * ratio)
            if 110 < x < 970 and 500 < y < 506:
                r, g, b = 224, 169, 72
            row.extend((r, g, b))
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    payload = b"\x89PNG\r\n\x1a\n"
    payload += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    payload += chunk(b"IDAT", zlib.compress(raw, 7))
    payload += chunk(b"IEND", b"")
    path.write_bytes(payload)


def _wrap_for_width(
    draw,
    text: str,
    font,
    *,
    max_width: int,
    max_lines: int = 3,
) -> str:
    words = text.replace("|", " | ").split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        width = draw.textbbox((0, 0), candidate, font=font)[2]
        if current and width > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and draw.textbbox((0, 0), last + "…", font=font)[2] > max_width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return "\n".join(lines)


def _prompt_color(prompt: str, label: str, fallback: str) -> str:
    match = re.search(
        rf"(?im)^\s*{re.escape(label)}\s*:\s*(#[0-9a-f]{{6}})\s*$",
        prompt,
    )
    return match.group(1).upper() if match else fallback


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return (
        int(value[0:2], 16),
        int(value[2:4], 16),
        int(value[4:6], 16),
    )


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return (
        int(round(a[0] + (b[0] - a[0]) * t)),
        int(round(a[1] + (b[1] - a[1]) * t)),
        int(round(a[2] + (b[2] - a[2]) * t)),
    )


def _shift(color: tuple[int, int, int], amount: int) -> tuple[int, int, int]:
    return tuple(max(0, min(255, channel + amount)) for channel in color)  # type: ignore[return-value]


def _vertical_gradient(image, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> None:
    from PIL import Image, ImageDraw

    width, height = image.size
    gradient = Image.new("RGB", (1, height))
    grad_draw = ImageDraw.Draw(gradient)
    for y in range(height):
        grad_draw.point((0, y), fill=_mix(top, bottom, y / max(1, height - 1)))
    image.paste(gradient.resize((width, height)))


def _split_badges(detail: str) -> list[str]:
    raw = re.split(r"\s*[·|]\s*", detail.strip())
    badges = [item.strip() for item in raw if item.strip() and item.strip() != "정보 없음"]
    return badges[:3]


# ── 썸네일 템플릿 시스템 ──────────────────────────────────────────
# 이미지 프롬프트의 '템플릿:' 줄로 디자인을 고른다. 색상 줄(배경색: #RRGGBB 등)을
# 추가로 적으면 템플릿 기본 팔레트보다 우선한다.

TEMPLATE_LABELS: dict[str, str] = {
    "classic": "클래식",
    "modern": "모던",
    "bold": "볼드",
    "photo": "포토",
}

_TEMPLATE_ALIASES: dict[str, str] = {
    "클래식": "classic",
    "classic": "classic",
    "기본": "classic",
    "모던": "modern",
    "modern": "modern",
    "미니멀": "modern",
    "볼드": "bold",
    "bold": "bold",
    "임팩트": "bold",
    "포토": "photo",
    "photo": "photo",
    "사진": "photo",
}

# 템플릿별 기본 팔레트(프롬프트 색상 줄이 없을 때 사용).
TEMPLATE_PALETTES: dict[str, dict[str, str]] = {
    "classic": {
        "배경색": "#10283D",
        "테두리색": "#36536A",
        "지역명 색상": "#DCE4EC",
        "구분선 색상": "#D6A546",
        "단지명 색상": "#F2C978",
        "가격·평형 색상": "#FFFFFF",
    },
    "modern": {
        "배경색": "#F5F2EA",
        "테두리색": "#D8D2C4",
        "지역명 색상": "#6B7280",
        "구분선 색상": "#2F6B4F",
        "단지명 색상": "#1B2B3A",
        "가격·평형 색상": "#FFFFFF",
    },
    "bold": {
        "배경색": "#191B2A",
        "테두리색": "#2A2D45",
        "지역명 색상": "#E8EAF6",
        "구분선 색상": "#F2B23E",
        "단지명 색상": "#FFFFFF",
        "가격·평형 색상": "#20222F",
    },
    "photo": {
        "배경색": "#22303C",
        "테두리색": "#3D4F5F",
        "지역명 색상": "#E3E9EF",
        "구분선 색상": "#E7B84F",
        "단지명 색상": "#FFFFFF",
        "가격·평형 색상": "#FFFFFF",
    },
}


# 색상 프리셋: 강조 금색은 유지하고 배경 계열만 바꿔 어떤 조합을 골라도
# 블로그 목록에서 일관된 브랜드 톤이 유지되게 한다(중개사 커스텀 후기에서 검증된 방식).
# 밝은 배경 프리셋은 글자·구분선 색을 어두운 계열로 함께 조정해 가독성을 지킨다.
COLOR_PRESETS: dict[str, dict[str, str]] = {
    "딥네이비": {
        "배경색": "#17324D",
        "테두리색": "#3A5670",
        "지역명 색상": "#DCE4EC",
        "구분선 색상": "#D6A546",
        "단지명 색상": "#F2C978",
        "가격·평형 색상": "#FFFFFF",
    },
    "버건디": {
        "배경색": "#4E2231",
        "테두리색": "#6E3A4B",
        "지역명 색상": "#EDD9DE",
        "구분선 색상": "#D6A546",
        "단지명 색상": "#F2C978",
        "가격·평형 색상": "#FFFFFF",
    },
    "에스프레소": {
        "배경색": "#2B231D",
        "테두리색": "#4A3E33",
        "지역명 색상": "#E5DCD2",
        "구분선 색상": "#D6A546",
        "단지명 색상": "#F2C978",
        "가격·평형 색상": "#FFFFFF",
    },
    "미드나잇그린": {
        "배경색": "#0E2A28",
        "테두리색": "#2E4B48",
        "지역명 색상": "#D8E4E1",
        "구분선 색상": "#D6A546",
        "단지명 색상": "#F2C978",
        "가격·평형 색상": "#FFFFFF",
    },
    "웜샌드": {
        "배경색": "#EBE2D1",
        "테두리색": "#CBBFA6",
        "지역명 색상": "#6E675A",
        "구분선 색상": "#B9862E",
        "단지명 색상": "#2E2A22",
        "가격·평형 색상": "#3A372E",
    },
    "소프트세이지": {
        "배경색": "#DBE2D8",
        "테두리색": "#B7C2B4",
        "지역명 색상": "#5F6B60",
        "구분선 색상": "#B9862E",
        "단지명 색상": "#26312A",
        "가격·평형 색상": "#33403A",
    },
}


def apply_color_preset_to_prompt(prompt: str, preset_name: str) -> str:
    """프롬프트의 색상 줄 6개를 선택한 색상 프리셋 값으로 바꾼다.

    색상 줄이 없으면 '템플릿:' 줄(없으면 첫 줄) 아래에 새로 넣어,
    화면의 프롬프트와 실제 결과가 항상 일치하게 한다.
    """
    palette = COLOR_PRESETS.get(preset_name)
    if palette is None:
        return prompt
    text = (prompt or "").strip()
    missing: list[str] = []
    for color_label, value in palette.items():
        pattern = rf"(?im)^\s*{re.escape(color_label)}\s*:\s*#[0-9a-fA-F]{{6}}\s*$"
        if re.search(pattern, text):
            text = re.sub(pattern, f"{color_label}: {value}", text, count=1)
        else:
            missing.append(f"{color_label}: {value}")
    if missing:
        lines = text.splitlines() or [""]
        anchor = 0
        for index, line in enumerate(lines):
            if re.match(r"^\s*템플릿\s*:", line):
                anchor = index
                break
        lines[anchor + 1 : anchor + 1] = [""] + missing
        text = "\n".join(lines)
    return text.strip()


def parse_template(prompt: str) -> str:
    """프롬프트에서 '템플릿: 모던' 같은 줄을 찾아 템플릿 키를 돌려준다."""
    match = re.search(r"(?im)^\s*템플릿\s*:\s*([A-Za-z가-힣]+)\s*$", prompt or "")
    if not match:
        return "classic"
    return _TEMPLATE_ALIASES.get(match.group(1).strip().lower(), "classic")


def template_colors(template: str, prompt: str) -> dict[str, str]:
    """템플릿 기본 팔레트 위에 프롬프트의 색상 지정을 덮어쓴 최종 색을 계산한다."""
    palette = TEMPLATE_PALETTES.get(template, TEMPLATE_PALETTES["classic"])
    return {
        label: _prompt_color(prompt, label, fallback)
        for label, fallback in palette.items()
    }


def apply_template_to_prompt(prompt: str, template: str) -> str:
    """프롬프트의 '템플릿:' 줄과 색상 줄을 선택한 템플릿 기준으로 바꿔 준다.

    - '템플릿:' 줄이 있으면 값을 바꾸고, 없으면 첫 줄 아래에 넣는다.
    - '배경색: #RRGGBB' 형식의 색상 줄이 있으면 템플릿 기본 팔레트 값으로 갱신해
      화면에서 보는 프롬프트와 실제 결과가 일치하도록 한다(직접 수정은 이후에도 가능).
    """
    template = template if template in TEMPLATE_PALETTES else "classic"
    palette = TEMPLATE_PALETTES[template]
    label = TEMPLATE_LABELS[template]
    text = (prompt or "").strip()
    if re.search(r"(?im)^\s*템플릿\s*:.*$", text):
        text = re.sub(r"(?im)^\s*템플릿\s*:.*$", f"템플릿: {label}", text, count=1)
    else:
        lines = text.splitlines() or [""]
        lines.insert(1, "")
        lines.insert(2, f"템플릿: {label}")
        text = "\n".join(lines)
    for color_label, value in palette.items():
        pattern = rf"(?im)^\s*{re.escape(color_label)}\s*:\s*#[0-9a-f]{{6}}\s*$"
        if re.search(pattern, text):
            text = re.sub(pattern, f"{color_label}: {value}", text, count=1)
    return text.strip()


def create_demo_thumbnail(
    path: Path,
    title: str,
    subtitle: str,
    detail: str = "",
    design_prompt: str = "",
    reference_path: Path | None = None,
    template: str = "",
    brand_name: str = "",
    brand_contact: str = "",
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image  # noqa: F401  (Pillow 로딩 가능 여부 확인)
    except Exception:
        # Pillow가 아예 import되지 않는 경우(설치 안 됨/네이티브 로딩 실패 등).
        # 원인과 실행 Python 경로를 남겨, 왜 텍스트 없는 대체본이 나오는지 진단한다.
        import sys

        _write_thumbnail_error(
            path,
            "Pillow(PIL) import 실패 — 텍스트 있는 대표 이미지를 그릴 수 없습니다.\n"
            f"실행 Python: {sys.executable}\n\n{traceback.format_exc()}",
        )
        _write_plain_png(path)
        return path
    resolved = template.strip() if template.strip() in TEMPLATE_PALETTES else parse_template(design_prompt)
    renderers = {
        "classic": _render_demo_thumbnail,
        "modern": _render_modern_thumbnail,
        "bold": _render_bold_thumbnail,
        "photo": _render_photo_thumbnail,
    }
    try:
        return renderers.get(resolved, _render_demo_thumbnail)(
            path,
            title,
            subtitle,
            detail,
            design_prompt,
            reference_path,
            brand_name=brand_name.strip(),
            brand_contact=brand_contact.strip(),
        )
    except Exception:
        # 폰트(.ttc)·글꼴컬렉션 로딩 등 렌더링 중 오류가 나도 앱 전체가 멈추지 않도록
        # 진단 로그를 남기고, 글자 없는 대체 이미지라도 반드시 생성한다.
        _write_thumbnail_error(path, traceback.format_exc())
        _write_plain_png(path)
        return path


def _draw_brand_center(
    draw,
    width: int,
    text: str,
    y: int,
    font,
    fill: str,
) -> None:
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(((width - (box[2] - box[0])) / 2 - box[0], y), text, font=font, fill=fill)


def _render_demo_thumbnail(
    path: Path,
    title: str,
    subtitle: str,
    detail: str = "",
    design_prompt: str = "",
    reference_path: Path | None = None,
    brand_name: str = "",
    brand_contact: str = "",
) -> Path:
    from PIL import Image, ImageDraw

    width = height = 1080
    background = _prompt_color(design_prompt, "배경색", "#10283D")
    border = _prompt_color(design_prompt, "테두리색", "#36536A")
    region_color = _prompt_color(design_prompt, "지역명 색상", "#DCE4EC")
    divider_color = _prompt_color(design_prompt, "구분선 색상", "#D6A546")
    title_color = _prompt_color(design_prompt, "단지명 색상", "#F2C978")
    detail_color = _prompt_color(design_prompt, "가격·평형 색상", "#FFFFFF")

    bg_rgb = _hex_to_rgb(background)
    accent_rgb = _hex_to_rgb(divider_color)

    # 배경: 위(살짝 밝게) → 아래(살짝 어둡게) 세로 그라디언트로 깊이감을 준다.
    image = Image.new("RGB", (width, height), background)
    _vertical_gradient(image, _shift(bg_rgb, 26), _shift(bg_rgb, -20))

    if reference_path is not None and reference_path.exists():
        try:
            from PIL import ImageOps

            with Image.open(reference_path) as reference:
                texture = ImageOps.fit(reference.convert("RGB"), (width, height))
            # 가이드 이미지의 질감만 은은하게 얹고, 글자는 아래 카드로 덮는다.
            image = Image.blend(image, texture, 0.12)
        except Exception:
            pass

    draw = ImageDraw.Draw(image, "RGBA")

    # 우상단·좌하단 골드 코너 액센트 (은은한 브랜드감)
    draw.line([(width - 300, 74), (width - 74, 74)], fill=divider_color, width=6)
    draw.line([(width - 74, 74), (width - 74, 300)], fill=divider_color, width=6)
    draw.line([(74, height - 300), (74, height - 74)], fill=divider_color, width=6)
    draw.line([(74, height - 74), (300, height - 74)], fill=divider_color, width=6)

    # 안쪽 테두리
    draw.rounded_rectangle(
        (110, 110, width - 110, height - 110),
        radius=40,
        outline=border,
        width=2,
    )

    region_font = _load_font(40)
    title_font = _load_font(88)
    title_font_sm = _load_font(72)
    badge_font = _load_font(46)
    tag_font = _load_font(34)

    def _center_x(text: str, font) -> float:
        box = draw.textbbox((0, 0), text, font=font)
        return (width - (box[2] - box[0])) / 2 - box[0]

    # ── 상단 지역 칩 ─────────────────────────────────────────
    region = " ".join(subtitle.split()[-2:]) if subtitle.strip() else "지역 확인"
    region = region[:18]
    rbox = draw.textbbox((0, 0), region, font=region_font)
    rw, rh = rbox[2] - rbox[0], rbox[3] - rbox[1]
    chip_pad_x, chip_pad_y = 34, 18
    chip_w = rw + chip_pad_x * 2
    chip_h = rh + chip_pad_y * 2
    chip_x0 = (width - chip_w) / 2
    # 하단 라벨을 없앤 대신, 남은 요소(지역칩·매물명·구분선·뱃지)를 세로 중앙 쪽으로
    # 내려 균형을 맞춘다.
    chip_y0 = 315
    draw.rounded_rectangle(
        (chip_x0, chip_y0, chip_x0 + chip_w, chip_y0 + chip_h),
        radius=chip_h / 2,
        fill=accent_rgb + (32,),
        outline=divider_color,
        width=2,
    )
    draw.text(
        (chip_x0 + chip_pad_x - rbox[0], chip_y0 + chip_pad_y - rbox[1]),
        region,
        font=region_font,
        fill=region_color,
    )

    # ── 단지명 (최대 2줄, 길면 폰트 축소) ────────────────────
    active_title_font = title_font
    wrapped_title = _wrap_for_width(draw, title, active_title_font, max_width=840, max_lines=2)
    if wrapped_title.count("\n") >= 1 and len(title) > 16:
        active_title_font = title_font_sm
        wrapped_title = _wrap_for_width(draw, title, active_title_font, max_width=880, max_lines=2)
    tbox = draw.multiline_textbbox((0, 0), wrapped_title, font=active_title_font, spacing=18, align="center")
    title_w = tbox[2] - tbox[0]
    title_y = chip_y0 + chip_h + 78
    draw.multiline_text(
        ((width - title_w) / 2 - tbox[0], title_y),
        wrapped_title,
        font=active_title_font,
        fill=title_color,
        spacing=18,
        align="center",
    )
    title_bottom = title_y + (tbox[3] - tbox[1])

    # 단지명 아래 골드 구분선
    div_y = title_bottom + 52
    draw.rounded_rectangle(
        (width / 2 - 90, div_y, width / 2 + 90, div_y + 6),
        radius=3,
        fill=divider_color,
    )

    # ── 가격·평형·거래유형 뱃지 행 ───────────────────────────
    badges = _split_badges(detail) or ["상세 조건 확인"]
    gap = 22
    pad_x, pad_y = 30, 18
    dims: list[tuple[int, int, int, int, int]] = []
    for text in badges:
        bb = draw.textbbox((0, 0), text, font=badge_font)
        bw, bh = bb[2] - bb[0], bb[3] - bb[1]
        dims.append((bw + pad_x * 2, bh + pad_y * 2, bw, bh, bb[1]))
    total_w = sum(d[0] for d in dims) + gap * (len(dims) - 1)
    badge_h = max(d[1] for d in dims)
    x = (width - total_w) / 2
    badge_y = div_y + 70
    for text, (bw_full, _bh_full, bw, bh, off_top) in zip(badges, dims):
        draw.rounded_rectangle(
            (x, badge_y, x + bw_full, badge_y + badge_h),
            radius=badge_h / 2,
            fill=(255, 255, 255, 16),
            outline=divider_color,
            width=2,
        )
        draw.text(
            (x + (bw_full - bw) / 2, badge_y + (badge_h - bh) / 2 - off_top),
            text,
            font=badge_font,
            fill=detail_color,
        )
        x += bw_full + gap

    # ── 브랜드 요소(선택): 상단 사무소명 · 하단 연락처 ────────
    if brand_name:
        _draw_brand_center(draw, width, brand_name, 168, _load_font(32), region_color)
    if brand_contact:
        _draw_brand_center(draw, width, brand_contact, 912, _load_font(28), region_color)

    image = image.convert("RGB")
    image.save(path, format="PNG", optimize=True)
    return path


def _render_modern_thumbnail(
    path: Path,
    title: str,
    subtitle: str,
    detail: str = "",
    design_prompt: str = "",
    reference_path: Path | None = None,
    brand_name: str = "",
    brand_contact: str = "",
) -> Path:
    """밝은 배경·왼쪽 정렬의 미니멀 에디토리얼 스타일."""
    from PIL import Image, ImageDraw

    width = height = 1080
    colors = template_colors("modern", design_prompt)
    bg_rgb = _hex_to_rgb(colors["배경색"])
    accent = colors["구분선 색상"]
    accent_rgb = _hex_to_rgb(accent)

    image = Image.new("RGB", (width, height), colors["배경색"])
    _vertical_gradient(image, _shift(bg_rgb, 8), _shift(bg_rgb, -10))
    draw = ImageDraw.Draw(image, "RGBA")

    # 얇은 안쪽 테두리
    draw.rectangle((56, 56, width - 56, height - 56), outline=colors["테두리색"], width=2)

    region_font = _load_font(38)
    title_font = _load_font(96)
    title_font_sm = _load_font(78)
    badge_font = _load_font(42)

    margin = 128

    # 상단: 액센트 사각형 + 지역명(왼쪽 정렬)
    region = " ".join(subtitle.split()[-2:]) if subtitle.strip() else "지역 확인"
    region = region[:18]
    draw.rectangle((margin, 168, margin + 26, 194), fill=accent)
    draw.text((margin + 44, 156), region, font=region_font, fill=colors["지역명 색상"])

    # 중앙: 큰 제목(왼쪽 정렬, 최대 3줄)
    active_font = title_font
    wrapped = _wrap_for_width(draw, title, active_font, max_width=820, max_lines=3)
    if wrapped.count("\n") >= 2 or len(title) > 18:
        active_font = title_font_sm
        wrapped = _wrap_for_width(draw, title, active_font, max_width=850, max_lines=3)
    tbox = draw.multiline_textbbox((0, 0), wrapped, font=active_font, spacing=20)
    title_h = tbox[3] - tbox[1]
    title_y = 340
    draw.multiline_text(
        (margin - tbox[0], title_y),
        wrapped,
        font=active_font,
        fill=colors["단지명 색상"],
        spacing=20,
    )

    # 제목 아래 액센트 바
    bar_y = title_y + title_h + 56
    draw.rounded_rectangle((margin, bar_y, margin + 150, bar_y + 10), radius=5, fill=accent)

    # 하단: 채운 알약형 뱃지(왼쪽 정렬)
    badges = _split_badges(detail) or ["상세 조건 확인"]
    gap = 20
    pad_x, pad_y = 32, 20
    x = margin
    badge_y = max(bar_y + 96, 856)
    for text in badges:
        bb = draw.textbbox((0, 0), text, font=badge_font)
        bw, bh = bb[2] - bb[0], bb[3] - bb[1]
        full_w, full_h = bw + pad_x * 2, bh + pad_y * 2
        if x + full_w > width - margin:
            break
        draw.rounded_rectangle(
            (x, badge_y, x + full_w, badge_y + full_h),
            radius=full_h / 2,
            fill=accent_rgb + (235,),
        )
        draw.text(
            (x + pad_x - bb[0], badge_y + pad_y - bb[1]),
            text,
            font=badge_font,
            fill=colors["가격·평형 색상"],
        )
        x += full_w + gap

    # 우하단 점 3개 장식
    for index in range(3):
        cx = width - 128 - index * 34
        draw.ellipse((cx - 7, height - 135, cx + 7, height - 121), fill=accent_rgb + (150,))

    # ── 브랜드 요소(선택): 우상단 사무소명 · 좌하단 연락처 ────
    if brand_name:
        bfont = _load_font(32)
        bbox = draw.textbbox((0, 0), brand_name, font=bfont)
        draw.text(
            (width - margin - (bbox[2] - bbox[0]) - bbox[0], 156),
            brand_name,
            font=bfont,
            fill=colors["지역명 색상"],
        )
    if brand_contact:
        draw.text(
            (margin, height - 102),
            brand_contact,
            font=_load_font(26),
            fill=colors["지역명 색상"],
        )

    image = image.convert("RGB")
    image.save(path, format="PNG", optimize=True)
    return path


def _render_bold_thumbnail(
    path: Path,
    title: str,
    subtitle: str,
    detail: str = "",
    design_prompt: str = "",
    reference_path: Path | None = None,
    brand_name: str = "",
    brand_contact: str = "",
) -> Path:
    """어두운 상단 + 강한 액센트 하단 밴드의 고대비 임팩트 스타일."""
    from PIL import Image, ImageDraw

    width = height = 1080
    colors = template_colors("bold", design_prompt)
    bg_rgb = _hex_to_rgb(colors["배경색"])
    accent = colors["구분선 색상"]

    image = Image.new("RGB", (width, height), colors["배경색"])
    _vertical_gradient(image, _shift(bg_rgb, 22), _shift(bg_rgb, -14))
    draw = ImageDraw.Draw(image, "RGBA")

    band_top = 764
    draw.rectangle((0, band_top, width, height), fill=accent)
    # 밴드 위 얇은 흰 라인으로 경계를 또렷하게
    draw.rectangle((0, band_top - 8, width, band_top - 2), fill=(255, 255, 255, 60))

    region_font = _load_font(40)
    title_font = _load_font(104)
    title_font_sm = _load_font(84)
    badge_font = _load_font(52)

    def _center_x(text: str, font) -> float:
        box = draw.textbbox((0, 0), text, font=font)
        return (width - (box[2] - box[0])) / 2 - box[0]

    # 좌상단 코너 프레임 장식
    draw.line([(72, 72), (250, 72)], fill=accent, width=10)
    draw.line([(72, 72), (72, 250)], fill=accent, width=10)
    draw.line([(width - 250, 72), (width - 72, 72)], fill=accent, width=10)
    draw.line([(width - 72, 72), (width - 72, 250)], fill=accent, width=10)

    # 지역명(상단 중앙)
    region = " ".join(subtitle.split()[-2:]) if subtitle.strip() else "지역 확인"
    region = region[:18]
    draw.text((_center_x(region, region_font), 176), region, font=region_font, fill=colors["지역명 색상"])
    rbox = draw.textbbox((0, 0), region, font=region_font)
    line_w = (rbox[2] - rbox[0]) / 2
    draw.rectangle(
        (width / 2 - line_w, 248, width / 2 + line_w, 252),
        fill=accent,
    )

    # 제목(중앙, 초대형, 최대 2줄)
    active_font = title_font
    wrapped = _wrap_for_width(draw, title, active_font, max_width=880, max_lines=2)
    if wrapped.count("\n") >= 1 and len(title) > 14:
        active_font = title_font_sm
        wrapped = _wrap_for_width(draw, title, active_font, max_width=900, max_lines=2)
    tbox = draw.multiline_textbbox((0, 0), wrapped, font=active_font, spacing=22, align="center")
    title_h = tbox[3] - tbox[1]
    title_y = 300 + (band_top - 320 - title_h) / 2
    draw.multiline_text(
        ((width - (tbox[2] - tbox[0])) / 2 - tbox[0], title_y),
        wrapped,
        font=active_font,
        fill=colors["단지명 색상"],
        spacing=22,
        align="center",
    )

    # 하단 밴드: 가격·평형(어두운 글자, 굵게 중앙 정렬)
    badges = _split_badges(detail) or ["상세 조건 확인"]
    band_text = "  ·  ".join(badges)
    bbox = draw.textbbox((0, 0), band_text, font=badge_font)
    if bbox[2] - bbox[0] > width - 140:
        badge_font = _load_font(42)
        bbox = draw.textbbox((0, 0), band_text, font=badge_font)
    band_center = band_top + (height - band_top) / 2
    if brand_contact:
        band_center -= 26
    draw.text(
        ((width - (bbox[2] - bbox[0])) / 2 - bbox[0], band_center - (bbox[3] - bbox[1]) / 2 - bbox[1]),
        band_text,
        font=badge_font,
        fill=colors["가격·평형 색상"],
    )

    # ── 브랜드 요소(선택): 상단 사무소명 · 밴드 하단 연락처 ────
    if brand_name:
        _draw_brand_center(draw, width, brand_name, 108, _load_font(30), colors["지역명 색상"])
    if brand_contact:
        _draw_brand_center(
            draw, width, brand_contact, height - 84, _load_font(26), colors["가격·평형 색상"]
        )

    image = image.convert("RGB")
    image.save(path, format="PNG", optimize=True)
    return path


def _render_photo_thumbnail(
    path: Path,
    title: str,
    subtitle: str,
    detail: str = "",
    design_prompt: str = "",
    reference_path: Path | None = None,
    brand_name: str = "",
    brand_contact: str = "",
) -> Path:
    """가이드 사진을 전체 배경으로 깔고 하단 그라디언트 위에 글자를 얹는 스타일.

    templates/썸네일가이드.png(reference_path)가 없으면 어두운 그라디언트 배경으로
    대체해 항상 결과물이 나온다."""
    from PIL import Image, ImageDraw

    width = height = 1080
    colors = template_colors("photo", design_prompt)
    bg_rgb = _hex_to_rgb(colors["배경색"])
    accent = colors["구분선 색상"]

    image = Image.new("RGB", (width, height), colors["배경색"])
    _vertical_gradient(image, _shift(bg_rgb, 24), _shift(bg_rgb, -22))
    if reference_path is not None and reference_path.exists():
        try:
            from PIL import ImageOps

            with Image.open(reference_path) as reference:
                image = ImageOps.fit(reference.convert("RGB"), (width, height))
        except Exception:
            pass

    # 하단 가독성 그라디언트(위 투명 → 아래 어둡게) + 상단 살짝 어둡게
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    for y in range(int(height * 0.42), height):
        ratio = (y - height * 0.42) / (height * 0.58)
        overlay_draw.line([(0, y), (width, y)], fill=(8, 12, 18, int(215 * ratio)))
    for y in range(0, 220):
        overlay_draw.line([(0, y), (width, y)], fill=(8, 12, 18, int(110 * (1 - y / 220))))
    image = Image.alpha_composite(image.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(image, "RGBA")

    region_font = _load_font(38)
    title_font = _load_font(88)
    title_font_sm = _load_font(72)
    badge_font = _load_font(42)

    margin = 96

    # 좌상단 지역 칩
    region = " ".join(subtitle.split()[-2:]) if subtitle.strip() else "지역 확인"
    region = region[:18]
    rbox = draw.textbbox((0, 0), region, font=region_font)
    rw, rh = rbox[2] - rbox[0], rbox[3] - rbox[1]
    pad_x, pad_y = 30, 16
    draw.rounded_rectangle(
        (margin, margin, margin + rw + pad_x * 2, margin + rh + pad_y * 2),
        radius=(rh + pad_y * 2) / 2,
        fill=(8, 12, 18, 150),
        outline=accent,
        width=2,
    )
    draw.text(
        (margin + pad_x - rbox[0], margin + pad_y - rbox[1]),
        region,
        font=region_font,
        fill=colors["지역명 색상"],
    )

    # 하단: 뱃지 행 → 제목 → 골드 바(아래에서 위로 배치)
    badges = _split_badges(detail) or ["상세 조건 확인"]
    badge_y = height - 190
    x = margin
    b_pad_x, b_pad_y = 26, 16
    for text in badges:
        bb = draw.textbbox((0, 0), text, font=badge_font)
        bw, bh = bb[2] - bb[0], bb[3] - bb[1]
        full_w, full_h = bw + b_pad_x * 2, bh + b_pad_y * 2
        if x + full_w > width - margin:
            break
        draw.rounded_rectangle(
            (x, badge_y, x + full_w, badge_y + full_h),
            radius=full_h / 2,
            fill=(8, 12, 18, 140),
            outline=accent,
            width=2,
        )
        draw.text(
            (x + b_pad_x - bb[0], badge_y + b_pad_y - bb[1]),
            text,
            font=badge_font,
            fill=colors["가격·평형 색상"],
        )
        x += full_w + 18

    active_font = title_font
    wrapped = _wrap_for_width(draw, title, active_font, max_width=880, max_lines=2)
    if wrapped.count("\n") >= 1 and len(title) > 16:
        active_font = title_font_sm
        wrapped = _wrap_for_width(draw, title, active_font, max_width=900, max_lines=2)
    tbox = draw.multiline_textbbox((0, 0), wrapped, font=active_font, spacing=16)
    title_h = tbox[3] - tbox[1]
    title_y = badge_y - 44 - title_h
    draw.multiline_text(
        (margin - tbox[0], title_y),
        wrapped,
        font=active_font,
        fill=colors["단지명 색상"],
        spacing=16,
    )
    draw.rounded_rectangle(
        (margin, title_y - 40, margin + 120, title_y - 32),
        radius=4,
        fill=accent,
    )

    # ── 브랜드 요소(선택): 우상단 사무소명 · 우하단 연락처 ────
    if brand_name:
        bfont = _load_font(30)
        bbox = draw.textbbox((0, 0), brand_name, font=bfont)
        draw.text(
            (width - margin - (bbox[2] - bbox[0]) - bbox[0], margin + 14),
            brand_name,
            font=bfont,
            fill=colors["지역명 색상"],
        )
    if brand_contact:
        cfont = _load_font(26)
        cbox = draw.textbbox((0, 0), brand_contact, font=cfont)
        draw.text(
            (width - margin - (cbox[2] - cbox[0]) - cbox[0], height - 64),
            brand_contact,
            font=cfont,
            fill=colors["지역명 색상"],
        )

    image = image.convert("RGB")
    image.save(path, format="PNG", optimize=True)
    return path


# 문서 하단에 '항상' 넣을 사용자 고정 안내 이미지(파일명 변형·확장자 허용).
_BOTTOM_NOTICE_STEMS = ("allert_sold_check", "alert_sold_check")
_BOTTOM_NOTICE_EXTS = (".jpeg", ".jpg", ".png", ".webp")


def find_bottom_notice_image(templates_dir: Path) -> Path | None:
    """templates 폴더에 사용자가 넣어둔 하단 고정 안내 이미지를 찾는다."""
    for stem in _BOTTOM_NOTICE_STEMS:
        for ext in _BOTTOM_NOTICE_EXTS:
            candidate = templates_dir / f"{stem}{ext}"
            if candidate.exists():
                return candidate
    return None


def create_support_images(templates_dir: Path) -> Path:
    """비용 없이 문서 하단 거래상태 확인 안내 이미지를 준비한다.

    문서 하단 고정 안내 이미지는 templates 폴더에 사용자가 넣어둔
    allert_sold_check.jpeg(있으면)를 '항상' 사용하고, 없을 때만 자동 생성한다.
    """
    templates_dir.mkdir(parents=True, exist_ok=True)
    custom_bottom = find_bottom_notice_image(templates_dir)
    warning_path = custom_bottom or (templates_dir / "거래완료경고.png")
    # 사용자가 넣어둔 하단 고정 이미지가 있으면 자동 생성본을 만들지 않고 그대로 사용.
    if custom_bottom is not None:
        return custom_bottom
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        _write_plain_png(warning_path, width=1200, height=300)
        return warning_path

    title_font = _load_font(54)
    detail_font = _load_font(34)

    warning = Image.new("RGB", (1200, 300), "#F7F3EC")
    warning_draw = ImageDraw.Draw(warning)
    warning_draw.rounded_rectangle(
        (18, 18, 1182, 282),
        radius=34,
        outline="#9A6A2F",
        width=4,
    )
    warning_draw.text(
        (600, 105),
        "매물 상태는 수시로 변경될 수 있습니다",
        anchor="mm",
        font=title_font,
        fill="#5B3A19",
    )
    warning_draw.text(
        (600, 205),
        "계약 전 거래 가능 여부와 최신 조건을 다시 확인해 주세요",
        anchor="mm",
        font=detail_font,
        fill="#6B5A49",
    )
    warning.save(warning_path, format="PNG", optimize=True)
    return warning_path
