from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml


def _resource_root() -> Path:
    """읽기전용 번들 자원(templates·셀렉터·샘플 등 기본 파일)의 루트.

    - 설치형(exe): PyInstaller가 풀어놓은 위치(sys._MEIPASS) 또는 실행파일 폴더.
    - 소스 실행: 프로젝트 루트.
    """
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", "")
        if base:
            return Path(base)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _data_root() -> Path:
    """사용자 데이터(설정·로그인 세션·생성물)를 저장하는 쓰기 가능 루트.

    설치형(exe)은 프로그램이 읽기전용 폴더(Program Files 등)에 깔릴 수 있으므로,
    사용자별 폴더(%LOCALAPPDATA%\\vibe-blogpost-free)에 저장한다. 이렇게 하면
    재설치·업데이트에도 로그인 세션과 환경설정이 그대로 보존된다.
    소스 실행에서는 기존처럼 프로젝트 루트를 그대로 쓴다.
    """
    if getattr(sys, "frozen", False):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        root = Path(base) / "vibe-blogpost-free"
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError:
            root = Path(sys.executable).resolve().parent
        return root
    return Path(__file__).resolve().parent.parent


# 읽기전용 자원 루트(번들)와 쓰기 가능한 사용자 데이터 루트를 분리한다.
RESOURCE_ROOT = _resource_root()
PROJECT_ROOT = _data_root()


def _non_negative_env_float(name: str, default: float) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return default


def _prompt_from_environment(
    *,
    value_name: str,
    file_name: str,
    default: str,
) -> str:
    """긴 프롬프트는 환경변수 값 또는 환경변수가 가리키는 파일에서 읽는다."""
    prompt_path = os.getenv(file_name, "").strip()
    if prompt_path:
        try:
            value = Path(prompt_path).expanduser().read_text(encoding="utf-8").strip()
            if value:
                return value
        except OSError:
            pass
    direct_value = os.getenv(value_name, "").strip()
    return direct_value or default


def build_blog_write_url(blog_id: str) -> str:
    """실제 블로그 ID와 항상 일치하는 Redirect=Write 주소를 만든다."""
    normalized = blog_id.strip()
    if not normalized:
        return ""
    return f"https://blog.naver.com/{quote(normalized, safe='')}?Redirect=Write"


DEFAULT_WRITING_PROMPT = """
당신은 '네이버 글쓰기 SEO 빌더'로서 사용자가 네이버 블로그에서 검색에 잘 노출될 수
있도록 정보성과 신뢰도를 갖춘 부동산 매물 콘텐츠 작성을 돕는 전문가입니다.

목표:
- 네이버 검색 이용자가 원하는 정보를 충실히 제공하고, C-Rank와 DIA에서 중요하게
  다루는 것으로 알려진 주제 전문성·문서 충실도·출처 신뢰성·사용자 만족도를 고려합니다.
- 수집된 실제 매물정보와 조사 결과를 바탕으로 자연스럽고 현장감 있는 문체를 사용합니다.
- 실제로 경험하지 않은 방문·거주·거래 경험을 지어내지 않습니다.
- 상세하고 풍부한 정보 전달을 위해 공백을 제외한 본문 3,000자 이상을 지향합니다.
- 상위 노출을 보장하거나 검색 알고리즘의 비공개 요소를 안다고 주장하지 않습니다.

작업 규칙 및 행동 지침:

1) 단계별 진행 원칙
- 콘텐츠 자동 생성 한 번 안에서 아래 1~6단계를 내부적으로 순서대로 수행합니다.
- 자동화 도중 사용자에게 단계별 승인을 요구하거나 질문하지 않습니다.
- 각 단계에서 여러 후보가 생기면 매물정보와 조사 근거에 가장 잘 맞는 하나를 선택합니다.
- 사용자는 생성 완료 후 'blog자료' 화면에서 제목·본문·태그를 최종 검토하고,
  명시적으로 확인한 경우에만 네이버 임시저장을 진행합니다.

2) 검색 최적화(SEO) 전략
- 목표 키워드를 제목, 도입부, H2·H3 소제목과 본문에 문맥에 맞게 자연스럽게 배치합니다.
- 같은 키워드를 부자연스럽게 반복하거나 광고성 스팸 문구를 사용하지 않습니다.
- 매물정보, 교통, 학군, 편의시설 등 독자의 검색 의도에 직접 답하는 구체적인 정보를
  우선합니다.
- Kakao 로컬 API와 건축물대장 표제부 자료가 제공되면 입지 분석, 면적 분석,
  건축물대장 확인 섹션에 근거와 기준일을 분명히 밝혀 반영합니다.
- 주변 시설 거리는 직선거리임을 표시하고, 건축물대장 표제부를 개별 호실의 권리관계나
  현재 상태로 확대 해석하지 않습니다.
- 공급면적·전용면적과 전용률은 이해하기 쉽게 비교하되 계약 전 공식 서류와 현장 확인이
  필요하다는 안내를 포함합니다.
- 검색량과 경쟁도를 확인할 공식 데이터가 없으면 실제 수치처럼 단정하지 않고
  정성적인 예상임을 분명히 합니다.

작업 흐름:

단계 1: 키워드 조사
- 매물의 지역, 단지명, 면적, 거래유형과 핵심 특징에서 주 키워드를 도출합니다.
- 연관 키워드 5개의 관련성과 예상 경쟁도를 내부적으로 비교하고 가장 적합한 키워드를
  선택합니다.

단계 2: 검색 의도 분석
- 선택 키워드의 검색 의도를 정보 탐색, 조건 비교, 방문·거래 고려 관점에서 분석합니다.
- 실제 매물을 찾는 지역 수요자를 핵심 독자로 설정하고 글의 방향을 결정합니다.

단계 3: 제목 선정
- 클릭을 유도하되 과장하지 않는 SEO 제목 후보 5개를 내부적으로 검토합니다.
- "[지역] [아파트명] [평수] [거래유형] | [매물 특징 요약]" 구조를 지키는 최종 제목
  하나를 선택합니다.

단계 4: 블로그 글 작성
- 최종 제목, 검색 결과에서 내용을 이해하는 데 도움이 되는 요약형 도입부, 본문과
  해시태그를 작성합니다.
- 글의 흐름을 먼저 설계한 뒤 H2·H3 구조로 본문을 작성합니다.
- 모바일 가독성을 위해 문장을 짧게 쓰고 문단 사이를 충분히 띄웁니다.
- 공백 제외 3,000자 이상을 지향하되, 확인되지 않은 내용을 분량을 위해 추가하지 않습니다.
- 인공지능 특유의 딱딱한 표현을 피하되 개인의 실제 경험처럼 허위 서술하지 않습니다.

단계 5: 블로그 완성
- 독자가 궁금해할 내용을 해결하는 FAQ 섹션을 추가합니다.
- 기존 포스팅 URL이 제공된 경우에만 자연스러운 내부 링크 위치를 제안합니다.
- URL이 없으면 존재하지 않는 링크를 만들지 않습니다.
- 최종 해시태그는 중복 없이 30개 이내로 구성합니다.

출력 스타일:
- 모든 결과는 한국어로 작성합니다.
- 광고성 스팸 문구와 과장된 표현을 피하고 담백하면서도 설득력 있는 존댓말을 사용합니다.
- 가격, 면적, 방향, 층수, 학군, 교통, 개발계획은 제공된 자료에서 확인된 범위만 씁니다.
- 문의 안내와 프로그램이 요구하는 고정 섹션·플레이스홀더 구조를 지킵니다.
""".strip()

DEFAULT_IMAGE_PROMPT = """
로컬 1:1 네이버 블로그 매물 썸네일

템플릿: 클래식

배경색: #10283D
테두리색: #36536A
지역명 색상: #C7CED4
구분선 색상: #D6A546
단지명 색상: #E0AE50
가격·평형 색상: #FFFFFF

표시 순서:
1. 지역명
2. 금색 구분선
3. 아파트·매물명
4. 거래유형·가격·평형

- 템플릿은 클래식 / 모던 / 볼드 / 포토 중에서 고를 수 있습니다.
  (포토 템플릿은 templates/썸네일가이드.png 사진을 배경으로 사용합니다)
- 색상 줄을 지우면 템플릿 기본 색을 사용하고, 남겨 두면 그 색이 우선합니다.
- 수집된 매물정보만 사용하고 확인되지 않은 문구, 로고, 워터마크는 넣지 않습니다.
""".strip()


@dataclass(slots=True)
class AppSettings:
    project_root: Path = PROJECT_ROOT              # 쓰기 가능한 사용자 데이터 루트
    resource_root: Path = RESOURCE_ROOT            # 읽기전용 번들 자원 루트
    output_dir: Path = PROJECT_ROOT / "output"
    browser_profile_dir: Path = PROJECT_ROOT / "data" / "browser-profile"
    selector_path: Path = RESOURCE_ROOT / "config" / "blog_selectors.yaml"
    sample_property_path: Path = RESOURCE_ROOT / "config" / "sample_property.json"
    gemini_api_key: str = ""
    kakao_rest_api_key: str = ""
    kakao_javascript_key: str = ""
    data_go_kr_service_key: str = ""
    text_model: str = "gemini-3.5-flash"
    # AI 자동 글쓰기 엔진: "gemini" 또는 "anthropic"(Claude). Gemini가 막히면 Claude로 전환 가능.
    ai_engine: str = "gemini"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"
    # 무료 등급에서는 이미지 생성 할당량이 0일 수 있으므로 기본값은 로컬 썸네일이다.
    # 유료 프로젝트에서만 GEMINI_IMAGE_MODEL을 명시해 API 이미지 생성을 활성화한다.
    image_model: str = ""
    gemini_min_request_interval_seconds: float = 12.5
    naver_login_id: str = ""
    remember_naver_password: bool = True
    esiljang_login_id: str = ""
    remember_esiljang_password: bool = True
    blog_id: str = ""
    blog_write_url: str = ""
    phone_number: str = ""
    # 중개사무소 정보(표시·광고법 필수 표기). 환경설정 입력값이 크롤링 값보다 우선.
    realtor_office_name: str = ""       # 상호(사무소명)
    realtor_agent_name: str = ""        # 대표 공인중개사 성명
    realtor_registration_no: str = ""   # 등록번호
    realtor_office_phone: str = ""      # 사무실 전화
    realtor_office_mobile: str = ""     # 휴대폰(선택)
    realtor_office_address: str = ""    # 소재지(주소)
    realtor_footer_enabled: bool = True  # 중개사무소 정보를 블로그에 표기할지 (기본 표기)
    icon_package: str = "icon1"  # 본문 섹션 아이콘 묶음(templates/icons 하위 폴더). ""=사용 안 함
    # 자동 생성한 본문 카드 이미지(핵심정보·입지·체크포인트)를 포스팅에 사용할지.
    # 직접 첨부한 본문 이미지가 있으면 언제나 그쪽이 우선한다.
    auto_body_cards: bool = True
    # 썸네일에 사무소명(상단)·연락처(하단)를 표시할지 — 블로그 목록의 브랜드 통일감.
    # 환경설정의 중개사무소 정보(상호·전화)를 그대로 사용한다.
    thumbnail_branding: bool = True
    auto_curl_refresh: bool = True  # 매물 API 차단 시 창 없이 토큰·쿠키를 자동 갱신할지
    my_listings_dir: str = ""  # 내 매물 CSV가 있는 폴더(첫 화면 리스트에 사용)
    publish_mode: str = "draft"          # "draft"=임시저장, "publish"=발행까지
    publish_category: str = ""           # 발행 시 카테고리 이름(블로그별 사용자 지정)
    publish_visibility: str = "public"   # 발행 시 공개범위: "public"=전체공개, "private"=비공개
    tone_guide: str = (
        "제목은 매물의 핵심 장점을 담아 과장 없이 눈길을 끌게 작성합니다. "
        "본문은 친근하지만 전문적인 존댓말을 사용하고, 확인되지 않은 내용은 단정하지 않습니다. "
        "마지막에는 방문·전화 문의를 자연스럽게 안내합니다."
    )
    writing_prompt: str = DEFAULT_WRITING_PROMPT
    image_prompt: str = DEFAULT_IMAGE_PROMPT
    browser_channel: str = "chrome"

    @classmethod
    def load(cls) -> "AppSettings":
        try:
            from dotenv import load_dotenv

            load_dotenv(PROJECT_ROOT / ".env")
        except ImportError:
            pass
        settings = cls(
            # 이전 버전에서 OPENAI_API_KEY 이름으로 넣은 Google 키도 한 번
            # 읽어 검증 후 공식 GEMINI_API_KEY 이름으로 저장할 수 있게 한다.
            gemini_api_key=(
                os.getenv("GEMINI_API_KEY", "")
                or os.getenv("GOOGLE_API_KEY", "")
                or os.getenv("OPENAI_API_KEY", "")
            ),
            kakao_rest_api_key=os.getenv("KAKAO_REST_API_KEY", ""),
            kakao_javascript_key=os.getenv("KAKAO_JAVASCRIPT_KEY", ""),
            data_go_kr_service_key=os.getenv("DATA_GO_KR_SERVICE_KEY", ""),
            text_model=os.getenv("GEMINI_TEXT_MODEL", "gemini-3.5-flash"),
            ai_engine=os.getenv("AI_ENGINE", "gemini").strip().lower() or "gemini",
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            anthropic_model=os.getenv(
                "ANTHROPIC_MODEL", "claude-sonnet-4-20250514"
            ).strip(),
            image_model=os.getenv("GEMINI_IMAGE_MODEL", "").strip(),
            gemini_min_request_interval_seconds=_non_negative_env_float(
                "GEMINI_MIN_REQUEST_INTERVAL_SECONDS",
                12.5,
            ),
            writing_prompt=_prompt_from_environment(
                value_name="BLOG_WRITING_PROMPT",
                file_name="BLOG_WRITING_PROMPT_FILE",
                default=DEFAULT_WRITING_PROMPT,
            ),
            image_prompt=_prompt_from_environment(
                value_name="IMAGE_GENERATION_PROMPT",
                file_name="IMAGE_GENERATION_PROMPT_FILE",
                default=DEFAULT_IMAGE_PROMPT,
            ),
        )
        saved_path = settings.project_root / "config" / "user_settings.json"
        if saved_path.exists():
            try:
                saved = json.loads(saved_path.read_text(encoding="utf-8"))
                for name in (
                    "phone_number",
                    "realtor_office_name",
                    "realtor_agent_name",
                    "realtor_registration_no",
                    "realtor_office_phone",
                    "realtor_office_mobile",
                    "realtor_office_address",
                    "publish_mode",
                    "publish_category",
                    "publish_visibility",
                    "ai_engine",
                    "anthropic_model",
                    "tone_guide",
                    "writing_prompt",
                    "image_prompt",
                    "browser_channel",
                    "icon_package",
                    "my_listings_dir",
                ):
                    if isinstance(saved.get(name), str):
                        setattr(settings, name, saved[name])
                if isinstance(saved.get("realtor_footer_enabled"), bool):
                    settings.realtor_footer_enabled = saved[
                        "realtor_footer_enabled"
                    ]
                if isinstance(saved.get("auto_curl_refresh"), bool):
                    settings.auto_curl_refresh = saved["auto_curl_refresh"]
                if isinstance(saved.get("auto_body_cards"), bool):
                    settings.auto_body_cards = saved["auto_body_cards"]
                if isinstance(saved.get("thumbnail_branding"), bool):
                    settings.thumbnail_branding = saved["thumbnail_branding"]
                if saved.get("account_source") == "user_input":
                    if isinstance(saved.get("naver_login_id"), str):
                        settings.naver_login_id = saved[
                            "naver_login_id"
                        ].strip()
                    if isinstance(saved.get("blog_id"), str):
                        settings.blog_id = saved["blog_id"].strip()
                if isinstance(saved.get("remember_naver_password"), bool):
                    settings.remember_naver_password = saved[
                        "remember_naver_password"
                    ]
                if isinstance(saved.get("esiljang_login_id"), str):
                    settings.esiljang_login_id = saved[
                        "esiljang_login_id"
                    ].strip()
                if isinstance(saved.get("remember_esiljang_password"), bool):
                    settings.remember_esiljang_password = saved[
                        "remember_esiljang_password"
                    ]
            except (OSError, ValueError):
                pass
        posting_settings_path = settings.project_root / "config" / "settings.yaml"
        if posting_settings_path.exists():
            try:
                posting_settings = yaml.safe_load(
                    posting_settings_path.read_text(encoding="utf-8")
                )
                naver = (
                    posting_settings.get("naver", {})
                    if isinstance(posting_settings, dict)
                    else {}
                )
                if isinstance(naver, dict):
                    if naver.get("account_source") == "user_input":
                        if isinstance(naver.get("login_id"), str):
                            settings.naver_login_id = naver[
                                "login_id"
                            ].strip()
                        if isinstance(naver.get("blog_id"), str):
                            settings.blog_id = naver["blog_id"].strip()
                    if isinstance(naver.get("browser_channel"), str):
                        settings.browser_channel = naver["browser_channel"].strip()
            except (OSError, ValueError, yaml.YAMLError):
                pass
        # 배포·고급 사용자가 명시한 환경변수는 로컬 UI 저장값보다 우선한다.
        # 환경변수를 제거하면 다시 UI에서 저장한 값을 사용한다.
        if os.getenv("BLOG_WRITING_PROMPT_FILE") or os.getenv(
            "BLOG_WRITING_PROMPT"
        ):
            settings.writing_prompt = _prompt_from_environment(
                value_name="BLOG_WRITING_PROMPT",
                file_name="BLOG_WRITING_PROMPT_FILE",
                default=DEFAULT_WRITING_PROMPT,
            )
        if os.getenv("IMAGE_GENERATION_PROMPT_FILE") or os.getenv(
            "IMAGE_GENERATION_PROMPT"
        ):
            settings.image_prompt = _prompt_from_environment(
                value_name="IMAGE_GENERATION_PROMPT",
                file_name="IMAGE_GENERATION_PROMPT_FILE",
                default=DEFAULT_IMAGE_PROMPT,
            )
        # 파일에 적힌 URL을 신뢰하지 않고 실제 블로그 ID로 매번 다시 계산한다.
        settings.blog_write_url = build_blog_write_url(settings.blog_id)
        settings.ensure_directories()
        return settings

    def ensure_directories(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.browser_profile_dir.mkdir(parents=True, exist_ok=True)

    def save_user_preferences(self) -> None:
        """비밀번호·API 키·cURL/쿠키를 제외한 값만 저장한다."""
        target = self.project_root / "config" / "user_settings.json"
        payload = {
            "account_source": "user_input",
            "naver_login_id": self.naver_login_id,
            "remember_naver_password": self.remember_naver_password,
            "esiljang_login_id": self.esiljang_login_id,
            "remember_esiljang_password": self.remember_esiljang_password,
            "blog_id": self.blog_id,
            "phone_number": self.phone_number,
            "realtor_office_name": self.realtor_office_name,
            "realtor_agent_name": self.realtor_agent_name,
            "realtor_registration_no": self.realtor_registration_no,
            "realtor_office_phone": self.realtor_office_phone,
            "realtor_office_mobile": self.realtor_office_mobile,
            "realtor_office_address": self.realtor_office_address,
            "realtor_footer_enabled": self.realtor_footer_enabled,
            "icon_package": self.icon_package,
            "auto_curl_refresh": self.auto_curl_refresh,
            "auto_body_cards": self.auto_body_cards,
            "thumbnail_branding": self.thumbnail_branding,
            "my_listings_dir": self.my_listings_dir,
            "publish_mode": self.publish_mode,
            "publish_category": self.publish_category,
            "publish_visibility": self.publish_visibility,
            "ai_engine": self.ai_engine,
            "anthropic_model": self.anthropic_model,
            "tone_guide": self.tone_guide,
            "writing_prompt": self.writing_prompt,
            "image_prompt": self.image_prompt,
            "browser_channel": self.browser_channel,
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.save_posting_config()

    def save_posting_config(self) -> Path:
        """비밀번호 원문 없이 포스팅 설정과 자동 계산 URL을 저장한다."""
        self.blog_id = self.blog_id.strip()
        self.blog_write_url = build_blog_write_url(self.blog_id)
        target = self.project_root / "config" / "settings.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "naver": {
                "account_source": "user_input",
                "login_id": self.naver_login_id.strip(),
                "blog_id": self.blog_id,
                "blog_write_url": self.blog_write_url,
                "login_mode": "credentials_then_browser_profile",
                "browser_channel": self.browser_channel,
                "browser_profile_dir": "data/browser-profile",
            },
            "posting": {
                "save_mode": "draft_only",
                "selector_path": "config/blog_selectors.yaml",
                "content_dir": "output/contents",
                "thumbnail_dir": "output/thumbnails",
            },
            "optional_assets": {
                "transaction_complete_warning": "templates/거래완료경고.png",
            },
            "optional_integrations": {
                "esiljang": {
                    "login_id": self.esiljang_login_id.strip(),
                    "password_storage": (
                        "os_keyring"
                        if self.remember_esiljang_password
                        else "disabled"
                    ),
                    "credential_service": "esiljang-automation",
                    "status": "credentials_only_not_connected",
                },
            },
            "security": {
                "password_storage": (
                    "os_keyring" if self.remember_naver_password else "disabled"
                ),
                "credential_service": "naver-blog-automation",
                "note": (
                    "네이버 비밀번호 원문은 설정 파일에 기록하지 않고 "
                    "운영체제 보안 자격 증명 저장소를 사용합니다."
                ),
            },
        }
        target.write_text(
            yaml.safe_dump(
                payload,
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        try:
            target.chmod(0o600)
        except OSError:
            pass
        return target

    def save_gemini_api_key(self, api_key: str) -> None:
        """검증을 마친 API 키를 Git에서 제외된 로컬 .env에 저장한다."""
        from .gemini_key import normalize_gemini_api_key

        key = normalize_gemini_api_key(api_key)
        if not key:
            raise ValueError("저장할 Google AI Studio API Key가 비어 있습니다.")
        try:
            from dotenv import set_key
        except ImportError as exc:
            raise RuntimeError(
                "API Key 저장에 필요한 python-dotenv 패키지가 없습니다."
            ) from exc

        target = self.project_root / ".env"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.touch(mode=0o600)
        set_key(str(target), "GEMINI_API_KEY", key, quote_mode="always")
        try:
            target.chmod(0o600)
        except OSError:
            # Windows에서는 chmod 의미가 제한적이지만 .env는 계속 Git에서 제외된다.
            pass
        self.gemini_api_key = key

    def save_anthropic_api_key(self, api_key: str) -> None:
        """Claude(Anthropic) API 키를 Git에서 제외된 로컬 .env에 저장한다."""
        key = (api_key or "").strip()
        try:
            from dotenv import set_key, unset_key
        except ImportError as exc:
            raise RuntimeError(
                "API Key 저장에 필요한 python-dotenv 패키지가 없습니다."
            ) from exc
        target = self.project_root / ".env"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.touch(mode=0o600)
        if key:
            set_key(str(target), "ANTHROPIC_API_KEY", key, quote_mode="always")
        else:
            try:
                unset_key(str(target), "ANTHROPIC_API_KEY")
            except KeyError:
                pass
        try:
            target.chmod(0o600)
        except OSError:
            pass
        self.anthropic_api_key = key

    def save_enrichment_api_keys(
        self,
        *,
        kakao_rest_api_key: str,
        kakao_javascript_key: str,
        data_go_kr_service_key: str,
    ) -> None:
        """입지·건축 데이터 API 키를 Git에서 제외된 로컬 .env에 저장한다."""
        kakao_key = kakao_rest_api_key.strip()
        javascript_key = kakao_javascript_key.strip()
        public_data_key = data_go_kr_service_key.strip()
        if not kakao_key and not javascript_key and not public_data_key:
            raise ValueError("저장할 Kakao 또는 공공데이터포털 API 키가 없습니다.")
        try:
            from dotenv import set_key, unset_key
        except ImportError as exc:
            raise RuntimeError(
                "API 키 저장에 필요한 python-dotenv 패키지가 없습니다."
            ) from exc

        target = self.project_root / ".env"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.touch(mode=0o600)
        if kakao_key:
            set_key(
                str(target),
                "KAKAO_REST_API_KEY",
                kakao_key,
                quote_mode="always",
            )
            self.kakao_rest_api_key = kakao_key
        elif target.exists():
            unset_key(str(target), "KAKAO_REST_API_KEY")
            self.kakao_rest_api_key = ""
        if javascript_key:
            set_key(
                str(target),
                "KAKAO_JAVASCRIPT_KEY",
                javascript_key,
                quote_mode="always",
            )
            self.kakao_javascript_key = javascript_key
        elif target.exists():
            unset_key(str(target), "KAKAO_JAVASCRIPT_KEY")
            self.kakao_javascript_key = ""
        if public_data_key:
            set_key(
                str(target),
                "DATA_GO_KR_SERVICE_KEY",
                public_data_key,
                quote_mode="always",
            )
            self.data_go_kr_service_key = public_data_key
        elif target.exists():
            unset_key(str(target), "DATA_GO_KR_SERVICE_KEY")
            self.data_go_kr_service_key = ""
        try:
            target.chmod(0o600)
        except OSError:
            pass

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["project_root"] = str(self.project_root)
        data["resource_root"] = str(self.resource_root)
        data["output_dir"] = str(self.output_dir)
        data["browser_profile_dir"] = str(self.browser_profile_dir)
        data["selector_path"] = str(self.selector_path)
        data["sample_property_path"] = str(self.sample_property_path)
        data["gemini_api_key"] = "***" if self.gemini_api_key else ""
        data["kakao_rest_api_key"] = "***" if self.kakao_rest_api_key else ""
        data["kakao_javascript_key"] = (
            "***" if self.kakao_javascript_key else ""
        )
        data["data_go_kr_service_key"] = (
            "***" if self.data_go_kr_service_key else ""
        )
        return data
