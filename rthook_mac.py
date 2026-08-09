# -*- coding: utf-8 -*-
"""PyInstaller 런타임 훅 — 맥 .app 전용. 진입점(app.py)보다 먼저 실행된다.

왜 필요한가
  app.py 의 `_bootstrap_core()` 는 frozen 이면 그대로 return 하므로
  VIBE_BLOG_DATA_ROOT 가 설정되지 않는다. 그러면 settings.py 가
  `LOCALAPPDATA or ~` 로 폴백하는데, 맥에는 LOCALAPPDATA 가 없어서
  홈 폴더 바로 아래에 데이터 폴더가 생긴다.
  → 맥 관례대로 ~/Library/Application Support/vibe-blogpost 로 고정한다.

운영 파일(app.py · vibe-blogcore/naver_blog_automation/settings.py)은 손대지 않는다.
`setdefault` 라서 사용자가 환경변수를 직접 준 경우에는 그쪽이 이긴다.
"""
import os
import sys

if sys.platform == "darwin" and getattr(sys, "frozen", False):
    try:
        from pathlib import Path

        root = Path.home() / "Library" / "Application Support" / "vibe-blogpost"
        root.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("VIBE_BLOG_DATA_ROOT", str(root))
    except Exception:
        pass
