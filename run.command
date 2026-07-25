#!/bin/zsh
set -e
cd "$(dirname "$0")"

if [[ -x ".venv/bin/python" ]]; then
  exec ".venv/bin/python" app.py
fi

echo "가상환경이 없습니다. 먼저 scripts/setup.command를 실행해 주세요."
read -r "?Enter를 누르면 닫힙니다."
