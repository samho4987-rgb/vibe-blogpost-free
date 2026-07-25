from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any, Mapping

from .models import PropertyInfo, floor_band, strip_dong


@dataclass(frozen=True, slots=True)
class TableBlock:
    html: str
    plain: str


@dataclass(frozen=True, slots=True)
class _RawCell:
    """이미 안전한 HTML을 그대로 넣어야 하는 셀(예: 하이퍼링크). plain은 표시용 텍스트."""

    html: str
    plain: str


def _meaningful(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, _RawCell):
        return bool(value.plain.strip())
    text = str(value).strip()
    return text not in {"", "-", "0", "0.0", "0.00", "정보 없음", "None"}


def _rows(values: list[tuple[str, Any]]) -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = []
    for label, value in values:
        if not _meaningful(value):
            continue
        rows.append((label, value if isinstance(value, _RawCell) else str(value).strip()))
    return rows


def _table(values: list[tuple[str, Any]]) -> TableBlock:
    rows = _rows(values) or [("안내", "확인 가능한 정보가 없습니다")]
    html_parts: list[str] = []
    plain_lines: list[str] = []
    for label, value in rows:
        if isinstance(value, _RawCell):
            cell_html = value.html
            cell_plain = value.plain
        else:
            cell_html = escape(value)
            cell_plain = value
        html_parts.append(
            "<tr>"
            f"<th style=\"padding:10px;border:1px solid #d8e0e5;"
            f"background:#eef3f6;text-align:left;\">{escape(label)}</th>"
            f"<td style=\"padding:10px;border:1px solid #d8e0e5;\">"
            f"{cell_html}</td></tr>"
        )
        plain_lines.append(f"{label}\t{cell_plain}")
    html = (
        '<table style="border-collapse:collapse;width:100%;font-size:15px;">'
        f"<tbody>{''.join(html_parts)}</tbody></table>"
    )
    plain = "\n".join(plain_lines)
    return TableBlock(html=html, plain=plain)


def _article_no_cell(article_no: Any) -> Any:
    """매물번호에 네이버 부동산 링크를 건다(HTML 표에서만 링크로 보이고, plain은 번호만)."""
    if not _meaningful(article_no):
        return article_no
    number = str(article_no).strip()
    # 네이버가 매물 상세 페이지를 new.land → fin.land로 이전했다. new.land/articles는
    # 죽은 링크라 프로그램이 실제로 페이지를 읽을 때 쓰는 fin.land 주소를 사용한다.
    url = f"https://fin.land.naver.com/articles/{escape(number)}"
    return _RawCell(
        html=(
            f'<a href="{url}" target="_blank" rel="noopener noreferrer">'
            f"{escape(number)}</a>"
        ),
        plain=number,
    )


def build_property_tables(
    property_info: PropertyInfo,
    enrichment_data: Mapping[str, Any] | None = None,
    *,
    phone_number: str = "",
) -> dict[str, TableBlock]:
    enrichment_data = enrichment_data or {}
    building = enrichment_data.get("building", {})
    building_fields = (
        building.get("fields", {})
        if isinstance(building, Mapping)
        else {}
    )
    complex_rows: list[tuple[str, Any]] = [
        # 빌라처럼 단지 정보가 없으면 '진주빌라 1동'이 아니라 건물명('진주빌라')만,
        # 건물명도 없으면 생략(strip_dong이 빈 값을 돌려주고 _meaningful이 거른다).
        ("단지·건물명", strip_dong(property_info.complex_name or property_info.name)),
        ("주소", property_info.address),
        ("건물 용도", property_info.building_use),
        ("총 세대수", property_info.total_units),
        ("사용승인일", property_info.approval_date),
        ("시공사", property_info.builder),
        ("난방", property_info.heating),
        ("주차", property_info.parking),
    ]
    if isinstance(building_fields, Mapping):
        complex_rows.extend(
            (str(label), value)
            for label, value in building_fields.items()
            if _meaningful(value)
        )

    tables = {
        "[TABLE_COMPLEX]": _table(complex_rows),
        "[TABLE_SUMMARY]": _table(
            [
                ("매물번호", _article_no_cell(property_info.article_no)),
                ("매물명", property_info.name),
                ("거래유형", property_info.trade_type),
                ("가격", property_info.price),
                ("면적", property_info.area),
                ("층", floor_band(property_info.floor)),
                ("방·욕실", " / ".join(
                    value
                    for value in (
                        property_info.rooms,
                        property_info.bathrooms,
                    )
                    if _meaningful(value)
                )),
            ]
        ),
        "[TABLE_DETAIL]": _table(
            [
                # '광고 문구'는 건물명+동만 담겨 매물명과 중복돼 제거(사용자 요청).
                ("매물 유형", property_info.property_type),
                ("방향", property_info.direction),
                ("입주 가능일", property_info.available_date),
                ("현관 구조", property_info.entrance_type),
                ("관리비", property_info.maintenance_fee),
                ("설명", property_info.description),
            ]
        ),
        "[TABLE_REALTOR]": _table(
            [
                ("중개사무소", property_info.realtor_name),
                ("대표자", property_info.realtor_ceo),
                ("등록번호", property_info.realtor_registration_no),
                ("전화", property_info.realtor_phone or phone_number),
                ("휴대전화", property_info.realtor_mobile),
                ("주소", property_info.realtor_address),
            ]
        ),
    }
    # 글 맨 아래 표기용(선택). 같은 내용의 별도 표 — 원고에 해당 자리표시가
    # 있을 때만 삽입되므로 항상 제공해도 무방하다.
    tables["[TABLE_REALTOR_FOOTER]"] = tables["[TABLE_REALTOR]"]
    return tables
