"""온라인 업데이트(공개 GitHub 저장소 + Releases).

동작(자동 업데이터 표준 패턴):
1) 앱 시작 시 백그라운드로 GitHub Releases API에서 최신 버전을 확인한다(공개 저장소라 토큰 불필요).
2) 새 버전이 있으면 릴리스에 첨부된 zip을 '스테이징 폴더'에 받아둔다.
3) 사용자가 재시작하면, 앱이 본격 로딩되기 '전'에 받아둔 zip을 앱 폴더에 적용한다
   (실행 중 파일 잠금을 피하기 위함). 사용자 데이터(.env·설정·세션·생성물)는 보존한다.

네트워크·형식 오류가 나도 예외를 삼키고 앱 동작에는 영향을 주지 않는다.
번들 실행파일(exe, sys.frozen)은 파일 단위 교체가 불가능하므로 적용을 건너뛴다.
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path
from typing import Any, Optional

# 받아둔 업데이트를 보관하는 폴더(사용자 홈, 쓰기 가능).
_STAGE = Path.home() / ".vibe-blogpost" / "update"

# 업데이트로 '덮어쓰면 안 되는' 사용자 데이터·환경 경로.
_PROTECTED = (
    ".env",
    "config/user_settings.json",
    "config/settings.yaml",
    "data",
    "output",
    "release",
    ".venv",
    ".git",
)

# 모든 파일이 안전하게 복사된 뒤에 버전이 올라가도록, 이 파일은 맨 마지막에 복사한다.
_VERSION_REL = "naver_blog_automation/version.py"


def _parse(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for token in str(version).strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in token if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer(candidate: str, current: str) -> bool:
    """candidate가 current보다 새 버전이면 True."""
    return _parse(candidate) > _parse(current)


def check_for_update(
    current_version: str,
    repo: str,
    *,
    timeout: float = 5.0,
) -> Optional[dict[str, Any]]:
    """공개 GitHub 저장소의 최신 릴리스를 확인한다. repo 형식: 'user/repo'.

    새 버전이 있으면 {version, tag, download_url(zip), html_url, notes}, 없으면 None.
    """
    repo = (repo or "").strip().strip("/")
    if not repo:
        return None
    try:
        import httpx

        response = httpx.get(
            f"https://api.github.com/repos/{repo}/releases/latest",
            timeout=timeout,
            follow_redirects=True,
            headers={"Accept": "application/vnd.github+json"},
        )
        if response.status_code >= 400:
            return None
        data = response.json()
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    tag = str(data.get("tag_name", "")).strip()
    if not tag or not is_newer(tag, current_version):
        return None
    download = ""
    for asset in data.get("assets", []) or []:
        if str(asset.get("name", "")).lower().endswith(".zip"):
            download = str(asset.get("browser_download_url", "")).strip()
            break
    return {
        "version": tag.lstrip("vV"),
        "tag": tag,
        "download_url": download,
        "html_url": str(data.get("html_url", "")).strip(),
        "notes": str(data.get("body", "")).strip(),
    }


def download_update(download_url: str, *, timeout: float = 180.0) -> bool:
    """새 버전 zip을 스테이징 폴더에 받아둔다(유효한 zip 확인 후 확정). 성공 시 True."""
    url = (download_url or "").strip()
    if not url:
        return False
    try:
        import httpx

        _STAGE.mkdir(parents=True, exist_ok=True)
        tmp = _STAGE / "download.part"
        with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as response:
            if response.status_code >= 400:
                return False
            with open(tmp, "wb") as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)
        with zipfile.ZipFile(tmp) as archive:
            if archive.testzip() is not None:
                tmp.unlink(missing_ok=True)
                return False
        tmp.replace(_STAGE / "update.zip")
        return True
    except Exception:
        try:
            (_STAGE / "download.part").unlink(missing_ok=True)
        except Exception:
            pass
        return False


def has_pending_update() -> bool:
    return (_STAGE / "update.zip").exists()


def apply_pending_update(app_root) -> bool:
    """받아둔 업데이트 zip을 앱 폴더에 적용한다(사용자 데이터 보존). 성공 시 True.

    반드시 앱이 본격 로딩되기 '전'에 호출해야 파일 잠금 없이 교체된다.
    """
    zip_path = _STAGE / "update.zip"
    if not zip_path.exists():
        return False
    app_root = Path(app_root)
    extract = _STAGE / "extracted"
    applied = False
    try:
        if extract.exists():
            shutil.rmtree(extract, ignore_errors=True)
        extract.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(extract)
        # zip 안에 최상위 폴더 하나(네이버…배포/)만 있으면 그 안을 소스로 삼는다.
        entries = list(extract.iterdir())
        src = entries[0] if len(entries) == 1 and entries[0].is_dir() else extract
        _copy_over(src, app_root)
        applied = True
    except Exception:
        applied = False
    finally:
        try:
            zip_path.unlink(missing_ok=True)
            shutil.rmtree(extract, ignore_errors=True)
        except Exception:
            pass
    return applied


def _is_protected(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    for protected in _PROTECTED:
        if rel == protected or rel.startswith(protected + "/"):
            return True
    return False


def _copy_over(src: Path, dst: Path) -> None:
    files = [path for path in src.rglob("*") if path.is_file()]
    # version.py를 맨 마지막에 복사해, 모든 파일이 성공적으로 바뀐 뒤에만 버전이 올라가게 한다.
    files.sort(key=lambda p: p.relative_to(src).as_posix() == _VERSION_REL)
    for path in files:
        rel = path.relative_to(src).as_posix()
        if _is_protected(rel):
            continue
        if "__pycache__" in rel.split("/"):
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
