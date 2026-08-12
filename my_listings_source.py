# -*- coding: utf-8 -*-
"""내 매물 CSV — 파일 선택·행 필터 도우미 (2026-08-10 신설).

왜 이 모듈이 생겼나 (배포 전 리뷰에서 확정된 세 가지 원인):
 1) 바이브맵의 [내 매물]은 이제 ``~/.greencore/vibemap_ui/.내매물.csv``
    (숨김·고정 파일명)에 저장하는데, 이 앱은 환경설정의 폴더(보통
    ``vibemap/data``)만 봐서 **서로 다른 곳을 보고 있었다** → 목록이 비거나
    갱신이 안 되는 것처럼 보였다.
 2) 예전 코드는 이름에 '내매물'이 든 CSV를 **전부 병합**해서, 옛 내보내기의
    내려간 매물이 계속 목록에 남았다 → **최신 파일 1개만 쓴다.**
 3) 행 단위 중개사 필터가 없어, 시장 수집 CSV가 '내매물' 이름으로 저장되면
    타인 매물 수만 건이 섞였다(08-06 실제 사고) → **중개사ID 대조 필터.**

전부 표준 라이브러리만 쓴다(단독 테스트 가능). app.py 가 임포트해 위임한다.
"""

from __future__ import annotations

import csv
import datetime as _dt
import json
import os
from pathlib import Path

# 크롤 CSV / 바이브맵 내매물 CSV 공통의 중개사 식별 컬럼 후보.
REALTOR_ID_COLS = ("중개사ID", "realtorId", "realtor_id")
ARTICLE_COLS = ("매물번호", "매물 번호", "articleNo", "article_no", "articleNumber")

# 시장 CSV 폴백에서 제외할 파일(수집 부산물 — 매물 행이 아니다).
_EXCLUDE_HINTS = ("노출순위리포트",)


def vibemap_ui_dir() -> Path:
    """바이브맵 UI 데이터 루트 — 바이브맵과 같은 규칙(환경변수 우선)."""
    env = os.environ.get("VIBEMAP_UI_DATA_ROOT", "").strip()
    if env:
        return Path(env).expanduser()
    return Path.home() / ".greencore" / "vibemap_ui"


def resolve_realtor_id(settings_value: str = "") -> tuple[str, str]:
    """내 중개사 ID를 찾는다. 반환: (값, 출처 설명 — 로그·화면용).

    우선순위: 환경변수 → 이 앱의 환경설정 → 바이브맵 설정(ui_proto_settings.json).
    바이브맵 쪽을 읽는 이유: 이미 거기에 넣어 두었으면 두 번 입력하지 않게.
    """
    env = os.environ.get("VIBE_MY_REALTOR_ID", "").strip()
    if env:
        return env, "환경변수"
    val = (settings_value or "").strip()
    if val:
        return val, "환경설정"
    try:
        cfg = vibemap_ui_dir() / "ui_proto_settings.json"
        if cfg.is_file():
            data = json.loads(cfg.read_text(encoding="utf-8")) or {}
            val = str(data.get("my_realtor_id", "") or "").strip()
            if val:
                return val, "바이브맵 설정"
    except Exception:
        pass
    return "", ""


def _mtime_text(path: Path) -> str:
    try:
        ts = _dt.datetime.fromtimestamp(path.stat().st_mtime)
        return ts.strftime("%m-%d %H:%M")
    except OSError:
        return ""


def _csv_files(folder: Path) -> list[Path]:
    try:
        return [
            p for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() == ".csv"
        ]
    except OSError:
        return []


def find_source_file(
    folder: str, has_realtor_id: bool = False
) -> tuple[Path | None, str]:
    """읽을 CSV 하나를 고른다. 반환: (경로, 종류) — 종류는 "mine"/"market"/"".

    - "mine": 이름에 '내매물'이 든 파일(숨김 ``.내매물.csv`` 포함).
      환경설정 폴더와 바이브맵 데이터 루트 양쪽을 본다.
    - "market": 시장 수집 CSV. ⚠️ 반드시 중개사ID 필터와 함께(무필터 금지).

    선택 규칙(2026-08-12 정정 — "새 크롤을 인식 못 한다" 실사용 보고):
    - **내 중개사 ID 가 있으면 두 갈래를 합쳐 가장 최신 파일이 이긴다.**
      예전엔 내매물 파일이 있으면 무조건 우선이라, 새로 받은 크롤 CSV 가
      더 최신이어도 옛 내매물 스냅샷을 계속 보여줬다.
    - ID 가 없으면 시장 CSV 는 못 쓰므로(타인 매물 방지) 내매물 파일만 본다.
    """
    base = Path(folder).expanduser() if folder else None

    mine: list[Path] = []
    if base and base.is_dir():
        mine.extend(p for p in _csv_files(base) if "내매물" in p.name)
    hidden = vibemap_ui_dir() / ".내매물.csv"
    if hidden.is_file():
        mine.append(hidden)

    market: list[Path] = []
    if base and base.is_dir():
        market = [
            p for p in _csv_files(base)
            if "내매물" not in p.name
            and not any(h in p.name for h in _EXCLUDE_HINTS)
        ]

    if has_realtor_id:
        pool = mine + market
        if pool:
            newest = max(pool, key=lambda p: p.stat().st_mtime)
            return newest, ("mine" if newest in mine else "market")
        return None, ""

    if mine:
        return max(mine, key=lambda p: p.stat().st_mtime), "mine"
    if market:
        # ID 없이는 못 읽지만, 호출 쪽이 "ID 를 넣으면 된다" 안내를 띄우도록
        # 시장 CSV 존재 사실은 알려준다(행은 require_realtor 가드가 막는다).
        return max(market, key=lambda p: p.stat().st_mtime), "market"
    return None, ""


def format_deal_price(record: dict) -> str:
    """거래방식 + 대표 가격 한 줄 (기존 app.py 로직 그대로 이관)."""

    def field(key: str) -> str:
        return str(record.get(key, "") or "").strip()

    deal = field("거래방식")
    if field("매매대금"):
        price = field("매매대금")
    elif field("전세금"):
        price = field("전세금")
    elif field("월세") or field("기보증금"):
        price = "/".join(x for x in (field("기보증금"), field("월세")) if x)
    else:
        price = ""
    return " ".join(part for part in (deal, price) if part)


def read_listings_csv(
    path, realtor_id: str = "", require_realtor: bool = False
) -> tuple[list[dict[str, str]], int, bool]:
    """CSV를 읽어 (목록, 걸러낸 타 중개사 행 수, 중개사ID 컬럼 존재 여부)를 돌려준다.

    - realtor_id 가 있고 중개사ID 컬럼이 있으면: 내 ID 행만 통과시키고 나머지를 센다.
    - require_realtor=True(시장 CSV 폴백)인데 중개사ID 컬럼이 없으면:
      **아무 행도 돌려주지 않는다** — 필터 없이 시장 CSV를 여는 사고 방지.
    - 중복 매물번호는 첫 행만 남긴다.
    """
    rid = (realtor_id or "").strip()
    for encoding in ("utf-8-sig", "cp949", "utf-8", "euc-kr"):
        out: list[dict[str, str]] = []
        dropped = 0
        try:
            with open(path, encoding=encoding, newline="") as handle:
                reader = csv.DictReader(handle)
                fields = reader.fieldnames or []
                article_col = None
                for name in fields:
                    if name and name.strip() in ARTICLE_COLS:
                        article_col = name
                        break
                if article_col is None:
                    article_col = fields[0] if fields else None
                if article_col is None:
                    return [], 0, False
                realtor_col = None
                for name in fields:
                    if name and name.strip() in REALTOR_ID_COLS:
                        realtor_col = name
                        break
                if require_realtor and (realtor_col is None or not rid):
                    # 시장 CSV인데 대조할 컬럼/ID가 없다 — 통째로 거른다.
                    return [], 0, realtor_col is not None
                seen: set[str] = set()
                for record in reader:
                    article_no = str(record.get(article_col, "") or "").strip()
                    if not article_no.isdigit():
                        continue
                    if rid and realtor_col is not None:
                        row_rid = str(record.get(realtor_col, "") or "").strip()
                        if row_rid != rid:
                            dropped += 1
                            continue
                    if article_no in seen:
                        continue
                    seen.add(article_no)
                    out.append(
                        {
                            "article_no": article_no,
                            "name": str(
                                record.get("매물명")
                                or record.get("매물 명")
                                or ""
                            ).strip(),
                            "deal_price": format_deal_price(record),
                            "desc": str(
                                record.get("간략설명")
                                or record.get("설명")
                                or ""
                            ).strip(),
                        }
                    )
            return out, dropped, realtor_col is not None
        except UnicodeDecodeError:
            continue
        except (OSError, csv.Error):
            return out, dropped, False
    return [], 0, False


def source_note(path: Path, kind: str, dropped: int, rid: str, rid_src: str) -> str:
    """화면 하단에 보여줄 '어느 파일을 읽었나' 한 줄."""
    parts = [f"출처 {path.name} ({_mtime_text(path)})"]
    if kind == "market":
        parts.append("최신 수집 CSV에서 내 중개사 ID로 추림")
    if dropped:
        parts.append(f"타 중개사 행 {dropped:,}건 제외")
    if rid and rid_src and rid_src != "환경설정":
        parts.append(f"ID는 {rid_src}에서 가져옴")
    return " · ".join(parts)
