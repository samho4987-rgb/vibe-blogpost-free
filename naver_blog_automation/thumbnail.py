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


def create_demo_thumbnail(
    path: Path,
    title: str,
    subtitle: str,
    detail: str = "",
    design_prompt: str = "",
    reference_path: Path | None = None,
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
    try:
        return _render_demo_thumbnail(
            path, title, subtitle, detail, design_prompt, reference_path
        )
    except Exception:
        # 폰트(.ttc)·글꼴컬렉션 로딩 등 렌더링 중 오류가 나도 앱 전체가 멈추지 않도록
        # 진단 로그를 남기고, 글자 없는 대체 이미지라도 반드시 생성한다.
        _write_thumbnail_error(path, traceback.format_exc())
        _write_plain_png(path)
        return path


def _render_demo_thumbnail(
    path: Path,
    title: str,
    subtitle: str,
    detail: str = "",
    design_prompt: str = "",
    reference_path: Path | None = None,
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
