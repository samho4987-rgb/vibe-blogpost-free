from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping


def _deep_find(data: Any, keys: Iterable[str]) -> Any:
    """중첩된 API 응답에서 처음 발견되는 유효 값을 찾는다."""
    wanted = set(keys)
    queue: list[Any] = [data]
    while queue:
        current = queue.pop(0)
        if isinstance(current, Mapping):
            for key, value in current.items():
                if key in wanted and value not in (None, "", [], {}):
                    return value
            queue.extend(current.values())
        elif isinstance(current, list):
            queue.extend(current[:50])
    return None


def _text(value: Any, default: str = "정보 없음") -> str:
    if value in (None, "", [], {}):
        return default
    if isinstance(value, bool):
        return "예" if value else "아니오"
    return str(value).strip()


def _deep_find_all(data: Any, keys: Iterable[str]) -> list[Any]:
    """중첩 구조에서 해당 키들의 '모든' 스칼라 값을 순서대로 모은다."""
    keyset = set(keys)
    found: list[Any] = []

    def walk(node: Any) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                if key in keyset and not isinstance(value, (Mapping, list)):
                    found.append(value)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return found


def _clean_null(text: Any) -> str:
    """네이버가 값 자리에 넣는 'null' 토큰을 제거한다('null 1동' -> '1동')."""
    cleaned = re.sub(r"(?i)(?<![\w가-힣])null(?![\w가-힣])", "", str(text))
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def _title(payload: Mapping[str, Any]) -> str:
    """광고 제목. articleName에 'null'이 섞이는 경우가 있어 정리하고,
    건물명(예: 진주빌라)과 동 표기(예: 1동)를 합쳐 깔끔한 제목을 만든다."""
    candidates = [
        _clean_null(value)
        for value in _deep_find_all(payload, ("articleName", "articleTitle", "title"))
    ]
    candidates = [c for c in candidates if c]
    if not candidates:
        return ""
    named = ""
    dong = ""
    for text in candidates:
        if re.fullmatch(r"\d+동", text):
            dong = dong or text
        elif not named:
            named = text
    if named and dong and dong not in named:
        return f"{named} {dong}"
    return named or candidates[0]


def strip_dong(name: Any) -> str:
    """건물명에서 '동' 표기(예: '1동', '101동')를 떼어 건물명만 남긴다.

    빌라처럼 단지 정보가 없을 때 '진주빌라 1동' 대신 '진주빌라'만 쓰기 위함이다.
    이름 전체가 'N동'뿐이면(건물명이 없으면) 빈 문자열을 돌려준다(→ 표에서 생략)."""
    text = _clean_null(name)
    if not text:
        return ""
    # 끝에 붙은 'N동'을 제거
    text = re.sub(r"\s*\d+\s*동\s*$", "", text).strip()
    # 남은 것이 없거나 여전히 순수 'N동'이면 건물명 없음으로 처리
    if not text or re.fullmatch(r"\d+동", text):
        return ""
    return text


def floor_band(floor: Any) -> str:
    """층 정보를 '저층/중층/고층'으로 표기한다.

    - 네이버가 이미 '저/중/고'로 주면 그대로 사용('고/24층' -> '고층').
    - 'N/M'(현재층/총층) 숫자면 총층 대비 위치로 저/중/고를 계산한다.
    - 판단할 수 없으면 원문을 그대로 둔다(정보 손실 방지)."""
    text = str(floor or "").strip()
    if not text:
        return ""
    first = text.split("/")[0].strip()
    if first[:1] in ("저", "중", "고"):
        return f"{first[:1]}층"
    if "지하" in text or re.search(r"(?i)\bB\d", text):
        return "저층"
    nums = [int(n) for n in re.findall(r"-?\d+", text)]
    if len(nums) >= 2 and nums[1] > 0:
        current, total = nums[0], nums[1]
        if current <= total / 3:
            return "저층"
        if current > total * 2 / 3:
            return "고층"
        return "중층"
    return text


def _price(payload: Mapping[str, Any]) -> str:
    """가격. 월세면 '보증금/월세'로 표기(네이버는 보증금만 dealOrWarrantPrc에 담음)."""
    trade = _text(_deep_find(payload, ("tradeTypeName", "tradeType", "dealType")), "")
    warrant = _clean_null(
        _text(
            _deep_find(
                payload, ("dealOrWarrantPrc", "warrantPrice", "dealPrice", "price")
            ),
            "",
        )
    )
    rent = _clean_null(
        _text(_deep_find(payload, ("rentPrc", "rentPrice")), "")
    )
    if rent in ("0", "0원"):
        rent = ""
    if "월세" in trade and warrant and rent:
        return f"{warrant}/{rent}"
    if warrant:
        return warrant
    return rent or "정보 없음"


def _maintenance(payload: Mapping[str, Any]) -> str:
    """관리비. 네이버는 maintenanceCost가 월별 내역 딕셔너리(costsByDate 등)로
    오므로 원본을 그대로 str()하면 통째로 노출된다. 평균 총액만 깔끔히 뽑는다."""
    cost = _deep_find(payload, ("maintenanceCost", "monthlyManagementCost"))
    if isinstance(cost, Mapping):
        for key in ("averageTotalPrice", "totalPrice"):
            value = cost.get(key)
            if value not in (None, "", "0", 0):
                try:
                    won = int(str(value).replace(",", "").strip())
                except (ValueError, TypeError):
                    continue
                return f"평균 약 {won:,}원/월"
        return ""
    scalar = _text(_deep_find(payload, ("maintenanceFee", "maintenanceCost")), "")
    if not scalar or scalar.lstrip().startswith("{") or "costsByDate" in scalar:
        return ""
    return scalar


def _area(payload: Mapping[str, Any]) -> str:
    supply = _deep_find(payload, ("area1", "supplyArea", "spc1"))
    exclusive = _deep_find(payload, ("area2", "exclusiveArea", "spc2"))
    parts: list[str] = []
    if supply not in (None, ""):
        parts.append(f"공급 {supply}㎡")
    if exclusive not in (None, ""):
        parts.append(f"전용 {exclusive}㎡")
    return " / ".join(parts) or "정보 없음"


@dataclass(slots=True)
class PropertyInfo:
    article_no: str
    name: str
    property_type: str
    trade_type: str
    price: str
    address: str
    area: str
    floor: str
    rooms: str
    direction: str
    description: str
    features: list[str] = field(default_factory=list)
    listing_title: str = ""
    complex_name: str = ""
    bathrooms: str = ""
    available_date: str = ""
    entrance_type: str = ""
    maintenance_fee: str = ""
    heating: str = ""
    parking: str = ""
    builder: str = ""
    total_units: str = ""
    approval_date: str = ""
    building_use: str = ""
    realtor_name: str = ""
    realtor_ceo: str = ""
    realtor_registration_no: str = ""
    realtor_phone: str = ""
    realtor_mobile: str = ""
    realtor_address: str = ""
    latitude: str = ""       # 매물 좌표(위도) — 주소에 지번이 없을 때 역지오코딩용
    longitude: str = ""      # 매물 좌표(경도)
    cortar_no: str = ""      # 네이버 법정동코드(cortarNo) — 건축물대장 b_code로 사용
    source: str = "네이버부동산 API"
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(
        cls,
        article_no: str,
        payload: Mapping[str, Any],
        *,
        source: str = "네이버부동산 API",
    ) -> "PropertyInfo":
        features = _deep_find(
            payload,
            ("articleFeatureDesc", "articleFeatureDescriptions", "tagList", "tags"),
        )
        if isinstance(features, str):
            feature_list = [item.strip() for item in features.replace("/", ",").split(",") if item.strip()]
        elif isinstance(features, list):
            feature_list = [_text(item) for item in features if item not in (None, "")]
        else:
            feature_list = []

        city = _deep_find(payload, ("cityName", "cortarName", "regionName"))
        detail = _deep_find(
            payload,
            ("roadAddress", "detailAddress", "exposureAddress", "address"),
        )
        address_parts = [part for part in (_text(city, ""), _text(detail, "")) if part]

        listing_title = _title(payload)
        # 단지·건물명은 aptName(네이버 단지명, 예: 'e편한세상오션테라스4단지')을 최우선으로.
        # complexName/buildingName은 종종 동 번호('401동')만 들어와 매물명을 동으로 만든다.
        complex_name = _clean_null(
            _text(_deep_find(payload, ("aptName",)), "")
        ) or _clean_null(
            _text(_deep_find(payload, ("complexName", "buildingName", "name")), "")
        )
        # 건물명이 비거나 단순 'N동'뿐이면 정리된 광고 제목을 매물명으로 쓴다.
        if not complex_name or re.fullmatch(r"\d+동", complex_name):
            resolved_name = listing_title or complex_name or "정보 없음"
        else:
            resolved_name = complex_name

        return cls(
            article_no=str(article_no),
            name=resolved_name,
            property_type=_text(
                _deep_find(
                    payload,
                    ("realEstateTypeName", "realEstateType", "propertyType"),
                )
            ),
            trade_type=_text(
                _deep_find(payload, ("tradeTypeName", "tradeType", "dealType"))
            ),
            price=_price(payload),
            address=" ".join(address_parts) or "정보 없음",
            area=_area(payload),
            floor=_text(_deep_find(payload, ("floorInfo", "floor", "targetFloor"))),
            rooms=_text(_deep_find(payload, ("roomCount", "rooms", "roomCnt"))),
            direction=_text(
                _deep_find(payload, ("direction", "directionName", "directionBaseType"))
            ),
            description=_text(
                _deep_find(
                    payload,
                    (
                        "articleDescription",
                        "description",
                        "detailDescription",
                        "articleDesc",
                    ),
                )
            ),
            features=feature_list,
            listing_title=listing_title,
            complex_name=complex_name,
            bathrooms=_text(
                _deep_find(payload, ("bathroomCount", "bathrooms", "bathroomCnt")),
                "",
            ),
            available_date=_text(
                _deep_find(payload, ("moveInPossibleYmd", "availableDate")),
                "",
            ),
            entrance_type=_text(
                _deep_find(payload, ("entranceTypeName", "entranceType")),
                "",
            ),
            maintenance_fee=_maintenance(payload),
            heating=_text(
                _deep_find(payload, ("heatMethodTypeName", "heatingType", "heating")),
                "",
            ),
            parking=_text(
                _deep_find(payload, ("totalParkingCount", "parkingCount", "parking")),
                "",
            ),
            builder=_text(
                _deep_find(payload, ("constructionCompanyName", "builder")),
                "",
            ),
            total_units=_text(
                _deep_find(payload, ("totalHouseholdCount", "householdCount", "totalUnits")),
                "",
            ),
            approval_date=_text(
                _deep_find(payload, ("useApproveYmd", "approvalDate")),
                "",
            ),
            building_use=_text(
                _deep_find(payload, ("buildingUseName", "buildingUse")),
                "",
            ),
            realtor_name=_text(
                _deep_find(payload, ("realtorName", "brokerageName")),
                "",
            ),
            realtor_ceo=_text(
                _deep_find(payload, ("representativeName", "realtorRepresentative")),
                "",
            ),
            realtor_registration_no=_text(
                _deep_find(payload, ("establishmentRegistrationNo", "registrationNo")),
                "",
            ),
            realtor_phone=_text(
                _deep_find(payload, ("realtorPhone", "brokeragePhone")),
                "",
            ),
            realtor_mobile=_text(
                _deep_find(payload, ("realtorMobile", "mobilePhone")),
                "",
            ),
            realtor_address=_text(
                _deep_find(payload, ("realtorAddress", "brokerageAddress")),
                "",
            ),
            latitude=_text(_deep_find(payload, ("latitude", "lat")), ""),
            longitude=_text(_deep_find(payload, ("longitude", "lng", "lon")), ""),
            cortar_no=_text(
                _deep_find(payload, ("cortarNo", "cortarNumber", "cortarCode")),
                "",
            ),
            source=source,
            raw=dict(payload),
        )

    def to_dict(self, *, include_raw: bool = False) -> dict[str, Any]:
        result = asdict(self)
        if not include_raw:
            result.pop("raw", None)
        return result

    def summary(self) -> str:
        feature_text = ", ".join(self.features) if self.features else "정보 없음"
        rows = [
            ("광고 제목", self.listing_title),
            ("매물번호", self.article_no),
            ("매물명", self.complex_name or self.name),
            ("유형", f"{self.property_type} / {self.trade_type}"),
            ("가격", self.price),
            ("주소", self.address),
            ("면적", self.area),
            ("층/방향/방", f"{self.floor} / {self.direction} / {self.rooms}"),
            ("욕실", self.bathrooms),
            ("입주 가능일", self.available_date),
            ("특징", feature_text),
            ("설명", self.description),
        ]
        return "\n".join(
            f"{label}: {value}"
            for label, value in rows
            if value and value not in {"정보 없음", "-"}
        )


@dataclass(slots=True)
class BlogContent:
    title: str
    body: str
    hashtags: list[str]
    image_prompt: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def markdown(self) -> str:
        hashtags = " ".join(
            f"#{tag.lstrip('#').replace(' ', '')}" for tag in self.hashtags if tag.strip()
        )
        return f"# {self.title}\n\n{self.body.strip()}\n\n{hashtags}".strip() + "\n"


@dataclass(slots=True)
class WorkflowResult:
    run_id: str
    output_dir: str
    property_info: PropertyInfo
    research: str
    content: BlogContent
    thumbnail_path: str | None
    map_image_path: str | None = None
    map_url: str = ""
    roadview_url: str = ""
    latitude: str = ""
    longitude: str = ""
    nearby_places: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    enrichment_data: dict[str, Any] = field(default_factory=dict)
    blog_markdown_path: str | None = None
    draft_saved: bool = False
    generation_warning: str | None = None
    preview_only: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "output_dir": self.output_dir,
            "property_info": self.property_info.to_dict(),
            "research": self.research,
            "content": self.content.to_dict(),
            "thumbnail_path": self.thumbnail_path,
            "map_image_path": self.map_image_path,
            "map_url": self.map_url,
            "roadview_url": self.roadview_url,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "nearby_places": self.nearby_places,
            "enrichment_data": self.enrichment_data,
            "blog_markdown_path": self.blog_markdown_path,
            "draft_saved": self.draft_saved,
            "generation_warning": self.generation_warning,
            "preview_only": self.preview_only,
        }
