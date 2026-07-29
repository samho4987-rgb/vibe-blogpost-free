"""
claude_theme.py — 클로드(Claude) 디자인 언어를 Tkinter/ttk 앱에 입히는 테마 모듈

사용법 (2줄이면 끝):

    from claude_theme import apply_claude_theme, C, S, F

    class BlogApp:
        def _configure_style(self) -> None:
            apply_claude_theme(self.root)          # 기존 함수 내용을 이 한 줄로 교체

기존 app.py가 쓰던 스타일 이름(App.TFrame, White.TFrame, Header.TLabel,
Primary.TButton, Safe.TButton, StepBusy.TButton, StepDone.TButton,
Secondary.TButton, Compact.TButton, Section.TLabelframe, Status.TLabel)을
그대로 유지하므로, 위젯 코드를 고칠 필요가 없다.

색을 직접 쓰던 자리(bg="#16344c" 등)는 C.NAVY 대신 C.INK 처럼
토큰 상수로 바꾸기만 하면 된다. 아래 MIGRATION 표 참고.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk


# ─────────────────────────────────────────────────────────────────────────────
# 1. 색 토큰 (Color tokens)
#    "무슨 색인가"가 아니라 "어디에 쓰는 색인가"로 이름을 붙인다.
#    나중에 색을 바꿔도 이름은 그대로라 코드를 고칠 일이 없다.
# ─────────────────────────────────────────────────────────────────────────────
class _Light:
    """밝은 테마 — 클로드의 기본. 파랑·회색 대신 따뜻한 크림 바탕."""

    # 바탕 (뒤로 갈수록 진해짐)
    CANVAS = "#FAF9F5"          # 창 전체 배경 (크림)
    SURFACE = "#FFFFFF"         # 카드·패널 배경
    SURFACE_SOFT = "#F5F0E8"    # 살짝 눌린 영역, 코드블록, 비활성 탭
    SURFACE_CARD = "#EFE9DE"    # 강조 카드 배경
    INK = "#141413"             # 헤더 등 어두운 면 / 가장 진한 글자

    # 선
    LINE = "#E6DFD8"            # 기본 테두리 (헤어라인)
    LINE_SOFT = "#EFEAE3"       # 더 연한 구분선

    # 글자
    TEXT = "#3D3D3A"            # 본문
    TEXT_STRONG = "#141413"     # 제목·강조
    TEXT_MUTED = "#6C6A64"      # 보조 설명
    TEXT_FAINT = "#75726B"      # 캡션·플레이스홀더 (흰 바탕에서 4.8:1)
    TEXT_ON_DARK = "#FAF9F5"    # 어두운 면 위 글자
    TEXT_ON_DARK_SOFT = "#A09D96"
    TEXT_ON_ACCENT = "#FFFFFF"  # 코럴 버튼 위 글자

    # 강조 (클로드의 상징색 — 코럴)
    # 주의: 브랜드 코럴(#D97757) 위에 흰 글자를 얹으면 대비가 3.1:1 밖에 안 된다.
    # 그래서 "글자를 얹는 면"에는 한 톤 진한 CORAL_DEEP(4.5:1)을 쓴다.
    CORAL = "#D97757"           # 브랜드 강조 — 진행바, 포커스링, 아이콘, 얇은 선
    CORAL_DEEP = "#BC5A38"      # 흰 글자를 얹는 버튼 배경
    CORAL_HOVER = "#A9583E"     # 마우스 올렸을 때
    CORAL_PRESS = "#94472F"     # 눌렸을 때
    CORAL_SOFT = "#F7E8E1"      # 코럴 계열 연한 배경
    CORAL_DISABLED = "#E6DFD8"  # 비활성

    # 상태색 — 면(_FILL)과 글자(_TEXT)를 따로 둔다. 같은 색을 둘 다 쓰면 대비가 깨진다.
    SUCCESS = "#4F7A55"         # 초록 버튼 면 (흰 글자 4.9:1)
    SUCCESS_TEXT = "#3E6344"    # 연한 초록 배경 위 글자 (5.8:1)
    SUCCESS_SOFT = "#E7EFE6"
    WARNING = "#9A6B1E"         # 주황 버튼 면 (흰 글자 4.7:1)
    WARNING_TEXT = "#7E5610"
    WARNING_SOFT = "#F7EEDB"
    ERROR = "#B03A3A"
    ERROR_TEXT = "#9E2F2F"
    ERROR_SOFT = "#F7E3E3"
    INFO = "#456380"
    INFO_TEXT = "#3D5A73"
    INFO_SOFT = "#E6EDF3"

    # 포커스 링
    FOCUS = "#D97757"

    IS_DARK = False


class _Dark:
    """어두운 테마 — 같은 이름, 다른 값. 코드는 하나도 안 바뀐다."""

    CANVAS = "#141413"
    SURFACE = "#1F1E1B"
    SURFACE_SOFT = "#252320"
    SURFACE_CARD = "#2A2825"
    INK = "#0F0E0D"

    LINE = "#332F2B"
    LINE_SOFT = "#292623"

    TEXT = "#E8E6DF"
    TEXT_STRONG = "#FAF9F5"
    TEXT_MUTED = "#A09D96"
    TEXT_FAINT = "#8E8B82"
    TEXT_ON_DARK = "#FAF9F5"
    TEXT_ON_DARK_SOFT = "#A09D96"
    # 어두운 화면에서는 밝은 코럴 + 어두운 글자가 더 잘 읽힌다(5.9:1)
    TEXT_ON_ACCENT = "#1A1613"

    CORAL = "#D97757"
    CORAL_DEEP = "#D97757"
    CORAL_HOVER = "#E08A6D"
    CORAL_PRESS = "#C4643F"
    CORAL_SOFT = "#3A2A24"
    CORAL_DISABLED = "#3A3632"

    SUCCESS = "#4F7A55"
    SUCCESS_TEXT = "#9ECFA4"
    SUCCESS_SOFT = "#222E24"
    WARNING = "#9A6B1E"
    WARNING_TEXT = "#E3B75E"
    WARNING_SOFT = "#332B18"
    ERROR = "#B03A3A"
    ERROR_TEXT = "#EE9494"
    ERROR_SOFT = "#3A2222"
    INFO = "#456380"
    INFO_TEXT = "#A6C4DC"
    INFO_SOFT = "#1E2833"

    FOCUS = "#D97757"

    IS_DARK = True


class _Tokens:
    """현재 활성 팔레트를 가리키는 얇은 껍데기.

    `from claude_theme import C` 로 가져다 써도, 나중에
    apply_claude_theme(dark=True)를 부르면 C.CANVAS 값이 알아서 바뀐다.
    (그냥 모듈 변수로 두면 import 시점 값이 고정돼 다크모드가 안 먹는다.)
    """

    _palette = _Light

    def __getattr__(self, name):
        try:
            return getattr(type(self)._palette, name)
        except AttributeError as exc:
            raise AttributeError(f"색 토큰 '{name}' 이(가) 없습니다") from exc

    def __dir__(self):
        return sorted(k for k in vars(type(self)._palette) if k.isupper())

    def __repr__(self):
        return f"<claude_theme.C {'dark' if self.IS_DARK else 'light'}>"


#: 현재 활성 색 토큰. apply_claude_theme(dark=True)를 부르면 값이 통째로 바뀐다.
C = _Tokens()


def set_palette(dark: bool) -> None:
    """색만 바꾼다(테마 재적용 없이)."""
    _Tokens._palette = _Dark if dark else _Light


# ─────────────────────────────────────────────────────────────────────────────
# 2. 간격 토큰 (Spacing) — 전부 4의 배수. 눈대중 금지.
# ─────────────────────────────────────────────────────────────────────────────
class S:
    XXS = 2
    XS = 4
    SM = 8
    MD = 12
    LG = 16
    XL = 24
    XXL = 32
    XXXL = 48

    # 자주 쓰는 조합 (가로, 세로)
    PAD_BUTTON = (18, 11)       # 주 버튼 안쪽 여백
    PAD_BUTTON_SM = (12, 6)     # 작은 버튼
    PAD_CARD = (20, 18)         # 카드 안쪽 여백
    PAD_PAGE = 28               # 창 가장자리 여백


# ─────────────────────────────────────────────────────────────────────────────
# 3. 모서리 둥글기 (Radius)
#    주의: ttk 위젯은 모서리를 둥글게 못 한다. RoundedButton / Card 헬퍼를 쓸 것.
# ─────────────────────────────────────────────────────────────────────────────
class R:
    SM = 6
    MD = 10      # 버튼·입력창 기본
    LG = 16      # 카드
    XL = 24      # 큰 패널
    PILL = 999   # 알약 모양 칩


# ─────────────────────────────────────────────────────────────────────────────
# 4. 글꼴 토큰 (Typography)
#    크기 차이 + 굵기 차이로 위계를 만든다. 색만으로 위계를 만들지 않는다.
# ─────────────────────────────────────────────────────────────────────────────
_PREFERRED_SANS = (
    "Pretendard",
    "Apple SD Gothic Neo",   # macOS
    "Malgun Gothic",         # Windows
    "Noto Sans KR",
    "AppleGothic",
    "DejaVu Sans",
)
_PREFERRED_SERIF = (
    "Nanum Myeongjo",
    "Apple SD Gothic Neo",
    "Times New Roman",
    "DejaVu Serif",
)
_PREFERRED_MONO = (
    "SFMono-Regular",
    "JetBrains Mono",
    "D2Coding",
    "Consolas",
    "Menlo",
    "DejaVu Sans Mono",
)


def _pick_family(candidates: tuple[str, ...], installed: set[str]) -> str:
    for name in candidates:
        if name in installed:
            return name
    return candidates[-1]


class F:
    """글꼴. apply_claude_theme()이 실행되며 실제 설치된 글꼴로 채워진다."""

    SANS = "Apple SD Gothic Neo"
    SERIF = "Apple SD Gothic Neo"
    MONO = "Menlo"

    # 크기 (pt)
    SIZE_DISPLAY = 26   # 앱 타이틀
    SIZE_H1 = 20
    SIZE_H2 = 15
    SIZE_H3 = 13
    SIZE_BODY = 12
    SIZE_SMALL = 11
    SIZE_CAPTION = 10

    # 바로 쓰는 튜플들 — ttk의 font= 에 그대로 넣으면 된다
    @classmethod
    def display(cls):
        return (cls.SERIF, cls.SIZE_DISPLAY, "bold")

    @classmethod
    def h1(cls):
        return (cls.SANS, cls.SIZE_H1, "bold")

    @classmethod
    def h2(cls):
        return (cls.SANS, cls.SIZE_H2, "bold")

    @classmethod
    def h3(cls):
        return (cls.SANS, cls.SIZE_H3, "bold")

    @classmethod
    def body(cls):
        return (cls.SANS, cls.SIZE_BODY)

    @classmethod
    def body_bold(cls):
        return (cls.SANS, cls.SIZE_BODY, "bold")

    @classmethod
    def small(cls):
        return (cls.SANS, cls.SIZE_SMALL)

    @classmethod
    def small_bold(cls):
        return (cls.SANS, cls.SIZE_SMALL, "bold")

    @classmethod
    def caption(cls):
        return (cls.SANS, cls.SIZE_CAPTION)

    @classmethod
    def mono(cls):
        return (cls.MONO, cls.SIZE_SMALL)


# ─────────────────────────────────────────────────────────────────────────────
# 5. 기존 색 → 새 토큰 대응표 (app.py를 고칠 때 이 표대로 치환하면 된다)
# ─────────────────────────────────────────────────────────────────────────────
MIGRATION = {
    "#f3f6f8": "C.CANVAS",        # 옛 BG
    "#16344c": "C.INK",           # 옛 NAVY
    "#2b6f8a": "C.CORAL_DEEP",    # 옛 BLUE (주 버튼)
    "#225a70": "C.CORAL_PRESS",   # 옛 BLUE active
    "#2f7d61": "C.SUCCESS",       # 옛 GREEN
    "#28684f": "C.SUCCESS",       # 옛 GREEN active
    "#e0a12e": "C.WARNING",       # 진행중 버튼
    "#c88f27": "C.WARNING",
    "#3f9068": "C.SUCCESS",       # 완료 버튼
    "#5f9e80": "C.SUCCESS",
    "#357a58": "C.SUCCESS",
    "#e8eef2": "C.SURFACE_SOFT",  # 보조 버튼 배경
    "#eaf1f5": "C.SURFACE_SOFT",  # 상태 표시줄
    "#d8e0e5": "C.LINE",          # 테두리
    "#DCE4EC": "C.TEXT_ON_DARK_SOFT",
    "#dce8ef": "C.TEXT_ON_DARK_SOFT",
    "#526574": "C.TEXT_MUTED",
    "#6b7780": "C.TEXT_MUTED",
    "#75838d": "C.TEXT_FAINT",
    "#26343c": "C.TEXT_STRONG",
    "white": "C.SURFACE",
}


# ─────────────────────────────────────────────────────────────────────────────
# 6. 테마 적용 함수
# ─────────────────────────────────────────────────────────────────────────────
def apply_claude_theme(root: tk.Misc, dark: bool = False) -> ttk.Style:
    """루트 창에 클로드 디자인 테마를 적용하고 ttk.Style을 돌려준다."""
    set_palette(dark)

    # 설치된 글꼴 중 가장 앞선 후보를 고른다
    try:
        installed = set(tkfont.families(root))
    except Exception:
        installed = set()
    F.SANS = _pick_family(_PREFERRED_SANS, installed)
    F.SERIF = _pick_family(_PREFERRED_SERIF, installed)
    F.MONO = _pick_family(_PREFERRED_MONO, installed)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")   # clam이라야 배경색·테두리색이 먹는다
    except tk.TclError:
        pass

    try:
        root.configure(bg=C.CANVAS)
    except tk.TclError:
        pass

    _base(style)
    _frames(style)
    _labels(style)
    _buttons(style)
    _inputs(style)
    _containers(style)
    _misc(style)
    return style


# --- 기본값 --------------------------------------------------------------
def _base(style: ttk.Style) -> None:
    style.configure(
        ".",
        background=C.CANVAS,
        foreground=C.TEXT,
        fieldbackground=C.SURFACE,
        bordercolor=C.LINE,
        lightcolor=C.LINE,
        darkcolor=C.LINE,
        focuscolor=C.FOCUS,
        font=F.body(),
    )


# --- 프레임 --------------------------------------------------------------
def _frames(style: ttk.Style) -> None:
    style.configure("App.TFrame", background=C.CANVAS)
    style.configure("TFrame", background=C.CANVAS)
    style.configure("White.TFrame", background=C.SURFACE)     # 기존 이름 유지
    style.configure("Surface.TFrame", background=C.SURFACE)
    style.configure("Soft.TFrame", background=C.SURFACE_SOFT)
    style.configure("Card.TFrame", background=C.SURFACE, relief="flat")
    style.configure("Header.TFrame", background=C.INK)
    style.configure(
        "Divider.TFrame", background=C.LINE, height=1
    )  # 구분선: 높이 1짜리 프레임


# --- 라벨 ----------------------------------------------------------------
def _labels(style: ttk.Style) -> None:
    style.configure("TLabel", background=C.CANVAS, foreground=C.TEXT, font=F.body())
    style.configure(
        "Header.TLabel",
        background=C.INK,
        foreground=C.TEXT_ON_DARK,
        font=F.display(),
    )
    style.configure(
        "HeaderSub.TLabel",
        background=C.INK,
        foreground=C.TEXT_ON_DARK_SOFT,
        font=F.small(),
    )
    style.configure(
        "H1.TLabel", background=C.SURFACE, foreground=C.TEXT_STRONG, font=F.h1()
    )
    style.configure(
        "H2.TLabel", background=C.SURFACE, foreground=C.TEXT_STRONG, font=F.h2()
    )
    style.configure(
        "H3.TLabel", background=C.SURFACE, foreground=C.TEXT_STRONG, font=F.h3()
    )
    style.configure(
        "Body.TLabel", background=C.SURFACE, foreground=C.TEXT, font=F.body()
    )
    style.configure(
        "Muted.TLabel", background=C.SURFACE, foreground=C.TEXT_MUTED, font=F.small()
    )
    style.configure(
        "Caption.TLabel", background=C.SURFACE, foreground=C.TEXT_FAINT,
        font=F.caption(),
    )
    style.configure(
        "Status.TLabel",
        background=C.SURFACE_SOFT,
        foreground=C.TEXT,
        padding=(S.LG, S.MD),
        font=F.small(),
    )
    # 상태 배지 (칩)
    for name, fg, bg in (
        ("Success", C.SUCCESS_TEXT, C.SUCCESS_SOFT),
        ("Warning", C.WARNING_TEXT, C.WARNING_SOFT),
        ("Error", C.ERROR_TEXT, C.ERROR_SOFT),
        ("Info", C.INFO_TEXT, C.INFO_SOFT),
    ):
        style.configure(
            f"{name}Badge.TLabel",
            background=bg,
            foreground=fg,
            padding=(S.MD, S.XS),
            font=F.small_bold(),
        )


# --- 버튼 ----------------------------------------------------------------
def _button(
    style: ttk.Style,
    name: str,
    bg: str,
    fg: str,
    hover: str,
    press: str,
    padding=S.PAD_BUTTON,
    font=None,
    border: str | None = None,
) -> None:
    style.configure(
        name,
        background=bg,
        foreground=fg,
        padding=padding,
        font=font or F.small_bold(),
        borderwidth=1 if border else 0,
        relief="solid" if border else "flat",
        bordercolor=border or bg,
        lightcolor=border or bg,
        darkcolor=border or bg,
        focusthickness=0,
        anchor="center",
    )
    style.map(
        name,
        background=[
            ("disabled", C.CORAL_DISABLED if bg == C.CORAL_DEEP else C.SURFACE_SOFT),
            ("pressed", press),
            ("active", hover),
        ],
        foreground=[("disabled", C.TEXT_FAINT)],
        bordercolor=[("active", border or hover)],
        lightcolor=[("active", border or hover)],
        darkcolor=[("active", border or hover)],
    )


def _buttons(style: ttk.Style) -> None:
    # 주 동작 — 화면당 1개가 원칙
    _button(style, "Primary.TButton", C.CORAL_DEEP, C.TEXT_ON_ACCENT,
            C.CORAL_HOVER, C.CORAL_PRESS)
    # 보조 동작 — 테두리만 있는 버튼
    _button(style, "Secondary.TButton", C.SURFACE, C.TEXT_STRONG,
            C.SURFACE_SOFT, C.SURFACE_CARD, padding=S.PAD_BUTTON, border=C.LINE)
    # 배경 없는 버튼 (링크에 가까운 것)
    _button(style, "Ghost.TButton", C.CANVAS, C.TEXT_MUTED,
            C.SURFACE_SOFT, C.SURFACE_CARD, padding=S.PAD_BUTTON_SM)
    # 작은 버튼
    _button(style, "Compact.TButton", C.SURFACE, C.TEXT_STRONG,
            C.SURFACE_SOFT, C.SURFACE_CARD, padding=S.PAD_BUTTON_SM,
            font=F.caption(), border=C.LINE)
    # 되돌릴 수 없는 동작
    _button(style, "Danger.TButton", C.ERROR, "#FFFFFF", "#9C3232", "#8A2C2C")

    # ── 진행 단계 버튼 (기존 이름 유지) ─────────────────────────────
    _button(style, "Safe.TButton", C.SUCCESS, "#FFFFFF", "#456B4B", "#3B5C40")

    # 비활성 상태에서도 색이 유지돼야 하므로 map에 disabled를 명시한다
    style.configure(
        "StepBusy.TButton",
        background=C.WARNING, foreground="#FFFFFF", padding=S.PAD_BUTTON,
        font=F.small_bold(), borderwidth=0, relief="flat", anchor="center",
    )
    style.map(
        "StepBusy.TButton",
        background=[("disabled", C.WARNING), ("pressed", "#7E5610"),
                    ("active", "#8A5F14")],
        foreground=[("disabled", "#FFFFFF")],
    )
    style.configure(
        "StepDone.TButton",
        background=C.SUCCESS, foreground="#FFFFFF", padding=S.PAD_BUTTON,
        font=F.small_bold(), borderwidth=0, relief="flat", anchor="center",
    )
    style.map(
        "StepDone.TButton",
        background=[("disabled", C.SUCCESS), ("pressed", "#3B5C40"),
                    ("active", "#456B4B")],
        foreground=[("disabled", "#FFFFFF")],
    )


# --- 입력 위젯 -----------------------------------------------------------
def _inputs(style: ttk.Style) -> None:
    style.configure(
        "TEntry",
        fieldbackground=C.SURFACE,
        foreground=C.TEXT_STRONG,
        bordercolor=C.LINE,
        lightcolor=C.LINE,
        darkcolor=C.LINE,
        insertcolor=C.CORAL,
        padding=(S.MD, S.SM + 1),
        relief="flat",
        borderwidth=1,
    )
    style.map(
        "TEntry",
        bordercolor=[("focus", C.FOCUS), ("hover", C.TEXT_FAINT)],
        lightcolor=[("focus", C.FOCUS)],
        darkcolor=[("focus", C.FOCUS)],
        fieldbackground=[("disabled", C.SURFACE_SOFT)],
        foreground=[("disabled", C.TEXT_FAINT)],
    )

    style.configure(
        "TCombobox",
        fieldbackground=C.SURFACE,
        background=C.SURFACE,
        foreground=C.TEXT_STRONG,
        arrowcolor=C.TEXT_MUTED,
        bordercolor=C.LINE,
        lightcolor=C.LINE,
        darkcolor=C.LINE,
        padding=(S.MD, S.SM),
        relief="flat",
        borderwidth=1,
    )
    style.map(
        "TCombobox",
        bordercolor=[("focus", C.FOCUS)],
        fieldbackground=[("readonly", C.SURFACE), ("disabled", C.SURFACE_SOFT)],
        arrowcolor=[("active", C.CORAL)],
    )

    # 체크박스·라디오: 꺼짐=흰 바탕에 회색 테두리, 켜짐=코럴 바탕에 흰 표시
    for widget in ("TCheckbutton", "TRadiobutton"):
        style.configure(
            widget,
            background=C.SURFACE,
            foreground=C.TEXT,
            indicatorbackground=C.SURFACE,
            indicatorforeground=C.TEXT_ON_ACCENT,
            indicatorsize=13,
            indicatormargin=(0, 0, S.SM, 0),
            upperbordercolor=C.LINE,
            lowerbordercolor=C.LINE,
            padding=(S.XS, S.XS),
            focusthickness=0,
            font=F.body(),
        )
        style.map(
            widget,
            indicatorbackground=[
                ("disabled", C.SURFACE_SOFT),
                ("selected", "pressed", C.CORAL_PRESS),
                ("selected", C.CORAL),
                ("active", C.SURFACE_SOFT),
            ],
            indicatorforeground=[("selected", C.TEXT_ON_ACCENT)],
            upperbordercolor=[("selected", C.CORAL), ("active", C.TEXT_FAINT)],
            lowerbordercolor=[("selected", C.CORAL), ("active", C.TEXT_FAINT)],
            background=[("active", C.SURFACE)],
            foreground=[("disabled", C.TEXT_FAINT)],
        )


# --- 묶는 위젯 -----------------------------------------------------------
def _containers(style: ttk.Style) -> None:
    style.configure(
        "TLabelframe",
        background=C.SURFACE,
        bordercolor=C.LINE,
        lightcolor=C.LINE,
        darkcolor=C.LINE,
        borderwidth=1,
        relief="solid",
        padding=S.LG,
    )
    style.configure(
        "TLabelframe.Label",
        background=C.SURFACE,
        foreground=C.TEXT_STRONG,
        font=F.h3(),
    )
    # 기존 이름 유지
    style.configure(
        "Section.TLabelframe",
        background=C.SURFACE,
        bordercolor=C.LINE,
        lightcolor=C.LINE,
        darkcolor=C.LINE,
        borderwidth=1,
        relief="solid",
        padding=S.LG,
    )
    style.configure(
        "Section.TLabelframe.Label",
        background=C.SURFACE,
        foreground=C.TEXT_STRONG,
        font=F.h3(),
    )

    style.configure("TNotebook", background=C.CANVAS, borderwidth=0, tabmargins=(0, 0, 0, 0))
    style.configure(
        "TNotebook.Tab",
        background=C.CANVAS,
        foreground=C.TEXT_MUTED,
        padding=(S.LG, S.MD),
        borderwidth=0,
        font=F.small_bold(),
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", C.SURFACE)],
        foreground=[("selected", C.TEXT_STRONG), ("active", C.TEXT_STRONG)],
    )


# --- 나머지 --------------------------------------------------------------
def _misc(style: ttk.Style) -> None:
    style.configure(
        "Treeview",
        background=C.SURFACE,
        fieldbackground=C.SURFACE,
        foreground=C.TEXT,
        bordercolor=C.LINE,
        borderwidth=1,
        relief="flat",
        rowheight=30,
        font=F.small(),
    )
    style.configure(
        "Treeview.Heading",
        background=C.SURFACE_SOFT,
        foreground=C.TEXT_MUTED,
        relief="flat",
        padding=(S.MD, S.SM),
        font=F.caption(),
    )
    style.map(
        "Treeview",
        background=[("selected", C.CORAL_SOFT)],
        foreground=[("selected", C.TEXT_STRONG)],
    )
    style.map("Treeview.Heading", background=[("active", C.SURFACE_CARD)])

    style.configure(
        "Horizontal.TProgressbar",
        background=C.CORAL,
        troughcolor=C.SURFACE_SOFT,
        bordercolor=C.SURFACE_SOFT,
        lightcolor=C.CORAL,
        darkcolor=C.CORAL,
        borderwidth=0,
        thickness=6,
    )

    for orient in ("Vertical", "Horizontal"):
        style.configure(
            f"{orient}.TScrollbar",
            background=C.LINE,
            troughcolor=C.CANVAS,
            bordercolor=C.CANVAS,
            arrowcolor=C.TEXT_FAINT,
            lightcolor=C.LINE,
            darkcolor=C.LINE,
            borderwidth=0,
            relief="flat",
        )
        style.map(f"{orient}.TScrollbar", background=[("active", C.TEXT_FAINT)])

    style.configure("TSeparator", background=C.LINE)


# ─────────────────────────────────────────────────────────────────────────────
# 7. ttk가 못 하는 것들 — 둥근 모서리 헬퍼
# ─────────────────────────────────────────────────────────────────────────────
def rounded_rect(canvas: tk.Canvas, x1, y1, x2, y2, r, **kwargs):
    """캔버스에 모서리가 둥근 사각형을 그린다."""
    points = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class Card(tk.Frame):
    """헤어라인 테두리 + 넉넉한 여백을 가진 카드. 내용은 .body 에 넣는다.

        card = Card(parent)
        card.pack(fill="x", pady=S.MD)
        ttk.Label(card.body, text="제목", style="H3.TLabel").pack(anchor="w")
    """

    def __init__(self, master, padding=S.PAD_CARD, bg=None, border=None, **kw):
        border = border or C.LINE
        bg = bg or C.SURFACE
        super().__init__(master, bg=border, bd=0, highlightthickness=0, **kw)
        self.body = tk.Frame(self, bg=bg, bd=0, highlightthickness=0)
        px, py = padding if isinstance(padding, tuple) else (padding, padding)
        self.body.pack(fill="both", expand=True, padx=1, pady=1)
        self.body.configure(padx=px, pady=py)


class RoundedButton(tk.Canvas):
    """모서리가 둥근 버튼. ttk.Button으로는 안 되는 모양을 캔버스로 그린다.

        RoundedButton(parent, "글 만들기", self.on_click).pack()
    """

    def __init__(
        self,
        master,
        text: str,
        command=None,
        bg: str | None = None,
        fg: str | None = None,
        hover: str | None = None,
        press: str | None = None,
        radius: int = R.MD,
        padx: int = S.PAD_BUTTON[0],
        pady: int = S.PAD_BUTTON[1],
        font=None,
        parent_bg: str | None = None,
        **kw,
    ):
        self._bg = bg or C.CORAL_DEEP
        self._fg = fg or C.TEXT_ON_ACCENT
        self._hover = hover or C.CORAL_HOVER
        self._press = press or C.CORAL_PRESS
        self._command = command
        self._radius = radius
        self._enabled = True

        font = font or F.small_bold()
        probe = tkfont.Font(font=font)
        w = probe.measure(text) + padx * 2
        h = probe.metrics("linespace") + pady * 2

        super().__init__(
            master, width=w, height=h, highlightthickness=0, bd=0,
            bg=parent_bg or master.cget("bg") if hasattr(master, "cget") else C.CANVAS,
            **kw,
        )
        self._shape = rounded_rect(self, 1, 1, w - 1, h - 1, radius,
                                   fill=self._bg, outline=self._bg)
        self._label = self.create_text(
            w / 2, h / 2, text=text, fill=self._fg, font=font
        )
        self.bind("<Enter>", lambda e: self._paint(self._hover))
        self.bind("<Leave>", lambda e: self._paint(self._bg))
        self.bind("<ButtonPress-1>", lambda e: self._paint(self._press))
        self.bind("<ButtonRelease-1>", self._release)
        self.configure(cursor="hand2")

    def _paint(self, color: str) -> None:
        if self._enabled:
            self.itemconfigure(self._shape, fill=color, outline=color)

    def _release(self, _event) -> None:
        self._paint(self._hover)
        if self._enabled and self._command:
            self._command()

    def set_enabled(self, value: bool) -> None:
        self._enabled = value
        color = self._bg if value else C.CORAL_DISABLED
        self.itemconfigure(self._shape, fill=color, outline=color)
        self.itemconfigure(self._label, fill=self._fg if value else C.TEXT_FAINT)
        self.configure(cursor="hand2" if value else "arrow")


def divider(master, pady=S.LG) -> tk.Frame:
    """1px 구분선."""
    line = tk.Frame(master, bg=C.LINE, height=1, bd=0, highlightthickness=0)
    line.pack(fill="x", pady=pady)
    return line


__all__ = [
    "apply_claude_theme", "set_palette", "C", "S", "R", "F", "MIGRATION",
    "Card", "RoundedButton", "rounded_rect", "divider",
]
