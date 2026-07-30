#!/bin/zsh
set -e
cd "$(dirname "$0")/.."

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

echo
echo "설치가 끝났습니다. run.command를 더블클릭해 실행하세요."
