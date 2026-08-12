#!/bin/zsh
set -e
cd "$(dirname "$0")/.."

# 2026-08-12: 시스템 python3 가 오래된 경우(예: macOS 기본 3.9) models.py 의
# @dataclass(slots=True) 문법(3.10 이상 필요)에서 알아보기 힘든 에러가 난다.
# 여기서 먼저 걸러서 명확한 안내를 준다. Homebrew 등으로 최신 파이썬이 따로
# 깔려 있으면 그쪽을 자동으로 찾아 쓴다.
PY=python3
PY_OK=$("$PY" -c 'import sys; print(1 if sys.version_info >= (3, 10) else 0)' 2>/dev/null || echo 0)
if [[ "$PY_OK" != "1" ]]; then
  for cand in python3.13 python3.12 python3.11 python3.10 \
              /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    if command -v "$cand" >/dev/null 2>&1; then
      OK=$("$cand" -c 'import sys; print(1 if sys.version_info >= (3, 10) else 0)' 2>/dev/null || echo 0)
      if [[ "$OK" == "1" ]]; then
        PY="$cand"; PY_OK=1; break
      fi
    fi
  done
fi
if [[ "$PY_OK" != "1" ]]; then
  echo "파이썬 3.10 이상이 필요합니다. (지금 python3: $(python3 --version 2>&1))"
  echo "https://www.python.org 에서 3.11 이상을 설치한 뒤 이 파일을 다시 실행해 주세요."
  read -r "?Enter를 누르면 닫힙니다."
  exit 1
fi

"$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

echo
echo "설치가 끝났습니다. run.command를 더블클릭해 실행하세요."
