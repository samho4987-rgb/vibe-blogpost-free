from __future__ import annotations


def _ensure_venv_python() -> None:
    """Pillow 없는 파이썬으로 앱이 실행되면(IDE·python3 직접 실행 등) 프로젝트 .venv
    파이썬으로 자동 재실행한다. 대표 이미지(썸네일) 글자 렌더링에 Pillow가 필요하기
    때문이다. 번들(exe) 상태이거나 재실행이 불가능하면 조용히 그대로 진행한다."""
    import os
    import sys as _sys

    if getattr(_sys, "frozen", False):
        return  # PyInstaller 등으로 번들된 실행 파일 → Pillow가 함께 포함됨
    if os.environ.get("_BLOG_APP_VENV_REEXEC"):
        return  # 이미 한 번 재실행함(무한 루프 방지)
    try:
        import PIL  # noqa: F401  (Pillow 사용 가능 여부만 확인)

        return
    except Exception:
        pass
    root = os.path.dirname(os.path.abspath(__file__))
    for candidate in (
        os.path.join(root, ".venv", "bin", "python"),
        os.path.join(root, ".venv", "Scripts", "python.exe"),
    ):
        try:
            if not os.path.exists(candidate):
                continue
            # 주의: venv의 python은 프레임워크 python으로의 심볼릭 링크라
            # realpath가 같더라도 site-packages(가상환경)는 다르다. 따라서
            # realpath 비교로 건너뛰면 안 된다(그러면 재실행이 안 됨).
            # 이미 그 경로로 실행 중이면(같은 abspath) 무한 루프 방지 차원에서만 건너뛴다.
            if os.path.abspath(candidate) == os.path.abspath(_sys.executable):
                continue
            os.environ["_BLOG_APP_VENV_REEXEC"] = "1"
            os.execv(
                candidate,
                [candidate, os.path.abspath(__file__), *_sys.argv[1:]],
            )
        except Exception:
            # 재실행 실패 시 현재 파이썬으로 계속 진행한다(썸네일은 글자 없는 대체본).
            os.environ.pop("_BLOG_APP_VENV_REEXEC", None)
            return


_ensure_venv_python()


def _apply_pending_update() -> None:
    """앱 로딩 전에, 받아둔 업데이트(zip)가 있으면 적용하고 새 코드로 재시작한다.

    실행 중 파일 잠금을 피하려면 반드시 본격 로딩 '전'에 적용해야 한다. 소스 설치에만
    적용하고, 번들(exe)이나 오류 시에는 조용히 건너뛴다."""
    import os
    import sys as _sys

    if getattr(_sys, "frozen", False):
        return  # 번들 실행파일은 파일 단위 교체 불가(알림·재설치 방식)
    if os.environ.get("_BLOG_APP_UPDATED"):
        return  # 이번 실행에서 이미 적용·재시작함(무한 루프 방지)
    try:
        from naver_blog_automation.update_check import (
            apply_pending_update,
            has_pending_update,
        )

        if not has_pending_update():
            return
        root = os.path.dirname(os.path.abspath(__file__))
        if apply_pending_update(root):
            # 새 코드로 즉시 재시작해 이번 실행부터 반영되게 한다.
            os.environ["_BLOG_APP_UPDATED"] = "1"
            os.execv(
                _sys.executable,
                [_sys.executable, os.path.abspath(__file__), *_sys.argv[1:]],
            )
    except Exception:
        pass


_apply_pending_update()

import os
import queue
import re
import sys
import threading
import webbrowser
from dataclasses import replace
from pathlib import Path
import csv
import tkinter as tk
from tkinter import messagebox, ttk

from naver_blog_automation.credentials import (
    delete_esiljang_password,
    delete_naver_password,
    delete_property_curl,
    load_property_curl,
    save_esiljang_password,
    save_naver_password,
    load_naver_password,
    save_property_curl,
)
from naver_blog_automation.models import BlogContent, WorkflowResult
from naver_blog_automation.gemini_key import (
    normalize_gemini_api_key,
    validate_gemini_api_key,
)
from naver_blog_automation.embedded_map import EmbeddedMapRenderer
from naver_blog_automation.kakao_map_server import (
    DEFAULT_PORT as KAKAO_MAP_PORT,
    KakaoMapServer,
)
from naver_blog_automation.settings import (
    AppSettings,
    DEFAULT_IMAGE_PROMPT,
    DEFAULT_WRITING_PROMPT,
)
from naver_blog_automation.workflow import BlogAutomationWorkflow


ACTION_LABELS = (
    "1. 매물 조사하기",
    "2. AI로 자동 글쓰기",
    "3. 블로그로 포스팅",
    "4. (선택) 프롬프트 생성",
    "5. (선택) 결과 붙여넣기",
)
FEEDBACK_URL = "https://vibe-feedback.onrender.com/"
GEMINI_API_KEY_URL = "https://aistudio.google.com/app/apikey"
GEMINI_USAGE_URL = "https://aistudio.google.com/rate-limit"
KAKAO_API_KEY_URL = "https://developers.kakao.com/console/app"
BUILDING_API_KEY_URL = "https://www.data.go.kr/data/15134735/openapi.do"
API_KEY_PASTE_LABEL = "클립보드 붙여넣기"
URL_IMAGE_HELP_TEXT = (
    "이미지 주소(URL) 얻는 법\n"
    "1) 웹브라우저에서 원하는 이미지를 마우스 우클릭\n"
    "2) '이미지 주소 복사'(Copy image address)를 선택\n"
    "3) 이 버튼을 눌러 붙여넣기\n\n"
    "· 주소가 .jpg / .png / .webp 등 이미지 파일로 끝나야 합니다.\n"
    "· 로그인해야 보이는 이미지, 미리보기 페이지 주소, 만료되는 주소는 "
    "받을 수 없습니다.\n"
    "· AI로 만든 이미지는 먼저 내려받아 '파일 선택'으로 넣는 편이 안전합니다."
)
ARTICLE_PASTE_LABEL = "붙여넣기"
WRITING_PROMPT_TAB_LABEL = "기본 글 작성 프롬프트"
ENVIRONMENT_TAB_LABEL = "환경설정"
WRITING_PROMPT_SAVE_LABEL = "프롬프트 저장"
WRITING_PROMPT_RESET_LABEL = "기본값 복원"
IMAGE_TAB_LABEL = "이미지"


def resolve_blog_id(login_id: str, blog_id: str) -> str:
    """별도 블로그 ID가 없을 때만 로그인 ID를 글쓰기 주소에 사용한다."""
    return blog_id.strip() or login_id.strip()


class BlogAutomationApp:
    BG = "#f3f6f8"
    NAVY = "#16344c"
    BLUE = "#2b6f8a"
    GOLD = "#d6a546"
    GREEN = "#2f7d61"
    # macOS 물리 키코드(한글 IME여도 불변): V=9, C=8, X=7, A=0
    _MAC_EDIT_KEYCODES = {9: "<<Paste>>", 8: "<<Copy>>", 7: "<<Cut>>", 0: "<<SelectAll>>"}

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.settings = AppSettings.load()
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.last_result: WorkflowResult | None = None
        self.action_buttons: list[ttk.Button] = []
        self.draft_browser_open = False

        self.root.title("네이버 블로그 매물 포스팅 자동화")
        self.root.geometry("1240x840")
        self.root.minsize(1050, 720)
        self.root.configure(bg=self.BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.article_var = tk.StringVar()
        self.naver_login_id_var = tk.StringVar(
            value=self.settings.naver_login_id
        )
        self.naver_password_var = tk.StringVar()
        self.remember_naver_password_var = tk.BooleanVar(
            value=self.settings.remember_naver_password
        )
        self.esiljang_login_id_var = tk.StringVar(
            value=self.settings.esiljang_login_id
        )
        self.esiljang_password_var = tk.StringVar()
        self.remember_esiljang_password_var = tk.BooleanVar(
            value=self.settings.remember_esiljang_password
        )
        self.blog_id_var = tk.StringVar(value=self.settings.blog_id)
        self.phone_var = tk.StringVar(value=self.settings.phone_number)
        # 중개사무소 정보(표시·광고 표기용)
        self.realtor_office_name_var = tk.StringVar(
            value=self.settings.realtor_office_name
        )
        self.realtor_agent_name_var = tk.StringVar(
            value=self.settings.realtor_agent_name
        )
        self.realtor_registration_no_var = tk.StringVar(
            value=self.settings.realtor_registration_no
        )
        self.realtor_office_phone_var = tk.StringVar(
            value=self.settings.realtor_office_phone
        )
        self.realtor_office_address_var = tk.StringVar(
            value=self.settings.realtor_office_address
        )
        self.realtor_footer_var = tk.BooleanVar(
            value=self.settings.realtor_footer_enabled
        )
        # 섹션 아이콘 기능은 정리될 때까지 일시 정지 → 선택 UI를 숨기고 항상
        # '사용 안 함'("")으로 둔다(포스팅 시 섹션 아이콘을 넣지 않음).
        self.icon_package_var = tk.StringVar(value="")
        self.settings.icon_package = ""
        self.remember_curl_var = tk.BooleanVar(value=False)
        self.auto_curl_refresh_var = tk.BooleanVar(
            value=self.settings.auto_curl_refresh
        )
        self.publish_mode_var = tk.StringVar(
            value=self.settings.publish_mode or "draft"
        )
        self.publish_category_var = tk.StringVar(
            value=self.settings.publish_category
        )
        self.publish_visibility_var = tk.StringVar(
            value=self.settings.publish_visibility or "public"
        )
        self.api_key_var = tk.StringVar(value=self.settings.gemini_api_key)
        self.ai_engine_var = tk.StringVar(
            value=self.settings.ai_engine or "gemini"
        )
        self.anthropic_key_var = tk.StringVar(
            value=self.settings.anthropic_api_key
        )
        self.ai_model_info_var = tk.StringVar(value=self._ai_model_info_text())
        # 외부 AI로 만든 이미지 첨부(선택). 썸네일 1 + 본문 3.
        self.selected_thumbnail_path: str | None = None
        self.selected_body_image_paths: list[str | None] = [None, None, None]
        self.thumbnail_pick_var = tk.StringVar(value="선택 안 함 (없으면 로컬 이미지 사용)")
        self.body_image_pick_vars = [
            tk.StringVar(value="선택 안 함") for _ in range(3)
        ]
        self.kakao_key_var = tk.StringVar(
            value=self.settings.kakao_rest_api_key
        )
        self.kakao_js_key_var = tk.StringVar(
            value=self.settings.kakao_javascript_key
        )
        self.public_data_key_var = tk.StringVar(
            value=self.settings.data_go_kr_service_key
        )
        self.enrichment_key_status_var = tk.StringVar(
            value=(
                "저장된 Kakao·공공데이터 API 키가 있습니다."
                if (
                    self.settings.kakao_rest_api_key
                    or self.settings.kakao_javascript_key
                    or self.settings.data_go_kr_service_key
                )
                else "선택 기능입니다. 키가 없어도 기본 콘텐츠 생성은 가능합니다."
            )
        )
        self.make_image_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="준비됨 · 샘플 미리보기부터 실행해 보세요.")
        self.api_key_status_var = tk.StringVar(
            value=(
                "저장된 API Key가 있습니다 · 필요하면 다시 검증하세요."
                if self.settings.gemini_api_key
                else "API Key를 입력한 뒤 검증 및 저장해 주세요."
            )
        )
        self.title_var = tk.StringVar()
        self.tags_var = tk.StringVar()
        self.map_title_var = tk.StringVar(value="매물 데이터를 먼저 불러와 주세요.")
        self.map_address_var = tk.StringVar(value="")
        self.map_status_var = tk.StringVar(
            value="Kakao JavaScript 키와 좌표가 있으면 동적 지도를 열 수 있습니다."
        )
        self.map_server: KakaoMapServer | None = None
        self.map_renderer: EmbeddedMapRenderer | None = None
        self.map_photo = None
        self.image_photo = None
        self.image_status_var = tk.StringVar(
            value=(
                "대표 이미지는 blog자료 '이미지 첨부'에서 파일/URL로 넣거나, "
                "이 탭의 '로컬 이미지 생성'으로 만들 수 있습니다."
            )
        )
        self.map_render_size = (0, 0)
        self.map_resize_after_id: str | None = None
        self.current_dynamic_map_url = ""
        self.current_map_url = ""
        self.current_roadview_url = ""
        self.current_latitude = ""
        self.current_longitude = ""
        self.step_labels: list[ttk.Label] = []

        self._configure_style()
        self._build_ui()
        self._configure_copy_shortcuts()
        self.root.after(120, self._drain_events)
        self._start_update_check()

    def _start_update_check(self) -> None:
        """앱 시작 시 백그라운드로 새 버전을 확인하고, 있으면 zip을 받아둔다(실패무해).

        version.py의 GITHUB_REPO가 비어 있으면 아무 것도 하지 않는다. 다운로드까지
        마치면 '재시작하면 적용' 안내를 띄우고, 실제 교체는 다음 실행의 로딩 전에 한다."""
        try:
            from naver_blog_automation.version import APP_VERSION, GITHUB_REPO
        except Exception:
            return
        if not (GITHUB_REPO or "").strip():
            return

        def worker() -> None:
            try:
                from naver_blog_automation.update_check import (
                    check_for_update,
                    download_update,
                )

                info = check_for_update(APP_VERSION, GITHUB_REPO)
                if not info:
                    return
                if info.get("download_url"):
                    # 번들(exe)은 파일 교체가 안 되므로 다운로드 대신 안내만 한다.
                    import sys as _sys

                    if not getattr(_sys, "frozen", False) and download_update(
                        info["download_url"]
                    ):
                        info["_downloaded"] = True
                self.events.put(("update_available", info))
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _notify_update(self, info: dict) -> None:
        """새 버전 안내를 한 번만 표시한다. 자동 다운로드가 끝났으면 재시작을 제안한다."""
        if getattr(self, "_update_notified", False):
            return
        self._update_notified = True
        version = str(info.get("version", "")).strip()
        notes = str(info.get("notes", "")).strip()
        html_url = str(info.get("html_url", "")).strip()
        if info.get("_downloaded"):
            self.status_var.set(
                f"새 버전 {version} 다운로드 완료 · 재시작하면 자동 적용됩니다."
            )
            message = f"새 버전 {version}을(를) 받았습니다."
            if notes:
                message += f"\n\n{notes[:400]}"
            message += "\n\n지금 재시작하여 적용할까요?"
            if messagebox.askyesno("업데이트 준비 완료", message):
                self._restart_app()
        else:
            # 다운로드 자산이 없거나 exe라 자동 교체 불가 → 릴리스 페이지 안내.
            self.status_var.set(f"새 버전 {version} 이(가) 있습니다.")
            message = f"새 버전 {version} 이(가) 나왔습니다."
            if notes:
                message += f"\n\n{notes[:400]}"
            if html_url:
                message += "\n\n다운로드 페이지를 여시겠습니까?"
                if messagebox.askyesno("업데이트 알림", message):
                    webbrowser.open(html_url)
            else:
                messagebox.showinfo("업데이트 알림", message)

    def _restart_app(self) -> None:
        """앱을 재시작한다. 다음 실행의 로딩 전에 받아둔 업데이트가 자동 적용된다."""
        import os
        import sys

        try:
            self.root.destroy()
        except Exception:
            pass
        try:
            os.execv(
                sys.executable,
                [sys.executable, os.path.abspath(__file__), *sys.argv[1:]],
            )
        except Exception:
            # 재시작 실패 시 사용자가 직접 껐다 켜도록 안내(다음 실행에 적용됨).
            pass

    def _configure_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("App.TFrame", background=self.BG)
        style.configure(
            "Header.TLabel",
            background=self.NAVY,
            foreground="white",
            font=("Apple SD Gothic Neo", 24, "bold"),
        )
        style.configure(
            "HeaderSub.TLabel",
            background=self.NAVY,
            foreground="#dce8ef",
            font=("Apple SD Gothic Neo", 11),
        )
        style.configure(
            "Section.TLabelframe",
            background="white",
            bordercolor="#d8e0e5",
            relief="solid",
        )
        style.configure(
            "Section.TLabelframe.Label",
            background="white",
            foreground=self.NAVY,
            font=("Apple SD Gothic Neo", 12, "bold"),
        )
        style.configure("White.TFrame", background="white")
        style.configure(
            "Primary.TButton",
            background=self.BLUE,
            foreground="white",
            padding=(14, 10),
            font=("Apple SD Gothic Neo", 11, "bold"),
        )
        style.map("Primary.TButton", background=[("active", "#225a70")])
        style.configure(
            "Safe.TButton",
            background=self.GREEN,
            foreground="white",
            padding=(14, 10),
            font=("Apple SD Gothic Neo", 11, "bold"),
        )
        style.map("Safe.TButton", background=[("active", "#28684f")])
        # 현재 진행 중인 단계 버튼 색상(황색). 작업 중에는 버튼이 비활성(disabled)이라
        # disabled 상태에서도 색이 유지되도록 map에 명시한다.
        style.configure(
            "StepBusy.TButton",
            background="#e0a12e",
            foreground="white",
            padding=(14, 10),
            font=("Apple SD Gothic Neo", 11, "bold"),
        )
        style.map(
            "StepBusy.TButton",
            background=[("disabled", "#e0a12e"), ("active", "#c88f27")],
            foreground=[("disabled", "white")],
        )
        # 수행 완료된 단계 버튼 색상(✓ 표시와 함께 '실행됨'을 나타냄, 초록)
        style.configure(
            "StepDone.TButton",
            background="#3f9068",
            foreground="white",
            padding=(14, 10),
            font=("Apple SD Gothic Neo", 11, "bold"),
        )
        style.map(
            "StepDone.TButton",
            background=[("disabled", "#5f9e80"), ("active", "#357a58")],
            foreground=[("disabled", "white")],
        )
        style.configure(
            "Secondary.TButton",
            background="#e8eef2",
            foreground=self.NAVY,
            padding=(12, 9),
        )
        style.configure(
            "Compact.TButton",
            background="#e8eef2",
            foreground=self.NAVY,
            padding=(8, 3),
        )
        style.configure(
            "Status.TLabel",
            background="#eaf1f5",
            foreground=self.NAVY,
            padding=(12, 8),
            font=("Apple SD Gothic Neo", 10),
        )

    def _build_ui(self) -> None:
        header = tk.Frame(self.root, bg=self.NAVY, height=92)
        header.pack(fill="x")
        header.pack_propagate(False)
        # 우측 상단: 기능개선·피드백 페이지 링크
        feedback_link = tk.Label(
            header,
            text="💬 기능개선·피드백",
            bg=self.NAVY,
            fg="#DCE4EC",
            cursor="hand2",
            font=("Apple SD Gothic Neo", 11, "underline"),
        )
        feedback_link.pack(side="right", anchor="n", padx=30, pady=(22, 0))
        feedback_link.bind("<Button-1>", lambda _event: self._open_feedback())
        ttk.Label(
            header,
            text="네이버 블로그 매물 포스팅 자동화",
            style="Header.TLabel",
        ).pack(anchor="w", padx=30, pady=(18, 0))
        ttk.Label(
            header,
            text="매물정보 → 주변 조사 → 글 작성 → 썸네일 → 네이버 임시저장",
            style="HeaderSub.TLabel",
        ).pack(anchor="w", padx=32, pady=(2, 0))

        main = ttk.Frame(self.root, style="App.TFrame", padding=18)
        main.pack(fill="both", expand=True)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(
            main,
            text="실행 설정",
            style="Section.TLabelframe",
            padding=15,
        )
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 14))
        left.configure(width=355)
        left.grid_propagate(False)
        left.columnconfigure(0, weight=1)

        self.article_entry = self._labeled_entry(
            left,
            "매물번호",
            self.article_var,
            0,
            paste_command=self._paste_article_no,
        )
        # OS 기본 붙여넣기(가상 이벤트)를 매물번호 정규화 붙여넣기로 연결(IME·키레이아웃 영향 회피)
        self.article_entry.bind("<<Paste>>", self._paste_article_no)
        self.article_entry.bind("<Button-2>", self._show_article_menu)
        self.article_entry.bind("<Button-3>", self._show_article_menu)
        self.article_menu = tk.Menu(self.root, tearoff=False)
        self.article_menu.add_command(
            label="매물번호 붙여넣기",
            command=self._paste_article_no,
        )
        self.article_menu.add_command(
            label="전체 선택",
            command=lambda: self.article_entry.selection_range(0, "end"),
        )
        self.article_menu.add_command(
            label="지우기",
            command=lambda: self.article_var.set(""),
        )
        option_frame = ttk.Frame(left, style="White.TFrame")
        option_frame.grid(row=2, column=0, sticky="ew", pady=(12, 10))
        ttk.Label(
            option_frame,
            text="이미지는 외부 API 없이 이 컴퓨터에서 생성됩니다.",
            background="white",
            foreground="#6b7780",
            wraplength=310,
        ).pack(side="left")

        # 좌측 단계 버튼(주 흐름 1~3, 선택 4~5).
        # 상태를 색으로 구분: 안 함(기본) → 진행 중(황색) → 완료(초록 ✓).
        # 주 흐름: 1.매물조사 → 2.AI 자동 글쓰기 → 3.블로그 포스팅
        # 선택(외부 AI 활용): 4.프롬프트 생성 → 5.결과 붙여넣기
        self.step_handlers = [
            self._run_sample,          # 1. 매물 조사하기
            self._run_real,            # 2. AI로 자동 글쓰기
            self._save_draft,          # 3. 블로그로 포스팅
            self._generate_copy_prompts,  # 4. (선택) 프롬프트 생성
            self._goto_result_paste,   # 5. (선택) 결과 붙여넣기
        ]
        self.step_base_styles = [
            "Primary.TButton",
            "Primary.TButton",
            "Primary.TButton",
            "Secondary.TButton",
            "Secondary.TButton",
        ]
        # 백그라운드 작업(진행 중 표시가 필요한) 단계. 나머지는 즉시 완료로 처리한다.
        self._ASYNC_STEPS = {0, 1, 2}
        self._pending_step = None
        self.step_buttons = []
        for index, style_name in enumerate(self.step_base_styles):
            button = self._add_button(
                left,
                ACTION_LABELS[index],
                lambda i=index: self._run_step(i),
                style_name,
                row=3 + index,
            )
            self.step_buttons.append(button)
        self.draft_button = self.step_buttons[2]  # 3. 블로그로 포스팅

        # 작업 진행 표시줄(조사·AI글쓰기·포스팅 동안 애니메이션으로 진행 중임을 알림)
        self.progress_bar = ttk.Progressbar(left, mode="indeterminate")
        self.progress_bar.grid(row=3 + len(self.step_buttons), column=0, sticky="ew", pady=(12, 0))
        self.progress_bar.grid_remove()

        right = ttk.LabelFrame(
            main,
            text="결과 검토",
            style="Section.TLabelframe",
            padding=10,
        )
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        notebook = ttk.Notebook(right)
        notebook.grid(row=0, column=0, sticky="nsew")
        self.notebook = notebook

        # 초보자 화면을 단순화: 핵심 탭만 보이고, 고급/참고 탭은 '⚙ 고급' 안의 내부 탭으로 접는다.
        advanced_tab = ttk.Frame(notebook, style="White.TFrame", padding=6)
        advanced_notebook = ttk.Notebook(advanced_tab)
        advanced_notebook.pack(fill="both", expand=True)
        self.advanced_tab = advanced_tab
        self.advanced_notebook = advanced_notebook

        # 핵심(항상 보이는) 탭
        my_listings_tab = ttk.Frame(notebook, style="White.TFrame", padding=12)
        research_tab = ttk.Frame(notebook, style="White.TFrame", padding=12)
        copyprompt_tab = ttk.Frame(notebook, style="White.TFrame", padding=12)
        preview_tab = ttk.Frame(notebook, style="White.TFrame", padding=12)
        image_tab = ttk.Frame(notebook, style="White.TFrame", padding=12)
        environment_tab = ttk.Frame(notebook, style="White.TFrame", padding=12)
        # 고급(⚙ 고급 안으로 접히는) 탭
        map_tab = ttk.Frame(advanced_notebook, style="White.TFrame", padding=12)
        settings_tab = ttk.Frame(advanced_notebook, style="White.TFrame", padding=12)
        prompt_tab = ttk.Frame(advanced_notebook, style="White.TFrame", padding=12)
        log_tab = ttk.Frame(advanced_notebook, style="White.TFrame", padding=12)

        self.map_tab = map_tab
        self.preview_tab = preview_tab
        self.research_tab = research_tab
        self.copyprompt_tab = copyprompt_tab

        # 워크플로우 순서대로: 내 매물 → 조사 메모 → 프롬프트(복사) → blog자료
        notebook.add(my_listings_tab, text="내 매물")
        notebook.add(research_tab, text="매물 조사 메모")
        notebook.add(copyprompt_tab, text="프롬프트(복사)")
        notebook.add(preview_tab, text="blog자료")
        notebook.add(image_tab, text=IMAGE_TAB_LABEL)
        notebook.add(environment_tab, text=ENVIRONMENT_TAB_LABEL)
        notebook.add(advanced_tab, text="⚙ 고급")
        advanced_notebook.add(map_tab, text="지도·로드뷰")
        advanced_notebook.add(settings_tab, text="문제 해결·고급 설정")
        advanced_notebook.add(prompt_tab, text=WRITING_PROMPT_TAB_LABEL)
        advanced_notebook.add(log_tab, text="실행 로그")

        preview_tab.columnconfigure(0, weight=1)
        preview_tab.rowconfigure(4, weight=1)
        # 상단 바로가기: 붙여넣은 글을 바로 포스팅
        preview_header = ttk.Frame(preview_tab, style="White.TFrame")
        preview_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        preview_header.columnconfigure(0, weight=1)
        ttk.Label(
            preview_header,
            text="제목·본문·이미지를 확인한 뒤 오른쪽 단추로 바로 포스팅할 수 있어요.",
            background="white",
            foreground="#6b7780",
        ).grid(row=0, column=0, sticky="w")
        self.preview_post_button = ttk.Button(
            preview_header,
            text="블로그로 포스팅",
            command=self._save_draft,
            style="Primary.TButton",
        )
        self.preview_post_button.grid(row=0, column=1, sticky="e")
        self.action_buttons.append(self.preview_post_button)
        # 본문 섹션 아이콘 묶음 선택 UI는 정리될 때까지 숨긴다(기능 일시 정지).
        # 숨긴 동안에는 섹션 아이콘을 넣지 않도록 icon_package를 비워 둔다.
        ttk.Label(
            preview_tab,
            text="제목",
            background="white",
            foreground=self.NAVY,
            font=("Apple SD Gothic Neo", 10, "bold"),
        ).grid(row=1, column=0, sticky="w")
        ttk.Entry(preview_tab, textvariable=self.title_var).grid(
            row=2, column=0, sticky="ew", pady=(4, 12)
        )
        ttk.Label(
            preview_tab,
            text="본문  (붙여넣기가 안 되면 마우스 우클릭 → 붙여넣기)",
            background="white",
            foreground=self.NAVY,
            font=("Apple SD Gothic Neo", 10, "bold"),
        ).grid(row=3, column=0, sticky="w")
        self.body_text = self._text_area(preview_tab)
        self.body_text.grid(row=4, column=0, sticky="nsew", pady=(4, 10))
        ttk.Label(
            preview_tab,
            text="해시태그 (쉼표로 구분)",
            background="white",
            foreground=self.NAVY,
            font=("Apple SD Gothic Neo", 10, "bold"),
        ).grid(row=5, column=0, sticky="w")
        ttk.Entry(preview_tab, textvariable=self.tags_var).grid(
            row=6, column=0, sticky="ew", pady=(4, 0)
        )

        image_attach = ttk.LabelFrame(
            preview_tab,
            text="이미지 첨부 (외부 AI로 만든 이미지를 넣으세요 · 선택)",
            style="Section.TLabelframe",
            padding=8,
        )
        image_attach.grid(row=7, column=0, sticky="ew", pady=(12, 0))
        image_attach.columnconfigure(1, weight=1)
        self._image_pick_row(
            image_attach, 0, "대표 이미지(썸네일)",
            self.thumbnail_pick_var, self._pick_thumbnail_image,
            self._attach_thumbnail_url,
        )
        for index in range(3):
            self._image_pick_row(
                image_attach, index + 1, f"본문 이미지 {index + 1}",
                self.body_image_pick_vars[index],
                lambda i=index: self._pick_body_image(i),
                lambda i=index: self._attach_body_image_url(i),
            )
        ttk.Label(
            image_attach,
            text=(
                "파일 선택: 컴퓨터에 저장한 이미지를 넣습니다.\n"
                "URL로 첨부: .jpg/.png 등으로 바로 열리는 공개 이미지 주소만 됩니다"
                "(로그인·만료 주소는 실패). AI 이미지는 먼저 다운로드하는 편이 안전합니다."
            ),
            background="white",
            foreground="#6b7780",
            wraplength=360,
            justify="left",
        ).grid(row=4, column=0, columnspan=4, sticky="w", pady=(8, 0))

        research_tab.columnconfigure(0, weight=1)
        research_tab.rowconfigure(2, weight=1)
        ttk.Label(
            research_tab,
            text=(
                "아래 조사 내용을 확인하고, 사실과 다르거나 빠진 부분을 자유롭게 수정·보완하세요.\n"
                "여기서 다듬은 내용이 '2. 프롬프트 생성' 시 그대로 프롬프트에 반영됩니다."
            ),
            background="white",
            foreground="#6b7780",
            wraplength=780,
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        research_actions = ttk.Frame(research_tab, style="White.TFrame")
        research_actions.grid(row=1, column=0, sticky="e", pady=(0, 8))
        self.research_map_button = ttk.Button(
            research_actions,
            text="프로그램에서 지도·로드뷰 보기",
            command=self._show_map_tab,
            style="Secondary.TButton",
            state="disabled",
        )
        self.research_map_button.pack(side="left")
        self.research_text = self._text_area(research_tab)
        self.research_text.grid(row=2, column=0, sticky="nsew")

        image_tab.columnconfigure(0, weight=1)
        image_tab.columnconfigure(1, weight=1)
        image_tab.rowconfigure(1, weight=1)
        ttk.Label(
            image_tab,
            text=(
                "색상과 표시 순서를 자유롭게 수정할 수 있습니다. "
                "이미지는 Google/Gemini 호출 없이 로컬에서 1:1 PNG로 생성됩니다."
            ),
            background="white",
            foreground="#526574",
            wraplength=760,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.image_prompt_text = self._text_area(image_tab)
        self.image_prompt_text.insert("1.0", self.settings.image_prompt)
        self.image_prompt_text.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=(0, 8),
        )
        image_preview_frame = ttk.Frame(image_tab, style="White.TFrame")
        image_preview_frame.grid(row=1, column=1, sticky="nsew")
        image_preview_frame.columnconfigure(0, weight=1)
        image_preview_frame.rowconfigure(0, weight=1)
        self.image_preview_label = tk.Label(
            image_preview_frame,
            text="생성된 1:1 대표 이미지가 여기에 표시됩니다.",
            bg="#eef3f6",
            fg="#526574",
            justify="center",
            relief="solid",
            borderwidth=1,
        )
        self.image_preview_label.grid(row=0, column=0, sticky="nsew")
        ttk.Label(
            image_preview_frame,
            textvariable=self.image_status_var,
            background="white",
            foreground="#526574",
            wraplength=340,
        ).grid(row=1, column=0, sticky="ew", pady=(8, 0))
        image_buttons = ttk.Frame(image_tab, style="White.TFrame")
        image_buttons.grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="e",
            pady=(10, 0),
        )
        self.image_prompt_reset_button = ttk.Button(
            image_buttons,
            text="이미지 프롬프트 기본값 복원",
            command=self._reset_image_prompt,
            style="Secondary.TButton",
        )
        self.image_prompt_reset_button.pack(side="left")
        self.image_prompt_save_button = ttk.Button(
            image_buttons,
            text="이미지 프롬프트 저장",
            command=self._save_image_prompt,
            style="Primary.TButton",
        )
        self.image_prompt_save_button.pack(side="left", padx=(8, 0))
        # 무료 로컬(Pillow) 대표 이미지 생성 — 외부 AI 없이 쓰고 싶을 때의 대체 경로
        self.image_button = ttk.Button(
            image_buttons,
            text="로컬 이미지 생성(선택)",
            command=self._generate_image,
            style="Secondary.TButton",
        )
        self.image_button.pack(side="left", padx=(8, 0))
        self.action_buttons.extend(
            [
                self.image_prompt_reset_button,
                self.image_prompt_save_button,
                self.image_button,
            ]
        )

        map_tab.columnconfigure(0, weight=1)
        map_tab.rowconfigure(2, weight=2)
        map_tab.rowconfigure(4, weight=2)
        map_actions = ttk.Frame(map_tab, style="White.TFrame")
        map_actions.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.map_view_button = ttk.Button(
            map_actions,
            text="지도 보기",
            command=self._show_embedded_map,
            style="Primary.TButton",
            state="disabled",
        )
        self.map_view_button.pack(side="left")
        self.roadview_view_button = ttk.Button(
            map_actions,
            text="로드뷰 보기",
            command=self._show_embedded_roadview,
            style="Secondary.TButton",
            state="disabled",
        )
        self.roadview_view_button.pack(side="left", padx=(8, 0))
        self.map_zoom_in_button = ttk.Button(
            map_actions,
            text="＋",
            command=lambda: self._zoom_embedded_map(-1),
            style="Secondary.TButton",
            state="disabled",
        )
        self.map_zoom_in_button.pack(side="left", padx=(8, 0))
        self.map_zoom_out_button = ttk.Button(
            map_actions,
            text="－",
            command=lambda: self._zoom_embedded_map(1),
            style="Secondary.TButton",
            state="disabled",
        )
        self.map_zoom_out_button.pack(side="left", padx=(4, 0))
        self.map_refresh_button = ttk.Button(
            map_actions,
            text="새로고침",
            command=self._refresh_map,
            style="Secondary.TButton",
            state="disabled",
        )
        self.map_refresh_button.pack(side="left", padx=(8, 0))
        self.open_map_external_button = ttk.Button(
            map_actions,
            text="공식 카카오맵 열기",
            command=self._open_current_map_external,
            style="Secondary.TButton",
            state="disabled",
        )
        self.open_map_external_button.pack(side="right")
        self.open_roadview_external_button = ttk.Button(
            map_actions,
            text="공식 로드뷰 열기",
            command=self._open_current_roadview_external,
            style="Secondary.TButton",
            state="disabled",
        )
        self.open_roadview_external_button.pack(side="right", padx=(0, 8))

        map_heading = ttk.Frame(map_tab, style="White.TFrame")
        map_heading.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        map_heading.columnconfigure(0, weight=1)
        ttk.Label(
            map_heading,
            textvariable=self.map_title_var,
            background="white",
            foreground=self.NAVY,
            font=("Apple SD Gothic Neo", 13, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            map_heading,
            textvariable=self.map_address_var,
            background="white",
            foreground="#526574",
            wraplength=760,
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))

        self.map_preview_label = tk.Label(
            map_tab,
            text=(
                "매물번호를 입력한 뒤 '1. 매물 조사하기'를 실행하면\n"
                "이곳에 동적 지도와 로드뷰가 표시됩니다.\n\n"
                "마우스로 지도를 끌거나 휠과 ＋/－ 버튼으로 확대·축소할 수 있습니다."
            ),
            bg="#eef3f6",
            fg="#526574",
            font=("Apple SD Gothic Neo", 12),
            justify="center",
            relief="solid",
            borderwidth=1,
            height=10,
        )
        self.map_preview_label.grid(row=2, column=0, sticky="nsew")
        self.map_preview_label.bind(
            "<Configure>",
            self._schedule_embedded_map_resize,
        )
        self.map_preview_label.bind(
            "<ButtonPress-1>",
            lambda event: self._embedded_map_pointer("down", event),
        )
        self.map_preview_label.bind(
            "<B1-Motion>",
            lambda event: self._embedded_map_pointer("move", event),
        )
        self.map_preview_label.bind(
            "<ButtonRelease-1>",
            lambda event: self._embedded_map_pointer("up", event),
        )
        self.map_preview_label.bind("<MouseWheel>", self._embedded_map_wheel)
        self.map_preview_label.bind("<Button-4>", self._embedded_map_wheel)
        self.map_preview_label.bind("<Button-5>", self._embedded_map_wheel)
        ttk.Label(
            map_tab,
            textvariable=self.map_status_var,
            background="white",
            foreground="#526574",
            wraplength=760,
        ).grid(row=3, column=0, sticky="ew", pady=(7, 8))

        facility_frame = ttk.LabelFrame(
            map_tab,
            text="주변 시설 · 카카오 API 직선거리",
            style="Section.TLabelframe",
            padding=6,
        )
        facility_frame.grid(row=4, column=0, sticky="nsew")
        facility_frame.columnconfigure(0, weight=1)
        facility_frame.rowconfigure(0, weight=1)
        self.facility_tree = ttk.Treeview(
            facility_frame,
            columns=("category", "name", "distance", "address"),
            show="headings",
            height=7,
        )
        self.facility_tree.heading("category", text="구분")
        self.facility_tree.heading("name", text="시설명")
        self.facility_tree.heading("distance", text="직선거리")
        self.facility_tree.heading("address", text="주소")
        self.facility_tree.column("category", width=85, anchor="center")
        self.facility_tree.column("name", width=180)
        self.facility_tree.column("distance", width=80, anchor="e")
        self.facility_tree.column("address", width=260)
        self.facility_tree.grid(row=0, column=0, sticky="nsew")
        facility_scroll = ttk.Scrollbar(
            facility_frame,
            orient="vertical",
            command=self.facility_tree.yview,
        )
        facility_scroll.grid(row=0, column=1, sticky="ns")
        self.facility_tree.configure(yscrollcommand=facility_scroll.set)

        settings_tab.columnconfigure(0, weight=1)
        settings_tab.rowconfigure(1, weight=1)
        ttk.Label(
            settings_tab,
            text=(
                "네이버 매물정보 요청이 403·429로 계속 차단될 때 사용합니다. "
                "개발자 도구 Network에서 해당 매물 API 요청을 Copy as cURL로 "
                "복사해 아래에 붙여 넣으세요. 매물번호는 조회할 때마다 자동으로 "
                "바뀌므로, 어느 매물의 cURL이든 한 번만 붙여 넣으면 됩니다."
            ),
            background="white",
            foreground="#526574",
            wraplength=700,
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.curl_text = self._text_area(settings_tab, height=9)
        self.curl_text.grid(row=1, column=0, sticky="nsew")
        # 저장해 둔 cURL이 있으면 시작할 때 불러와 채운다.
        saved_curl = ""
        try:
            saved_curl = load_property_curl()
        except Exception:
            saved_curl = ""
        if saved_curl:
            self.curl_text.insert("1.0", saved_curl)
            self.remember_curl_var.set(True)
        ttk.Checkbutton(
            settings_tab,
            text="인증이 만료·차단되면 창 없이 자동으로 갱신(권장)",
            variable=self.auto_curl_refresh_var,
        ).grid(row=2, column=0, sticky="w", pady=(8, 0))
        curl_button_row = ttk.Frame(settings_tab, style="White.TFrame")
        curl_button_row.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Checkbutton(
            curl_button_row,
            text="다음 실행에도 사용하도록 안전하게 저장(키체인)",
            variable=self.remember_curl_var,
        ).pack(side="left")
        ttk.Button(
            curl_button_row,
            text="cURL 저장",
            command=self._save_curl,
        ).pack(side="left", padx=(10, 0))
        ttk.Button(
            curl_button_row,
            text="지우기",
            command=self._clear_curl,
        ).pack(side="left", padx=(6, 0))
        ttk.Label(
            settings_tab,
            text=(
                "저장하면 토큰·쿠키가 macOS 키체인(암호화)에 보관되어 다음 실행에도 "
                "쓰입니다. 위 자동 갱신을 켜두면 토큰이 만료(약 3시간)되어 조회가 막힐 때 "
                "창 없이 새 토큰·쿠키를 자동으로 발급해 이어서 수집합니다. 자동 갱신이 "
                "차단되는 경우에만 cURL을 직접 복사해 붙여 넣어 주세요."
            ),
            background="white",
            foreground="#7a5b20",
            wraplength=760,
        ).grid(row=4, column=0, sticky="w", pady=(8, 0))

        prompt_tab.columnconfigure(0, weight=1)
        prompt_tab.rowconfigure(4, weight=1)
        ttk.Label(
            prompt_tab,
            text=(
                "'(선택) AI로 자동 글쓰기'에 사용하는 기본 프롬프트입니다. 필요에 맞게 수정한 뒤 "
                "'프롬프트 저장'을 누르세요. 변경 내용은 이 컴퓨터에만 저장됩니다."
            ),
            background="white",
            foreground="#526574",
            wraplength=760,
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Label(
            prompt_tab,
            text="글쓰기 말투·형식 지침",
            background="white",
            foreground=self.NAVY,
            font=("Apple SD Gothic Neo", 10, "bold"),
        ).grid(row=1, column=0, sticky="w", pady=(0, 4))
        self.tone_text = self._text_area(prompt_tab, height=4)
        self.tone_text.insert("1.0", self.settings.tone_guide)
        self.tone_text.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(
            prompt_tab,
            text="상세 글 작성 프롬프트",
            background="white",
            foreground=self.NAVY,
            font=("Apple SD Gothic Neo", 10, "bold"),
        ).grid(row=3, column=0, sticky="w", pady=(0, 4))
        self.writing_prompt_text = self._text_area(prompt_tab)
        self.writing_prompt_text.insert("1.0", self.settings.writing_prompt)
        self.writing_prompt_text.grid(row=4, column=0, sticky="nsew")
        prompt_buttons = ttk.Frame(prompt_tab, style="White.TFrame")
        prompt_buttons.grid(row=5, column=0, sticky="e", pady=(10, 0))
        self.prompt_reset_button = ttk.Button(
            prompt_buttons,
            text=WRITING_PROMPT_RESET_LABEL,
            command=self._reset_writing_prompt,
            style="Secondary.TButton",
        )
        self.prompt_reset_button.pack(side="left")
        self.prompt_save_button = ttk.Button(
            prompt_buttons,
            text=WRITING_PROMPT_SAVE_LABEL,
            command=self._save_writing_prompt,
            style="Primary.TButton",
        )
        self.prompt_save_button.pack(side="left", padx=(8, 0))
        self.action_buttons.extend(
            [self.prompt_reset_button, self.prompt_save_button]
        )

        self._build_my_listings_tab(my_listings_tab)
        self._build_copyprompt_tab(copyprompt_tab)
        self._build_environment_tab(environment_tab)

        log_tab.columnconfigure(0, weight=1)
        log_tab.rowconfigure(1, weight=1)
        steps_frame = ttk.Frame(log_tab, style="White.TFrame")
        steps_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        steps = [
            "① 매물 자료 수집",
            "② AI 글쓰기(선택)",
            "③ 대표 이미지(선택)",
            "④ 블로그 포스팅",
        ]
        for index, text in enumerate(steps):
            steps_frame.columnconfigure(index, weight=1)
            label = ttk.Label(
                steps_frame,
                text=text,
                background="white",
                foreground="#75838d",
                padding=(4, 2),
            )
            label.grid(row=0, column=index, sticky="w")
            self.step_labels.append(label)
        self.log_text = self._text_area(log_tab)
        self.log_text.grid(row=1, column=0, sticky="nsew")

        bottom = ttk.Frame(self.root, style="App.TFrame", padding=(18, 0, 18, 14))
        bottom.pack(fill="x")
        ttk.Label(bottom, textvariable=self.status_var, style="Status.TLabel").pack(
            side="left", fill="x", expand=True
        )

    # ── 내 매물(CSV) 목록 ────────────────────────────────────
    def _build_my_listings_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)
        ttk.Label(
            parent,
            text=(
                "내 매물 CSV가 있는 폴더를 지정하면 목록이 표시됩니다. "
                "매물을 클릭하면 왼쪽 '매물번호' 칸에 자동으로 채워집니다."
            ),
            background="white",
            foreground="#526574",
            wraplength=680,
        ).grid(row=0, column=0, sticky="w")

        bar = ttk.Frame(parent, style="White.TFrame")
        bar.grid(row=1, column=0, sticky="ew", pady=(8, 8))
        bar.columnconfigure(1, weight=1)
        ttk.Button(
            bar, text="폴더 지정", command=self._choose_listings_dir
        ).grid(row=0, column=0)
        self.listings_dir_label = ttk.Label(
            bar,
            text=self.settings.my_listings_dir or "(폴더 미지정)",
            background="white",
            foreground="#6b7780",
        )
        self.listings_dir_label.grid(row=0, column=1, sticky="w", padx=(10, 6))
        ttk.Button(
            bar, text="새로고침", command=self._refresh_my_listings
        ).grid(row=0, column=2)

        table_wrap = ttk.Frame(parent, style="White.TFrame")
        table_wrap.grid(row=2, column=0, sticky="nsew")
        table_wrap.rowconfigure(0, weight=1)
        table_wrap.columnconfigure(0, weight=1)
        columns = ("article_no", "name", "deal", "desc")
        tree = ttk.Treeview(
            table_wrap, columns=columns, show="headings", selectmode="browse"
        )
        for col, head, width in (
            ("article_no", "매물번호", 110),
            ("name", "매물명", 180),
            ("deal", "거래/가격", 150),
            ("desc", "간략설명", 320),
        ):
            tree.heading(col, text=head)
            tree.column(col, width=width, anchor="w")
        tree.grid(row=0, column=0, sticky="nsew")
        ysb = ttk.Scrollbar(table_wrap, orient="vertical", command=tree.yview)
        ysb.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=ysb.set)
        tree.bind("<<TreeviewSelect>>", self._on_listing_selected)
        tree.bind("<Double-1>", self._on_listing_activate)
        self.listings_tree = tree

        self.listings_count_label = ttk.Label(
            parent, text="", background="white", foreground="#6b7780"
        )
        self.listings_count_label.grid(row=3, column=0, sticky="w", pady=(6, 0))
        self._refresh_my_listings()

    def _choose_listings_dir(self) -> None:
        from tkinter import filedialog

        folder = filedialog.askdirectory(
            title="내 매물 CSV 폴더 선택",
            initialdir=self.settings.my_listings_dir or None,
        )
        if not folder:
            return
        self.settings.my_listings_dir = folder
        try:
            self.settings.save_user_preferences()
        except Exception:
            pass
        self.listings_dir_label.configure(text=folder)
        self._refresh_my_listings()

    def _refresh_my_listings(self) -> None:
        tree = getattr(self, "listings_tree", None)
        if tree is None:
            return
        for item in tree.get_children():
            tree.delete(item)
        folder = (self.settings.my_listings_dir or "").strip()
        if not folder:
            self.listings_count_label.configure(text="폴더를 지정해 주세요.")
            return
        try:
            listings = self._load_my_listings(folder)
        except Exception as exc:
            self.listings_count_label.configure(
                text=f"목록을 읽지 못했습니다: {exc}"
            )
            return
        for row in listings:
            tree.insert(
                "",
                "end",
                values=(
                    row["article_no"],
                    row["name"],
                    row["deal_price"],
                    row["desc"],
                ),
            )
        if listings:
            self.listings_count_label.configure(
                text=f"{len(listings)}건 · 매물을 클릭하면 매물번호가 채워집니다."
            )
        else:
            self.listings_count_label.configure(
                text="이 폴더에서 매물 CSV(내매물)를 찾지 못했습니다."
            )

    def _on_listing_selected(self, _event=None) -> None:
        tree = getattr(self, "listings_tree", None)
        if tree is None:
            return
        selection = tree.selection()
        if not selection:
            return
        values = tree.item(selection[0], "values")
        if not values:
            return
        article_no = str(values[0]).strip()
        if not article_no:
            return
        self.article_var.set(article_no)
        self._append_log(f"내 매물에서 매물번호 {article_no}를 불러왔습니다.")

    def _on_listing_activate(self, _event=None) -> None:
        """내 매물을 더블클릭하면 매물번호를 채우고 '1. 매물 조사하기'를 실행한다."""
        self._on_listing_selected()
        if self.article_var.get().strip():
            self._run_step(0)

    def _load_my_listings(self, folder: str) -> list[dict[str, str]]:
        """폴더의 매물 CSV를 읽어 목록을 만든다. '내매물' 파일이 있으면 그것만 쓴다."""
        from pathlib import Path

        base = Path(folder)
        if not base.is_dir():
            return []
        csv_files = [
            entry
            for entry in base.iterdir()
            if entry.is_file() and entry.suffix.lower() == ".csv"
        ]
        my_files = [f for f in csv_files if "내매물" in f.name]
        target_files = my_files if my_files else sorted(csv_files, key=lambda f: f.name)
        seen: set[str] = set()
        rows: list[dict[str, str]] = []
        for path in target_files:
            for row in self._read_listings_csv(path):
                if row["article_no"] in seen:
                    continue
                seen.add(row["article_no"])
                rows.append(row)
        return rows

    def _read_listings_csv(self, path) -> list[dict[str, str]]:
        for encoding in ("utf-8-sig", "cp949", "utf-8", "euc-kr"):
            out: list[dict[str, str]] = []
            try:
                with open(path, encoding=encoding, newline="") as handle:
                    reader = csv.DictReader(handle)
                    fields = reader.fieldnames or []
                    article_col = None
                    for name in fields:
                        if name and name.strip() in (
                            "매물번호",
                            "매물 번호",
                            "articleNo",
                            "article_no",
                            "articleNumber",
                        ):
                            article_col = name
                            break
                    if article_col is None:
                        article_col = fields[0] if fields else None
                    if article_col is None:
                        return []
                    for record in reader:
                        article_no = str(record.get(article_col, "") or "").strip()
                        if not article_no.isdigit():
                            continue
                        out.append(
                            {
                                "article_no": article_no,
                                "name": str(
                                    record.get("매물명")
                                    or record.get("매물 명")
                                    or ""
                                ).strip(),
                                "deal_price": self._format_listing_deal_price(record),
                                "desc": str(
                                    record.get("간략설명")
                                    or record.get("설명")
                                    or ""
                                ).strip(),
                            }
                        )
                return out
            except UnicodeDecodeError:
                continue
            except (OSError, csv.Error):
                return out
        return []

    @staticmethod
    def _format_listing_deal_price(record) -> str:
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

    def _build_copyprompt_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(3, weight=1)
        parent.rowconfigure(6, weight=1)

        ttk.Label(
            parent,
            text=(
                "아래에 생성된 프롬프트를 복사해 사용하는 AI(제미나이·챗GPT 등)에 붙여넣으세요.\n"
                "더 좋은 글을 원하시면, 먼저 '매물 조사 메모' 탭에서 내용을 보강·수정하세요. "
                "수정한 조사 메모가 프롬프트에 그대로 반영됩니다.\n"
                "완성된 글은 blog자료 본문에, 이미지는 파일로 넣어 포스팅합니다. (앱이 Gemini를 호출하지 않아 503 없음)\n"
                "💡 붙여넣기가 안 되면 입력칸에서 마우스 우측 버튼(우클릭) → '붙여넣기'를 사용하세요."
            ),
            background="white",
            foreground="#6b7780",
            wraplength=780,
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        blog_head = ttk.Frame(parent, style="White.TFrame")
        blog_head.grid(row=2, column=0, sticky="ew", pady=(14, 2))
        blog_head.columnconfigure(0, weight=1)
        ttk.Label(
            blog_head,
            text="블로그 글 작성 프롬프트",
            background="white",
            foreground=self.NAVY,
            font=("Apple SD Gothic Neo", 10, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(
            blog_head,
            text="복사",
            command=lambda: self._copy_text_widget(self.copy_blog_prompt_text),
            style="Secondary.TButton",
        ).grid(row=0, column=1, sticky="e")
        ttk.Label(
            blog_head,
            text="↓ 아래 프롬프트를 '복사'해서 사용하는 AI(제미나이·챗GPT 등)에 붙여넣어 글을 요청하세요.",
            background="white",
            foreground="#6b7780",
            wraplength=780,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))
        self.copy_blog_prompt_text = self._text_area(parent, height=10)
        self.copy_blog_prompt_text.grid(row=3, column=0, sticky="nsew")

        image_head = ttk.Frame(parent, style="White.TFrame")
        image_head.grid(row=5, column=0, sticky="ew", pady=(14, 2))
        image_head.columnconfigure(0, weight=1)
        ttk.Label(
            image_head,
            text="이미지 생성 프롬프트 (썸네일 1 + 본문 개념 이미지 3, JSON)",
            background="white",
            foreground=self.NAVY,
            font=("Apple SD Gothic Neo", 10, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(
            image_head,
            text="복사",
            command=lambda: self._copy_text_widget(self.copy_image_prompt_text),
            style="Secondary.TButton",
        ).grid(row=0, column=1, sticky="e")
        ttk.Label(
            image_head,
            text="↓ 아래 프롬프트를 '복사'해서 이미지 생성 AI에 붙여넣어 이미지를 요청하세요(매물명이 최상단에 포함됩니다).",
            background="white",
            foreground="#6b7780",
            wraplength=780,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))
        self.copy_image_prompt_text = self._text_area(parent, height=10)
        self.copy_image_prompt_text.grid(row=6, column=0, sticky="nsew")

    def _generate_copy_prompts(self) -> None:
        result = self.last_result
        if result is None:
            messagebox.showinfo(
                "먼저 자료 수집",
                "'1. 매물 조사하기'로 매물 자료를 먼저 수집해 주세요.",
            )
            return
        from naver_blog_automation.prompt_builder import (
            build_blog_prompt,
            build_image_prompt_text,
        )

        # 사용자가 '매물 조사 메모' 탭에서 보강·수정한 내용을 프롬프트에 반영한다.
        edited_research = self.research_text.get("1.0", "end-1c").strip()
        research = edited_research or result.research

        blog_prompt = build_blog_prompt(
            result.property_info,
            research,
            office_name=self.settings.realtor_office_name,
            writing_prompt=self.settings.writing_prompt,
        )
        image_prompt = build_image_prompt_text(
            result.property_info,
            research,
        )
        self._replace_text(self.copy_blog_prompt_text, blog_prompt)
        self._replace_text(self.copy_image_prompt_text, image_prompt)
        self.notebook.select(self.copyprompt_tab)
        self.status_var.set(
            "프롬프트를 생성했습니다. '복사'로 가져가 사용하는 AI에 붙여넣으세요."
        )

    def _copy_text_widget(self, widget: tk.Text) -> None:
        text = widget.get("1.0", "end-1c")
        if not text.strip():
            self.status_var.set("복사할 프롬프트가 없습니다. 먼저 프롬프트를 생성하세요.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status_var.set("클립보드에 복사했습니다.")

    def _goto_result_paste(self) -> None:
        """3단계: 외부 AI로 완성한 글을 붙여넣는 blog자료 탭으로 이동한다."""
        self.notebook.select(self.preview_tab)
        try:
            self.body_text.focus_set()
        except (AttributeError, tk.TclError):
            pass
        self.status_var.set(
            "완성한 글을 blog자료 '본문'에 붙여넣고, 아래 '이미지 첨부'에서 이미지를 넣으세요."
        )

    def _image_pick_row(self, parent, row, label, var, command, url_command=None) -> None:
        ttk.Label(
            parent, text=label, background="white", foreground=self.NAVY,
            font=("Apple SD Gothic Neo", 10),
        ).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Label(
            parent, textvariable=var, background="white", foreground="#6b7780",
            wraplength=240,
        ).grid(row=row, column=1, sticky="w", padx=(8, 8))
        button = ttk.Button(
            parent, text="파일 선택", style="Compact.TButton", command=command,
        )
        button.grid(row=row, column=2, sticky="e")
        self.action_buttons.append(button)
        if url_command is not None:
            url_button = ttk.Button(
                parent, text="URL로 첨부", style="Compact.TButton",
                command=url_command,
            )
            url_button.grid(row=row, column=3, sticky="e", padx=(6, 0))
            self.action_buttons.append(url_button)
            self._attach_tooltip(url_button, URL_IMAGE_HELP_TEXT)

    def _attach_tooltip(self, widget, text: str) -> None:
        """마우스를 올리면 안내 문구를 보여주는 간단한 툴팁."""
        state: dict[str, object] = {"win": None}

        def show(_event=None) -> None:
            if state["win"] is not None or not text:
                return
            x = widget.winfo_rootx() + 12
            y = widget.winfo_rooty() + widget.winfo_height() + 6
            win = tk.Toplevel(widget)
            win.wm_overrideredirect(True)
            win.wm_geometry(f"+{x}+{y}")
            tk.Label(
                win,
                text=text,
                background=self.NAVY,
                foreground="white",
                wraplength=340,
                justify="left",
                padx=10,
                pady=8,
                font=("Apple SD Gothic Neo", 9),
            ).pack()
            state["win"] = win

        def hide(_event=None) -> None:
            win = state["win"]
            if win is not None:
                win.destroy()
                state["win"] = None

        widget.bind("<Enter>", show, add="+")
        widget.bind("<Leave>", hide, add="+")

    @staticmethod
    def _pick_image_file(title: str) -> str:
        from tkinter import filedialog

        return filedialog.askopenfilename(
            title=title,
            filetypes=[
                ("이미지 파일", "*.png *.jpg *.jpeg *.webp *.gif"),
                ("모든 파일", "*.*"),
            ],
        )

    def _pick_thumbnail_image(self) -> None:
        path = self._pick_image_file("대표 이미지(썸네일) 선택")
        if path:
            self.selected_thumbnail_path = path
            self.thumbnail_pick_var.set(Path(path).name)

    def _pick_body_image(self, index: int) -> None:
        path = self._pick_image_file(f"본문 이미지 {index + 1} 선택")
        if path:
            self.selected_body_image_paths[index] = path
            self.body_image_pick_vars[index].set(Path(path).name)

    def _attach_thumbnail_url(self) -> None:
        path = self._prompt_and_download_image("대표 이미지(썸네일) URL")
        if path:
            self.selected_thumbnail_path = path
            self.thumbnail_pick_var.set(f"URL 이미지 첨부됨 ({Path(path).name})")

    def _attach_body_image_url(self, index: int) -> None:
        path = self._prompt_and_download_image(f"본문 이미지 {index + 1} URL")
        if path:
            self.selected_body_image_paths[index] = path
            self.body_image_pick_vars[index].set(
                f"URL 이미지 첨부됨 ({Path(path).name})"
            )

    def _prompt_and_download_image(self, title: str) -> str | None:
        from tkinter import simpledialog

        url = simpledialog.askstring(
            title,
            "이미지 주소(URL)를 붙여넣으세요.\n"
            ".jpg/.png 등으로 바로 열리는 공개 이미지 주소만 됩니다\n"
            "(로그인·만료 주소는 받을 수 없습니다).",
            parent=self.root,
        )
        if not url or not url.strip():
            return None
        self.root.config(cursor="watch")
        self.root.update_idletasks()
        try:
            return self._download_image_to_temp(url.strip())
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("URL 이미지 첨부 실패", str(exc))
            return None
        finally:
            self.root.config(cursor="")

    def _download_image_to_temp(self, url: str) -> str:
        import tempfile
        from urllib.parse import urlparse

        import httpx

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(
                "http 또는 https로 시작하는 이미지 주소만 사용할 수 있습니다."
            )
        try:
            with httpx.Client(follow_redirects=True, timeout=15.0) as client:
                response = client.get(
                    url, headers={"User-Agent": "Mozilla/5.0"}
                )
        except httpx.HTTPError as exc:
            raise ValueError(
                "이미지를 내려받지 못했습니다. 주소가 정확한지, 인터넷 연결이 "
                "되어 있는지 확인해 주세요."
            ) from exc
        if response.status_code != 200:
            raise ValueError(
                f"이미지를 내려받지 못했습니다(HTTP {response.status_code}). "
                "만료되었거나 로그인이 필요한 주소일 수 있습니다."
            )
        data = response.content
        if len(data) > 20 * 1024 * 1024:
            raise ValueError("이미지 용량이 20MB를 넘어 사용할 수 없습니다.")
        extension = self._image_extension(
            response.headers.get("content-type", ""), data
        )
        if extension is None:
            raise ValueError(
                "이 주소의 응답이 이미지 파일이 아닙니다. 이미지가 바로 열리는 "
                "주소(.jpg/.png 등)인지 확인해 주세요."
            )
        handle = tempfile.NamedTemporaryFile(
            prefix="vibe_img_", suffix=extension, delete=False
        )
        try:
            handle.write(data)
        finally:
            handle.close()
        return handle.name

    @staticmethod
    def _image_extension(content_type: str, data: bytes) -> str | None:
        # 확장자는 매직 바이트를 우선 확인하고, 없으면 Content-Type으로 판정한다.
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return ".png"
        if data[:3] == b"\xff\xd8\xff":
            return ".jpg"
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return ".gif"
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return ".webp"
        ct = (content_type or "").lower()
        if "png" in ct:
            return ".png"
        if "jpeg" in ct or "jpg" in ct:
            return ".jpg"
        if "gif" in ct:
            return ".gif"
        if "webp" in ct:
            return ".webp"
        return None

    def _build_environment_tab(self, parent: ttk.Frame) -> None:
        # 환경설정 항목이 화면 높이를 넘어가도 잘리지 않도록 세로 스크롤을 제공한다.
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        env_canvas = tk.Canvas(
            parent, background="white", highlightthickness=0
        )
        env_scroll = ttk.Scrollbar(
            parent, orient="vertical", command=env_canvas.yview
        )
        env_canvas.configure(yscrollcommand=env_scroll.set)
        env_canvas.grid(row=0, column=0, sticky="nsew")
        env_scroll.grid(row=0, column=1, sticky="ns")
        inner = ttk.Frame(env_canvas, style="White.TFrame")
        inner_id = env_canvas.create_window((0, 0), window=inner, anchor="nw")

        def _sync_scrollregion(_event=None) -> None:
            env_canvas.configure(scrollregion=env_canvas.bbox("all"))

        def _sync_width(event) -> None:
            env_canvas.itemconfigure(inner_id, width=event.width)

        inner.bind("<Configure>", _sync_scrollregion)
        env_canvas.bind("<Configure>", _sync_width)

        def _on_mousewheel(event) -> None:
            if event.num == 4:
                env_canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                env_canvas.yview_scroll(1, "units")
            else:
                step = -1 if event.delta > 0 else 1
                env_canvas.yview_scroll(step, "units")

        env_canvas.bind("<Enter>", lambda _e: (
            env_canvas.bind_all("<MouseWheel>", _on_mousewheel),
            env_canvas.bind_all("<Button-4>", _on_mousewheel),
            env_canvas.bind_all("<Button-5>", _on_mousewheel),
        ))
        env_canvas.bind("<Leave>", lambda _e: (
            env_canvas.unbind_all("<MouseWheel>"),
            env_canvas.unbind_all("<Button-4>"),
            env_canvas.unbind_all("<Button-5>"),
        ))

        # 이후 코드는 스크롤 가능한 inner 프레임에 배치한다.
        parent = inner
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)

        # 왼쪽 열은 컨테이너에 계정·중개사무소 프레임을 위에서부터 쌓아,
        # 오른쪽 API 열이 길어도 아래로 밀려나지 않게 한다.
        left_column = ttk.Frame(parent, style="White.TFrame")
        left_column.grid(row=0, column=0, sticky="new", padx=(0, 6))
        left_column.columnconfigure(0, weight=1)

        account_frame = ttk.LabelFrame(
            left_column,
            text="계정·일반 설정",
            style="Section.TLabelframe",
            padding=10,
        )
        account_frame.grid(row=0, column=0, sticky="ew")
        account_frame.columnconfigure(0, weight=1)

        (
            self.naver_login_id_entry,
            self.naver_password_entry,
        ) = self._paired_entry_row(
            account_frame,
            row=0,
            left_label="네이버 로그인 ID",
            left_variable=self.naver_login_id_var,
            right_label="네이버 비밀번호",
            right_variable=self.naver_password_var,
            right_show="•",
        )

        security_options = ttk.Frame(account_frame, style="White.TFrame")
        security_options.grid(row=3, column=0, sticky="ew", pady=(12, 6))
        ttk.Checkbutton(
            security_options,
            text="네이버 비밀번호 보안 저장",
            variable=self.remember_naver_password_var,
        ).pack(anchor="w")
        ttk.Label(
            account_frame,
            text=(
                "블로그는 로그인한 네이버 계정의 블로그에 저장됩니다.\n"
                "비밀번호는 설정 파일에 기록하지 않으며, 보안 저장을 선택하면 "
                "macOS Keychain 또는 Windows 자격 증명 저장소를 사용합니다."
            ),
            background="white",
            foreground="#526574",
            wraplength=350,
            justify="left",
        ).grid(row=4, column=0, sticky="w", pady=(0, 8))

        # 저장 방식: 임시저장(안전) / 발행(즉시 공개)
        publish_frame = ttk.Frame(account_frame, style="White.TFrame")
        publish_frame.grid(row=5, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(
            publish_frame,
            text="포스팅 방식",
            background="white",
            foreground=self.NAVY,
            font=("Apple SD Gothic Neo", 10, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 3))
        ttk.Radiobutton(
            publish_frame, text="임시저장(안전)", value="draft",
            variable=self.publish_mode_var,
        ).grid(row=1, column=0, sticky="w")
        ttk.Radiobutton(
            publish_frame, text="발행(즉시 공개)", value="publish",
            variable=self.publish_mode_var,
        ).grid(row=1, column=1, sticky="w", padx=(12, 0))
        ttk.Label(
            publish_frame,
            text="발행 카테고리 (발행 시 필수 · 블로그의 카테고리 이름과 정확히 일치)",
            background="white",
            foreground="#526574",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 2))
        ttk.Entry(
            publish_frame, textvariable=self.publish_category_var,
        ).grid(row=3, column=0, columnspan=2, sticky="ew")
        # 공개 범위(발행 시에만 적용): 전체공개 / 비공개
        ttk.Label(
            publish_frame,
            text="공개 범위 (발행 시 적용)",
            background="white",
            foreground="#526574",
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 2))
        ttk.Radiobutton(
            publish_frame, text="전체공개", value="public",
            variable=self.publish_visibility_var,
        ).grid(row=5, column=0, sticky="w")
        ttk.Radiobutton(
            publish_frame, text="비공개", value="private",
            variable=self.publish_visibility_var,
        ).grid(row=5, column=1, sticky="w", padx=(12, 0))
        publish_frame.columnconfigure(1, weight=1)
        ttk.Label(
            account_frame,
            text=(
                "발행은 글이 즉시 공개됩니다. 발행하려면 카테고리 이름을 반드시 "
                "입력해야 하며, 입력한 카테고리가 블로그에 없으면 발행하지 않고 "
                "임시저장까지만 진행합니다. 처음엔 임시저장으로 확인 후 사용하세요."
            ),
            background="white",
            foreground="#9a6a2f",
            wraplength=350,
            justify="left",
        ).grid(row=6, column=0, sticky="w", pady=(0, 8))

        self.account_save_button = ttk.Button(
            account_frame,
            text="계정·일반 설정 저장",
            command=self._save_account_settings,
            style="Primary.TButton",
        )
        self.account_save_button.grid(row=7, column=0, sticky="ew")
        self.action_buttons.append(self.account_save_button)

        # 중개사무소 정보 — 공인중개사 표시·광고 규정에 맞춰 글에 표기하는 데 사용
        realtor_frame = ttk.LabelFrame(
            left_column,
            text="중개사무소 정보 (표시·광고 표기용)",
            style="Section.TLabelframe",
            padding=10,
        )
        realtor_frame.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        realtor_frame.columnconfigure(0, weight=1)
        realtor_fields = (
            ("상호(사무소명)", self.realtor_office_name_var),
            ("대표 공인중개사 이름", self.realtor_agent_name_var),
            ("연락처(전화번호)", self.realtor_office_phone_var),
            ("등록번호", self.realtor_registration_no_var),
            ("소재지(주소)", self.realtor_office_address_var),
        )
        for slot, (label, variable) in enumerate(realtor_fields):
            self._labeled_entry(realtor_frame, label, variable, slot)
        footer_row = len(realtor_fields) * 2
        ttk.Checkbutton(
            realtor_frame,
            text="중개사무소 정보를 블로그에 표기 (해제하면 올리지 않음)",
            variable=self.realtor_footer_var,
        ).grid(row=footer_row, column=0, sticky="w", pady=(10, 0))
        ttk.Label(
            realtor_frame,
            text=(
                "블로그 글에 상호·대표 공인중개사·연락처·등록번호·소재지를 함께 "
                "표기하기 위한 정보입니다. 연락처는 중개사무소 정보 표에 사용되며, "
                "공인중개사법 표시·광고 규정 준수에 활용됩니다. 기본으로 표기되며, "
                "위 체크를 해제하면 블로그에 중개사무소 정보를 올리지 않습니다."
            ),
            background="white",
            foreground="#526574",
            wraplength=350,
            justify="left",
        ).grid(row=footer_row + 1, column=0, sticky="w", pady=(8, 0))
        self.realtor_save_button = ttk.Button(
            realtor_frame,
            text="중개사무소 정보 저장",
            command=self._save_account_settings,
            style="Primary.TButton",
        )
        self.realtor_save_button.grid(
            row=footer_row + 2, column=0, sticky="ew", pady=(8, 0)
        )
        self.action_buttons.append(self.realtor_save_button)

        api_frame = ttk.LabelFrame(
            parent,
            text="API 키 설정",
            style="Section.TLabelframe",
            padding=10,
        )
        api_frame.grid(
            row=0,
            column=1,
            sticky="new",
            padx=(6, 0),
        )
        api_frame.columnconfigure(0, weight=1)

        ttk.Label(
            api_frame,
            text="Google AI Studio API Key",
            background="white",
            foreground=self.NAVY,
            font=("Apple SD Gothic Neo", 10, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))
        google_key_frame = ttk.Frame(api_frame, style="White.TFrame")
        google_key_frame.grid(row=1, column=0, sticky="ew")
        google_key_frame.columnconfigure(0, weight=1)
        self.api_key_entry = ttk.Entry(
            google_key_frame,
            textvariable=self.api_key_var,
            show="•",
        )
        self.api_key_entry.grid(row=0, column=0, sticky="ew")
        self.api_key_entry.bind("<Button-2>", self._show_api_key_menu)
        self.api_key_entry.bind("<Button-3>", self._show_api_key_menu)
        self.api_key_menu = tk.Menu(self.root, tearoff=False)
        self.api_key_menu.add_command(
            label=API_KEY_PASTE_LABEL,
            command=self._paste_api_key,
        )
        self.api_key_menu.add_command(
            label="전체 선택",
            command=lambda: self.api_key_entry.selection_range(0, "end"),
        )
        self.api_key_menu.add_command(
            label="지우기",
            command=lambda: self.api_key_var.set(""),
        )
        self.api_key_button = ttk.Button(
            google_key_frame,
            text="검증 및 저장",
            command=self._validate_and_save_api_key,
            style="Secondary.TButton",
        )
        self.api_key_button.grid(row=0, column=1, padx=(6, 0))
        self.action_buttons.append(self.api_key_button)
        google_actions = ttk.Frame(api_frame, style="White.TFrame")
        google_actions.grid(row=2, column=0, sticky="ew", pady=(5, 2))
        for column in range(3):
            google_actions.columnconfigure(column, weight=1)
        self.api_key_paste_button = ttk.Button(
            google_actions,
            text=API_KEY_PASTE_LABEL,
            command=self._paste_api_key,
            style="Compact.TButton",
        )
        self.api_key_paste_button.grid(row=0, column=0, sticky="ew")
        self.api_key_link_button = ttk.Button(
            google_actions,
            text="Google 키 발급",
            command=self._open_gemini_api_key_page,
            style="Compact.TButton",
        )
        self.api_key_link_button.grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(5, 0),
        )
        self.api_usage_button = ttk.Button(
            google_actions,
            text="사용량 확인",
            command=self._open_gemini_usage_page,
            style="Compact.TButton",
        )
        self.api_usage_button.grid(
            row=0,
            column=2,
            sticky="ew",
            padx=(5, 0),
        )
        self.action_buttons.extend(
            [
                self.api_key_paste_button,
                self.api_key_link_button,
                self.api_usage_button,
            ]
        )
        ttk.Label(
            api_frame,
            textvariable=self.api_key_status_var,
            background="white",
            foreground="#526574",
            wraplength=350,
        ).grid(row=3, column=0, sticky="w", pady=(2, 6))

        self.kakao_key_entry = self._secret_key_row(
            api_frame,
            row=4,
            label="Kakao REST API 키",
            variable=self.kakao_key_var,
            paste_title="Kakao REST API 키",
        )
        self.kakao_js_key_entry = self._secret_key_row(
            api_frame,
            row=6,
            label="Kakao JavaScript 키",
            variable=self.kakao_js_key_var,
            paste_title="Kakao JavaScript 키",
        )
        self.public_data_key_entry = self._secret_key_row(
            api_frame,
            row=8,
            label="공공데이터포털 서비스키",
            variable=self.public_data_key_var,
            paste_title="공공데이터포털 서비스키",
        )
        api_actions = ttk.Frame(api_frame, style="White.TFrame")
        api_actions.grid(row=10, column=0, sticky="ew", pady=(8, 5))
        for column in range(3):
            api_actions.columnconfigure(column, weight=1)
        self.enrichment_key_save_button = ttk.Button(
            api_actions,
            text="그 외 API 키 저장",
            command=self._save_enrichment_api_keys,
            style="Primary.TButton",
        )
        self.enrichment_key_save_button.grid(row=0, column=0, sticky="ew")
        self.kakao_key_page_button = ttk.Button(
            api_actions,
            text="Kakao 키 발급",
            command=lambda: webbrowser.open(KAKAO_API_KEY_URL),
            style="Compact.TButton",
        )
        self.kakao_key_page_button.grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(5, 0),
        )
        self.building_key_page_button = ttk.Button(
            api_actions,
            text="건축 API 신청",
            command=lambda: webbrowser.open(BUILDING_API_KEY_URL),
            style="Compact.TButton",
        )
        self.building_key_page_button.grid(
            row=0,
            column=2,
            sticky="ew",
            padx=(5, 0),
        )
        self.action_buttons.extend(
            [
                self.enrichment_key_save_button,
                self.kakao_key_page_button,
                self.building_key_page_button,
            ]
        )
        ttk.Label(
            api_frame,
            textvariable=self.enrichment_key_status_var,
            background="white",
            foreground="#526574",
            wraplength=350,
        ).grid(row=11, column=0, sticky="w")

        # AI 자동 글쓰기 엔진 선택 + Claude(Anthropic) 키
        ttk.Label(
            api_frame,
            text="AI 자동 글쓰기 엔진 (선택)",
            background="white",
            foreground=self.NAVY,
            font=("Apple SD Gothic Neo", 10, "bold"),
        ).grid(row=12, column=0, sticky="w", pady=(12, 2))
        engine_row = ttk.Frame(api_frame, style="White.TFrame")
        engine_row.grid(row=13, column=0, sticky="w")
        ttk.Radiobutton(
            engine_row, text="Gemini", value="gemini",
            variable=self.ai_engine_var,
        ).pack(side="left")
        ttk.Radiobutton(
            engine_row, text="Claude", value="anthropic",
            variable=self.ai_engine_var,
        ).pack(side="left", padx=(12, 0))
        # 현재 사용 중인 모델 버전과 키 저장 여부 표시
        ttk.Label(
            api_frame,
            textvariable=self.ai_model_info_var,
            background="white",
            foreground="#526574",
            wraplength=350,
            justify="left",
        ).grid(row=14, column=0, sticky="w", pady=(2, 4))
        self.anthropic_key_entry = self._secret_key_row(
            api_frame,
            row=15,
            label="Claude(Anthropic) API 키 (Claude 선택 시)",
            variable=self.anthropic_key_var,
            paste_title="Claude(Anthropic) API 키",
        )
        self.ai_engine_save_button = ttk.Button(
            api_frame,
            text="AI 엔진·Claude 키 저장",
            command=self._save_ai_engine_settings,
            style="Primary.TButton",
        )
        self.ai_engine_save_button.grid(row=17, column=0, sticky="ew", pady=(6, 0))
        self.action_buttons.append(self.ai_engine_save_button)

        guide_frame = ttk.LabelFrame(
            parent,
            text="환경설정 안내",
            style="Section.TLabelframe",
            padding=10,
        )
        guide_frame.grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(12, 0),
        )
        ttk.Label(
            guide_frame,
            text=(
                f"• 동적 지도·로드뷰: Kakao JavaScript 키의 JavaScript SDK 도메인에 "
                f"http://localhost:{KAKAO_MAP_PORT} 를 등록하세요.\n"
                "• Kakao REST 키는 주소·좌표·주변시설 조회에 사용하고, JavaScript 키는 "
                "동적 지도와 같은 화면의 로드뷰에 사용합니다.\n"
                "• Google 키는 검증에 성공한 경우에만 저장합니다. 나머지 API 키는 "
                "Git에서 제외된 로컬 .env에 저장하며 결과·로그에는 기록하지 않습니다.\n"
                "• 무료 Gemini 호출량은 프로젝트 전체 기준이므로 '사용량 확인'에서 "
                "확인하세요. 기본 모델은 Gemini 3.5 Flash입니다.\n"
                "• 절대적인 0원 운영이 필요하면 결제가 연결되지 않은 무료 프로젝트의 "
                "Google 키만 사용하거나 키를 비워 두세요. 이미지는 항상 로컬에서 생성합니다."
            ),
            background="white",
            foreground="#4b6070",
            wraplength=760,
            justify="left",
        ).grid(row=0, column=0, sticky="w")

    def _labeled_entry(
        self,
        parent: ttk.LabelFrame,
        label: str,
        variable: tk.StringVar,
        slot: int,
        *,
        show: str | None = None,
        paste_command=None,
    ) -> ttk.Entry:
        row = slot * 2
        ttk.Label(
            parent,
            text=label,
            background="white",
            foreground=self.NAVY,
            font=("Apple SD Gothic Neo", 10, "bold"),
        ).grid(row=row, column=0, sticky="w", pady=(0 if slot == 0 else 9, 3))
        entry_frame = ttk.Frame(parent, style="White.TFrame")
        entry_frame.grid(row=row + 1, column=0, sticky="ew")
        entry_frame.columnconfigure(0, weight=1)
        entry = ttk.Entry(entry_frame, textvariable=variable, show=show or "")
        entry.grid(
            row=0,
            column=0,
            sticky="ew",
        )
        if paste_command is not None:
            paste_button = ttk.Button(
                entry_frame,
                text=ARTICLE_PASTE_LABEL,
                command=paste_command,
                style="Compact.TButton",
            )
            paste_button.grid(row=0, column=1, padx=(6, 0))
            self.article_paste_button = paste_button
            self.action_buttons.append(paste_button)
        return entry

    def _paired_entry_row(
        self,
        parent: ttk.LabelFrame,
        *,
        row: int,
        left_label: str,
        left_variable: tk.StringVar,
        right_label: str,
        right_variable: tk.StringVar,
        left_show: str = "",
        right_show: str = "",
    ) -> tuple[ttk.Entry, ttk.Entry]:
        frame = ttk.Frame(parent, style="White.TFrame")
        frame.grid(row=row, column=0, sticky="ew", pady=(9, 0))
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        ttk.Label(
            frame,
            text=left_label,
            background="white",
            foreground=self.NAVY,
            font=("Apple SD Gothic Neo", 10, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 3))
        ttk.Label(
            frame,
            text=right_label,
            background="white",
            foreground=self.NAVY,
            font=("Apple SD Gothic Neo", 10, "bold"),
        ).grid(row=0, column=1, sticky="w", padx=(8, 0), pady=(0, 3))
        left_entry = ttk.Entry(
            frame,
            textvariable=left_variable,
            show=left_show,
            width=13,
        )
        left_entry.grid(row=1, column=0, sticky="ew")
        right_entry = ttk.Entry(
            frame,
            textvariable=right_variable,
            show=right_show,
            width=13,
        )
        right_entry.grid(row=1, column=1, sticky="ew", padx=(8, 0))
        return left_entry, right_entry

    def _add_button(
        self,
        parent: ttk.LabelFrame,
        text: str,
        command,
        style: str,
        *,
        row: int,
    ) -> ttk.Button:
        button = ttk.Button(parent, text=text, command=command, style=style)
        button.grid(row=row, column=0, sticky="ew", pady=2)
        self.action_buttons.append(button)
        return button

    @staticmethod
    def _text_area(parent, height: int = 15) -> tk.Text:
        return tk.Text(
            parent,
            height=height,
            wrap="word",
            undo=True,
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
            font=("Apple SD Gothic Neo", 11),
            padx=10,
            pady=9,
            background="#fbfcfd",
            foreground="#26343c",
            insertbackground="#26343c",
        )

    def _configure_copy_shortcuts(self) -> None:
        """키보드 복사·붙여넣기·잘라내기는 Tk 위젯 기본 동작(<<Copy>>/<<Paste>>/<<Cut>>)에
        전적으로 맡긴다.

        macOS에서는 selection_get()(PRIMARY 셀렉션)이 동작하지 않아 직접 만든 복사
        핸들러가 실패하고, 게다가 ⌘C/⌘V를 가로채면 기본 복사·붙여넣기까지 막혀 버린다.
        그래서 키는 전혀 가로채지 않고, 대신 모든 텍스트 위젯에 우클릭 메뉴만 추가한다.
        """
        self.text_context_menu = tk.Menu(self.root, tearoff=False)
        self.text_context_menu.add_command(
            label="복사", command=lambda: self._context_edit("copy")
        )
        self.text_context_menu.add_command(
            label="붙여넣기", command=lambda: self._context_edit("paste")
        )
        self.text_context_menu.add_command(
            label="잘라내기", command=lambda: self._context_edit("cut")
        )
        self.text_context_menu.add_separator()
        self.text_context_menu.add_command(
            label="전체 선택", command=lambda: self._context_edit("selectall")
        )
        for widget_class in ("Text", "Entry", "TEntry", "TCombobox"):
            for sequence in ("<Button-3>", "<Button-2>", "<Control-Button-1>"):
                self.root.bind_class(
                    widget_class,
                    sequence,
                    self._show_text_context_menu,
                    add="+",
                )
        # Treeview(주변시설)는 텍스트 위젯이 아니므로 복사만 별도 바인딩 유지
        for shortcut in ("<Control-c>", "<Control-C>", "<Command-c>", "<Command-C>"):
            self.facility_tree.bind(shortcut, self._copy_tree_selection)

        if sys.platform == "darwin":  # macOS에서만 설치(Windows는 Tk 기본 동작으로 충분)
            # 한글 IME에서 Cmd+V가 'Command+ㅍ'으로 들어와 <<Paste>>가 실패하는 문제를
            # 물리 키코드 기반으로 폴백 처리한다.
            self.root.bind_all("<Command-KeyPress>", self._command_hotkey, add="+")

    def _command_hotkey(self, event):
        # 영문 모드: keysym이 정상이면 Tk 기본 <<Paste>> 등이 이미 처리했으므로 개입 금지
        # (여기서 또 처리하면 두 번 붙여넣기되는 버그 발생 — 반드시 이 가드 유지)
        if event.keysym.lower() in ("c", "v", "x", "a"):
            return None
        # 한글 모드: keysym이 'ㅍ' 등으로 와서 기본 동작이 실패한 경우만 물리 키코드로 처리
        virtual = self._MAC_EDIT_KEYCODES.get(event.keycode)
        if virtual is None:
            return None
        widget = self.root.focus_get()
        if widget is None:
            return None
        try:
            widget.event_generate(virtual)
        except tk.TclError:
            pass
        return "break"

    def _show_text_context_menu(self, event) -> str:
        self._context_widget = event.widget
        try:
            event.widget.focus_set()
        except tk.TclError:
            pass
        try:
            self.text_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.text_context_menu.grab_release()
        return "break"

    def _context_edit(self, action: str) -> None:
        widget = getattr(self, "_context_widget", None)
        if widget is None:
            return
        try:
            if action == "selectall":
                if isinstance(widget, tk.Text):
                    widget.tag_add("sel", "1.0", "end-1c")
                else:
                    widget.select_range(0, "end")
                    widget.icursor("end")
            else:
                widget.event_generate(
                    {"copy": "<<Copy>>", "paste": "<<Paste>>", "cut": "<<Cut>>"}[action]
                )
        except (tk.TclError, KeyError):
            pass

    def _copy_selected_text(self, event) -> str:
        try:
            selected = event.widget.selection_get()
        except (tk.TclError, AttributeError):
            return "break"
        self.root.clipboard_clear()
        self.root.clipboard_append(selected)
        return "break"

    def _paste_clipboard_text(self, event) -> str:
        widget = event.widget
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            return "break"
        try:
            try:
                widget.delete("sel.first", "sel.last")
            except tk.TclError:
                pass
            widget.insert("insert", text)
        except tk.TclError:
            return "break"
        return "break"

    def _cut_selected_text(self, event) -> str:
        widget = event.widget
        try:
            selected = widget.selection_get()
        except (tk.TclError, AttributeError):
            return "break"
        self.root.clipboard_clear()
        self.root.clipboard_append(selected)
        try:
            widget.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        return "break"

    def _select_all_text(self, event) -> str:
        widget = event.widget
        try:
            if isinstance(widget, tk.Text):
                widget.tag_add("sel", "1.0", "end-1c")
            else:
                widget.select_range(0, "end")
                widget.icursor("end")
        except (tk.TclError, AttributeError):
            pass
        return "break"

    def _copy_tree_selection(self, _event=None) -> str:
        rows = []
        for item in self.facility_tree.selection():
            values = self.facility_tree.item(item, "values")
            rows.append("\t".join(str(value) for value in values))
        if rows:
            self.root.clipboard_clear()
            self.root.clipboard_append("\n".join(rows))
        return "break"

    def _secret_key_row(
        self,
        parent,
        *,
        row: int,
        label: str,
        variable: tk.StringVar,
        paste_title: str,
    ) -> ttk.Entry:
        ttk.Label(
            parent,
            text=label,
            background="white",
            foreground=self.NAVY,
            font=("Apple SD Gothic Neo", 10, "bold"),
        ).grid(row=row, column=0, sticky="w", pady=(0, 4))
        frame = ttk.Frame(parent, style="White.TFrame")
        frame.grid(row=row + 1, column=0, sticky="ew")
        frame.columnconfigure(0, weight=1)
        entry = ttk.Entry(frame, textvariable=variable, show="•")
        entry.grid(row=0, column=0, sticky="ew")
        button = ttk.Button(
            frame,
            text="붙여넣기",
            command=lambda target=entry, title=paste_title: (
                self._paste_external_key(target, title)
            ),
            style="Compact.TButton",
        )
        button.grid(row=0, column=1, padx=(8, 0))
        self.action_buttons.append(button)
        return entry

    def _apply_form_settings(self) -> None:
        login_id = self.naver_login_id_var.get().strip()
        blog_id = resolve_blog_id(login_id, self.blog_id_var.get())
        self.settings.naver_login_id = login_id
        self.settings.remember_naver_password = (
            self.remember_naver_password_var.get()
        )
        self.settings.esiljang_login_id = (
            self.esiljang_login_id_var.get().strip()
        )
        self.settings.remember_esiljang_password = (
            self.remember_esiljang_password_var.get()
        )
        self.settings.blog_id = blog_id
        if blog_id and not self.blog_id_var.get().strip():
            self.blog_id_var.set(blog_id)
        self.settings.realtor_office_name = (
            self.realtor_office_name_var.get().strip()
        )
        self.settings.realtor_agent_name = (
            self.realtor_agent_name_var.get().strip()
        )
        self.settings.realtor_registration_no = (
            self.realtor_registration_no_var.get().strip()
        )
        self.settings.realtor_office_phone = (
            self.realtor_office_phone_var.get().strip()
        )
        self.settings.realtor_office_address = (
            self.realtor_office_address_var.get().strip()
        )
        self.settings.realtor_footer_enabled = bool(
            self.realtor_footer_var.get()
        )
        self.settings.icon_package = self.icon_package_var.get().strip()
        self.settings.auto_curl_refresh = bool(
            self.auto_curl_refresh_var.get()
        )
        self.settings.publish_mode = (
            self.publish_mode_var.get() or "draft"
        ).strip()
        self.settings.publish_category = (
            self.publish_category_var.get().strip()
        )
        self.settings.publish_visibility = (
            self.publish_visibility_var.get() or "public"
        )
        # 중개사무소 연락처를 글의 문의 전화(중개사무소 정보 표 등)로도 사용한다.
        self.settings.phone_number = (
            self.settings.realtor_office_phone
            or self.phone_var.get().strip()
        )
        self.phone_var.set(self.settings.phone_number)
        self.settings.tone_guide = self.tone_text.get("1.0", "end").strip()
        self.settings.kakao_rest_api_key = self.kakao_key_var.get().strip()
        self.settings.kakao_javascript_key = (
            self.kakao_js_key_var.get().strip()
        )
        self.settings.data_go_kr_service_key = (
            self.public_data_key_var.get().strip()
        )
        prompt = self.writing_prompt_text.get("1.0", "end").strip()
        self.settings.writing_prompt = prompt or DEFAULT_WRITING_PROMPT
        image_prompt = self.image_prompt_text.get("1.0", "end").strip()
        self.settings.image_prompt = image_prompt or DEFAULT_IMAGE_PROMPT
        self.settings.save_user_preferences()

    def _save_account_settings(self) -> None:
        naver_id = self.naver_login_id_var.get().strip()
        naver_password = self.naver_password_var.get()
        esiljang_id = self.esiljang_login_id_var.get().strip()
        esiljang_password = self.esiljang_password_var.get()
        try:
            self._apply_form_settings()
            if naver_id and naver_password:
                if self.remember_naver_password_var.get():
                    save_naver_password(naver_id, naver_password)
                else:
                    delete_naver_password(naver_id)
            elif naver_id and not self.remember_naver_password_var.get():
                delete_naver_password(naver_id)

            if esiljang_id and esiljang_password:
                if self.remember_esiljang_password_var.get():
                    save_esiljang_password(esiljang_id, esiljang_password)
                else:
                    delete_esiljang_password(esiljang_id)
            elif (
                esiljang_id
                and not self.remember_esiljang_password_var.get()
            ):
                delete_esiljang_password(esiljang_id)
        except Exception as exc:
            messagebox.showerror("계정 설정 저장 실패", str(exc))
            return
        finally:
            self.naver_password_var.set("")
            self.esiljang_password_var.set("")
            naver_password = ""
            esiljang_password = ""
        self.status_var.set("계정·일반 설정을 저장했습니다.")
        self._append_log(
            "계정 ID와 일반 설정 저장 완료 · 비밀번호 원문은 파일에 기록하지 않음"
        )
        messagebox.showinfo(
            "설정 저장 완료",
            "계정·일반 설정을 저장했습니다. 선택한 비밀번호만 운영체제 "
            "보안 저장소에 보관됩니다.",
        )

    def _save_writing_prompt(self) -> None:
        prompt = self.writing_prompt_text.get("1.0", "end").strip()
        if not prompt:
            messagebox.showinfo(
                "프롬프트 필요",
                "글 작성 프롬프트를 입력하거나 '기본값 복원'을 눌러 주세요.",
            )
            return
        self._apply_form_settings()
        self.status_var.set("기본 글 작성 프롬프트를 저장했습니다.")
        self._append_log("기본 글 작성 프롬프트 저장 완료")
        messagebox.showinfo(
            "저장 완료",
            "변경한 글 작성 프롬프트를 이 컴퓨터에 저장했습니다.",
        )

    def _save_image_prompt(self) -> None:
        prompt = self.image_prompt_text.get("1.0", "end").strip()
        if not prompt:
            messagebox.showinfo(
                "프롬프트 필요",
                "이미지 프롬프트를 입력하거나 기본값을 복원해 주세요.",
            )
            return
        self._apply_form_settings()
        self.status_var.set("이미지 프롬프트를 저장했습니다.")
        self._append_log("로컬 이미지 프롬프트 저장 완료")

    def _reset_image_prompt(self) -> None:
        if not messagebox.askyesno(
            "이미지 프롬프트 복원",
            "현재 이미지 프롬프트를 프로그램 기본값으로 되돌릴까요?",
        ):
            return
        self._replace_text(self.image_prompt_text, DEFAULT_IMAGE_PROMPT)
        self._apply_form_settings()
        self.status_var.set("이미지 프롬프트 기본값을 복원했습니다.")
        self._append_log("로컬 이미지 프롬프트 기본값 복원 완료")

    def _paste_external_key(
        self,
        entry: ttk.Entry,
        title: str,
        _event=None,
    ) -> str:
        try:
            value = self.root.clipboard_get()
        except tk.TclError:
            messagebox.showinfo(
                "붙여넣기 실패",
                f"클립보드에서 {title} 텍스트를 찾지 못했습니다.",
            )
            return "break"
        entry.delete(0, "end")
        entry.insert(0, value.strip())
        entry.icursor("end")
        entry.focus_set()
        return "break"

    def _save_enrichment_api_keys(self) -> None:
        kakao_key = self.kakao_key_var.get().strip()
        kakao_js_key = self.kakao_js_key_var.get().strip()
        public_data_key = self.public_data_key_var.get().strip()
        if not kakao_key and not kakao_js_key and not public_data_key:
            messagebox.showinfo(
                "API 키 필요",
                "Kakao REST/JavaScript 키 또는 공공데이터포털 서비스키를 "
                "입력해 주세요.",
            )
            return
        try:
            self.settings.save_enrichment_api_keys(
                kakao_rest_api_key=kakao_key,
                kakao_javascript_key=kakao_js_key,
                data_go_kr_service_key=public_data_key,
            )
        except Exception as exc:
            messagebox.showerror("API 키 저장 실패", str(exc))
            return
        self.enrichment_key_status_var.set(
            "Kakao·공공데이터 API 키를 로컬 .env에 저장했습니다. "
            "다음 콘텐츠 생성 시 연동을 확인합니다."
        )
        if self.last_result is not None:
            self._update_map_result(self.last_result)
        self.status_var.set("Kakao·공공데이터 API 키 저장 완료")
        self._append_log("Kakao·공공데이터 API 키 로컬 저장 완료")
        messagebox.showinfo(
            "저장 완료",
            "Kakao·공공데이터 API 키를 이 컴퓨터에 저장했습니다.",
        )

    def _reset_writing_prompt(self) -> None:
        confirmed = messagebox.askyesno(
            "기본 프롬프트 복원",
            "현재 프롬프트를 기본 글 작성 기준으로 되돌릴까요?",
        )
        if not confirmed:
            return
        self._replace_text(self.writing_prompt_text, DEFAULT_WRITING_PROMPT)
        self._apply_form_settings()
        self.status_var.set("기본 글 작성 프롬프트를 복원하고 저장했습니다.")
        self._append_log("기본 글 작성 프롬프트 복원 완료")

    def _workflow(self, *, offline: bool = False) -> BlogAutomationWorkflow:
        self._apply_form_settings()
        entered_key = self.api_key_var.get().strip()
        active_key = (
            self.settings.gemini_api_key
            if entered_key and entered_key == self.settings.gemini_api_key
            else ""
        )
        active_settings = replace(
            self.settings,
            gemini_api_key="" if offline else active_key,
        )
        return BlogAutomationWorkflow(
            active_settings,
            progress=lambda step, message: self.events.put(
                ("progress", (step, message))
            ),
        )

    def _set_busy(self, busy: bool) -> None:
        self._task_running = busy
        state = "disabled" if busy else "normal"
        for button in self.action_buttons:
            button.configure(state=state)
        progress = getattr(self, "progress_bar", None)
        if progress is not None:
            if busy:
                progress.grid()
                progress.start(12)
            else:
                progress.stop()
                progress.grid_remove()
        if not busy:
            # 백그라운드 작업이 끝나면 진행 중이던 단계를 '완료(초록 ✓)'로 바꾼다.
            self._finish_step()
        if not busy and self.draft_browser_open:
            self.draft_button.configure(state="disabled")

    def _run_step(self, index: int) -> None:
        """단계 실행 + 상태색 갱신. 안 함 → 진행 중(황색) → 완료(초록 ✓).
        1단계(매물 조사)는 새 흐름이라 전체 단계를 기본색으로 초기화한다."""
        if index == 0:
            self._reset_step_buttons()
        self._pending_step = index
        self._mark_step_busy(index)  # 클릭 즉시 '진행 중'(황색)
        self.step_handlers[index]()
        if not getattr(self, "_task_running", False):
            # 백그라운드 작업이 시작되지 않은 경우
            if index in self._ASYNC_STEPS:
                # 비동기 단계인데 작업이 안 시작됨(조건 미충족·사용자 취소) → 기본색 복원
                self._restore_step(index)
                self._pending_step = None
            else:
                # 동기 단계(프롬프트 생성·결과 붙여넣기)는 즉시 완료 처리
                self._finish_step()

    def _mark_step_busy(self, index: int) -> None:
        try:
            self.step_buttons[index].configure(
                text=ACTION_LABELS[index], style="StepBusy.TButton"
            )
        except Exception:
            pass

    def _finish_step(self) -> None:
        index = getattr(self, "_pending_step", None)
        if index is None:
            return
        self._pending_step = None
        self._mark_step_done(index)

    def _mark_step_done(self, index: int) -> None:
        try:
            self.step_buttons[index].configure(
                text=f"✓ {ACTION_LABELS[index]}", style="StepDone.TButton"
            )
        except Exception:
            pass

    def _restore_step(self, index: int) -> None:
        try:
            self.step_buttons[index].configure(
                text=ACTION_LABELS[index], style=self.step_base_styles[index]
            )
        except Exception:
            pass

    def _reset_step_buttons(self) -> None:
        self._pending_step = None
        for i, button in enumerate(self.step_buttons):
            try:
                button.configure(
                    text=ACTION_LABELS[i], style=self.step_base_styles[i]
                )
            except Exception:
                pass

    def _run_task(self, label: str, function, *, switch_result_tab: bool = True) -> None:
        # switch_result_tab=False면 결과가 와도 현재 탭을 유지한다(예: 이미지 탭에서
        # 로컬 이미지 생성 시 blog자료 탭으로 넘어가지 않도록).
        self._switch_result_tab = switch_result_tab
        self._set_busy(True)
        self.status_var.set(label)
        thread = threading.Thread(
            target=self._task_worker,
            args=(function,),
            daemon=True,
        )
        thread.start()

    def _task_worker(self, function) -> None:
        try:
            result = function()
            self.events.put(("result", result))
        except Exception as exc:
            self.events.put(("error", exc))

    def _validate_and_save_api_key(self) -> None:
        key = normalize_gemini_api_key(self.api_key_var.get())
        if not key:
            messagebox.showinfo(
                "API Key 필요",
                "Google AI Studio API Key를 입력해 주세요.",
            )
            return
        # 환경변수 표기나 따옴표가 함께 붙은 경우 정리된 값으로 화면 상태를 맞춘다.
        self.api_key_var.set(key)
        self._set_busy(True)
        self.api_key_status_var.set("API Key를 검증하고 있습니다…")
        self.status_var.set("Google AI Studio API Key를 검증하고 있습니다…")
        thread = threading.Thread(
            target=self._api_key_validation_worker,
            args=(key,),
            daemon=True,
        )
        thread.start()

    @staticmethod
    def _open_gemini_api_key_page() -> None:
        webbrowser.open(GEMINI_API_KEY_URL)

    @staticmethod
    def _open_gemini_usage_page() -> None:
        webbrowser.open(GEMINI_USAGE_URL)

    @staticmethod
    def _open_feedback() -> None:
        """미인증 프로그램 피드백 게시판을 이 프로그램 제목으로 연다."""
        import urllib.parse

        program = urllib.parse.quote("네이버 블로그 매물 포스팅 자동화")
        webbrowser.open(f"{FEEDBACK_URL}public?program={program}")

    def _ai_model_info_text(self) -> str:
        """현재 사용 중인 AI 모델 버전과 키 저장 여부를 한 줄로 정리한다."""
        text_model = self.settings.text_model or "gemini-2.5-flash"
        anthropic_model = self.settings.anthropic_model or "claude-sonnet-4"
        image_model = self.settings.image_model.strip()
        image_desc = f"API {image_model}" if image_model else "로컬(Pillow)"
        gemini_saved = "저장됨" if self.settings.gemini_api_key else "미저장"
        claude_saved = "저장됨" if self.settings.anthropic_api_key else "미저장"
        return (
            f"사용 버전 — Gemini(글): {text_model} · "
            f"Claude(글): {anthropic_model} · "
            f"이미지: {image_desc}\n"
            f"API 키 — Gemini: {gemini_saved} · Claude: {claude_saved}"
        )

    def _refresh_ai_model_info(self) -> None:
        try:
            self.ai_model_info_var.set(self._ai_model_info_text())
        except AttributeError:
            pass

    def _save_ai_engine_settings(self) -> None:
        self.settings.ai_engine = (
            self.ai_engine_var.get() or "gemini"
        ).strip().lower()
        key = self.anthropic_key_var.get().strip()
        try:
            self.settings.save_anthropic_api_key(key)
            self.settings.save_user_preferences()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("저장 실패", str(exc))
            return
        engine_name = (
            "Claude(Anthropic)"
            if self.settings.ai_engine == "anthropic"
            else "Gemini"
        )
        self._refresh_ai_model_info()
        self.status_var.set(
            f"AI 자동 글쓰기 엔진: {engine_name} · 설정을 저장했습니다."
        )

    def _paste_api_key(self, _event=None) -> str:
        try:
            value = self.root.clipboard_get()
        except tk.TclError:
            messagebox.showinfo(
                "붙여넣기 실패",
                "클립보드에서 텍스트를 찾지 못했습니다.",
            )
            return "break"
        self.api_key_entry.delete(0, "end")
        self.api_key_entry.insert(0, value)
        self.api_key_entry.icursor("end")
        self.api_key_entry.focus_set()
        return "break"

    def _paste_naver_password(self, _event=None) -> str:
        return self._paste_password_entry(
            self.naver_password_entry,
            "네이버 비밀번호",
            _event,
        )

    def _paste_password_entry(
        self,
        entry: ttk.Entry,
        label: str,
        _event=None,
    ) -> str:
        try:
            value = self.root.clipboard_get()
        except tk.TclError:
            messagebox.showinfo(
                "붙여넣기 실패",
                f"클립보드에서 {label}를 찾지 못했습니다.",
            )
            return "break"
        entry.delete(0, "end")
        entry.insert(0, value)
        entry.icursor("end")
        entry.focus_set()
        return "break"

    @staticmethod
    def _normalize_article_clipboard(value: str) -> str:
        cleaned = value.strip()
        if cleaned.isdigit():
            return cleaned
        article_url = re.search(
            r"/(?:api/)?articles?/([0-9]+)",
            cleaned,
            re.IGNORECASE,
        )
        if article_url:
            return article_url.group(1)
        labeled = re.search(
            r"(?:매물번호|articleNo)\s*[:=]?\s*([0-9]+)",
            cleaned,
            re.IGNORECASE,
        )
        if labeled:
            return labeled.group(1)
        return cleaned

    def _paste_article_no(self, _event=None) -> str:
        try:
            value = self.root.clipboard_get()
        except tk.TclError:
            messagebox.showinfo(
                "붙여넣기 실패",
                "클립보드에서 매물번호 또는 매물 URL을 찾지 못했습니다.",
            )
            return "break"
        article_no = self._normalize_article_clipboard(value)
        self.article_entry.delete(0, "end")
        self.article_entry.insert(0, article_no)
        self.article_entry.icursor("end")
        self.article_entry.focus_set()
        return "break"

    def _show_article_menu(self, event) -> str:
        try:
            self.article_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.article_menu.grab_release()
        return "break"

    def _show_api_key_menu(self, event) -> str:
        try:
            self.api_key_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.api_key_menu.grab_release()
        return "break"

    def _api_key_validation_worker(self, key: str) -> None:
        try:
            message = validate_gemini_api_key(key)
            self.settings.save_gemini_api_key(key)
            self.events.put(("api_key_valid", message))
        except Exception as exc:
            self.events.put(("api_key_error", exc))

    def _save_curl(self) -> None:
        curl = self.curl_text.get("1.0", "end").strip()
        if not curl:
            messagebox.showinfo(
                "cURL 없음", "저장할 cURL을 먼저 붙여 넣어 주세요."
            )
            return
        try:
            save_property_curl(curl)
        except Exception as exc:
            messagebox.showerror("cURL 저장 실패", str(exc))
            return
        self.remember_curl_var.set(True)
        self._append_log("cURL을 키체인에 안전하게 저장했습니다(다음 실행에도 사용).")
        messagebox.showinfo(
            "cURL 저장됨",
            "cURL을 안전하게 저장했습니다. 다음 실행에도 자동으로 사용됩니다.\n"
            "토큰이 만료되면(약 3시간) 다시 복사해 붙여 넣고 저장해 주세요.",
        )

    def _clear_curl(self) -> None:
        self.curl_text.delete("1.0", "end")
        self.remember_curl_var.set(False)
        try:
            delete_property_curl()
        except Exception:
            pass
        self._append_log("저장된 cURL을 삭제했습니다.")

    def _persist_curl_preference(self, curl: str) -> None:
        """체크 상태에 따라 현재 cURL을 저장하거나 삭제한다(수집 실행 시 호출)."""
        try:
            if self.remember_curl_var.get() and curl:
                save_property_curl(curl)
            elif not self.remember_curl_var.get():
                delete_property_curl()
        except Exception:
            pass

    def _run_sample(self) -> None:
        article_no = self.article_var.get().strip()
        curl = self.curl_text.get("1.0", "end").strip()
        self._persist_curl_preference(curl)
        # 자동 갱신 체크 상태를 즉시 반영(워크플로 생성 전에 설정에 적용).
        self.settings.auto_curl_refresh = bool(self.auto_curl_refresh_var.get())
        use_builtin_sample = not article_no
        workflow = self._workflow(offline=True)
        if use_builtin_sample:
            status = "내장 샘플로 Google AI 없는 미리보기를 만들고 있습니다…"
            self._append_log(
                "매물번호가 비어 있어 내장 샘플을 사용합니다. Google Gemini API는 "
                "호출하지 않습니다."
            )
        else:
            status = "실제 매물 데이터를 AI 없이 수집해 미리보기를 만들고 있습니다…"
            self._append_log(
                f"매물번호 {article_no}의 수집 가능한 데이터를 가져옵니다. "
                "Google Gemini API는 호출하지 않습니다."
            )
        self._run_task(
            status,
            lambda: workflow.preview(
                article_no=article_no or "SAMPLE-001",
                curl_command=curl,
                sample=use_builtin_sample,
            ),
        )

    def _run_real(self) -> None:
        article_no = self.article_var.get().strip()
        if self.last_result is None:
            messagebox.showinfo(
                "미리보기 필요",
                "먼저 '1. 매물 조사하기'를 실행해 주세요.",
            )
            return
        target_article = article_no or self.last_result.property_info.article_no
        if (
            self.last_result.property_info.article_no != target_article
        ):
            messagebox.showinfo(
                "미리보기 필요",
                "같은 매물번호로 먼저 '1. 매물 조사하기'를 실행해 주세요.",
            )
            return
        entered_key = self.api_key_var.get().strip()
        if entered_key and entered_key != self.settings.gemini_api_key:
            messagebox.showinfo(
                "API Key 검증 필요",
                "새로 입력한 Google AI Studio API Key는 먼저 "
                "'검증 및 저장'을 눌러 주세요.",
            )
            return
        workflow = self._workflow()
        if not entered_key:
            self._append_log(
                "Google AI Studio API Key가 없어 웹검색·AI 생성 대신 "
                "오프라인 초안을 만듭니다."
            )
        self._run_task(
            "매물 콘텐츠를 생성하고 있습니다…",
            lambda: workflow.generate_content(self.last_result),
        )

    def _generate_image(self) -> None:
        if self.last_result is None:
            messagebox.showinfo(
                "매물정보 필요",
                "먼저 '1. 매물 조사하기'를 실행해 주세요.",
            )
            return
        prompt = self.image_prompt_text.get("1.0", "end").strip()
        if not prompt:
            messagebox.showinfo(
                "이미지 프롬프트 필요",
                "이미지 탭에서 프롬프트를 입력하거나 기본값을 복원해 주세요.",
            )
            return
        self._apply_form_settings()
        workflow = self._workflow(offline=True)

        def generate() -> WorkflowResult:
            workflow.generate_image(self.last_result, prompt=prompt)
            return self.last_result

        self._run_task(
            "비용 없는 로컬 방식으로 대표 이미지를 생성하고 있습니다…",
            generate,
            switch_result_tab=False,
        )

    def _resolve_thumbnail_path(self) -> str:
        """대표이미지 우선순위: 직접 업로드 > 로컬 생성 > 없음.

        직접 올린 이미지가 있으면 그것을, 없으면 '로컬 이미지 생성'으로 만든
        이미지를 쓴다. 파일이 없거나 너무 작으면(깨짐·빈 이미지) 대표이미지 없이
        포스팅한다."""
        uploaded = (self.selected_thumbnail_path or "").strip()
        if uploaded and Path(uploaded).exists():
            return uploaded
        generated = ""
        if self.last_result is not None:
            generated = (self.last_result.thumbnail_path or "").strip()
        if generated:
            try:
                candidate = Path(generated)
                if candidate.exists() and candidate.stat().st_size > 2048:
                    return generated
            except OSError:
                pass
        return ""

    def _save_draft(self) -> None:
        if self.last_result is None:
            messagebox.showinfo("콘텐츠 필요", "먼저 '1. 매물 조사하기'와 글 작성(붙여넣기 또는 AI 자동 글쓰기)을 완료해 주세요.")
            return
        # BYO-AI 방식: 제목·본문은 화면(blog자료)에 붙여넣은 값을 기준으로 확인한다.
        # (AI 자동 생성을 실행하지 않아도 붙여넣은 글로 포스팅할 수 있어야 한다.)
        pasted_title = self.title_var.get().strip()
        pasted_body = self.body_text.get("1.0", "end").strip()
        if not pasted_title or not pasted_body:
            messagebox.showinfo(
                "내용 필요",
                "blog자료 탭에 제목과 본문을 먼저 입력(붙여넣기)해 주세요.\n"
                "외부 AI 결과가 있으면 '3. 결과 붙여넣기'로 넣거나, "
                "'(선택) AI로 자동 글쓰기'를 실행하세요.",
            )
            return
        # 대표 이미지 우선순위: 직접 업로드 > 로컬 생성 > 없음.
        # (없거나 깨진 파일은 걸러 대표이미지 없이 포스팅한다.)
        self.last_result.thumbnail_path = self._resolve_thumbnail_path()
        self._apply_form_settings()
        if not self.settings.naver_login_id:
            messagebox.showinfo(
                "네이버 계정 필요",
                "환경설정 탭에 네이버 로그인 ID를 입력해 주세요.",
            )
            return
        if self.settings.publish_mode == "publish":
            if not self.settings.publish_category:
                messagebox.showinfo(
                    "발행 카테고리 필요",
                    "발행(즉시 공개)하려면 환경설정 → '발행 카테고리'에 블로그의 "
                    "카테고리 이름을 정확히 입력해 주세요.\n"
                    "카테고리를 지정하지 않으면 발행할 수 없습니다.",
                )
                return
            category = self.settings.publish_category
            visibility_label = (
                "비공개" if self.settings.publish_visibility == "private"
                else "전체 공개"
            )
            confirmed = messagebox.askyesno(
                "네이버 발행",
                (
                    f"블로그 '{self.settings.blog_id}'에 현재 글을 '{visibility_label}'(으)로 "
                    f"발행합니다.\n카테고리: {category}\n\n"
                    "⚠️ 발행하면 글이 즉시 등록됩니다(임시저장이 아닙니다).\n"
                    "입력한 카테고리 이름이 블로그에 없으면 발행하지 않고 "
                    "임시저장까지만 진행합니다.\n\n"
                    "정말 발행할까요?"
                ),
                icon="warning",
            )
        else:
            confirmed = messagebox.askyesno(
                "네이버 임시저장",
                (
                    f"블로그 '{self.settings.blog_id}'에 현재 화면의 제목·본문·해시태그와 "
                    "이미지를 임시저장합니다.\n\n필요하면 자동 로그인한 뒤 글을 작성하고 "
                    "임시저장합니다. 완료 후 확인할 수 있도록 Chrome 창은 닫지 않습니다.\n\n"
                    "자동 발행은 하지 않습니다. 계속할까요?"
                ),
            )
        if not confirmed:
            return
        naver_id = self.settings.naver_login_id
        password = self.naver_password_var.get()
        remember_password = self.remember_naver_password_var.get()
        if not password and remember_password and naver_id:
            try:
                password = load_naver_password(naver_id)
            except Exception as exc:
                messagebox.showerror("비밀번호 불러오기 실패", str(exc))
                return
        self.naver_password_var.set("")
        tags = [
            item.strip().lstrip("#")
            for item in self.tags_var.get().replace("#", ",").split(",")
            if item.strip()
        ]
        self.last_result.content = BlogContent(
            title=pasted_title,
            body=pasted_body,
            hashtags=tags,
            image_prompt=self.last_result.content.image_prompt,
        )
        # 붙여넣은 글로 확정되었으므로 미리보기 상태를 해제한다(포스팅 허용).
        self.last_result.preview_only = False
        body_image_paths = [
            path for path in self.selected_body_image_paths if path
        ]
        workflow = self._workflow()
        self._run_task(
            "네이버 블로그에 임시저장하고 있습니다…",
            lambda: self._save_draft_with_credentials(
                workflow,
                self.last_result,
                naver_id,
                password,
                remember_password,
                body_image_paths,
            ),
        )

    def _save_draft_with_credentials(
        self,
        workflow: BlogAutomationWorkflow,
        result: WorkflowResult,
        naver_id: str,
        password: str,
        remember_password: bool,
        body_image_paths: list[str] | None = None,
    ) -> dict[str, object]:
        password_saved = False
        if naver_id and password:
            if remember_password:
                save_naver_password(naver_id, password)
                password_saved = True
            else:
                delete_naver_password(naver_id)

        def notify_saved(published: bool = False) -> None:
            self.events.put(
                (
                    "draft_saved_open",
                    {"password_saved": password_saved, "published": published},
                )
            )

        workflow.save_draft(
            result,
            naver_id=naver_id,
            password=password,
            keep_browser_open=True,
            body_image_paths=[Path(path) for path in (body_image_paths or [])],
            on_saved=notify_saved,
        )
        password = ""
        return {
            "naver_window_closed": True,
        }

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "progress":
                    step, message = payload  # type: ignore[misc]
                    self._show_progress(int(step), str(message))
                elif kind == "update_available":
                    self._notify_update(payload if isinstance(payload, dict) else {})
                elif kind == "result":
                    self._set_busy(False)
                    if isinstance(payload, WorkflowResult):
                        self.last_result = payload
                        self._show_result(payload)
                        # 1단계 결과는 조사 메모 탭, 콘텐츠 완성 결과는 blog자료 탭으로 전환.
                        # 단, 로컬 이미지 생성처럼 탭 유지가 필요한 작업은 건너뛴다.
                        if getattr(self, "_switch_result_tab", True):
                            if payload.preview_only:
                                self.notebook.select(self.research_tab)
                            else:
                                self.notebook.select(self.preview_tab)
                        if payload.preview_only:
                            self.status_var.set(
                                "매물 조사 완료 · 매물 조사 메모를 확인·보완하세요."
                            )
                        elif payload.generation_warning:
                            self.status_var.set(
                                "오프라인 대체 초안 생성 완료 · 내용을 반드시 검토하세요."
                            )
                            warning_text = payload.generation_warning
                            # 503 서버 혼잡은 사용량·결제 문제가 아니므로 한도 안내를
                            # 붙이지 않고, 429(할당량)일 때만 사용량 확인을 안내한다.
                            is_transient = (
                                "503" in warning_text or "혼잡" in warning_text
                            )
                            if is_transient:
                                messagebox.showwarning(
                                    "Gemini 서버 일시 혼잡",
                                    warning_text,
                                )
                            else:
                                messagebox.showwarning(
                                    "Gemini 사용량 한도",
                                    (
                                        f"{warning_text}\n\n"
                                        "'Gemini 사용량 확인'에서 한도와 결제 상태를 "
                                        "확인할 수 있습니다."
                                    ),
                                )
                        else:
                            self.status_var.set(
                                (
                                    "대표 이미지 생성 완료 · '블로그로 포스팅'을 실행하세요."
                                    if payload.thumbnail_path
                                    else "AI 원고 작성 완료 · 검토 후 이미지·포스팅을 진행하세요."
                                )
                            )
                    elif (
                        isinstance(payload, dict)
                        and payload.get("naver_window_closed") is True
                    ):
                        self.draft_browser_open = False
                        self.draft_button.configure(state="normal")
                        message = (
                            "임시저장 확인용 Chrome 창이 닫혔습니다. "
                            "저장된 글은 네이버 임시저장 목록에서 확인할 수 있습니다."
                        )
                        self.status_var.set(message)
                        self._append_log(message)
                    else:
                        self.status_var.set("작업을 완료했습니다.")
                elif kind == "draft_saved_open":
                    self.draft_browser_open = True
                    self._set_busy(False)
                    self.draft_button.configure(state="disabled")
                    saved = (
                        isinstance(payload, dict)
                        and payload.get("password_saved") is True
                    )
                    published = (
                        isinstance(payload, dict)
                        and payload.get("published") is True
                    )
                    if published:
                        title = "발행 완료"
                        message = (
                            "네이버 블로그에 발행을 완료했습니다(전체 공개). "
                            "확인용 Chrome 창은 그대로 열어 두었습니다."
                        )
                    else:
                        title = "임시저장 완료"
                        message = (
                            "네이버 블로그 임시저장을 완료했습니다. "
                            "확인용 Chrome 창은 그대로 열어 두었습니다. "
                            "자동 발행은 하지 않았습니다."
                        )
                    if saved:
                        message += " 비밀번호는 운영체제 보안 저장소에 저장했습니다."
                    self.status_var.set(message)
                    self._append_log(message)
                    messagebox.showinfo(title, message)
                elif kind == "error":
                    self._set_busy(False)
                    self.status_var.set("작업 중 오류가 발생했습니다.")
                    self._append_log(f"[오류] {payload}")
                    messagebox.showerror("작업 실패", str(payload))
                elif kind == "map_frame":
                    try:
                        from io import BytesIO

                        from PIL import Image, ImageTk

                        image_bytes, width, height = payload  # type: ignore[misc]
                        with Image.open(BytesIO(image_bytes)) as image:
                            frame = image.convert("RGB")
                            self.map_photo = ImageTk.PhotoImage(frame)
                        self.map_render_size = (int(width), int(height))
                        self.map_preview_label.configure(
                            image=self.map_photo,
                            text="",
                        )
                        self.map_status_var.set(
                            "지도·로드뷰를 프로그램 안에서 표시 중입니다. "
                            "마우스 드래그와 상단 버튼을 사용할 수 있습니다."
                        )
                    except Exception as exc:
                        detail = str(exc)
                        if "PIL" in detail or "Pillow" in detail.lower():
                            detail = (
                                "이미지 라이브러리(Pillow)가 설치되지 않아 내장 지도를 표시할 수 없습니다. "
                                "위 '새 창으로 보기' 버튼으로 지도를 확인하시거나, 설치 스크립트를 다시 실행해 주세요."
                            )
                        self.map_status_var.set(f"내장 지도 화면 표시 실패: {detail}")
                elif kind == "map_render_status":
                    self.map_status_var.set(str(payload))
                elif kind == "map_render_error":
                    self.map_photo = None
                    self.map_preview_label.configure(
                        image="",
                        text=(
                            "프로그램 안에서 지도를 표시하지 못했습니다.\n\n"
                            f"{payload}"
                        ),
                    )
                    self.map_status_var.set("내장 지도 렌더링에 실패했습니다.")
                    self._append_log(f"[내장 지도 오류] {payload}")
                elif kind == "api_key_valid":
                    self._set_busy(False)
                    self.api_key_status_var.set(f"✓ {payload} · 로컬 .env에 저장됨")
                    self._refresh_ai_model_info()
                    self.status_var.set(
                        "Google AI Studio API Key 검증 및 저장을 완료했습니다."
                    )
                    self._append_log(
                        "Google AI Studio API Key 검증 및 로컬 저장 완료"
                    )
                    messagebox.showinfo(
                        "API Key 검증 완료",
                        "Google AI Studio API Key가 확인되어 이 컴퓨터의 "
                        ".env에 저장되었습니다.",
                    )
                elif kind == "api_key_error":
                    self._set_busy(False)
                    self.api_key_status_var.set("검증 실패 · 입력값을 확인해 주세요.")
                    self.status_var.set(
                        "Google AI Studio API Key 검증에 실패했습니다."
                    )
                    self._append_log(f"[API Key 검증 실패] {payload}")
                    messagebox.showerror("API Key 검증 실패", str(payload))
        except queue.Empty:
            pass
        self.root.after(120, self._drain_events)

    def _show_progress(self, step: int, message: str) -> None:
        self.status_var.set(message)
        self._append_log(message)
        for index, label in enumerate(self.step_labels, start=1):
            if index < step:
                label.configure(foreground=self.GREEN)
            elif index == step:
                label.configure(foreground=self.BLUE)
            else:
                label.configure(foreground="#75838d")

    def _show_result(self, result: WorkflowResult) -> None:
        # 로컬 이미지 생성처럼 탭을 유지하는 작업은 대표 이미지만 갱신하고,
        # 사용자가 blog자료에 붙여넣은 제목·본문·해시태그는 덮어쓰지 않는다.
        image_only_refresh = not getattr(self, "_switch_result_tab", True)
        if not result.preview_only and not image_only_refresh:
            self.title_var.set(result.content.title)
            self.tags_var.set(", ".join(result.content.hashtags))
            self._replace_text(self.body_text, result.content.body)
        if image_only_refresh:
            if result.thumbnail_path:
                self._show_thumbnail(Path(result.thumbnail_path))
            return
        # 해시태그 미리 채우기: '1. 매물 조사하기'(새 매물)는 매물 데이터로 새로
        # 만들고, AI 글쓰기 결과는 해시태그가 비어 있을 때만 자동으로 채운다.
        if result.preview_only:
            self._prefill_hashtags(result.property_info, overwrite=True)
        elif not self.tags_var.get().strip():
            self._prefill_hashtags(result.property_info)
        memo = result.research.strip()
        if "## 수집된 매물정보" not in memo:
            memo = (
                "## 수집된 매물정보\n\n"
                f"{result.property_info.summary()}\n\n"
                "## 공부상·API 사실관계 확인\n\n"
                f"{memo}"
            ).strip()
        self._replace_text(self.research_text, memo)
        self._update_map_result(result)
        self._append_log(f"결과 저장 폴더: {result.output_dir}")
        if result.generation_warning:
            self._append_log(f"[주의] {result.generation_warning}")
        if result.blog_markdown_path:
            self._append_log(f"post_blog.py용 원고: {result.blog_markdown_path}")
        if result.thumbnail_path:
            self._show_thumbnail(Path(result.thumbnail_path))

    def _prefill_hashtags(self, property_info, *, overwrite: bool = False) -> None:
        """매물 데이터로 해시태그를 미리 만들어 blog자료 해시태그 칸에 채운다."""
        if not overwrite and self.tags_var.get().strip():
            return
        try:
            from naver_blog_automation.prompt_builder import build_hashtags

            tags = build_hashtags(property_info)
        except Exception:  # noqa: BLE001
            tags = []
        if tags:
            self.tags_var.set(" ".join(f"#{tag}" for tag in tags))

    def _show_thumbnail(self, path: Path) -> None:
        try:
            from PIL import Image, ImageTk

            with Image.open(path) as image:
                preview = image.convert("RGB")
                preview.thumbnail((420, 420))
                self.image_photo = ImageTk.PhotoImage(preview)
            self.image_preview_label.configure(
                image=self.image_photo,
                text="",
            )
            self.image_status_var.set(f"저장 위치: {path}")
            self._append_log(f"대표 이미지: {path}")
        except ModuleNotFoundError:
            # Pillow 미설치: 이미지는 이미 저장되었고 첨부도 가능하다. 미리보기만 불가.
            self.image_photo = None
            self.image_preview_label.configure(
                image="",
                text=(
                    "이미지는 저장되었지만 앱 안 미리보기에는 Pillow가 필요합니다.\n"
                    f"저장 위치: {path}\n\n"
                    "미리보기를 켜려면 프로그램 폴더에서 아래를 한 번 실행하세요:\n"
                    "  .venv/bin/pip install Pillow   (Windows: .venv\\Scripts\\pip install Pillow)\n"
                    "설치 없이도 이 이미지는 '이미지 첨부'에서 그대로 사용할 수 있습니다."
                ),
            )
            self.image_status_var.set(f"저장 위치: {path} (미리보기: Pillow 필요)")
            self._append_log(
                f"대표 이미지 저장: {path} · 미리보기는 Pillow 미설치로 생략"
            )
        except Exception as exc:
            self.image_photo = None
            self.image_preview_label.configure(
                image="",
                text=f"이미지 미리보기 실패\n{exc}\n저장 위치: {path}",
            )
            self.image_status_var.set(str(path))

    def _update_map_result(self, result: WorkflowResult) -> None:
        self.current_dynamic_map_url = ""
        self.current_map_url = result.map_url.strip()
        self.current_roadview_url = result.roadview_url.strip()
        self.current_latitude = result.latitude.strip()
        self.current_longitude = result.longitude.strip()
        self.map_title_var.set(result.property_info.name)
        coordinate_text = (
            f" · 위도 {self.current_latitude}, 경도 {self.current_longitude}"
            if self.current_latitude and self.current_longitude
            else ""
        )
        self.map_address_var.set(
            f"{result.property_info.address}{coordinate_text}"
        )

        dynamic_state = (
            "normal"
            if (
                self.settings.kakao_javascript_key
                and self.current_latitude
                and self.current_longitude
            )
            else "disabled"
        )
        self.research_map_button.configure(state=dynamic_state)
        self.map_view_button.configure(state=dynamic_state)
        self.roadview_view_button.configure(state=dynamic_state)
        self.map_zoom_in_button.configure(state=dynamic_state)
        self.map_zoom_out_button.configure(state=dynamic_state)
        self.map_refresh_button.configure(state=dynamic_state)
        self.open_map_external_button.configure(
            state="normal" if self.current_map_url else "disabled"
        )
        self.open_roadview_external_button.configure(
            state="normal" if self.current_roadview_url else "disabled"
        )

        for item in self.facility_tree.get_children():
            self.facility_tree.delete(item)
        for category, places in result.nearby_places.items():
            for place in places:
                distance = place.get("distance_m")
                distance_text = (
                    f"{int(distance):,}m"
                    if isinstance(distance, (int, float))
                    else "미확인"
                )
                self.facility_tree.insert(
                    "",
                    "end",
                    values=(
                        category,
                        place.get("name") or "이름 미확인",
                        distance_text,
                        place.get("road_address") or "",
                    ),
                )
        if not self.facility_tree.get_children():
            self.facility_tree.insert(
                "",
                "end",
                values=(
                    "안내",
                    "주변시설 데이터 없음",
                    "-",
                    "Kakao REST API 키와 정확한 주소를 확인해 주세요.",
                ),
            )
        self._render_map_status()
        if dynamic_state == "normal":
            self.root.after(100, self._load_embedded_map)

    def _show_map_tab(self) -> None:
        # 지도는 '⚙ 고급' 안의 내부 탭이므로 바깥 탭 → 내부 탭 순으로 선택한다.
        self.notebook.select(self.advanced_tab)
        self.advanced_notebook.select(self.map_tab)
        self._load_embedded_map()

    def _render_map_status(self) -> None:
        if not self.current_latitude or not self.current_longitude:
            text = (
                "표시할 좌표가 없습니다.\n\n"
                "Kakao REST API 키와 매물 주소를 확인한 뒤 데이터를 다시 불러와 주세요."
            )
            status = "동적 지도를 열 좌표가 없습니다."
        elif not self.settings.kakao_javascript_key:
            text = (
                "Kakao JavaScript 키가 필요합니다.\n\n"
                "환경설정 탭에 JavaScript 키를 저장하면\n"
                "동적 지도와 로드뷰를 같은 지도 페이지에서 확인할 수 있습니다."
            )
            status = "JavaScript 키를 저장해 주세요."
        else:
            text = (
                "동적 지도 준비가 완료되었습니다.\n\n"
                "잠시 후 이 영역에 지도가 표시됩니다.\n"
                "상단 버튼으로 지도와 로드뷰를 전환할 수 있습니다."
            )
            status = (
                "지도와 로드뷰는 외부 브라우저가 아닌 프로그램 안에서 표시됩니다."
            )
        self.map_preview_label.configure(image="", text=text)
        self.map_status_var.set(status)

    def _build_dynamic_map_url(self, *, renew: bool = False) -> str:
        if self.last_result is None:
            raise ValueError("먼저 매물 데이터를 불러와 주세요.")
        if not self.settings.kakao_javascript_key:
            raise ValueError(
                "환경설정 탭에서 Kakao JavaScript 키를 저장해 주세요."
            )
        if not self.current_latitude or not self.current_longitude:
            raise ValueError("동적 지도를 열 수 있는 매물 좌표가 없습니다.")
        if self.current_dynamic_map_url and not renew:
            return self.current_dynamic_map_url
        if self.map_server is None:
            self.map_server = KakaoMapServer()
        self.current_dynamic_map_url = self.map_server.register(
            javascript_key=self.settings.kakao_javascript_key,
            title=self.last_result.property_info.name,
            address=self.last_result.property_info.address,
            latitude=self.current_latitude,
            longitude=self.current_longitude,
            nearby_places=self.last_result.nearby_places,
        )
        return self.current_dynamic_map_url

    def _ensure_map_renderer(self) -> EmbeddedMapRenderer:
        if self.map_renderer is None:
            self.map_renderer = EmbeddedMapRenderer(
                on_frame=lambda image, width, height: self.events.put(
                    ("map_frame", (image, width, height))
                ),
                on_error=lambda message: self.events.put(
                    ("map_render_error", message)
                ),
                on_status=lambda message: self.events.put(
                    ("map_render_status", message)
                ),
                browser_channel=self.settings.browser_channel,
            )
        return self.map_renderer

    def _map_viewport_size(self) -> tuple[int, int]:
        width = max(360, self.map_preview_label.winfo_width())
        height = max(280, self.map_preview_label.winfo_height())
        return width, height

    def _load_embedded_map(self, *, renew: bool = False) -> None:
        try:
            url = self._build_dynamic_map_url(renew=renew)
        except Exception as exc:
            self.map_status_var.set(str(exc))
            return
        width, height = self._map_viewport_size()
        self._ensure_map_renderer().load(url, width, height)
        self.map_status_var.set(
            "프로그램 안에서 카카오 지도를 불러오고 있습니다…"
        )

    def _show_embedded_map(self) -> None:
        self.map_view_button.configure(style="Primary.TButton")
        self.roadview_view_button.configure(style="Secondary.TButton")
        if self.map_renderer is None:
            self._load_embedded_map()
            return
        self.map_renderer.show_map()
        self.map_status_var.set("프로그램 안의 지도 화면으로 전환합니다…")

    def _show_embedded_roadview(self) -> None:
        self.map_view_button.configure(style="Secondary.TButton")
        self.roadview_view_button.configure(style="Primary.TButton")
        if self.map_renderer is None:
            self._load_embedded_map()
        if self.map_renderer is not None:
            self.map_renderer.show_roadview()
        self.map_status_var.set(
            "같은 영역에서 로드뷰를 불러오고 있습니다…"
        )

    def _zoom_embedded_map(self, delta: int) -> None:
        if self.map_renderer is not None:
            self.map_renderer.zoom(delta)

    def _refresh_map(self) -> None:
        self._load_embedded_map(renew=True)

    def _open_current_map_external(self) -> None:
        if self.current_map_url:
            webbrowser.open(self.current_map_url)

    def _open_current_roadview_external(self) -> None:
        if self.current_roadview_url:
            webbrowser.open(self.current_roadview_url)

    def _schedule_embedded_map_resize(self, _event=None) -> None:
        if self.map_resize_after_id is not None:
            self.root.after_cancel(self.map_resize_after_id)
        self.map_resize_after_id = self.root.after(
            350,
            self._resize_embedded_map,
        )

    def _resize_embedded_map(self) -> None:
        self.map_resize_after_id = None
        if self.map_renderer is None:
            return
        width, height = self._map_viewport_size()
        if (width, height) != self.map_render_size:
            self.map_renderer.resize(width, height)

    def _embedded_map_coordinates(self, event) -> tuple[float, float]:
        image_width, image_height = self.map_render_size
        widget_width = self.map_preview_label.winfo_width()
        widget_height = self.map_preview_label.winfo_height()
        offset_x = max((widget_width - image_width) / 2, 0)
        offset_y = max((widget_height - image_height) / 2, 0)
        return event.x - offset_x, event.y - offset_y

    def _embedded_map_pointer(self, kind: str, event) -> str:
        if self.map_renderer is not None:
            x, y = self._embedded_map_coordinates(event)
            self.map_renderer.pointer(kind, x, y)
        return "break"

    def _embedded_map_wheel(self, event) -> str:
        if self.map_renderer is not None:
            if getattr(event, "num", None) == 4:
                delta_y = -500
            elif getattr(event, "num", None) == 5:
                delta_y = 500
            else:
                delta_y = -float(getattr(event, "delta", 0))
            self.map_renderer.wheel(delta_y)
        return "break"

    @staticmethod
    def _replace_text(widget: tk.Text, value: str) -> None:
        widget.delete("1.0", "end")
        widget.insert("1.0", value)

    def _append_log(self, message: str) -> None:
        self.log_text.insert("end", f"{message}\n")
        self.log_text.see("end")

    def _on_close(self) -> None:
        try:
            self._apply_form_settings()
        finally:
            if self.map_renderer is not None:
                self.map_renderer.stop()
            if self.map_server is not None:
                self.map_server.stop()
            self.root.destroy()


def main() -> None:
    root = tk.Tk()
    BlogAutomationApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
