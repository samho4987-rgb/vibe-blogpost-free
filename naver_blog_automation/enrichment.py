from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote, unquote

import httpx

from .models import PropertyInfo


KAKAO_ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"
# 좌표 → 지번/도로명 주소(역지오코딩). 매물 주소에 지번이 없을 때 사용.
KAKAO_COORD2ADDRESS_URL = "https://dapi.kakao.com/v2/local/geo/coord2address.json"
KAKAO_COORD2REGION_URL = "https://dapi.kakao.com/v2/local/geo/coord2regioncode.json"
KAKAO_CATEGORY_URL = "https://dapi.kakao.com/v2/local/search/category.json"
KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
DAUM_WEB_SEARCH_URL = "https://dapi.kakao.com/v2/search/web"
KAKAO_STATIC_MAP_URL = "https://dapi.kakao.com/v2/maps/staticmap"
BUILDING_REGISTER_URL = (
    "https://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo"
)

CATEGORY_GROUPS = {
    "지하철역": "SW8",
    "학교": "SC4",
    "대형마트": "MT1",
    "병원": "HP8",
    "약국": "PM9",
    "편의점": "CS2",
    "학원": "AC5",
    "문화시설": "CT1",
}

KEYWORD_PLACE_GROUPS = {
    "공원": "공원",
    "버스정류장": "버스정류장",
}

WEB_RESEARCH_QUERIES = {
    "개발계획·교통 호재": "교통 연장 개발계획",
    "학군 참고": "초등학교 학군 학원가",
    "단지 기본정보 참고": "세대수 입주년도 주차대수",
    "교통·생활편의 참고": "지하철 버스 상권 마트 공원 병원",
}

BUILDING_FIELD_LABELS = {
    "bldNm": "건물명",
    "dongNm": "동명",
    # "regstrKindCdNm"(대장 종류: 표제부 등)은 독자에게 의미 없는 정보라 표기에서 제외.
    "mainPurpsCdNm": "주용도",
    "strctCdNm": "구조",
    "useAprDay": "사용승인일",
    "grndFlrCnt": "지상층수",
    "ugrndFlrCnt": "지하층수",
    "hhldCnt": "세대수",
    "totPkngCnt": "총 주차대수",
    "rideUseElvtCnt": "승용 엘리베이터",
    "emgenUseElvtCnt": "비상용 엘리베이터",
    "platArea": "대지면적(㎡)",
    "archArea": "건축면적(㎡)",
    "totArea": "연면적(㎡)",
    "bcRat": "건폐율(%)",
    "vlRat": "용적률(%)",
}


class EnrichmentError(RuntimeError):
    pass


def _has_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    number = text.replace(",", "")
    if re.fullmatch(r"[+-]?0+(?:\.0+)?", number):
        return False
    return True


def _place_phrase(place: Mapping[str, Any]) -> str:
    name = str(place.get("name") or "이름 미확인")
    distance = place.get("distance_m")
    distance_text = (
        f"직선거리 {int(distance):,}m"
        if isinstance(distance, (int, float))
        else "거리 미확인"
    )
    return f"**{name}**({distance_text})"


@dataclass(slots=True)
class EnrichmentResult:
    address: dict[str, Any] = field(default_factory=dict)
    nearby: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    building: dict[str, Any] = field(default_factory=dict)
    area: dict[str, Any] = field(default_factory=dict)
    web_sources: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        blocks: list[str] = []

        if self.address or self.nearby:
            lines = ["## 📍 입지 분석"]
            resolved = self.address.get("resolved_address")
            road = self.address.get("road_address")
            if resolved:
                lines.append(f"- 카카오맵 확인 지번 주소: **{resolved}**")
            if road and road != resolved:
                lines.append(f"- 도로명 주소: **{road}**")
            longitude = self.address.get("longitude")
            latitude = self.address.get("latitude")
            if longitude and latitude:
                lines.append(f"- 좌표: 위도 {latitude}, 경도 {longitude}")
            map_url = self.address.get("map_url")
            if map_url:
                lines.append(f"- [카카오맵에서 위치 확인]({map_url})")
            roadview_url = self.address.get("roadview_url")
            if roadview_url:
                lines.append(f"- [카카오맵 로드뷰 확인]({roadview_url})")

            blocks.append("\n".join(lines))

        subway = self.nearby.get("지하철역", [])
        if subway:
            names = ", ".join(_place_phrase(place) for place in subway[:3])
            blocks.append(
                "## 🚇 교통\n\n"
                f"카카오맵 주변 검색 기준으로 {names}이 확인됩니다.\n\n"
                "표시 거리는 직선거리이며 실제 출입구, 도보 동선과 소요시간은 "
                "현장에서 다시 확인해 주세요."
            )

        schools = self.nearby.get("학교", [])
        if schools:
            names = ", ".join(_place_phrase(place) for place in schools[:3])
            blocks.append(
                "## 🎓 학군\n\n"
                f"주변 학교로는 {names} 등이 확인됩니다.\n\n"
                "학교 위치 정보와 실제 배정·통학구역은 다를 수 있으므로 "
                "관할 교육청과 학교에 최종 확인이 필요합니다."
            )

        convenience_parts = []
        for category in ("대형마트", "병원", "약국"):
            places = self.nearby.get(category, [])
            if places:
                convenience_parts.append(
                    f"**{category}**은 "
                    + ", ".join(_place_phrase(place) for place in places[:2])
                    + "이 확인됩니다."
                )
        if convenience_parts:
            blocks.append(
                "## 🛒 생활 편의\n\n"
                + "\n\n".join(convenience_parts)
                + "\n\n카카오맵 주변 검색의 직선거리 기준이며 영업 여부와 실제 "
                "이동 경로는 방문 전에 확인해 주세요."
            )

        if self.area:
            lines = ["## 📐 면적 분석"]
            supply = self.area.get("supply_m2")
            exclusive = self.area.get("exclusive_m2")
            if supply is not None:
                lines.append(
                    f"- 공급면적: **{supply:g}㎡ ({supply / 3.3058:.1f}평)**"
                )
            if exclusive is not None:
                lines.append(
                    f"- 전용면적: **{exclusive:g}㎡ ({exclusive / 3.3058:.1f}평)**"
                )
            ratio = self.area.get("exclusive_ratio")
            if ratio is not None:
                lines.append(
                    f"- 전용률: **약 {ratio:.1f}%** "
                    "(전용면적 ÷ 공급면적 기준)"
                )
            lines.append(
                "- 면적 표기는 매물정보 기준이며 계약 전 등기·건축물대장 및 "
                "중개대상물 확인설명서와 대조가 필요합니다."
            )
            blocks.append("\n".join(lines))

        if self.building:
            lines = ["## 🏗 건축물대장 확인"]
            lines.append(
                "- 국토교통부 건축물대장에서 확인한 이 단지(대표 동)의 표제부 정보입니다. "
                "사용승인일·층수·주용도·구조 등은 확인된 공식 자료이므로 본문에 단지 정보로 "
                "사용해도 됩니다."
            )
            fields = self.building.get("fields", {})
            if isinstance(fields, Mapping):
                for label, value in fields.items():
                    if _has_meaningful_value(value):
                        lines.append(f"- {label}: **{value}**")
            lines.append(
                "- 다만 표제부는 건물(동) 단위 장부이므로, 개별 호수의 면적·권리관계는 "
                "계약 전 등기사항증명서·중개대상물 확인·설명서로 대조해 확인하세요."
            )
            blocks.append("\n".join(lines))

        if self.web_sources:
            lines = [
                "## 🔎 웹검색 참고자료",
                "",
                "아래 항목은 Daum 웹검색 결과의 제목·요약 링크입니다. "
                "자동으로 사실로 확정하지 않으며 원문과 기준일을 확인한 뒤 사용해야 합니다.",
            ]
            for topic, documents in self.web_sources.items():
                if not documents:
                    continue
                lines.append(f"\n### {topic}")
                for document in documents[:3]:
                    title = document.get("title") or "제목 없음"
                    url = document.get("url") or ""
                    summary = document.get("summary") or ""
                    if url:
                        lines.append(f"- [{title}]({url})")
                    else:
                        lines.append(f"- {title}")
                    if summary:
                        lines.append(f"  - {summary}")
            blocks.append("\n".join(lines))

        if self.warnings:
            warning_lines = ["## ⚠️ 데이터 확인 필요"]
            warning_lines.extend(f"- {warning}" for warning in self.warnings)
            blocks.append("\n".join(warning_lines))

        if self.sources:
            source_lines = ["## 공식 API 출처"]
            source_lines.extend(f"- {source}" for source in self.sources)
            blocks.append("\n".join(source_lines))

        return "\n\n".join(blocks).strip()


def _to_float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _area_analysis(area_text: str) -> dict[str, Any]:
    supply_match = re.search(
        r"공급\s*([0-9]+(?:\.[0-9]+)?)\s*㎡?",
        area_text,
    )
    exclusive_match = re.search(
        r"전용\s*([0-9]+(?:\.[0-9]+)?)\s*㎡?",
        area_text,
    )
    supply = float(supply_match.group(1)) if supply_match else None
    exclusive = float(exclusive_match.group(1)) if exclusive_match else None
    result: dict[str, Any] = {}
    if supply is not None:
        result["supply_m2"] = supply
    if exclusive is not None:
        result["exclusive_m2"] = exclusive
    if supply and exclusive:
        result["exclusive_ratio"] = exclusive / supply * 100
    return result


class PropertyDataEnricher:
    def __init__(
        self,
        *,
        kakao_rest_api_key: str = "",
        data_go_kr_service_key: str = "",
        timeout_seconds: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.kakao_rest_api_key = kakao_rest_api_key.strip()
        # 공공데이터포털이 제공하는 인코딩 키도 httpx params에서 안전하게 쓸 수 있게 복원한다.
        self.data_go_kr_service_key = unquote(data_go_kr_service_key.strip())
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def enrich(self, property_info: PropertyInfo) -> EnrichmentResult:
        result = EnrichmentResult(area=_area_analysis(property_info.area))
        if not self.kakao_rest_api_key:
            if self.data_go_kr_service_key:
                result.warnings.append(
                    "건축물대장 조회에 필요한 법정동코드·지번을 확인할 "
                    "Kakao REST API 키가 없어 건축물대장 조회를 건너뛰었습니다."
                )
            return result

        client_options: dict[str, Any] = {
            "timeout": httpx.Timeout(self.timeout_seconds),
            "follow_redirects": True,
        }
        if self.transport is not None:
            client_options["transport"] = self.transport

        with httpx.Client(**client_options) as client:
            try:
                document = self._resolve_address(client, property_info.address)
            except EnrichmentError as exc:
                # 매물 주소에 지번이 없어도(동 단위·좌표만 있는 경우) 좌표로 역지오코딩해
                # 지번을 되찾아 입지 분석·건축물대장 조회를 이어간다.
                document = None
                lng = (property_info.longitude or "").strip()
                lat = (property_info.latitude or "").strip()
                if lng and lat:
                    try:
                        document = self._resolve_by_coordinates(
                            client, lng, lat, property_info.cortar_no
                        )
                        result.warnings.append(
                            "매물 주소에 지번이 없어 좌표로 주소를 역추적했습니다."
                        )
                    except EnrichmentError as coord_exc:
                        result.warnings.append(str(coord_exc))
                if document is None:
                    result.warnings.append(str(exc))
                    return result

            result.address = self._safe_address(document, property_info.name)
            result.sources.append(
                "Kakao Local API 주소 검색 및 카테고리 장소 검색 "
                "(https://developers.kakao.com/docs/latest/ko/local/dev-guide)"
            )

            longitude = result.address.get("longitude")
            latitude = result.address.get("latitude")
            if longitude and latitude:
                for label, category_code in CATEGORY_GROUPS.items():
                    try:
                        result.nearby[label] = self._nearby_places(
                            client,
                            category_code,
                            str(longitude),
                            str(latitude),
                        )
                    except EnrichmentError as exc:
                        result.warnings.append(f"{label} 조회 실패: {exc}")
                for label, keyword in KEYWORD_PLACE_GROUPS.items():
                    try:
                        result.nearby[label] = self._keyword_places(
                            client,
                            keyword,
                            str(longitude),
                            str(latitude),
                        )
                    except EnrichmentError as exc:
                        result.warnings.append(f"{label} 조회 실패: {exc}")

            search_base = " ".join(
                part
                for part in (
                    property_info.complex_name or property_info.name,
                    property_info.address,
                )
                if part and part != "정보 없음"
            ).strip()
            if search_base:
                relevance_terms = self._relevance_terms(property_info)
                for topic, suffix in WEB_RESEARCH_QUERIES.items():
                    try:
                        result.web_sources[topic] = self._web_search(
                            client,
                            f"{search_base} {suffix}",
                            relevance_terms=relevance_terms,
                        )
                    except EnrichmentError as exc:
                        result.warnings.append(f"{topic} 웹검색 실패: {exc}")

            if self.data_go_kr_service_key:
                cadastral = document.get("address")
                if isinstance(cadastral, Mapping):
                    try:
                        result.building = self._building_register(
                            client,
                            cadastral,
                            property_info.name,
                            property_info.property_type,
                        )
                        if result.building:
                            result.sources.append(
                                "국토교통부 건축HUB 건축물대장정보 서비스 "
                                "(https://www.data.go.kr/data/15134735/openapi.do)"
                            )
                    except EnrichmentError as exc:
                        result.warnings.append(str(exc))
                else:
                    result.warnings.append(
                        "카카오 주소 검색 결과에 지번 주소가 없어 건축물대장을 "
                        "조회하지 못했습니다."
                    )

        return result

    def create_static_map(
        self,
        enrichment: EnrichmentResult,
        target: Path,
    ) -> Path | None:
        """REST API 키로 매물과 주변시설 마커가 포함된 정적 지도를 저장한다."""
        longitude = str(enrichment.address.get("longitude") or "").strip()
        latitude = str(enrichment.address.get("latitude") or "").strip()
        if not self.kakao_rest_api_key or not longitude or not latitude:
            return None

        marker_locations = [(longitude, latitude)]
        for places in enrichment.nearby.values():
            for place in places:
                x = str(place.get("longitude") or "").strip()
                y = str(place.get("latitude") or "").strip()
                if x and y and (x, y) not in marker_locations:
                    marker_locations.append((x, y))
                if len(marker_locations) >= 5:
                    break
            if len(marker_locations) >= 5:
                break

        params: list[tuple[str, str]] = [
            ("center", f"{longitude},{latitude}"),
            ("size", "640x480"),
            ("lv", "4"),
            ("format", "png"),
        ]
        for x, y in marker_locations:
            params.append(
                ("markers", f"location:{x},{y}|option:false")
            )

        client_options: dict[str, Any] = {
            "timeout": httpx.Timeout(self.timeout_seconds),
            "follow_redirects": True,
        }
        if self.transport is not None:
            client_options["transport"] = self.transport
        try:
            with httpx.Client(**client_options) as client:
                response = client.get(
                    KAKAO_STATIC_MAP_URL,
                    headers={
                        "Authorization": f"KakaoAK {self.kakao_rest_api_key}"
                    },
                    params=params,
                )
        except httpx.RequestError as exc:
            raise EnrichmentError(
                "카카오 정적 지도 API에 연결하지 못했습니다."
            ) from exc
        if response.status_code in {401, 403}:
            raise EnrichmentError(
                "카카오 정적 지도 인증에 실패했습니다. Kakao Map API 사용 설정과 "
                "REST API 키를 확인해 주세요."
            )
        if response.status_code == 429:
            raise EnrichmentError(
                "카카오 정적 지도 API 사용량 한도에 도달했습니다."
            )
        if response.status_code >= 400:
            raise EnrichmentError(
                f"카카오 정적 지도 요청 실패: HTTP {response.status_code}"
            )
        content_type = response.headers.get("content-type", "").lower()
        if not content_type.startswith("image/"):
            raise EnrichmentError(
                "카카오 정적 지도 응답이 이미지 형식이 아닙니다."
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
        return target

    def _resolve_address(
        self,
        client: httpx.Client,
        address: str,
    ) -> Mapping[str, Any]:
        try:
            response = client.get(
                KAKAO_ADDRESS_URL,
                headers={"Authorization": f"KakaoAK {self.kakao_rest_api_key}"},
                params={
                    "query": address,
                    "analyze_type": "similar",
                    "size": 5,
                },
            )
        except httpx.RequestError as exc:
            raise EnrichmentError(
                "카카오 주소 API에 연결하지 못했습니다."
            ) from exc
        if response.status_code in {401, 403}:
            raise EnrichmentError(
                "Kakao REST API 키 인증에 실패했습니다. JavaScript 키가 아닌 "
                "REST API 키인지 확인해 주세요."
            )
        if response.status_code == 429:
            raise EnrichmentError(
                "카카오 로컬 API 사용량 한도에 도달해 입지 분석을 건너뛰었습니다."
            )
        if response.status_code >= 400:
            raise EnrichmentError(
                f"카카오 주소 API 요청 실패: HTTP {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise EnrichmentError("카카오 주소 API 응답이 JSON이 아닙니다.") from exc
        documents = payload.get("documents", []) if isinstance(payload, dict) else []
        if not isinstance(documents, list) or not documents:
            raise EnrichmentError(
                "매물 주소를 카카오맵 좌표로 변환하지 못했습니다. "
                "도로명 또는 지번이 포함된 정확한 주소가 필요합니다."
            )
        document = documents[0]
        if not isinstance(document, Mapping):
            raise EnrichmentError("카카오 주소 검색 결과 형식이 올바르지 않습니다.")
        cadastral = document.get("address")
        road = document.get("road_address")
        cadastral = cadastral if isinstance(cadastral, Mapping) else {}
        road = road if isinstance(road, Mapping) else {}
        if not (
            str(cadastral.get("main_address_no") or "").strip()
            or str(road.get("main_building_no") or "").strip()
        ):
            raise EnrichmentError(
                "매물 주소에 도로명 건물번호 또는 지번이 없어 정확한 입지 분석을 "
                "진행하지 않았습니다."
            )
        return document

    def _resolve_by_coordinates(
        self,
        client: httpx.Client,
        longitude: str,
        latitude: str,
        cortar_no: str = "",
    ) -> Mapping[str, Any]:
        """좌표(경도·위도)를 Kakao 역지오코딩으로 지번 주소로 바꿔 문서 형태로 돌려준다.

        주소 검색 결과와 같은 구조({"address": {...}, "road_address": {...}})로 맞춰,
        이후 입지 분석·건축물대장 조회가 그대로 이어지게 한다. 법정동코드(b_code)는
        네이버 cortarNo를 우선 쓰고, 없으면 coord2regioncode로 보완한다."""
        try:
            response = client.get(
                KAKAO_COORD2ADDRESS_URL,
                headers={"Authorization": f"KakaoAK {self.kakao_rest_api_key}"},
                params={"x": longitude, "y": latitude},
            )
        except httpx.RequestError as exc:
            raise EnrichmentError(
                "카카오 좌표→주소 변환 API에 연결하지 못했습니다."
            ) from exc
        if response.status_code in {401, 403}:
            raise EnrichmentError(
                "Kakao REST API 키 인증에 실패했습니다(좌표→주소)."
            )
        if response.status_code >= 400:
            raise EnrichmentError(
                f"카카오 좌표→주소 API 요청 실패: HTTP {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise EnrichmentError(
                "카카오 좌표→주소 API 응답이 JSON이 아닙니다."
            ) from exc
        documents = payload.get("documents", []) if isinstance(payload, dict) else []
        if not isinstance(documents, list) or not documents:
            raise EnrichmentError("좌표를 지번 주소로 변환하지 못했습니다.")
        document = documents[0]
        if not isinstance(document, Mapping):
            raise EnrichmentError("좌표→주소 결과 형식이 올바르지 않습니다.")

        cadastral = document.get("address")
        road = document.get("road_address")
        cadastral = dict(cadastral) if isinstance(cadastral, Mapping) else {}
        road = dict(road) if isinstance(road, Mapping) else {}
        if not str(cadastral.get("main_address_no") or "").strip():
            raise EnrichmentError(
                "좌표로 찾은 주소에도 지번이 없어 정확한 입지 분석을 진행하지 못했습니다."
            )
        # 법정동코드: 네이버 cortarNo(10자리) 우선, 없으면 coord2regioncode로 보완.
        legal_code = (cortar_no or "").strip()
        if len(legal_code) != 10 or not legal_code.isdigit():
            legal_code = self._region_code_from_coordinates(client, longitude, latitude)
        if legal_code:
            cadastral["b_code"] = legal_code
        # 좌표 검색 결과에는 x/y가 없으므로 입력 좌표를 채워 넣는다.
        cadastral.setdefault("x", str(longitude))
        cadastral.setdefault("y", str(latitude))
        return {
            "address": cadastral,
            "road_address": road,
            "x": str(longitude),
            "y": str(latitude),
            "address_name": str(cadastral.get("address_name") or ""),
        }

    def _region_code_from_coordinates(
        self, client: httpx.Client, longitude: str, latitude: str
    ) -> str:
        """coord2regioncode로 법정동(B) 코드를 얻는다. 실패하면 빈 문자열."""
        try:
            response = client.get(
                KAKAO_COORD2REGION_URL,
                headers={"Authorization": f"KakaoAK {self.kakao_rest_api_key}"},
                params={"x": longitude, "y": latitude},
            )
            if response.status_code >= 400:
                return ""
            payload = response.json()
        except (httpx.RequestError, ValueError):
            return ""
        documents = payload.get("documents", []) if isinstance(payload, dict) else []
        for region in documents if isinstance(documents, list) else []:
            if isinstance(region, Mapping) and region.get("region_type") == "B":
                code = str(region.get("code") or "").strip()
                if len(code) == 10 and code.isdigit():
                    return code
        return ""

    @staticmethod
    def _safe_address(
        document: Mapping[str, Any],
        property_name: str,
    ) -> dict[str, Any]:
        cadastral = document.get("address")
        road = document.get("road_address")
        cadastral = cadastral if isinstance(cadastral, Mapping) else {}
        road = road if isinstance(road, Mapping) else {}
        longitude = str(document.get("x", "") or cadastral.get("x", "")).strip()
        latitude = str(document.get("y", "") or cadastral.get("y", "")).strip()
        name = quote(property_name or "매물", safe="")
        map_url = (
            f"https://map.kakao.com/link/map/{name},{latitude},{longitude}"
            if longitude and latitude
            else ""
        )
        roadview_url = (
            f"https://map.kakao.com/link/roadview/{latitude},{longitude}"
            if longitude and latitude
            else ""
        )
        return {
            "resolved_address": str(
                cadastral.get("address_name") or document.get("address_name") or ""
            ),
            "road_address": str(road.get("address_name") or ""),
            "longitude": longitude,
            "latitude": latitude,
            "legal_code": str(cadastral.get("b_code") or ""),
            "main_lot_no": str(cadastral.get("main_address_no") or ""),
            "sub_lot_no": str(cadastral.get("sub_address_no") or ""),
            "mountain_yn": str(cadastral.get("mountain_yn") or "N"),
            "map_url": map_url,
            "roadview_url": roadview_url,
        }

    def _nearby_places(
        self,
        client: httpx.Client,
        category_code: str,
        longitude: str,
        latitude: str,
    ) -> list[dict[str, Any]]:
        try:
            response = client.get(
                KAKAO_CATEGORY_URL,
                headers={"Authorization": f"KakaoAK {self.kakao_rest_api_key}"},
                params={
                    "category_group_code": category_code,
                    "x": longitude,
                    "y": latitude,
                    "radius": 2000,
                    "sort": "distance",
                    "size": 3,
                },
            )
        except httpx.RequestError as exc:
            raise EnrichmentError("카카오 장소 API에 연결하지 못했습니다.") from exc
        if response.status_code >= 400:
            raise EnrichmentError(f"카카오 장소 API HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise EnrichmentError("카카오 장소 API 응답이 JSON이 아닙니다.") from exc
        documents = payload.get("documents", []) if isinstance(payload, dict) else []
        if not isinstance(documents, list):
            return []
        places: list[dict[str, Any]] = []
        for item in documents[:3]:
            if not isinstance(item, Mapping):
                continue
            places.append(
                {
                    "name": str(item.get("place_name") or ""),
                    "distance_m": _to_float(item.get("distance")),
                    "category": str(item.get("category_name") or ""),
                    "road_address": str(item.get("road_address_name") or ""),
                    "place_url": str(item.get("place_url") or ""),
                    "longitude": str(item.get("x") or ""),
                    "latitude": str(item.get("y") or ""),
                }
            )
        return places

    def _keyword_places(
        self,
        client: httpx.Client,
        keyword: str,
        longitude: str,
        latitude: str,
    ) -> list[dict[str, Any]]:
        try:
            response = client.get(
                KAKAO_KEYWORD_URL,
                headers={"Authorization": f"KakaoAK {self.kakao_rest_api_key}"},
                params={
                    "query": keyword,
                    "x": longitude,
                    "y": latitude,
                    "radius": 2000,
                    "sort": "distance",
                    "size": 3,
                },
            )
        except httpx.RequestError as exc:
            raise EnrichmentError("카카오 키워드 장소 API에 연결하지 못했습니다.") from exc
        if response.status_code >= 400:
            raise EnrichmentError(
                f"카카오 키워드 장소 API HTTP {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise EnrichmentError(
                "카카오 키워드 장소 API 응답이 JSON이 아닙니다."
            ) from exc
        return self._place_documents(payload)

    @staticmethod
    def _place_documents(payload: Any) -> list[dict[str, Any]]:
        documents = payload.get("documents", []) if isinstance(payload, dict) else []
        if not isinstance(documents, list):
            return []
        places: list[dict[str, Any]] = []
        for item in documents[:3]:
            if not isinstance(item, Mapping):
                continue
            distance = _to_float(item.get("distance"))
            places.append(
                {
                    "name": str(item.get("place_name") or "").strip(),
                    "distance_m": distance,
                    "address": str(item.get("address_name") or "").strip(),
                    "road_address": str(
                        item.get("road_address_name") or ""
                    ).strip(),
                    "longitude": str(item.get("x") or "").strip(),
                    "latitude": str(item.get("y") or "").strip(),
                    "place_url": str(item.get("place_url") or "").strip(),
                }
            )
        return places

    def _web_search(
        self,
        client: httpx.Client,
        query: str,
        *,
        relevance_terms: list[str] | None = None,
    ) -> list[dict[str, str]]:
        try:
            response = client.get(
                DAUM_WEB_SEARCH_URL,
                headers={"Authorization": f"KakaoAK {self.kakao_rest_api_key}"},
                params={"query": query, "size": 15, "sort": "accuracy"},
            )
        except httpx.RequestError as exc:
            raise EnrichmentError("Daum 웹검색 API에 연결하지 못했습니다.") from exc
        if response.status_code >= 400:
            raise EnrichmentError(f"Daum 웹검색 API HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise EnrichmentError("Daum 웹검색 API 응답이 JSON이 아닙니다.") from exc
        documents = payload.get("documents", []) if isinstance(payload, dict) else []
        if not isinstance(documents, list):
            return []

        def clean_html(value: Any) -> str:
            # 태그 제거 후 HTML 엔티티(&#39; &amp; 등)를 실제 문자로 복원해 깨진 텍스트를 막는다.
            text = re.sub(r"<[^>]+>", "", str(value or ""))
            text = html.unescape(text)
            return re.sub(r"\s+", " ", text).strip()

        # 무관한 스팸/타지역 결과를 걸러내기 위한 관련성 키워드(단지명 핵심 등)
        terms = [re.sub(r"\s+", "", term) for term in (relevance_terms or []) if term]
        terms = [term for term in terms if len(term) >= 3]

        results: list[dict[str, str]] = []
        for item in documents:
            if not isinstance(item, Mapping):
                continue
            title = clean_html(item.get("title"))
            summary = clean_html(item.get("contents"))[:240]
            url = str(item.get("url") or "").strip()
            if terms:
                haystack = re.sub(r"\s+", "", f"{title}{summary}")
                if not any(term in haystack for term in terms):
                    continue
            results.append(
                {
                    "title": title,
                    "summary": summary,
                    "url": url,
                    "datetime": str(item.get("datetime") or "").strip(),
                }
            )
            if len(results) >= 3:
                break
        return results

    @staticmethod
    def _relevance_terms(property_info: PropertyInfo) -> list[str]:
        """웹검색 결과의 관련성 판정에 쓸 단지명 핵심 키워드."""
        terms: list[str] = []
        raw = property_info.complex_name or property_info.name or ""
        norm = re.sub(r"\s+", "", raw)
        if norm and norm != "정보없음":
            terms.append(norm)
            # 앞의 지역 접두(예: '광안'삼정그린코아)를 떼어낸 핵심형도 후보로 둔다.
            if len(norm) >= 6:
                terms.append(norm[2:])
                terms.append(norm[3:])
        return terms

    def _building_register(
        self,
        client: httpx.Client,
        cadastral: Mapping[str, Any],
        property_name: str,
        property_type: str = "",
    ) -> dict[str, Any]:
        legal_code = str(cadastral.get("b_code") or "").strip()
        main_lot = str(cadastral.get("main_address_no") or "").strip()
        sub_lot = str(cadastral.get("sub_address_no") or "0").strip() or "0"
        if len(legal_code) < 10 or not main_lot.isdigit() or not sub_lot.isdigit():
            raise EnrichmentError(
                "법정동코드 또는 지번이 불완전해 건축물대장을 조회하지 못했습니다."
            )
        params = {
            "serviceKey": self.data_go_kr_service_key,
            "sigunguCd": legal_code[:5],
            "bjdongCd": legal_code[5:10],
            "platGbCd": "1" if cadastral.get("mountain_yn") == "Y" else "0",
            "bun": main_lot.zfill(4),
            "ji": sub_lot.zfill(4),
            "numOfRows": 100,
            "pageNo": 1,
            "_type": "json",
        }
        try:
            response = client.get(BUILDING_REGISTER_URL, params=params)
        except httpx.RequestError as exc:
            raise EnrichmentError(
                "공공데이터포털 건축물대장 API에 연결하지 못했습니다."
            ) from exc
        if response.status_code in {401, 403}:
            raise EnrichmentError(
                "공공데이터포털 서비스키 인증에 실패했습니다."
            )
        if response.status_code == 429:
            raise EnrichmentError(
                "건축물대장 API 사용량 한도에 도달했습니다."
            )
        if response.status_code >= 400:
            raise EnrichmentError(
                f"건축물대장 API 요청 실패: HTTP {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise EnrichmentError("건축물대장 API 응답이 JSON이 아닙니다.") from exc
        items = self._building_items(payload)
        if not items:
            raise EnrichmentError(
                "해당 법정동코드와 지번에서 건축물대장 표제부를 찾지 못했습니다."
            )
        selected = self._select_building(items, property_name, property_type)
        # 주거용 매물인데 이 지번에 주거용 표제부가 없어 업무시설 등이 선택된 경우,
        # 매물 유형과 맞지 않는 잘못된 정보를 넣지 않도록 건축물대장 정보를 생략한다.
        if self._is_residential_property(property_type) and not self._is_residential_building(
            selected
        ):
            raise EnrichmentError(
                "이 지번의 건축물대장 표제부가 매물 유형(주거용)과 맞지 않아"
                "(업무시설 등만 확인됨) 건축물대장 정보를 넣지 않았습니다."
            )
        fields: dict[str, Any] = {}
        for key, label in BUILDING_FIELD_LABELS.items():
            value = selected.get(key)
            if _has_meaningful_value(value):
                fields[label] = value
        return {
            "record_count": len(items),
            "fields": fields,
            "legal_code": legal_code,
            "lot_no": f"{main_lot}-{sub_lot}" if sub_lot != "0" else main_lot,
        }

    @staticmethod
    def _building_items(payload: Any) -> list[Mapping[str, Any]]:
        if not isinstance(payload, Mapping):
            return []
        response = payload.get("response", {})
        if not isinstance(response, Mapping):
            return []
        header = response.get("header", {})
        if isinstance(header, Mapping):
            result_code = str(header.get("resultCode", "00"))
            if result_code not in {"00", "0"}:
                message = str(header.get("resultMsg") or "알 수 없는 오류")
                raise EnrichmentError(f"건축물대장 API 오류: {message}")
        body = response.get("body", {})
        if not isinstance(body, Mapping):
            return []
        items = body.get("items", {})
        if isinstance(items, Mapping):
            item = items.get("item", [])
        else:
            item = []
        if isinstance(item, Mapping):
            return [item]
        if isinstance(item, list):
            return [entry for entry in item if isinstance(entry, Mapping)]
        return []

    @staticmethod
    def _is_residential_property(property_type: str) -> bool:
        return any(
            keyword in (property_type or "")
            for keyword in ("아파트", "공동주택", "주택", "빌라", "연립", "다세대", "오피스텔")
        )

    @staticmethod
    def _is_residential_building(item: Mapping[str, Any]) -> bool:
        """건축물대장 표제부가 주거용(공동주택 등)인지 판별한다."""
        descriptor = "".join(
            str(item.get(key) or "")
            for key in ("mainPurpsCdNm", "etcPurps", "bldNm")
        )
        residential_markers = (
            "공동주택", "아파트", "주택", "연립", "다세대", "도시형", "오피스텔",
        )
        non_residential_markers = (
            "업무시설", "근린생활", "판매시설", "공장", "창고", "교육연구",
            "숙박", "위락", "종교", "운수",
        )
        if any(marker in descriptor for marker in residential_markers):
            return True
        if any(marker in descriptor for marker in non_residential_markers):
            return False
        # 주용도가 불명확하면 세대수가 있으면 주거로 본다.
        return (_to_float(item.get("hhldCnt")) or 0.0) > 0

    @staticmethod
    def _select_building(
        items: list[Mapping[str, Any]],
        property_name: str,
        property_type: str = "",
    ) -> Mapping[str, Any]:
        normalized_name = re.sub(r"\s+", "", property_name)
        residential_property = PropertyDataEnricher._is_residential_property(
            property_type
        )

        # 주거용 매물이면 주거용 표제부만 후보로 좁힌다(업무시설·부속동을 아예 배제).
        candidates = items
        if residential_property:
            residential_items = [
                item
                for item in items
                if PropertyDataEnricher._is_residential_building(item)
            ]
            if residential_items:
                candidates = residential_items

        def score(item: Mapping[str, Any]) -> tuple[int, int, float, float, int]:
            building_name = re.sub(
                r"\s+",
                "",
                str(item.get("bldNm") or item.get("platPlc") or ""),
            )
            exact = int(
                bool(normalized_name)
                and (
                    normalized_name in building_name
                    or building_name in normalized_name
                )
            )
            residential = int(
                PropertyDataEnricher._is_residential_building(item)
            )
            # 대표 동은 연면적·세대수가 가장 큰 표제부(16㎡ 부속건물 등 배제).
            total_area = _to_float(item.get("totArea")) or 0.0
            households = _to_float(item.get("hhldCnt")) or 0.0
            populated = sum(
                1
                for key in BUILDING_FIELD_LABELS
                if _has_meaningful_value(item.get(key))
            )
            return residential, exact, total_area, households, populated

        return max(candidates, key=score)
