"""배포용 패키지 생성 스크립트.

프로그램 운영에 '꼭 필요한 파일만' 골라 release/ 폴더에 모으고 zip으로 압축한다.
민감정보(.env, 개인 설정, 로그인 세션, 생성물)는 허용 목록(allowlist) 방식으로
'애초에 포함하지 않는다'. 실수로 개인정보가 배포되는 것을 막기 위함이다.

사용법 (프로젝트 루트에서):
    .venv/bin/python scripts/build_release.py          # macOS/Linux
    .venv\\Scripts\\python.exe scripts\\build_release.py  # Windows
"""

from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 2026-07-30 코어 분리 — 패키지·templates·번들 config 는 형제 폴더 vibe-blogcore 에 있다.
# 배포 zip 은 예전처럼 '자기완결'로 만든다: 코어 쪽 파일을 zip 루트에 그대로 담으면
# 사용자 PC 에서는 분리 전과 동일한 구조로 동작한다(app.py 부트스트랩은 코어 폴더가
# 없으면 아무것도 하지 않는다).
CORE_ROOT = ROOT.parent / "vibe-blogcore"
RELEASE_NAME = "네이버블로그매물자동화_배포"
OUT_DIR = ROOT / "release"
STAGE = OUT_DIR / RELEASE_NAME

# 배포에 포함할 '파일'(운영 필수 + 안내 문서).
INCLUDE_FILES = [
    "app.py",
    "my_listings_source.py",   # 2026-08-10: 내 매물 CSV 선택·중개사ID 필터
    "claude_theme.py",         # 2026-08-12: app.py:205 가 직접 import — 누락 시 실행 자체가 안 됨(실사용 확인)
    "vibe_auth.py",            # app.py 의 로그인 게이트가 조건부로 import(현재는 REQUIRE_LOGIN=False 라 없어도 안 죽지만, 있어야 완전함)
    "run.bat",
    "run.command",
    "requirements.txt",
    "requirements-dev.txt",       # exe 빌드용(빌드 PC에서만 사용)
    "README.md",
    "사용설명서.md",
    "빠른시작.html",
    "사용설명서.html",
    ".env.example",
    "config/blog_selectors.yaml",
    "config/sample_property.json",
    "config/settings.example.yaml",
]

# 통째로 포함할 '폴더'(내부의 __pycache__ 등은 아래에서 자동 제외).
INCLUDE_DIRS = [
    "naver_blog_automation",
    "templates",
    "scripts",
]

# 폴더를 복사할 때 항상 제외할 이름들.
#  - _to_delete: 삭제 예정 임시 폴더(쓰레기)
#  - icons: 현재 숨긴 섹션 아이콘 기능용 에셋(~27MB) — 기능 재활성 시 다시 포함
#  - 전화연결배너.png: 제거된 전화배너 기능의 잔여 에셋
EXCLUDE_NAMES = {
    "__pycache__",
    ".DS_Store",
    ".pytest_cache",
    "_to_delete",
    "icons",
    "전화연결배너.png",
}

# 절대 배포하면 안 되는(민감) 경로 — 안전장치 차원의 이중 확인용.
NEVER_INCLUDE = {
    ".env",
    "config/user_settings.json",
    "config/settings.yaml",
    "data",
    "output",
    ".venv",
    ".git",
}


def _copy_file(rel: str) -> bool:
    src = ROOT / rel
    if not src.exists():
        src = CORE_ROOT / rel  # 코어 분리분(번들 자원)은 vibe-blogcore 에서
    if not src.exists():
        print(f"  (건너뜀, 없음) {rel}")
        return False
    dst = STAGE / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"  + {rel}")
    return True


def _copy_dir(rel: str) -> None:
    base = ROOT
    src = base / rel
    if not src.is_dir():
        base = CORE_ROOT  # 코어 분리분(naver_blog_automation·templates)
        src = base / rel
    if not src.is_dir():
        print(f"  (건너뜀, 없음) {rel}/")
        return
    for path in src.rglob("*"):
        if any(part in EXCLUDE_NAMES for part in path.relative_to(base).parts):
            continue
        if path.is_dir():
            continue
        rel_path = path.relative_to(base)
        dst = STAGE / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst)
    print(f"  + {rel}/ (하위 파일 포함)")


def _guard_no_secrets() -> None:
    """스테이징 폴더에 민감 파일이 섞이지 않았는지 마지막으로 검사한다."""
    leaked = []
    for rel in NEVER_INCLUDE:
        if (STAGE / rel).exists():
            leaked.append(rel)
    if leaked:
        print("\n[중단] 민감 파일이 배포 폴더에 포함됨:", leaked)
        sys.exit(1)


def main() -> None:
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    STAGE.mkdir(parents=True)

    print("배포 파일 복사:")
    for rel in INCLUDE_FILES:
        _copy_file(rel)
    for rel in INCLUDE_DIRS:
        _copy_dir(rel)

    _guard_no_secrets()

    zip_path = OUT_DIR / f"{RELEASE_NAME}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in STAGE.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(OUT_DIR))

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"\n완료: {zip_path}  ({size_mb:.1f} MB)")
    print("이 zip에는 개인 키·계정·세션·생성물이 포함되지 않습니다.")


if __name__ == "__main__":
    main()
