"""본문용 섹션 카드 이미지 자동 생성(외부 API 비용 없음, Pillow 로컬 렌더링).

대표 썸네일 1장 외에, 블로그 본문 중간에 넣을 정보 카드 이미지를 만든다.
- 핵심 정보 카드: 가격·면적·층·방향 등 확인된 값만 표로 정리
- 입지 카드: Kakao 기초자료의 주변 시설(지하철·학교 등)과 직선거리
- 체크포인트 카드: 매물 특징 또는 계약 전 공통 확인 사항

썸네일과 같은 템플릿 팔레트를 사용해 게시물 전체의 디자인 톤을 맞춘다.
실패해도 예외를 밖으로 던지지 않고 만들어진 카드 목록만 돌려준다(포스팅 흐름 보호).
"""

from __future__ import annotations

import re
import traceback
from pathlib import Path
from typing import Any, Mapping, Sequence

from .thumbnail import (
    _hex_to_rgb,
    _load_font,
    _shift,
    _vertical_gradient,
    _write_thumbnail_error,
    parse_template,
    template_colors,
)

CARD_WIDTH = 1200
CARD_HEIGHT = 900

# 특징이 하나도 수집되지 않았을 때 쓰는 공통 확인 안내(사실 단정 없는 일반 절차).
_GENERIC_CHECKPOINTS = [
    "등기부등본·건축물대장으로 권리관계 확인",
    "관리비 포함 항목과 별도 부과 항목 확인",
    "입주 가능일과 계약 조건 협의 여부 확인",
    "현장 방문으로 채광·소음·주차 확인",
]

# 입지 카드에 표시할 주변 시설 분류 우선순위.
_NEARBY_PRIORITY = ["지하철역", "학교", "마트", "편의점", "병원", "약국", "공원", "은행"]


def _is_light(rgb: tuple[int, int, int]) -> bool:
    return (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) > 150


def _card_canvas(colors: Mapping[str, str]):
    """카드 공통 배경(그라디언트 + 테두리)을 만든다."""
    from PIL import Image, ImageDraw

    bg_rgb = _hex_to_rgb(colors["배경색"])
    image = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), colors["배경색"])
    _vertical_gradient(image, _shift(bg_rgb, 14), _shift(bg_rgb, -12))
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle(
        (36, 36, CARD_WIDTH - 36, CARD_HEIGHT - 36),
        radius=28,
        outline=colors["테두리색"],
        width=2,
    )
    return image, draw


def _card_header(draw, colors: Mapping[str, str], title: str, subtitle: str = "") -> int:
    """카드 상단 제목 영역을 그리고 본문 시작 y 좌표를 돌려준다."""
    accent = colors["구분선 색상"]
    title_font = _load_font(56)
    sub_font = _load_font(30)
    draw.rounded_rectangle((84, 92, 116, 148), radius=8, fill=accent)
    draw.text((140, 88), title, font=title_font, fill=colors["단지명 색상"])
    y = 176
    if subtitle:
        draw.text((140, y), subtitle, font=sub_font, fill=colors["지역명 색상"])
        y += 48
    draw.line([(84, y + 14), (CARD_WIDTH - 84, y + 14)], fill=colors["테두리색"], width=2)
    return y + 52


def _ellipsize(draw, text: str, font, max_width: int) -> str:
    if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
        return text
    while text and draw.textbbox((0, 0), text + "…", font=font)[2] > max_width:
        text = text[:-1]
    return text.rstrip() + "…"


def _info_rows(info: Any) -> list[tuple[str, str]]:
    """PropertyInfo에서 카드에 실을 (라벨, 값) 목록을 만든다. 빈 값·'정보 없음' 제외."""

    def value(attr: str) -> str:
        raw = str(getattr(info, attr, "") or "").strip()
        return "" if raw in {"정보 없음", "-"} else raw

    area = value("area")
    pyeong = ""
    exclusive = re.search(r"전용\s*([0-9]+(?:\.[0-9]+)?)", area)
    if exclusive:
        pyeong = f" (약 {round(float(exclusive.group(1)) / 3.3058)}평)"
    rooms = value("rooms")
    bathrooms = value("bathrooms")
    room_text = ""
    if rooms:
        room_text = f"방 {rooms}" if rooms.isdigit() else rooms
        if bathrooms:
            room_text += f" / 욕실 {bathrooms}" if bathrooms.isdigit() else f" / {bathrooms}"
    candidates = [
        ("거래", " ".join(part for part in (value("trade_type"), value("price")) if part)),
        ("면적", f"{area}{pyeong}" if area else ""),
        ("층·방향", " / ".join(part for part in (value("floor"), value("direction")) if part)),
        ("방·욕실", room_text),
        ("관리비", value("maintenance_fee")),
        ("입주", value("available_date")),
        ("주차", value("parking")),
        ("난방", value("heating")),
    ]
    return [(label, text) for label, text in candidates if text][:8]


def _draw_label_value_rows(
    draw,
    colors: Mapping[str, str],
    rows: Sequence[tuple[str, str]],
    start_y: int,
) -> None:
    label_font = _load_font(36)
    value_font = _load_font(40)
    accent_rgb = _hex_to_rgb(colors["구분선 색상"])
    row_h = min(84, (CARD_HEIGHT - 96 - start_y) // max(1, len(rows)))
    y = start_y + max(0, (CARD_HEIGHT - 96 - start_y - row_h * len(rows)) // 2)
    for label, text in rows:
        draw.rounded_rectangle(
            (84, y + 8, 96, y + row_h - 20),
            radius=4,
            fill=accent_rgb + (200,),
        )
        draw.text((124, y), label, font=label_font, fill=colors["지역명 색상"])
        shown = _ellipsize(draw, text, value_font, CARD_WIDTH - 340 - 84)
        draw.text((340, y - 4), shown, font=value_font, fill=colors["단지명 색상"])
        y += row_h


def _nearby_rows(
    nearby: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[tuple[str, str, str]]:
    """(분류, 이름, 거리표시) 목록. 분류 우선순위대로 최대 6곳."""
    rows: list[tuple[str, str, str]] = []
    categories = [c for c in _NEARBY_PRIORITY if c in nearby]
    categories += [c for c in nearby if c not in categories]
    for category in categories:
        for place in list(nearby.get(category, []))[:2]:
            name = str(place.get("name") or "").strip()
            if not name:
                continue
            distance = place.get("distance_m")
            distance_text = (
                f"직선 {int(distance):,}m"
                if isinstance(distance, (int, float))
                else ""
            )
            rows.append((category, name, distance_text))
            if len(rows) >= 6:
                return rows
    return rows


def create_body_cards(
    target_dir: Path,
    property_info: Any,
    *,
    nearby: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    design_prompt: str = "",
    template: str = "",
) -> list[Path]:
    """본문 카드 이미지들을 만들고 성공한 파일 경로 목록을 돌려준다.

    Pillow가 없거나 개별 카드 렌더링이 실패해도 예외를 밖으로 던지지 않는다.
    """
    try:
        from PIL import Image  # noqa: F401
    except Exception:
        _write_thumbnail_error(
            target_dir / "body_card.png",
            "Pillow(PIL) import 실패 — 본문 카드 이미지를 생략합니다.\n"
            + traceback.format_exc(),
        )
        return []

    resolved = template.strip() if template.strip() else parse_template(design_prompt)
    colors = template_colors(resolved, design_prompt)
    # 밝은 배경 템플릿(모던)은 카드도 밝게, 어두운 템플릿은 어둡게 유지된다.
    target_dir.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []

    # 썸네일과 같은 제목 규칙을 써서 '1동'·'정보 없음' 같은 값이 카드에 찍히지 않게 한다.
    try:
        from .models import thumbnail_title

        name = thumbnail_title(property_info)
    except Exception:
        name = str(
            getattr(property_info, "complex_name", "")
            or getattr(property_info, "name", "")
        ).strip()

    # 1) 핵심 정보 카드
    try:
        rows = _info_rows(property_info)
        if rows:
            image, draw = _card_canvas(colors)
            body_y = _card_header(draw, colors, "핵심 정보 한눈에", name)
            _draw_label_value_rows(draw, colors, rows, body_y)
            card_path = target_dir / "body_card_1_핵심정보.png"
            image.convert("RGB").save(card_path, format="PNG", optimize=True)
            made.append(card_path)
    except Exception:
        _write_thumbnail_error(target_dir / "body_card_1_핵심정보.png", traceback.format_exc())

    # 2) 입지·주변 카드 (수집된 주변 시설이 있을 때만)
    try:
        nearby_rows = _nearby_rows(nearby or {})
        if nearby_rows:
            image, draw = _card_canvas(colors)
            body_y = _card_header(
                draw, colors, "주변 생활 인프라", "Kakao 지도 기준 직선거리"
            )
            cat_font = _load_font(32)
            name_font = _load_font(40)
            dist_font = _load_font(34)
            accent_rgb = _hex_to_rgb(colors["구분선 색상"])
            row_h = min(96, (CARD_HEIGHT - 96 - body_y) // max(1, len(nearby_rows)))
            y = body_y + max(0, (CARD_HEIGHT - 96 - body_y - row_h * len(nearby_rows)) // 2)
            for category, place_name, distance_text in nearby_rows:
                chip_box = draw.textbbox((0, 0), category, font=cat_font)
                chip_w = chip_box[2] - chip_box[0] + 36
                chip_h = chip_box[3] - chip_box[1] + 20
                draw.rounded_rectangle(
                    (84, y, 84 + chip_w, y + chip_h),
                    radius=chip_h / 2,
                    fill=accent_rgb + (46,),
                    outline=colors["구분선 색상"],
                    width=2,
                )
                draw.text(
                    (84 + 18 - chip_box[0], y + 10 - chip_box[1]),
                    category,
                    font=cat_font,
                    fill=colors["단지명 색상"],
                )
                shown = _ellipsize(draw, place_name, name_font, 560)
                draw.text((84 + chip_w + 28, y - 2), shown, font=name_font, fill=colors["단지명 색상"])
                if distance_text:
                    dbox = draw.textbbox((0, 0), distance_text, font=dist_font)
                    draw.text(
                        (CARD_WIDTH - 84 - (dbox[2] - dbox[0]), y + 4),
                        distance_text,
                        font=dist_font,
                        fill=colors["지역명 색상"],
                    )
                y += row_h
            card_path = target_dir / "body_card_2_입지.png"
            image.convert("RGB").save(card_path, format="PNG", optimize=True)
            made.append(card_path)
    except Exception:
        _write_thumbnail_error(target_dir / "body_card_2_입지.png", traceback.format_exc())

    # 3) 체크포인트 카드 (특징이 있으면 특징, 없으면 공통 확인 안내)
    try:
        features = [
            str(item).strip()
            for item in (getattr(property_info, "features", None) or [])
            if str(item).strip() and str(item).strip() != "정보 없음"
        ][:5]
        if features:
            heading, subtitle, items = "이 매물 체크포인트", "수집된 매물 특징 기준", features
        else:
            heading, subtitle, items = (
                "계약 전 확인 체크리스트",
                "안전한 거래를 위한 공통 안내",
                _GENERIC_CHECKPOINTS,
            )
        image, draw = _card_canvas(colors)
        body_y = _card_header(draw, colors, heading, subtitle)
        item_font = _load_font(40)
        accent_rgb = _hex_to_rgb(colors["구분선 색상"])
        check_color = colors["구분선 색상"]
        row_h = min(110, (CARD_HEIGHT - 96 - body_y) // max(1, len(items)))
        y = body_y + max(0, (CARD_HEIGHT - 96 - body_y - row_h * len(items)) // 2)
        for text in items:
            cx, cy = 108, y + 24
            draw.ellipse((cx - 22, cy - 22, cx + 22, cy + 22), fill=accent_rgb + (46,), outline=check_color, width=2)
            draw.line([(cx - 9, cy), (cx - 2, cy + 8), (cx + 10, cy - 8)], fill=check_color, width=4, joint="curve")
            shown = _ellipsize(draw, text, item_font, CARD_WIDTH - 170 - 84)
            draw.text((170, y), shown, font=item_font, fill=colors["단지명 색상"])
            y += row_h
        card_path = target_dir / "body_card_3_체크포인트.png"
        image.convert("RGB").save(card_path, format="PNG", optimize=True)
        made.append(card_path)
    except Exception:
        _write_thumbnail_error(target_dir / "body_card_3_체크포인트.png", traceback.format_exc())

    return made
