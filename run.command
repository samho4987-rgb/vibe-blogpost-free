#!/bin/zsh
set -e
cd "$(dirname "$0")"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "처음 실행이라 전용 환경을 구성합니다(인터넷 필요, 몇 분 걸릴 수 있습니다)..."
  zsh scripts/setup.command
fi

exec ".venv/bin/python" app.py
