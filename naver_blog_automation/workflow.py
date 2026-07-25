from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence
from zoneinfo import ZoneInfo

from .ai_agent import (
    AIQuotaExceededError,
    AIServiceUnavailableError,
    ContentAgent,
)
from .content_writer import write_blog_file
from .credentials import save_property_curl
from .enrichment import PropertyDataEnricher
from .models import BlogContent, WorkflowResult
from .naver_blog import NaverBlogPoster
from .property_fetcher import PropertyFetcher
from .settings import AppSettings
from .thumbnail import create_demo_thumbnail, create_support_images


ProgressCallback = Callable[[int, str], None]


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z가-힣_-]+", "-", value).strip("-")
    return cleaned[:48] or "property"


def _thumbnail_detail(price: str, area: str, trade_type: str) -> str:
    exclusive = re.search(r"전용\s*([0-9]+(?:\.[0-9]+)?)", area)
    pyeong = ""
    if exclusive:
        pyeong = f"{round(float(exclusive.group(1)) / 3.3058)}평"
    return " · ".join(
        item for item in (trade_type, price, pyeong) if item and item != "정보 없음"
    )


class BlogAutomationWorkflow:
    def __init__(
        self,
        settings: AppSettings,
        *,
        progress: ProgressCallback | None = None,
    ) -> None:
        self.settings = settings
        self.progress = progress or (lambda _step, _message: None)
        self.fetcher = PropertyFetcher(
            browser_channel=settings.browser_channel,
            auto_refresh=settings.auto_curl_refresh,
            credential_saver=save_property_curl,
            log=lambda message: self._notify(1, message),
        )
        self.enricher = PropertyDataEnricher(
            kakao_rest_api_key=settings.kakao_rest_api_key,
            data_go_kr_service_key=settings.data_go_kr_service_key,
        )

    def _notify(self, step: int, message: str) -> None:
        self.progress(step, message)

    def _run_dir(self, article_no: str) -> tuple[str, Path]:
        now = datetime.now(ZoneInfo("Asia/Seoul"))
        run_id = f"{now:%Y%m%d-%H%M%S}-{_safe_name(article_no or 'sample')}"
        run_dir = self.settings.output_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_id, run_dir

    @staticmethod
    def _save_json(path: Path, value: object) -> None:
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _save_result(self, result: WorkflowResult) -> None:
        self._save_json(Path(result.output_dir) / "run.json", result.to_dict())

    def _agent(self, *, offline: bool = False) -> ContentAgent:
        return ContentAgent(
            api_key="" if offline else self.settings.gemini_api_key,
            text_model=self.settings.text_model,
            image_model="",
            tone_guide=self.settings.tone_guide,
            writing_prompt=self.settings.writing_prompt,
            phone_number=self.settings.phone_number,
            office_name=self.settings.realtor_office_name,
            min_request_interval_seconds=(
                self.settings.gemini_min_request_interval_seconds
            ),
            ai_engine=self.settings.ai_engine,
            anthropic_api_key=(
                "" if offline else self.settings.anthropic_api_key
            ),
            anthropic_model=self.settings.anthropic_model,
        )

    def _quota_fallback(
        self,
        agent: ContentAgent,
        step: int,
        stage: str,
    ) -> tuple[ContentAgent, str]:
        warning = (
            f"Google Gemini API 무료 사용량 한도로 {stage} 단계의 온라인 AI 호출을 "
            "완료하지 못했습니다. 수집된 매물정보로 오프라인 초안으로 전환했습니다. "
            "환경설정에서 엔진을 Claude로 바꾸거나, '프롬프트(복사)' 방식을 쓰실 수 "
            "있습니다. 내용을 반드시 검토해 주세요."
        )
        self._notify(step, warning)
        return agent.offline_copy(), warning

    def _service_fallback(
        self,
        agent: ContentAgent,
        step: int,
        stage: str,
    ) -> tuple[ContentAgent, str]:
        warning = (
            f"Google Gemini 서버가 일시적으로 혼잡해(503) {stage} 단계의 온라인 AI "
            "호출을 완료하지 못했습니다. 우선 수집된 매물정보로 오프라인 초안을 "
            "만들었으니, 잠시 후 '(선택) AI로 자동 글쓰기'를 다시 누르거나, 환경설정에서 "
            "엔진을 Claude로 바꿔 다시 시도할 수 있습니다. 내용을 반드시 검토해 주세요."
        )
        self._notify(step, warning)
        return agent.offline_copy(), warning

    def preview(
        self,
        *,
        article_no: str,
        curl_command: str = "",
        sample: bool = False,
    ) -> WorkflowResult:
        """Gemini를 호출하지 않고 매물·공부상·Kakao 기초자료만 수집한다."""
        run_id, run_dir = self._run_dir(article_no)
        self._notify(1, "매물 기본정보를 수집합니다. (Google AI 미사용)")
        if sample:
            property_info = self.fetcher.load_sample(self.settings.sample_property_path)
        else:
            property_info = self.fetcher.fetch(article_no, curl_command)
        self._save_json(
            run_dir / "property.json",
            property_info.to_dict(include_raw=True),
        )

        self._notify(1, "공부상·Kakao·무료 웹검색 기초자료를 확인합니다.")
        enrichment = (
            PropertyDataEnricher().enrich(property_info)
            if sample
            else self.enricher.enrich(property_info)
        )
        for warning in enrichment.warnings:
            self._notify(1, f"기초자료 안내: {warning}")
        enrichment_data = enrichment.to_dict()
        self._save_json(run_dir / "enrichment.json", enrichment_data)

        research_parts = [
            "## 수집된 매물정보",
            "",
            property_info.summary(),
            "",
            f"- 수집 출처: {property_info.source}",
        ]
        enrichment_markdown = enrichment.to_markdown()
        if enrichment_markdown:
            research_parts.extend(["", enrichment_markdown])
        research = "\n".join(research_parts).strip()
        (run_dir / "research.md").write_text(research + "\n", encoding="utf-8")

        result = WorkflowResult(
            run_id=run_id,
            output_dir=str(run_dir),
            property_info=property_info,
            research=research,
            content=BlogContent(
                title="",
                body="",
                hashtags=[],
                image_prompt=self.settings.image_prompt,
            ),
            thumbnail_path=None,
            map_image_path=None,
            map_url=str(enrichment.address.get("map_url") or ""),
            roadview_url=str(enrichment.address.get("roadview_url") or ""),
            latitude=str(enrichment.address.get("latitude") or ""),
            longitude=str(enrichment.address.get("longitude") or ""),
            nearby_places=enrichment.nearby,
            enrichment_data=enrichment_data,
            preview_only=True,
        )
        self._save_result(result)
        self._notify(
            1,
            "매물 조사 메모가 준비되었습니다. 내용을 확인·보완하세요.",
        )
        return result

    def generate_content(self, result: WorkflowResult) -> WorkflowResult:
        """현재 미리보기 자료를 사용해 blog자료 원고만 생성한다."""
        run_dir = Path(result.output_dir)
        agent = self._agent()
        generation_warning: str | None = None

        # 입지·웹검색은 1단계의 무료 Kakao/Daum 경로에서 이미 수집한다.
        # Google Search grounding을 별도로 호출하지 않아 한 게시물당 Gemini
        # 생성 요청을 한 번으로 제한한다.
        research = result.research
        (run_dir / "research.md").write_text(research + "\n", encoding="utf-8")

        self._notify(
            2,
            "AI로 blog자료 원고를 작성합니다. (수집 자료·설정 프롬프트 기반)",
        )
        try:
            content = agent.write(result.property_info, research)
        except AIServiceUnavailableError:
            agent, generation_warning = self._service_fallback(
                agent,
                2,
                "블로그 글 작성",
            )
            content = agent.write(result.property_info, research)
        except AIQuotaExceededError:
            agent, generation_warning = self._quota_fallback(
                agent,
                2,
                "블로그 글 작성",
            )
            content = agent.write(result.property_info, research)

        content.image_prompt = self.settings.image_prompt
        result.research = research
        result.content = content
        result.generation_warning = generation_warning
        result.preview_only = False
        result.blog_markdown_path = str(self.sync_content(result))
        self._save_result(result)
        self._notify(2, "AI 원고 작성이 끝났습니다. 내용을 검토·수정하세요.")

        # AI 자동 글쓰기 시 대표 이미지(로컬·무료) 한 장도 함께 만들어 두어,
        # 포스팅할 때 본문 맨 위에 자동으로 첨부되도록 한다. 직접 올린 이미지가
        # 있으면 포스팅 단계에서 그쪽이 우선한다(대표이미지 우선순위 유지).
        # 이미지 생성 실패가 원고 작성 전체를 막지 않도록 예외는 삼킨다.
        try:
            self.generate_image(result)
        except Exception as error:  # noqa: BLE001 - 대표 이미지 없이라도 진행
            self._notify(
                3,
                "대표 이미지 자동 생성에 실패해 이미지 없이 진행합니다. "
                f"필요하면 '로컬 이미지 생성'을 눌러 주세요. ({error})",
            )
        return result

    def sync_content(self, result: WorkflowResult) -> Path:
        """화면에서 수정된 원고를 고정 파일명과 실행 폴더에 함께 반영한다."""
        run_dir = Path(result.output_dir)
        blog_path = write_blog_file(
            self.settings.output_dir,
            result.property_info.article_no,
            result.content,
            realtor_footer=self.settings.realtor_footer_enabled,
        )
        result.blog_markdown_path = str(blog_path)
        shutil.copy2(blog_path, run_dir / "post.md")
        self._save_json(run_dir / "content.json", result.content.to_dict())
        self._save_result(result)
        return blog_path

    def generate_image(
        self,
        result: WorkflowResult,
        *,
        prompt: str = "",
    ) -> Path:
        """외부 이미지 API 없이 Pillow로 1:1 대표 이미지를 만든다."""
        self._notify(3, "비용 없는 로컬 방식으로 1:1 대표 이미지를 만듭니다.")
        active_prompt = prompt.strip() or self.settings.image_prompt
        safe_article = _safe_name(result.property_info.article_no)
        fixed_path = (
            self.settings.output_dir
            / "thumbnails"
            / f"thumbnail_{safe_article}.png"
        )
        property_info = result.property_info
        create_demo_thumbnail(
            fixed_path,
            property_info.complex_name or property_info.name,
            property_info.address,
            _thumbnail_detail(
                property_info.price,
                property_info.area,
                property_info.trade_type,
            ),
            active_prompt,
            self.settings.project_root / "templates" / "썸네일가이드.png",
        )
        run_thumbnail = Path(result.output_dir) / "thumbnail.png"
        run_thumbnail.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fixed_path, run_thumbnail)
        result.thumbnail_path = str(fixed_path)
        result.content.image_prompt = active_prompt
        if result.blog_markdown_path:
            self.sync_content(result)
        self._save_result(result)
        self._notify(3, f"대표 이미지를 저장했습니다: {fixed_path}")
        return fixed_path

    def run(
        self,
        *,
        article_no: str,
        curl_command: str = "",
        sample: bool = False,
        generate_thumbnail: bool = True,
    ) -> WorkflowResult:
        """기존 호출 호환용: 미리보기→글 생성→선택 시 로컬 이미지."""
        result = self.preview(
            article_no=article_no,
            curl_command=curl_command,
            sample=sample,
        )
        result = self.generate_content(result)
        if generate_thumbnail:
            self.generate_image(result)
        else:
            self._notify(3, "대표 이미지 생성을 건너뜁니다.")
        self._notify(4, "검토 후 '블로그로 포스팅'을 실행할 수 있습니다.")
        return result

    def _apply_realtor_identity(self, property_info) -> None:
        """환경설정에 입력한 중개사무소 정보로 매물의 중개사 표기를 채운다."""
        settings = self.settings
        overrides = (
            ("realtor_name", settings.realtor_office_name),
            ("realtor_ceo", settings.realtor_agent_name),
            ("realtor_registration_no", settings.realtor_registration_no),
            ("realtor_phone", settings.realtor_office_phone),
            ("realtor_mobile", settings.realtor_office_mobile),
            ("realtor_address", settings.realtor_office_address),
        )
        for attr, value in overrides:
            value = (value or "").strip()
            if value:
                setattr(property_info, attr, value)

    def _section_icons_dir(self) -> Path | None:
        """선택된 아이콘 묶음 폴더(templates/icons/<icon_package>)를 돌려준다.

        설정이 비어 있거나 폴더가 없으면 None(섹션 아이콘 삽입 생략)."""
        package = (self.settings.icon_package or "").strip()
        if not package:
            return None
        candidate = self.settings.project_root / "templates" / "icons" / package
        return candidate if candidate.is_dir() else None

    def save_draft(
        self,
        result: WorkflowResult,
        *,
        naver_id: str = "",
        password: str = "",
        keep_browser_open: bool = False,
        body_image_paths: Sequence[Path] | None = None,
        on_saved: Callable[[bool], None] | None = None,
    ) -> None:
        if result.preview_only or not result.content.title.strip():
            raise ValueError(
                "먼저 제목·본문을 입력(붙여넣기)하거나 "
                "'(선택) AI로 자동 글쓰기'를 실행해 주세요."
            )
        # 환경설정의 중개사무소 정보가 있으면 매물에서 긁어온 값보다 우선 사용한다.
        self._apply_realtor_identity(result.property_info)
        blog_path = self.sync_content(result)
        warning_image = create_support_images(
            self.settings.project_root / "templates",
        )
        poster = NaverBlogPoster(
            profile_dir=self.settings.browser_profile_dir,
            selector_path=self.settings.selector_path,
            write_url=self.settings.blog_write_url,
            browser_channel=self.settings.browser_channel,
            log=lambda message: self._notify(4, message),
        )
        thumbnail = Path(result.thumbnail_path) if result.thumbnail_path else None
        saved_notified = False

        def mark_saved(published: bool = False) -> None:
            nonlocal saved_notified
            if saved_notified:
                return
            saved_notified = True
            result.draft_saved = True
            self._save_result(result)
            if on_saved is not None:
                on_saved(published)

        poster.save_draft(
            blog_id=self.settings.blog_id,
            content=result.content,
            thumbnail_path=thumbnail,
            markdown_path=blog_path,
            property_info=result.property_info,
            enrichment_data=result.enrichment_data,
            phone_number=self.settings.phone_number,
            warning_image_path=warning_image,
            body_image_paths=body_image_paths,
            templates_dir=self._section_icons_dir(),
            publish_mode=self.settings.publish_mode,
            publish_category=self.settings.publish_category,
            publish_visibility=self.settings.publish_visibility,
            naver_id=naver_id,
            password=password,
            keep_browser_open=keep_browser_open,
            on_saved=mark_saved,
        )
        mark_saved()
