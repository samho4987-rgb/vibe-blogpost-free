"""테마 미리보기 — python3.12 demo_theme.py"""
import sys
import tkinter as tk
from tkinter import ttk

from claude_theme import (
    apply_claude_theme, C, S, F, Card, RoundedButton, divider,
)

DARK = "--dark" in sys.argv

root = tk.Tk()
root.title("클로드 디자인 미리보기")
root.geometry("880x880")
apply_claude_theme(root, dark=DARK)

# ── 헤더 ──────────────────────────────────────────────────────────
header = tk.Frame(root, bg=C.INK, height=104)
header.pack(fill="x")
header.pack_propagate(False)
ttk.Label(header, text="네이버 블로그 매물 포스팅 자동화",
          style="Header.TLabel").pack(anchor="w", padx=S.PAD_PAGE, pady=(S.XL, 0))
ttk.Label(header, text="매물 정보를 넣으면 블로그 원고와 대표 이미지를 만들어 줍니다",
          style="HeaderSub.TLabel").pack(anchor="w", padx=S.PAD_PAGE, pady=(2, 0))

body = ttk.Frame(root, style="App.TFrame")
body.pack(fill="both", expand=True, padx=S.PAD_PAGE, pady=S.XL)

# ── 카드 1: 입력 ──────────────────────────────────────────────────
c1 = Card(body)
c1.pack(fill="x")
ttk.Label(c1.body, text="1단계 · 매물 정보", style="H3.TLabel").pack(anchor="w")
ttk.Label(c1.body, text="매물 번호를 넣거나 주소를 직접 입력하세요.",
          style="Muted.TLabel").pack(anchor="w", pady=(S.XS, S.LG))

row = tk.Frame(c1.body, bg=C.SURFACE)
row.pack(fill="x")
ttk.Entry(row, width=34).pack(side="left")
ttk.Combobox(row, values=["아파트", "빌라", "오피스텔"], width=12,
             state="readonly").pack(side="left", padx=(S.SM, 0))
ttk.Button(row, text="불러오기", style="Secondary.TButton").pack(side="left",
                                                              padx=(S.SM, 0))

opts = tk.Frame(c1.body, bg=C.SURFACE)
opts.pack(fill="x", pady=(S.MD, 0))
ttk.Checkbutton(opts, text="지도 이미지 포함").pack(side="left")
ttk.Radiobutton(opts, text="숏폼", value=1).pack(side="left", padx=(S.LG, 0))
ttk.Radiobutton(opts, text="롱폼", value=2).pack(side="left", padx=(S.SM, 0))

# ── 카드 2: 실행 단계 ──────────────────────────────────────────────
c2 = Card(body)
c2.pack(fill="x", pady=(S.LG, 0))
ttk.Label(c2.body, text="2단계 · 실행", style="H3.TLabel").pack(anchor="w")
divider(c2.body, pady=S.MD)

steps = tk.Frame(c2.body, bg=C.SURFACE)
steps.pack(fill="x")
ttk.Button(steps, text="✓ 정보 수집", style="StepDone.TButton",
           state="disabled").pack(side="left")
ttk.Button(steps, text="원고 작성 중…", style="StepBusy.TButton",
           state="disabled").pack(side="left", padx=(S.SM, 0))
ttk.Button(steps, text="이미지 만들기", style="Secondary.TButton").pack(
    side="left", padx=(S.SM, 0))

ttk.Progressbar(c2.body, mode="determinate", value=62,
                style="Horizontal.TProgressbar").pack(fill="x", pady=(S.LG, S.SM))

badges = tk.Frame(c2.body, bg=C.SURFACE)
badges.pack(fill="x", pady=(S.SM, 0))
for text, st in (("완료", "Success"), ("확인 필요", "Warning"),
                 ("실패", "Error"), ("안내", "Info")):
    ttk.Label(badges, text=text, style=f"{st}Badge.TLabel").pack(
        side="left", padx=(0, S.SM))

# ── 카드 3: 결과 표 ────────────────────────────────────────────────
c3 = Card(body)
c3.pack(fill="both", expand=True, pady=(S.LG, 0))
ttk.Label(c3.body, text="3단계 · 결과", style="H3.TLabel").pack(anchor="w",
                                                             pady=(0, S.MD))
tree = ttk.Treeview(c3.body, columns=("a", "b", "c"), show="headings", height=4)
for cid, title, w in (("a", "매물", 240), ("b", "상태", 120), ("c", "만든 시각", 160)):
    tree.heading(cid, text=title)
    tree.column(cid, width=w, anchor="w")
tree.insert("", "end", values=("래미안 강남 84㎡", "발행 완료", "07-29 10:12"))
tree.insert("", "end", values=("자이 서초 59㎡", "원고 작성", "07-29 10:31"))
tree.insert("", "end", values=("힐스테이트 판교 101㎡", "대기", "07-29 10:44"))
tree.pack(fill="both", expand=True)

# ── 하단 액션 ──────────────────────────────────────────────────────
foot = ttk.Frame(root, style="App.TFrame")
foot.pack(fill="x", padx=S.PAD_PAGE, pady=(0, S.XL))
ttk.Label(foot, text="준비되었습니다 · 마지막 저장 10:44",
          style="Status.TLabel").pack(side="left")
RoundedButton(foot, "블로그에 발행하기", parent_bg=C.CANVAS).pack(side="right")
ttk.Button(foot, text="미리보기", style="Secondary.TButton").pack(
    side="right", padx=(0, S.SM))
ttk.Button(foot, text="초기화", style="Ghost.TButton").pack(
    side="right", padx=(0, S.SM))

if "--shot" in sys.argv:
    root.after(900, root.quit)
root.mainloop()
