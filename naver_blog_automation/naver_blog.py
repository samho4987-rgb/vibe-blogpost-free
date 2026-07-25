from __future__ import annotations

import os
import time
import re
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import quote

import yaml

from .models import BlogContent, PropertyInfo
from .post_format import TableBlock, build_property_tables
from .prompt_builder import BODY_IMAGE_CAPTION
from .content_writer import MANDATORY_TRANSACTION_NOTICE


class NaverBlogError(RuntimeError):
    pass


class NaverLoginRequired(NaverBlogError):
    pass


LogCallback = Callable[[str], None]


class NaverBlogPoster:
    """전용 로컬 프로필에서 네이버 로그인 상태를 유지하며 임시저장한다."""

    def __init__(
        self,
        *,
        profile_dir: Path,
        selector_path: Path,
        write_url: str = "",
        browser_channel: str = "chrome",
        log: LogCallback | None = None,
    ) -> None:
        self.profile_dir = profile_dir
        self.selector_path = selector_path
        self.write_url = write_url.strip()
        self.browser_channel = browser_channel
        self.log = log or (lambda _message: None)
        self.selectors = self._load_selectors()

    def _load_selectors(self) -> dict[str, Any]:
        if not self.selector_path.exists():
            raise NaverBlogError(f"셀렉터 파일이 없습니다: {self.selector_path}")
        data = yaml.safe_load(self.selector_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise NaverBlogError("셀렉터 설정 형식이 올바르지 않습니다.")
        return data

    def _playwright(self):
        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError as exc:
            raise NaverBlogError(
                "Playwright가 설치되지 않았습니다. 먼저 설치 스크립트를 실행해 주세요."
            ) from exc
        return sync_playwright, Error

    def _launch_context(self, playwright: Any, error_type: type[Exception]):
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        options: dict[str, Any] = {
            "user_data_dir": str(self.profile_dir),
            "headless": False,
            "viewport": {"width": 1440, "height": 960},
            "locale": "ko-KR",
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if self.browser_channel:
            options["channel"] = self.browser_channel
        try:
            return playwright.chromium.launch_persistent_context(**options)
        except error_type as first_error:
            if "channel" not in options:
                raise
            self.log("설정된 Chrome 채널을 찾지 못해 Playwright Chromium으로 다시 시도합니다.")
            options.pop("channel", None)
            try:
                return playwright.chromium.launch_persistent_context(**options)
            except error_type as second_error:
                raise NaverBlogError(
                    "자동화 브라우저를 열지 못했습니다. 같은 자동화 프로필을 사용하는 "
                    "Chrome 창을 모두 닫은 뒤 다시 시도해 주세요."
                ) from second_error

    def open_login(
        self,
        naver_id: str = "",
        password: str = "",
        timeout_seconds: int = 300,
    ) -> None:
        """로그인 정보를 자동 입력하고 성공한 세션만 전용 프로필에 유지한다."""
        naver_id = naver_id.strip()
        if not naver_id or not password:
            raise NaverBlogError(
                "환경설정 탭에 네이버 로그인 ID와 비밀번호를 모두 입력해 주세요."
            )

        sync_playwright, error_type = self._playwright()
        self.log(
            "네이버 로그인 창을 열어 계정 정보를 입력합니다. "
            "비밀번호는 파일이나 로그에 저장하지 않습니다."
        )
        with sync_playwright() as playwright:
            context = self._launch_context(playwright, error_type)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                self._login_page(
                    page,
                    naver_id,
                    password,
                    timeout_seconds=timeout_seconds,
                )
            finally:
                context.close()

    def _login_page(
        self,
        page: Any,
        naver_id: str,
        password: str,
        *,
        timeout_seconds: int = 300,
    ) -> None:
        login_config = self.selectors.get("login", {})
        login_url = str(
            login_config.get("url")
            or "https://nid.naver.com/nidlogin.login"
        )
        page.goto(
            login_url,
            wait_until="domcontentloaded",
            timeout=45_000,
        )
        if "nid.naver.com" not in page.url.lower():
            self.log("이미 로그인된 네이버 세션을 확인했습니다.")
            return

        self._submit_login_form(
            page,
            login_config,
            naver_id,
            password,
        )
        self.log(
            "로그인 정보를 전송했습니다. 보안 확인이나 CAPTCHA가 나타나면 "
            "열린 브라우저에서 직접 완료해 주세요."
        )

        deadline = time.monotonic() + timeout_seconds
        security_notice_logged = False
        while time.monotonic() < deadline:
            if page.is_closed():
                raise NaverBlogError(
                    "로그인 완료 전에 브라우저 창이 닫혔습니다."
                )
            current = page.url.lower()
            if "nidlogin.login" not in current and "nid.naver.com" not in current:
                self.log("네이버 로그인 상태를 확인했습니다.")
                return
            error_message = self._login_error_message(page, login_config)
            if error_message:
                raise NaverBlogError(
                    f"네이버 로그인에 실패했습니다: {error_message}"
                )
            if not security_notice_logged and self._has_login_challenge(
                page,
                login_config,
            ):
                self.log(
                    "네이버 보안 확인 화면이 표시되었습니다. "
                    "열린 브라우저에서 확인을 완료하면 자동으로 계속됩니다."
                )
                security_notice_logged = True
            page.wait_for_timeout(800)
        raise NaverBlogError(
            "로그인 대기 시간이 지났습니다. 계정 정보와 네이버 보안 확인 "
            "화면을 확인한 뒤 다시 시도해 주세요."
        )

    def _submit_login_form(
        self,
        page: Any,
        login_config: dict[str, Any],
        naver_id: str,
        password: str,
    ) -> None:
        id_input = self._first_visible(
            page,
            login_config.get("id", ["#id"]),
        )
        password_input = self._first_visible(
            page,
            login_config.get("password", ["#pw"]),
        )
        login_button = self._first_visible(
            page,
            login_config.get(
                "submit",
                ["#loginBtn_column", "#loginBtn_row"],
            ),
        )
        if id_input is None or password_input is None or login_button is None:
            raise NaverBlogError(
                "네이버 로그인 입력칸 또는 로그인 버튼을 찾지 못했습니다. "
                "config/blog_selectors.yaml을 확인해 주세요."
            )
        id_input.fill(naver_id)
        password_input.fill(password)
        login_button.click()

    def _login_error_message(
        self,
        page: Any,
        login_config: dict[str, Any],
    ) -> str:
        selectors = login_config.get(
            "error",
            [
                "#err_common",
                ".error_message",
                "[role='alert']",
            ],
        )
        locator = self._first_visible(page, selectors)
        if locator is None:
            return ""
        try:
            message = " ".join(locator.inner_text().split())
        except Exception:
            return ""
        return message[:240]

    def _has_login_challenge(
        self,
        page: Any,
        login_config: dict[str, Any],
    ) -> bool:
        selectors = login_config.get(
            "challenge",
            [
                "#captcha",
                "[class*='captcha']",
                "[class*='device']",
            ],
        )
        return self._first_visible(page, selectors) is not None

    @staticmethod
    def _first_visible(scope: Any, selectors: list[str]):
        for selector in selectors:
            try:
                locator = scope.locator(selector)
                count = locator.count()
                for index in range(min(count, 8)):
                    candidate = locator.nth(index)
                    if candidate.is_visible():
                        return candidate
            except Exception:
                continue
        return None

    def _editor_scope(self, page: Any) -> Any:
        frame_names = self.selectors.get("editor", {}).get("iframe", ["mainFrame"])
        for name in frame_names:
            try:
                frame = page.frame(name=name)
                if frame is not None:
                    return frame
            except Exception:
                continue
        return page

    def _wait_for_editor(self, page: Any, timeout_seconds: int = 35) -> Any:
        title_selectors = self.selectors.get("editor", {}).get("title", [])
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            scope = self._editor_scope(page)
            if self._first_visible(scope, title_selectors) is not None:
                return scope
            page.wait_for_timeout(600)
        raise NaverBlogError(
            "네이버 스마트에디터의 제목 입력칸을 찾지 못했습니다. "
            "config/blog_selectors.yaml을 최신 화면에 맞게 수정해 주세요."
        )

    def _open_editor(self, page: Any, blog_id: str) -> Any:
        escaped_blog_id = quote(blog_id.strip(), safe="")
        matched_write_url = (
            f"https://blog.naver.com/{escaped_blog_id}?Redirect=Write"
        )
        write_url = (
            self.write_url
            if self.write_url == matched_write_url
            else matched_write_url
        )
        page.goto(write_url, wait_until="domcontentloaded", timeout=45_000)
        if "nidlogin" in page.url.lower():
            raise NaverLoginRequired(
                "네이버 로그인이 필요합니다. 환경설정 탭의 계정 정보를 확인하고 "
                "'3. 검토한 글을 임시저장'을 다시 실행해 주세요."
            )
        try:
            return self._wait_for_editor(page)
        except NaverBlogError:
            fallback_url = (
                "https://blog.naver.com/PostWriteForm.naver"
                f"?blogId={escaped_blog_id}"
            )
            self.log(
                "Redirect=Write 주소에서 에디터를 찾지 못해 직접 글쓰기 주소로 "
                "한 번 다시 시도합니다."
            )
            page.goto(
                fallback_url,
                wait_until="domcontentloaded",
                timeout=45_000,
            )
            if "nidlogin" in page.url.lower():
                raise NaverLoginRequired(
                    "네이버 로그인이 필요합니다. 환경설정 탭의 계정 정보를 확인하고 "
                    "'3. 검토한 글을 임시저장'을 다시 실행해 주세요."
                )
            return self._wait_for_editor(page)

    def _open_editor_with_login(
        self,
        page: Any,
        *,
        blog_id: str,
        naver_id: str = "",
        password: str = "",
    ) -> Any:
        try:
            return self._open_editor(page, blog_id)
        except NaverBlogError as exc:
            if not naver_id.strip() or not password:
                if isinstance(exc, NaverLoginRequired):
                    raise NaverLoginRequired(
                        "네이버 로그인 세션이 없습니다. 환경설정 탭에서 비밀번호를 "
                        "입력하거나 저장된 비밀번호를 확인한 뒤 다시 시도해 주세요."
                    ) from exc
                raise
            self.log(
                "임시저장 브라우저에서 계정 또는 글쓰기 화면을 확인하지 못해 "
                "저장된 계정으로 한 번 자동 재로그인합니다."
            )
            self._login_page(page, naver_id.strip(), password)
            return self._open_editor(page, blog_id)

    def _fill_title(self, scope: Any, title: str) -> None:
        selectors = self.selectors.get("editor", {}).get("title", [])
        locator = self._first_visible(scope, selectors)
        if locator is None:
            raise NaverBlogError("제목 입력칸을 찾지 못했습니다.")
        locator.click()
        try:
            locator.fill(title)
        except Exception:
            locator.press("ControlOrMeta+A")
            locator.type(title, delay=15)

    def _dismiss_draft_popup(self, page: Any, scope: Any) -> bool:
        selectors = self.selectors.get("editor", {}).get(
            "draft_popup_cancel",
            [
                ".se-popup-alert-confirm button.se-popup-button-cancel",
                "button.se-popup-button.se-popup-button-cancel",
            ],
        )
        button = self._first_visible(scope, selectors)
        if button is None:
            return False
        button.click()
        page.wait_for_timeout(350)
        self.log("이전에 작성 중이던 글 안내 팝업을 취소했습니다.")
        return True

    @staticmethod
    def _page_is_closed(page: Any) -> bool:
        try:
            return bool(page.is_closed())
        except Exception:
            return False

    def _dismiss_blocking_overlays(self, page: Any, scope: Any) -> bool:
        popup_config = self.selectors.get("popup", {})
        help_selectors = popup_config.get(
            "blocking_help",
            [
                "h1.se-help-title",
                "div[class*='container']:has(h1.se-help-title)",
            ],
        )
        help_panel = self._first_visible(page, help_selectors) or self._first_visible(
            scope,
            help_selectors,
        )
        if help_panel is None:
            return False

        close_selectors = popup_config.get(
            "close",
            [
                "button.se-help-panel-close-button",
                "button[aria-label*='닫기']",
            ],
        )
        close_button = self._first_visible(page, close_selectors) or self._first_visible(
            scope,
            close_selectors,
        )
        if close_button is not None:
            try:
                close_button.click(timeout=2_000)
            except TypeError:
                close_button.click()
            except Exception:
                try:
                    close_button.click(force=True, timeout=2_000)
                except Exception:
                    close_button = None

        if close_button is None:
            try:
                page.keyboard.press("Escape")
            except Exception:
                return False

        try:
            page.wait_for_timeout(250)
        except Exception:
            return False
        self.log("임시저장 버튼을 가리던 네이버 도움말 패널을 닫았습니다.")
        return True

    def _fill_body(self, scope: Any, body: str) -> None:
        configured = self.selectors.get("editor", {}).get("body", [])
        selectors = [
            *configured,
            ".se-component[data-a11y-title='본문'] .se-text-paragraph",
            ".se-component.se-text .se-text-paragraph",
        ]
        locator = self._first_visible(scope, selectors)
        if locator is None:
            raise NaverBlogError("본문 입력칸을 찾지 못했습니다.")
        locator.click()
        try:
            locator.fill(body)
        except Exception:
            locator.press("ControlOrMeta+A")
            locator.type(body, delay=1)

    # 업로드 전 대용량 이미지를 줄일 기준(가로/세로 최대 픽셀, 재압축 유발 용량).
    _UPLOAD_MAX_DIM = 1600
    _UPLOAD_RESIZE_TRIGGER = 3 * 1024 * 1024  # 3MB

    def _prepare_image_for_upload(
        self, image_path: Path, *, label: str = "이미지", max_dim: int | None = None
    ) -> Path:
        """너무 큰 이미지는 업로드가 느려 실패할 수 있으므로 미리 축소한다.

        네이버가 어차피 업로드 후 재압축하므로 가로·세로를 1600px 이내로 줄여도
        화질 저하는 거의 없다. max_dim을 주면(예: 섹션 아이콘) 그 크기로 더 작게
        줄인다. 투명 PNG는 형식을 유지하고 나머지는 JPEG로 저장한다.
        Pillow가 없거나 처리에 실패하면 원본을 그대로 쓴다(안전한 후퇴)."""
        try:
            size_bytes = image_path.stat().st_size
        except OSError:
            return image_path
        try:
            from PIL import Image
        except Exception:
            return image_path
        target = max_dim if max_dim else self._UPLOAD_MAX_DIM
        try:
            with Image.open(image_path) as img:
                fmt = (img.format or "").upper()
                width, height = img.size
                longest = max(width, height)
                need_resize = longest > target or (
                    max_dim is None and size_bytes > self._UPLOAD_RESIZE_TRIGGER
                )
                if not need_resize:
                    return image_path
                work = img
                if longest > target:
                    scale = target / float(longest)
                    resample = getattr(
                        getattr(Image, "Resampling", Image), "LANCZOS", None
                    )
                    work = img.resize(
                        (max(1, int(width * scale)), max(1, int(height * scale))),
                        resample or Image.LANCZOS,
                    )
                has_alpha = work.mode in ("RGBA", "LA") or (
                    work.mode == "P" and "transparency" in work.info
                )
                keep_png = fmt == "PNG" or has_alpha
                fd, tmp_name = tempfile.mkstemp(
                    prefix="blog_upload_", suffix=".png" if keep_png else ".jpg"
                )
                os.close(fd)
                tmp_path = Path(tmp_name)
                if keep_png:
                    work.save(tmp_path, "PNG", optimize=True)
                else:
                    work.convert("RGB").save(
                        tmp_path, "JPEG", quality=85, optimize=True
                    )
            try:
                new_bytes = tmp_path.stat().st_size
                self.log(
                    f"{label} 용량을 줄여 업로드합니다"
                    f"({size_bytes // 1024}KB → {new_bytes // 1024}KB)."
                )
            except OSError:
                pass
            return tmp_path
        except Exception:
            return image_path

    def _count_editor_images(self, page: Any, scope: Any) -> int:
        """에디터에 삽입된 이미지 개수(대략치). 업로드 완료 감지에 쓴다."""
        best = 0
        for owner in (scope, page):
            if owner is None:
                continue
            for selector in (
                ".se-component.se-image",
                ".se-image-resource",
                ".se-image",
            ):
                try:
                    best = max(best, owner.locator(selector).count())
                except Exception:
                    continue
        return best

    def _wait_for_image_added(
        self,
        page: Any,
        scope: Any,
        before: int,
        label: str,
        *,
        timeout_ms: int = 25_000,
    ) -> bool:
        """직전 이미지가 실제로 삽입될 때까지 기다린다(다음 이미지 전 준비 완료 보장).

        완료 신호를 못 봐도 예외를 던지지 않고 넘어간다(중복 삽입 방지)."""
        waited = 0
        step = 500
        while waited < timeout_ms:
            try:
                if self._count_editor_images(page, scope) > before:
                    page.wait_for_timeout(700)  # 처리 안정화용 여유
                    return True
            except Exception:
                pass
            page.wait_for_timeout(step)
            waited += step
        page.wait_for_timeout(1200)
        return False

    def _upload_image(
        self,
        page: Any,
        scope: Any,
        image_path: Path,
        *,
        label: str = "이미지",
        max_dim: int | None = None,
    ) -> None:
        if not image_path.exists():
            raise NaverBlogError(f"업로드할 {label}가 없습니다: {image_path}")
        upload_path = self._prepare_image_for_upload(
            image_path, label=label, max_dim=max_dim
        )
        before = self._count_editor_images(page, scope)

        # 1) 숨은 file input에 직접 파일 주입(가능하면 가장 안정적)
        file_selectors = self.selectors.get("insert", {}).get("image", {}).get(
            "file_input", []
        )
        for candidate_scope in (scope, page):
            for selector in file_selectors:
                try:
                    locator = candidate_scope.locator(selector)
                    if locator.count():
                        locator.nth(0).set_input_files(str(upload_path.resolve()))
                        self._wait_for_image_added(page, scope, before, label)
                        self.log(f"{label}를 에디터에 넣었습니다.")
                        return
                except Exception:
                    continue

        # 2) 사진 버튼 클릭 → 파일 선택창. 직전 업로드가 아직 처리 중이면
        #    창이 안 열릴 수 있으므로 잠시 기다렸다가 여러 번 재시도한다.
        button_selectors = self.selectors.get("insert", {}).get("image", {}).get(
            "button", []
        )
        last_exc: Exception | None = None
        for attempt in range(1, 4):
            button = self._first_visible(
                scope, button_selectors
            ) or self._first_visible(page, button_selectors)
            if button is None:
                raise NaverBlogError("사진 업로드 버튼을 찾지 못했습니다.")
            try:
                with page.expect_file_chooser(timeout=15_000) as chooser_info:
                    button.click()
                chooser_info.value.set_files(str(upload_path.resolve()))
                self._wait_for_image_added(page, scope, before, label)
                self.log(f"{label}를 에디터에 넣었습니다.")
                return
            except Exception as exc:
                last_exc = exc
                if attempt < 3:
                    self.log(
                        f"{label} 사진 선택 창이 아직 안 열려 재시도합니다"
                        f"… ({attempt}/3)"
                    )
                    page.wait_for_timeout(3000)
        raise NaverBlogError(
            f"사진 선택 창에 {label}를 전달하지 못했습니다."
        ) from last_exc

    def _keyboard_press(self, page: Any, scope: Any, combo: str) -> None:
        """에디터에 키 조합을 보낸다(scope.page 우선, 실패 시 page)."""
        for owner in (getattr(scope, "page", None), page):
            if owner is None:
                continue
            try:
                owner.keyboard.press(combo)
                return
            except Exception:
                continue

    def _body_locator(self, scope: Any) -> Any:
        configured = self.selectors.get("editor", {}).get("body", [])
        return self._first_visible(
            scope,
            [
                *configured,
                ".se-component[data-a11y-title='본문'] .se-text-paragraph",
                ".se-component.se-text .se-text-paragraph",
            ],
        )

    def _place_caret_at_start(self, page: Any, scope: Any) -> None:
        """본문 맨 앞에 캐럿을 둔다(대표 이미지를 글 맨 위에 넣기 위해)."""
        body = self._body_locator(scope)
        if body is not None:
            try:
                body.click(timeout=5000)
            except Exception:
                try:
                    body.click(timeout=3000, force=True)
                except Exception:
                    pass
        self._keyboard_press(page, scope, "ControlOrMeta+Home")

    def _place_caret_before_section(
        self, page: Any, scope: Any, keyword: str
    ) -> bool:
        """본문에서 특정 소제목(예: '단지 정보')을 실제 클릭해 그 앞에 캐럿을 둔다.

        본문 개념 이미지를 글 중간(표 섹션 앞)에 넣기 위한 위치 지정.
        찾아서 클릭하면 True, 못 찾으면 False."""
        selectors = [
            f".se-text-paragraph:has-text('{keyword}')",
            f"h2:has-text('{keyword}')",
            f"h3:has-text('{keyword}')",
        ]
        for target in (scope, page):
            for selector in selectors:
                try:
                    locator = target.locator(selector).first
                    if locator.count() and locator.is_visible():
                        locator.click(timeout=5000)
                        # 소제목 맨 앞으로 이동해 이미지가 그 위에 오도록 한다.
                        self._keyboard_press(page, scope, "Home")
                        return True
                except Exception:
                    continue
        return False

    def _wait_for_body_render(self, page: Any, scope: Any) -> None:
        """붙여넣은 본문(문단)이 스마트에디터에 다 그려질 때까지 기다린다.

        Ctrl+V 붙여넣기는 비동기라, 바로 다음 작업을 하면 아직 문단이 1개(인사말)만
        만들어져 있을 수 있다. 문단 수가 2회 연속 그대로면 렌더가 끝난 것으로 본다.
        최대 약 3.6초까지만 기다린다(그 이상은 그냥 진행)."""
        last = -1
        stable = 0
        for _ in range(12):
            count = 0
            for target in (scope, page):
                try:
                    current = target.locator(".se-text-paragraph").count()
                    if current > count:
                        count = current
                except Exception:
                    continue
            if count and count == last:
                stable += 1
                if stable >= 2:
                    return
            else:
                stable = 0
            last = count
            try:
                page.wait_for_timeout(300)
            except Exception:
                return

    def _place_caret_at_end(self, page: Any, scope: Any) -> None:
        """본문 맨 끝에 캐럿을 둔다(본문 이미지·배너를 글 끝에 넣기 위해).

        첫 문단을 클릭하고 Ctrl+End에 의존하면 스마트에디터에서 캐럿이 위에 남아
        배너가 글 상단에 들어가는 문제가 있어, 마지막 문단을 직접 클릭한다."""
        clicked = False
        # 넓은 셀렉터(.se-text-paragraph)는 본문의 '모든' 문단을 잡으므로 마지막이
        # 해시태그(=글의 진짜 끝)다. 반면 특정 컴포넌트 한정 셀렉터는 첫 문단(인사말)만
        # 잡아 마지막이 인사말이 되어, 배너가 글 위쪽에 끼어드는 문제가 있었다.
        # 그래서 '가장 많이 매칭되는' 셀렉터를 골라 그 마지막 문단을 클릭한다.
        selectors = [
            ".se-text-paragraph",
            *self.selectors.get("editor", {}).get("body", []),
            ".se-component.se-text .se-text-paragraph",
        ]
        for target in (scope, page):
            best_loc = None
            best_count = 0
            for selector in selectors:
                try:
                    loc = target.locator(selector)
                    count = loc.count()
                    if count > best_count:
                        best_count, best_loc = count, loc
                except Exception:
                    continue
            if best_loc is not None and best_count:
                try:
                    last = best_loc.nth(best_count - 1)
                    if last.is_visible():
                        try:
                            last.click(timeout=5000)
                        except Exception:
                            last.click(timeout=3000, force=True)
                        clicked = True
                except Exception:
                    pass
            if clicked:
                break
        # 마지막 문단 안에서 문서 끝으로 이동. 클릭이 문단 중간에 떨어졌을 수 있으니
        # 줄 끝(End)으로도 이동해 캐럿이 마지막 문단의 끝에 오게 한다.
        self._keyboard_press(page, scope, "ControlOrMeta+End")
        self._keyboard_press(page, scope, "End")

    def _write_html_clipboard(
        self, page: Any, scope: Any, html: str, plain: str
    ) -> bool:
        """브라우저 클립보드에 HTML(+텍스트)을 기록한다."""
        js = """async ([html, plain]) => {
            try {
                if (navigator.clipboard && window.ClipboardItem) {
                    const item = new ClipboardItem({
                        'text/html': new Blob([html], {type: 'text/html'}),
                        'text/plain': new Blob([plain], {type: 'text/plain'}),
                    });
                    await navigator.clipboard.write([item]);
                    return true;
                }
            } catch (e) { return false; }
            return false;
        }"""
        # 최상위 페이지에서 기록하면 iframe 제약을 피할 수 있다(클립보드는 공유됨).
        for target in (page, scope):
            try:
                if bool(target.evaluate(js, [html, plain])):
                    return True
            except Exception:
                continue
        return False

    def _insert_body_html(
        self, scope: Any, page: Any, html: str, plain: str = ""
    ) -> bool:
        """본문 HTML을 삽입한다.

        네이버 스마트에디터는 자체 문서 모델을 쓰므로 execCommand('insertHTML')는
        저장에 반영되지 않는다(참고: 검증된 기존 코드도 클립보드 붙여넣기를 사용).
        따라서 (1) 클립보드에 HTML을 넣고 Ctrl/Cmd+V로 붙여넣기를 먼저 시도하고,
        실패하면 (2) execCommand 경로로 폴백한다."""
        if plain and self._write_html_clipboard(page, scope, html, plain):
            self._keyboard_press(page, scope, "ControlOrMeta+V")
            self.log("클립보드 붙여넣기로 본문을 입력했습니다.")
            return True
        simple = (
            "html => { const a = document.activeElement;"
            " if (!a) return false;"
            " return document.execCommand('insertHTML', false, html); }"
        )
        for target in (scope, page):
            try:
                if bool(target.evaluate(simple, html)):
                    return True
            except Exception:
                continue
        js = """(html) => {
            const body = document.querySelector(
                ".se-component[data-a11y-title='본문']");
            let el = null;
            if (body) {
                el = body.querySelector('[contenteditable=\"true\"]');
                if (!el) {
                    const p = body.querySelector('.se-text-paragraph');
                    el = p && p.closest
                        ? p.closest('[contenteditable=\"true\"]')
                        : null;
                }
            }
            el = el
                || document.querySelector('.se-content [contenteditable=\"true\"]')
                || document.querySelector('[contenteditable=\"true\"]');
            if (!el) return false;
            el.focus();
            try {
                const range = document.createRange();
                range.selectNodeContents(el);
                range.collapse(false);
                const sel = window.getSelection();
                sel.removeAllRanges();
                sel.addRange(range);
            } catch (e) {}
            return document.execCommand('insertHTML', false, html);
        }"""
        for target in (scope, page):
            try:
                if bool(target.evaluate(js, html)):
                    return True
            except Exception:
                continue
        return False

    def _insert_caption(self, page: Any, scope: Any, text: str) -> None:
        """방금 넣은 이미지 아래에 안내 캡션 문구를 넣는다.

        스마트에디터는 execCommand 삽입을 저장에 반영하지 않으므로, 실제 키 입력
        (keyboard.type)으로 캡션 문구를 넣어 저장까지 남게 한다."""
        if not text.strip():
            return
        self._keyboard_press(page, scope, "End")
        self._keyboard_press(page, scope, "Enter")
        for owner in (getattr(scope, "page", None), page):
            if owner is None:
                continue
            try:
                owner.keyboard.type(text)
                self._keyboard_press(page, scope, "Enter")
                return
            except Exception:
                continue
        self.log("이미지 캡션 문구를 자동으로 넣지 못했습니다.")

    @staticmethod
    def _inline_html(text: str) -> str:
        from html import escape

        escaped = escape(text)
        escaped = re.sub(
            r"\*\*(.+?)\*\*",
            r"<strong>\1</strong>",
            escaped,
        )
        escaped = re.sub(
            r"\[([^\]]+)\]\((https?://[^)]+)\)",
            r'<a href="\2">\1</a>',
            escaped,
        )
        return escaped

    def _markdown_html(
        self,
        markdown: str,
        tables: Mapping[str, TableBlock],
    ) -> tuple[str, str]:
        """고정 원고를 네이버에 붙일 HTML과 텍스트 대체본으로 변환한다."""
        html_parts: list[str] = []
        plain_parts: list[str] = []
        paragraph: list[str] = []

        def flush() -> None:
            if not paragraph:
                return
            text = " ".join(item.strip() for item in paragraph if item.strip())
            if text:
                html_parts.append(
                    '<p style="line-height:1.9;margin:0 0 22px 0;">'
                    f"{self._inline_html(text)}</p>"
                )
                plain_parts.extend([text, ""])
            paragraph.clear()

        lines = markdown.splitlines()
        if lines and lines[0].startswith("# "):
            lines = lines[1:]
        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                flush()
                continue
            if line == "[THUMBNAIL_IMAGE]":
                flush()
                continue
            if line == MANDATORY_TRANSACTION_NOTICE:
                # 거래상태 확인 고지문은 눈에 띄게 강조(빨간 굵은 글씨 + 배경).
                flush()
                html_parts.append(
                    '<p style="color:#d6335a;font-weight:bold;line-height:1.9;'
                    'background:#fdeef1;padding:14px 16px;border-radius:8px;'
                    'margin:0 0 22px 0;">'
                    f"{self._inline_html(line)}</p>"
                )
                plain_parts.extend([line, ""])
                continue
            if line in tables:
                flush()
                table = tables[line]
                html_parts.append(table.html)
                html_parts.append("<p><br></p>")
                plain_parts.extend([table.plain, ""])
                continue
            if line == "---":
                flush()
                html_parts.append(
                    '<hr style="border:0;border-top:1px solid #d8e0e5;'
                    'margin:28px 0;">'
                )
                plain_parts.extend(["―" * 18, ""])
                continue
            if line.startswith("### "):
                flush()
                text = line[4:].strip()
                html_parts.append(
                    '<h3 style="font-size:19px;margin:26px 0 12px;">'
                    f"{self._inline_html(text)}</h3>"
                )
                plain_parts.extend([text, ""])
                continue
            if line.startswith("## "):
                flush()
                text = line[3:].strip()
                html_parts.append(
                    '<h2 style="font-size:23px;margin:32px 0 14px;">'
                    f"<strong>{self._inline_html(text)}</strong></h2>"
                )
                plain_parts.extend([text, ""])
                continue
            if line.startswith(("- ", "* ")):
                flush()
                text = line[2:].strip()
                html_parts.append(
                    '<p style="line-height:1.9;margin:0 0 8px 0;">• '
                    f"{self._inline_html(text)}</p>"
                )
                plain_parts.append(f"• {text}")
                continue
            paragraph.append(line)
        flush()
        return "\n".join(html_parts), "\n".join(plain_parts).strip()

    def _fill_rich_body(
        self,
        page: Any,
        scope: Any,
        *,
        markdown: str,
        tables: Mapping[str, TableBlock],
        thumbnail_path: Path | None,
        warning_image_path: Path | None,
        body_image_paths: Sequence[Path] | None = None,
        templates_dir: Path | None = None,
    ) -> None:
        configured = self.selectors.get("editor", {}).get("body", [])
        locator = self._first_visible(
            scope,
            [
                *configured,
                ".se-component[data-a11y-title='본문'] .se-text-paragraph",
                ".se-component.se-text .se-text-paragraph",
            ],
        )
        if locator is None:
            raise NaverBlogError("본문 입력칸을 찾지 못했습니다.")
        # 실제 클릭으로 본문에 캐럿을 두고 내용을 비운다(스마트에디터 동기화 보장).
        locator.click()
        locator.press("ControlOrMeta+A")
        locator.press("Backspace")

        html, plain = self._markdown_html(markdown, tables)

        # 스마트에디터는 Ctrl+Home/End로 캐럿을 되돌리는 것이 불안정하다. 따라서
        # 위→아래 순서로만 쌓아 위치를 고정한다(썸네일 → 본문 → 배너).

        # 1) 대표 이미지(썸네일)를 빈 본문에 먼저 넣어 글 맨 위에 오게 한다.
        if thumbnail_path is not None:
            self._upload_image(
                page, scope, thumbnail_path, label="대표 이미지"
            )
            self._keyboard_press(page, scope, "End")
            self._keyboard_press(page, scope, "Enter")

        # 2) 본문 텍스트/표를 썸네일 아래에 넣는다.
        inserted = self._insert_body_html(scope, page, html, plain)
        if not inserted:
            self.log(
                "HTML 표 직접 삽입을 지원하지 않는 에디터 화면이라 "
                "표 내용을 텍스트 형식으로 입력합니다."
            )
            try:
                page.keyboard.insert_text(plain)
            except Exception:
                locator.type(plain, delay=1)
        else:
            self.log("소제목·굵은 글씨·HTML 표를 포함한 본문을 입력했습니다.")

        # 붙여넣기(Ctrl+V)는 비동기라 스마트에디터가 문단·표를 만드는 데 시간이 걸린다.
        # 렌더가 끝나기 전에 배너 이미지를 넣으면 캐럿이 첫 문단(인사말)에 남아 본문
        # 위쪽을 갈라놓는다. 그래서 문단 수가 안정될 때까지 잠시 기다린다.
        self._wait_for_body_render(page, scope)

        # 3) 거래상태 확인 안내 배너를 '문서 제일 하단'(해시태그 아래)에 넣는다.
        #    붙여넣기(Ctrl+V) 직후 캐럿은 이미 문서의 맨 끝(마지막 문단=해시태그 뒤)에
        #    있으므로, 문단을 다시 '클릭'하지 않는다. 클릭하면 캐럿이 문단 중간에
        #    떨어져 본문(인사말·해시태그)을 갈라놓는 문제가 있었다. 뒤의 아이콘·본문
        #    이미지는 글 중간에 들어가므로, 먼저 넣은 이 하단 배너 위치에는 영향이 없다.
        if warning_image_path is not None:
            self._keyboard_press(page, scope, "ControlOrMeta+End")
            self._keyboard_press(page, scope, "Enter")
            self._upload_image(
                page, scope, warning_image_path, label="거래 상태 확인 이미지"
            )

        # 4) 섹션 아이콘(templates에 파일이 있으면) 각 소제목 위에 넣는다.
        if templates_dir is not None:
            self._insert_section_icons(page, scope, Path(templates_dir))

        # 5) 본문 개념 이미지는 글 중간(단지정보 표 앞)에 넣는다(소제목 클릭=신뢰 가능).
        valid_body_images = [
            Path(p) for p in (body_image_paths or []) if p and Path(p).exists()
        ]
        if valid_body_images:
            placed_middle = self._place_caret_before_section(
                page, scope, "단지 정보"
            )
            if placed_middle:
                for index, body_image in enumerate(valid_body_images, start=1):
                    self._keyboard_press(page, scope, "End")
                    self._keyboard_press(page, scope, "Enter")
                    self._upload_image(
                        page, scope, body_image, label=f"본문 이미지 {index}"
                    )
                    self._insert_caption(page, scope, BODY_IMAGE_CAPTION)

    # 섹션 소제목 → templates 아이콘 파일명(있으면 소제목 위에 삽입).
    _SECTION_ICONS = (
        ("sec_매물소개", ("매물 소개", "매물소개")),
        ("sec_매물특징", ("매물 특징", "매물특징")),
        ("sec_단지정보", ("단지 정보", "단지정보")),
        ("sec_매물상세", ("매물 상세", "매물상세", "상세 정보")),
        ("sec_거래상태", ("거래상태", "거래 상태")),
        ("sec_지역가치", ("지역 가치", "지역가치", "개발 호재", "미래 가치", "주변 환경")),
        ("sec_학군", ("학군",)),
        ("sec_교통", ("교통", "편의시설")),
        ("sec_중개사무소", ("중개사무소", "중개 사무소")),
        ("sec_문의안내", ("문의 안내", "문의안내")),
    )
    _SECTION_ICON_EXTS = (".png", ".jpg", ".jpeg", ".webp")
    # 섹션 아이콘은 제목용 아이콘처럼 작게(가로·세로 최대 100px) 넣는다.
    _SECTION_ICON_MAX_DIM = 100

    def _find_section_icon(self, templates_dir: Path, stem: str) -> Path | None:
        for ext in self._SECTION_ICON_EXTS:
            candidate = templates_dir / f"{stem}{ext}"
            if candidate.exists():
                return candidate
        return None

    def _insert_section_icons(
        self, page: Any, scope: Any, templates_dir: Path
    ) -> None:
        """templates에 준비된 섹션 아이콘 이미지를 각 소제목 위에 넣는다(있는 것만)."""
        for stem, keywords in self._SECTION_ICONS:
            icon = self._find_section_icon(templates_dir, stem)
            if icon is None:
                continue
            placed = False
            for keyword in keywords:
                if self._place_caret_before_section(page, scope, keyword):
                    placed = True
                    break
            if not placed:
                continue
            self._upload_image(
                page,
                scope,
                icon,
                label=f"섹션 아이콘({stem})",
                max_dim=self._SECTION_ICON_MAX_DIM,
            )

    def _click_draft(self, page: Any, scope: Any) -> None:
        if self._page_is_closed(page):
            raise NaverBlogError(
                "임시저장이 끝나기 전에 브라우저 창이 닫혔습니다. "
                "완료 메시지가 나올 때까지 자동화 창을 닫지 말아 주세요."
            )
        self._dismiss_blocking_overlays(page, scope)
        selectors = self.selectors.get("publish", {}).get("draft", [])
        button = self._first_visible(page, selectors) or self._first_visible(
            scope, selectors
        )
        if button is None:
            raise NaverBlogError(
                "임시저장 버튼을 찾지 못했습니다. 자동 발행은 시도하지 않았습니다."
            )
        try:
            button.click(timeout=4_000)
        except Exception as first_error:
            if self._page_is_closed(page):
                raise NaverBlogError(
                    "임시저장이 끝나기 전에 브라우저 창이 닫혔습니다. "
                    "완료 메시지가 나올 때까지 자동화 창을 닫지 말아 주세요."
                ) from first_error
            self._dismiss_blocking_overlays(page, scope)
            try:
                # 도움말 패널의 애니메이션이 남아 있는 경우에만 강제 클릭한다.
                button.click(force=True, timeout=4_000)
            except Exception as retry_error:
                if self._page_is_closed(page):
                    raise NaverBlogError(
                        "임시저장이 끝나기 전에 브라우저 창이 닫혔습니다. "
                        "완료 메시지가 나올 때까지 자동화 창을 닫지 말아 주세요."
                    ) from retry_error
                raise NaverBlogError(
                    "네이버 도움말 또는 팝업이 임시저장 버튼을 가리고 있습니다. "
                    "열린 창에서 도움말을 닫은 뒤 다시 시도해 주세요."
                ) from retry_error
        try:
            page.wait_for_timeout(2500)
        except Exception as exc:
            if self._page_is_closed(page):
                raise NaverBlogError(
                    "임시저장 확인 전에 브라우저 창이 닫혔습니다. "
                    "네이버 블로그의 임시저장 목록을 확인해 주세요."
                ) from exc
            raise

    def _publish(
        self,
        page: Any,
        scope: Any,
        *,
        category_name: str = "",
        visibility: str = "public",
    ) -> bool:
        """발행 레이어를 열어 (지정)카테고리·전체공개 설정 후 발행한다.

        카테고리 이름이 지정됐는데 블로그 카테고리 목록에 없으면 발행하지 않고
        False를 돌려준다(호출부에서 임시저장으로 대체). 발행 성공 시 True.
        상단 '발행' 버튼 → 발행 설정 레이어 → 카테고리 선택 → 레이어의 '발행' 확정."""
        self._dismiss_blocking_overlays(page, scope)
        publish_selectors = self.selectors.get("publish", {}).get("publish", [])
        # 1) 상단 '발행' 버튼(발행 설정 레이어 열기)
        open_btn = self._first_visible(page, publish_selectors) or self._first_visible(
            scope, publish_selectors
        )
        if open_btn is None:
            self.log(
                "발행 버튼을 찾지 못해 발행 대신 임시저장으로 진행합니다. "
                "(네이버 에디터 화면 구조가 바뀌었을 수 있습니다.)"
            )
            return False
        try:
            open_btn.click(timeout=5_000)
        except Exception:
            open_btn.click(force=True, timeout=5_000)
        page.wait_for_timeout(1200)

        # 2) 카테고리 선택. 지정된 카테고리가 블로그에 없으면 발행을 중단한다.
        target = category_name.strip()
        if target:
            if not self._select_category(page, scope, target):
                self.log(
                    f"카테고리 '{target}'을(를) 블로그 카테고리에서 선택하지 못해 "
                    "발행을 중단하고 임시저장합니다."
                )
                self._close_publish_layer(page, scope)
                return False
            self.log(f"카테고리 '{target}'을(를) 선택했습니다.")

        # 3) 공개 설정. 환경설정의 공개범위에 따라 전체공개/비공개를 정한다.
        #    네이버 기본값이 '비공개'이므로, 전체공개일 때만 명시적으로 선택한다.
        if str(visibility).strip().lower() == "private":
            self.log("공개 범위를 '비공개'로 발행합니다(환경설정).")
        else:
            self._set_public_visibility(page, scope)

        # 4) 발행 설정 패널 '맨 아래'의 발행 확정(제출) 버튼.
        #    상단 발행 버튼(패널 열기)과 반드시 다른 요소여야 한다. 같은 셀렉터를
        #    재사용하면 상단 버튼을 다시 눌러 패널만 닫히고 실제 발행이 안 된다.
        page.wait_for_timeout(600)
        self._dismiss_blocking_overlays(page, scope)
        confirm = self._find_publish_confirm(page, scope)
        if confirm is None:
            self.log(
                "발행 확정(제출) 버튼을 정확히 찾지 못했습니다. 잘못 발행되지 "
                "않도록 발행을 중단하고 임시저장으로 진행합니다."
            )
            self._close_publish_layer(page, scope)
            return False
        try:
            confirm.click(timeout=5_000)
        except Exception:
            confirm.click(force=True, timeout=5_000)
        # 비공개→전체공개로 바꾸면 뜨는 '발행하시겠습니까?' 확인 팝업의 '확인'을 누른다.
        self._confirm_publish_dialog(page, scope)
        try:
            page.wait_for_timeout(2500)
        except Exception as exc:
            if self._page_is_closed(page):
                raise NaverBlogError(
                    "발행 확인 전에 브라우저 창이 닫혔습니다. "
                    "네이버 블로그에서 발행 결과를 확인해 주세요."
                ) from exc
            raise
        return True

    def _confirm_publish_dialog(self, page: Any, scope: Any) -> None:
        """발행 직후 '공개 범위 변경(비공개→전체공개) 확인' 팝업이 뜨면 '확인'을 누른다.

        이 팝업을 처리하지 않으면 발행이 완료되지 않는다."""
        page.wait_for_timeout(900)
        selectors = self.selectors.get("publish", {}).get("change_confirm", [])
        button = self._first_visible(page, selectors) or self._first_visible(
            scope, selectors
        )
        if button is None:
            # 텍스트가 '확인'인 버튼 중 마지막으로 보이는 것(모달이 보통 최상위).
            for owner in (page, scope):
                if owner is None:
                    continue
                try:
                    candidates = owner.get_by_role("button", name="확인")
                    total = candidates.count()
                except Exception:
                    continue
                for index in range(total - 1, -1, -1):
                    try:
                        item = candidates.nth(index)
                        if item.is_visible():
                            button = item
                            break
                    except Exception:
                        continue
                if button is not None:
                    break
        if button is None:
            return
        try:
            button.click(timeout=3_000)
            self.log("공개 범위 변경 확인 팝업에서 '확인'을 눌렀습니다.")
            page.wait_for_timeout(1500)
        except Exception:
            try:
                button.click(force=True, timeout=3_000)
                page.wait_for_timeout(1500)
            except Exception:
                pass

    def _set_public_visibility(self, page: Any, scope: Any) -> None:
        """공개 범위를 '전체공개'로 설정한다. 네이버 기본값이 '비공개'라 반드시 명시.

        커스텀 라디오라 라벨 클릭을 우선하고, 클릭 후 실제로 체크됐는지 확인한다."""
        public_selectors = self.selectors.get("visibility", {}).get("public", [])
        target = self._first_visible(
            page, public_selectors
        ) or self._first_visible(scope, public_selectors)
        if target is None:
            self.log(
                "'전체공개' 옵션을 찾지 못했습니다. 발행 전에 공개 범위를 직접 "
                "확인해 주세요(기본값은 비공개입니다)."
            )
            return
        try:
            target.click(timeout=3_000)
        except Exception:
            try:
                target.click(force=True, timeout=3_000)
            except Exception:
                self.log("'전체공개' 선택을 자동 완료하지 못했습니다. 공개 범위를 확인해 주세요.")
                return
        page.wait_for_timeout(300)
        # 실제로 전체공개 라디오가 선택됐는지 확인(가능하면).
        for owner in (page, scope):
            if owner is None:
                continue
            try:
                radio = owner.locator("#open_public")
                if radio.count() and radio.first.is_checked():
                    self.log("공개 범위를 '전체공개'로 설정했습니다.")
                    return
            except Exception:
                continue
        self.log("공개 범위를 '전체공개'로 설정했습니다(확인 생략).")

    def _find_publish_confirm(self, page: Any, scope: Any) -> Any:
        """발행 패널 하단의 발행 확정(제출) 버튼을 찾는다(상단 열기 버튼과 구분).

        확인된 값(data-testid='seOnePublishBtn' 등)을 우선 쓰고, 못 찾으면
        텍스트가 '발행'인 버튼 중 '마지막으로 보이는' 것(패널 하단)을 쓴다."""
        confirm_selectors = self.selectors.get("publish", {}).get(
            "publish_confirm", []
        )
        confirm = self._first_visible(
            page, confirm_selectors
        ) or self._first_visible(scope, confirm_selectors)
        if confirm is not None:
            return confirm
        # 폴백: 접근성 이름이 '발행'인 버튼 중 마지막으로 보이는 것.
        for owner in (page, scope):
            if owner is None:
                continue
            try:
                candidates = owner.get_by_role("button", name="발행")
                total = candidates.count()
            except Exception:
                continue
            for index in range(total - 1, -1, -1):
                try:
                    item = candidates.nth(index)
                    if item.is_visible():
                        return item
                except Exception:
                    continue
        return None

    def _select_category(self, page: Any, scope: Any, target: str) -> bool:
        """발행 레이어에서 카테고리를 선택한다. 성공하면 True.

        최신 에디터는 커스텀 드롭다운(버튼→메뉴)이고, 구버전은 <select>다.
        지정한 카테고리가 목록에 없으면 False(→ 임시저장으로 대체)."""
        category = self.selectors.get("category", {})
        # 1) 커스텀 드롭다운(최신 에디터)
        button_selectors = category.get("button", [])
        button = self._first_visible(page, button_selectors) or self._first_visible(
            scope, button_selectors
        )
        if button is not None:
            return self._select_category_custom(page, scope, button, target)
        # 2) 구버전 네이티브 <select>
        select = self._first_visible(
            page, category.get("dropdown", [])
        ) or self._first_visible(scope, category.get("dropdown", []))
        if select is None:
            return False
        try:
            available = [
                text.strip()
                for text in select.locator("option").all_text_contents()
            ]
        except Exception:
            available = []
        if available and target not in available:
            return False
        try:
            select.select_option(label=target)
            return True
        except Exception:
            return False

    def _select_category_custom(
        self, page: Any, scope: Any, button: Any, target: str
    ) -> bool:
        """커스텀 카테고리 드롭다운: 버튼을 눌러 메뉴를 열고, 텍스트가 정확히
        일치하는 항목을 클릭한다. 일치 항목이 없으면(=블로그에 없는 카테고리) False."""
        # 이미 현재 선택이 target이면 그대로 둔다.
        try:
            current = button.inner_text().strip()
            if current == target:
                return True
        except Exception:
            pass
        try:
            button.click(timeout=4_000)
        except Exception:
            try:
                button.click(force=True, timeout=4_000)
            except Exception:
                return False
        page.wait_for_timeout(700)

        item_selectors = self.selectors.get("category", {}).get("menu_item", [])
        for owner in (page, scope):
            if owner is None:
                continue
            for selector in item_selectors:
                try:
                    items = owner.locator(selector)
                    count = items.count()
                except Exception:
                    continue
                for index in range(count):
                    item = items.nth(index)
                    try:
                        text = item.inner_text().strip()
                    except Exception:
                        continue
                    if text == target or text.split("\n")[0].strip() == target:
                        try:
                            item.click(timeout=3_000)
                        except Exception:
                            try:
                                item.click(force=True, timeout=3_000)
                            except Exception:
                                continue
                        page.wait_for_timeout(500)
                        return True
        # 일치 항목 없음 → 메뉴 닫기
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        except Exception:
            pass
        return False

    def _close_publish_layer(self, page: Any, scope: Any) -> None:
        """발행 설정 레이어를 닫는다(임시저장으로 대체하기 위해). best-effort."""
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(600)
        except Exception:
            pass
        self._dismiss_blocking_overlays(page, scope)

    def save_draft(
        self,
        *,
        blog_id: str,
        content: BlogContent,
        thumbnail_path: Path | None = None,
        markdown_path: Path | None = None,
        property_info: PropertyInfo | None = None,
        enrichment_data: Mapping[str, Any] | None = None,
        phone_number: str = "",
        warning_image_path: Path | None = None,
        body_image_paths: Sequence[Path] | None = None,
        templates_dir: Path | None = None,
        publish_mode: str = "draft",
        publish_category: str = "",
        publish_visibility: str = "public",
        naver_id: str = "",
        password: str = "",
        keep_browser_open: bool = False,
        on_saved: Callable[[bool], None] | None = None,
    ) -> None:
        if not blog_id.strip():
            raise NaverBlogError("네이버 블로그 ID를 입력해 주세요.")

        sync_playwright, error_type = self._playwright()
        self.log("네이버 블로그 스마트에디터를 엽니다.")
        with sync_playwright() as playwright:
            context = self._launch_context(playwright, error_type)
            # 클립보드 붙여넣기로 본문 HTML을 넣기 위해 권한을 부여한다
            # (스마트에디터는 execCommand 대신 실제 붙여넣기만 문서 모델에 반영됨).
            try:
                context.grant_permissions(
                    ["clipboard-read", "clipboard-write"],
                    origin="https://blog.naver.com",
                )
            except Exception:
                pass
            try:
                page = context.pages[0] if context.pages else context.new_page()
                scope = self._open_editor_with_login(
                    page,
                    blog_id=blog_id.strip(),
                    naver_id=naver_id,
                    password=password,
                )
                password = ""
                self.log("에디터 로그인·열기 완료. 팝업을 닫고 제목을 입력합니다.")
                self._dismiss_draft_popup(page, scope)
                self._fill_title(scope, content.title)
                self.log("제목 입력 완료. 본문·이미지를 입력합니다.")
                if (
                    markdown_path is not None
                    and markdown_path.exists()
                    and property_info is not None
                ):
                    tables = build_property_tables(
                        property_info,
                        enrichment_data,
                        phone_number=phone_number,
                    )
                    self._fill_rich_body(
                        page,
                        scope,
                        markdown=markdown_path.read_text(encoding="utf-8"),
                        tables=tables,
                        thumbnail_path=thumbnail_path,
                        warning_image_path=warning_image_path,
                        body_image_paths=body_image_paths,
                        templates_dir=templates_dir,
                    )
                else:
                    hashtags = " ".join(
                        f"#{tag.lstrip('#').replace(' ', '')}"
                        for tag in content.hashtags
                        if tag.strip()
                    )
                    full_body = f"{content.body.strip()}\n\n{hashtags}".strip()
                    self._fill_body(scope, full_body)
                    if thumbnail_path is not None:
                        self._upload_image(
                            page,
                            scope,
                            thumbnail_path,
                            label="대표 이미지",
                        )
                published_ok = False
                if publish_mode == "publish":
                    self.log("제목과 본문을 입력했습니다. 발행을 시도합니다.")
                    published_ok = self._publish(
                        page,
                        scope,
                        category_name=publish_category,
                        visibility=publish_visibility,
                    )
                    if published_ok:
                        self.log("네이버 블로그 발행 동작을 완료했습니다.")
                    else:
                        self.log(
                            "발행 카테고리를 확인하지 못해 발행 대신 "
                            "임시저장으로 진행합니다."
                        )
                        self._click_draft(page, scope)
                        self.log("네이버 블로그 임시저장 동작을 완료했습니다.")
                else:
                    self.log("제목과 본문을 입력했습니다. 임시저장 버튼을 누릅니다.")
                    self._click_draft(page, scope)
                    self.log("네이버 블로그 임시저장 동작을 완료했습니다.")
                if on_saved is not None:
                    on_saved(published_ok)
                if keep_browser_open:
                    self.log(
                        "임시저장된 글을 확인할 수 있도록 브라우저 창을 "
                        "그대로 유지합니다. 사용자가 창을 닫으면 자동화가 종료됩니다."
                    )
                    while not page.is_closed():
                        try:
                            page.wait_for_timeout(1_000)
                        except error_type:
                            if page.is_closed():
                                break
                            raise
            except NaverBlogError:
                raise
            except error_type as exc:
                if "closed" in str(exc).lower():
                    raise NaverBlogError(
                        "네이버 자동화가 완료되기 전에 브라우저 창이 닫혔습니다. "
                        "다시 실행하고 완료 메시지가 나올 때까지 창을 닫지 말아 주세요."
                    ) from exc
                # 실제 원인을 실행 로그에 남겨 진단할 수 있게 한다(비밀번호·쿠키는
                # 이 예외 메시지에 포함되지 않으므로 노출 위험 없음).
                detail = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
                self.log(
                    "네이버 자동화 중 브라우저 제어 오류 "
                    f"({type(exc).__name__}): {detail[:300]}"
                )
                raise NaverBlogError(
                    "네이버 블로그 임시저장 중 브라우저 제어 오류가 발생했습니다. "
                    "도움말과 팝업을 닫은 뒤 다시 시도해 주세요. "
                    "(자세한 원인은 '⚙ 고급 → 실행 로그'에서 확인할 수 있습니다.)"
                ) from exc
            finally:
                try:
                    context.close()
                except Exception:
                    pass
