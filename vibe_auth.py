# -*- coding: utf-8 -*-
"""바이브 계정 인증 — 발행 앱(tkinter)용 경량 클라이언트.

vibemap login_dialog.py 와 **같은 라이선스 서버·같은 keyring**을 쓴다. 단
login_dialog 는 PySide6 에 묶여 있어 이 venv(PySide6 없음)에서 임포트할 수 없으므로,
GUI 없는 부분(서버 호출·토큰 저장)만 requests+keyring 으로 복제한다.

- 서버·엔드포인트·keyring 키는 login_dialog.py 정본과 동일해야 한다(바뀌면 같이 고칠 것):
    LICENSE_SERVER = https://license-server-wxvb.onrender.com
    POST /api/auth/login   json{login_id,password} -> 200 user_info(token 포함)/401/403
    GET  /api/auth/validate  Bearer -> 200 user_info
    keyring service "vibe_sozhang", token key "auth_token"
- vibemap 에서 로그인한 토큰을 그대로 공유하므로, vibemap→발행 호출 시 재로그인 0회.
"""
from __future__ import annotations

LICENSE_SERVER = "https://license-server-wxvb.onrender.com"
KEYRING_SERVICE = "vibe_sozhang"
_TOKEN_KEY = "auth_token"
TIMEOUT = 60  # Render 콜드스타트(30~50초) 감안


def saved_token() -> str:
    try:
        import keyring
        return keyring.get_password(KEYRING_SERVICE, _TOKEN_KEY) or ""
    except Exception:
        return ""


def _save_token(token: str) -> None:
    try:
        import keyring
        keyring.set_password(KEYRING_SERVICE, _TOKEN_KEY, token)
    except Exception:
        pass


def validate(token: str) -> dict | None:
    """유효하면 user_info dict, 아니면 None. (login_dialog.validate_token 동일 규격)"""
    if not token:
        return None
    try:
        import requests
        res = requests.get(
            f"{LICENSE_SERVER}/api/auth/validate",
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT,
        )
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return None


def login(login_id: str, password: str) -> tuple[dict | None, str]:
    """(user_info, error_msg). 성공 시 토큰을 keyring 에 저장하고 (info, "")."""
    try:
        import requests
        res = requests.post(
            f"{LICENSE_SERVER}/api/auth/login",
            json={"login_id": login_id, "password": password},
            timeout=TIMEOUT,
        )
    except Exception as e:  # noqa: BLE001
        return None, f"서버에 연결할 수 없습니다: {e}"
    if res.status_code == 200:
        info = res.json()
        _save_token(info.get("token", ""))
        return info, ""
    if res.status_code == 401:
        return None, "아이디 또는 비밀번호가 올바르지 않습니다."
    if res.status_code == 403:
        err = ""
        try:
            err = res.json().get("error", "")
        except Exception:
            pass
        if err == "DISABLED":
            return None, "사용이 정지된 계정입니다. 관리자에게 문의해주세요."
        if err == "EXPIRED":
            return None, "이용 기간이 만료되었습니다. 구독 갱신 후 이용해주세요."
        return None, "사용 권한이 없습니다. 관리자에게 문의해주세요."
    return None, f"서버 오류({res.status_code}). 잠시 후 다시 시도해주세요."


def current_user() -> dict | None:
    """저장된 토큰으로 통과 가능한지 확인. 통과 시 user_info."""
    return validate(saved_token())
