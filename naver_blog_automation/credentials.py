from __future__ import annotations


NAVER_CREDENTIAL_SERVICE = "naver-blog-automation"
ESILJANG_CREDENTIAL_SERVICE = "esiljang-automation"
# 매물 API cURL(토큰·쿠키 포함)을 OS 보안 저장소에 보관하기 위한 서비스명.
PROPERTY_CURL_SERVICE = "naver-property-curl"
PROPERTY_CURL_ACCOUNT = "default"


class CredentialStoreError(RuntimeError):
    pass


def _keyring():
    try:
        import keyring
        from keyring.errors import KeyringError
    except ImportError as exc:
        raise CredentialStoreError(
            "비밀번호 보안 저장 기능이 설치되지 않았습니다. "
            "설치 스크립트를 다시 실행해 주세요."
        ) from exc
    return keyring, KeyringError


def _save_password(
    service: str,
    service_label: str,
    login_id: str,
    password: str,
) -> None:
    normalized_id = login_id.strip()
    if not normalized_id or not password:
        raise CredentialStoreError(
            f"저장할 {service_label} 로그인 ID와 비밀번호를 모두 입력해 주세요."
        )
    keyring, keyring_error = _keyring()
    try:
        keyring.set_password(service, normalized_id, password)
    except keyring_error as exc:
        raise CredentialStoreError(
            f"운영체제 보안 저장소에 {service_label} 비밀번호를 저장하지 못했습니다."
        ) from exc


def _load_password(service: str, service_label: str, login_id: str) -> str:
    normalized_id = login_id.strip()
    if not normalized_id:
        return ""
    keyring, keyring_error = _keyring()
    try:
        return keyring.get_password(service, normalized_id) or ""
    except keyring_error as exc:
        raise CredentialStoreError(
            f"운영체제 보안 저장소에서 {service_label} 비밀번호를 불러오지 못했습니다."
        ) from exc


def _delete_password(service: str, service_label: str, login_id: str) -> None:
    normalized_id = login_id.strip()
    if not normalized_id:
        return
    keyring, keyring_error = _keyring()
    try:
        keyring.delete_password(service, normalized_id)
    except keyring_error as exc:
        # 저장된 항목이 없는 경우를 포함해 삭제 실패는 로그인 자체를 막지 않는다.
        if exc.__class__.__name__ != "PasswordDeleteError":
            raise CredentialStoreError(
                f"운영체제 보안 저장소의 {service_label} 비밀번호를 삭제하지 못했습니다."
            ) from exc


def save_naver_password(login_id: str, password: str) -> None:
    _save_password(
        NAVER_CREDENTIAL_SERVICE,
        "네이버",
        login_id,
        password,
    )


def load_naver_password(login_id: str) -> str:
    return _load_password(NAVER_CREDENTIAL_SERVICE, "네이버", login_id)


def delete_naver_password(login_id: str) -> None:
    _delete_password(NAVER_CREDENTIAL_SERVICE, "네이버", login_id)


def save_esiljang_password(login_id: str, password: str) -> None:
    _save_password(
        ESILJANG_CREDENTIAL_SERVICE,
        "이실장",
        login_id,
        password,
    )


def load_esiljang_password(login_id: str) -> str:
    return _load_password(ESILJANG_CREDENTIAL_SERVICE, "이실장", login_id)


def delete_esiljang_password(login_id: str) -> None:
    _delete_password(ESILJANG_CREDENTIAL_SERVICE, "이실장", login_id)


def save_property_curl(curl: str) -> None:
    """매물 API cURL(토큰·쿠키 포함)을 OS 보안 저장소에 저장한다.

    쿠키·토큰이 들어 있으므로 평문 설정 파일이 아니라 키체인에 보관한다."""
    text = curl.strip()
    if not text:
        delete_property_curl()
        return
    keyring, keyring_error = _keyring()
    try:
        keyring.set_password(PROPERTY_CURL_SERVICE, PROPERTY_CURL_ACCOUNT, text)
    except keyring_error as exc:
        raise CredentialStoreError(
            "운영체제 보안 저장소에 cURL을 저장하지 못했습니다."
        ) from exc


def load_property_curl() -> str:
    # 시작 시 호출되므로 어떤 이유(키체인 미설치·접근 실패)로도 앱을 막지 않는다.
    try:
        keyring, keyring_error = _keyring()
        return keyring.get_password(
            PROPERTY_CURL_SERVICE, PROPERTY_CURL_ACCOUNT
        ) or ""
    except Exception:
        return ""


def delete_property_curl() -> None:
    keyring, keyring_error = _keyring()
    try:
        keyring.delete_password(PROPERTY_CURL_SERVICE, PROPERTY_CURL_ACCOUNT)
    except keyring_error as exc:
        if exc.__class__.__name__ != "PasswordDeleteError":
            raise CredentialStoreError(
                "운영체제 보안 저장소의 cURL을 삭제하지 못했습니다."
            ) from exc
