from __future__ import annotations

from typing import Any, Callable


class GeminiKeyValidationError(RuntimeError):
    pass


def normalize_gemini_api_key(value: str) -> str:
    """붙여넣을 때 함께 들어온 환경변수 표기·따옴표·공백을 제거한다."""
    key = value.strip().replace("\ufeff", "").replace("\u200b", "")
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY"):
        if key.upper().startswith(f"{name}="):
            key = key.split("=", 1)[1].strip()
            break
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    if len(key) >= 2 and key[0] == key[-1] and key[0] in {"'", '"', "`"}:
        key = key[1:-1].strip()
    return "".join(key.split())


def validate_gemini_api_key(
    api_key: str,
    *,
    client_factory: Callable[[str], Any] | None = None,
) -> str:
    """생성 비용이 없는 모델 목록 요청으로 Google AI Studio 키를 확인한다."""
    key = normalize_gemini_api_key(api_key)
    if not key:
        raise GeminiKeyValidationError("Google AI Studio API Key를 입력해 주세요.")

    client = None
    try:
        if client_factory is not None:
            client = client_factory(key)
        else:
            try:
                from google import genai
            except ImportError as exc:
                raise GeminiKeyValidationError(
                    "Google Gen AI 패키지가 없습니다. 설치 스크립트를 다시 실행해 주세요."
                ) from exc
            client = genai.Client(api_key=key)

        pager = client.models.list(config={"page_size": 1})
        first_model = next(iter(pager), None)
    except GeminiKeyValidationError:
        raise
    except Exception as exc:
        code = int(getattr(exc, "code", 0) or 0)
        if code in {400, 401, 403}:
            raise GeminiKeyValidationError(
                "Google AI Studio API Key 인증에 실패했습니다.\n"
                "https://aistudio.google.com/app/apikey 에서 발급한 Gemini API "
                "키의 전체 값을 붙여 넣어 주세요."
            ) from exc
        if code == 429:
            raise GeminiKeyValidationError(
                "Gemini API 요청 한도에 도달했습니다. 잠시 후 다시 검증해 주세요."
            ) from exc
        if code:
            raise GeminiKeyValidationError(
                f"Google Gemini 서버가 HTTP {code} 오류를 반환했습니다."
            ) from exc
        raise GeminiKeyValidationError(
            "Google Gemini 서버에 연결하지 못했습니다. 인터넷 연결을 확인해 주세요."
        ) from exc
    finally:
        if client is not None and client_factory is None:
            try:
                client.close()
            except Exception:
                pass

    if first_model is not None:
        return "검증 완료 · 사용 가능한 Gemini 모델 확인"
    return "검증 완료 · Google Gemini 인증 응답 확인"
