#!/bin/zsh
# 2026-08-06 진단용 — vibe-blogpost 전용 가상환경에서 Google Gen AI 가
# 실제로 불러와지는지 확인하고, 실패하면 오류 전문을 파일로 남긴다.
# 더블클릭으로 실행하면 결과가 텍스트 창으로 열린다.
cd "$(dirname "$0")"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "가상환경(.venv)이 없습니다. scripts/setup.command 를 먼저 실행해 주세요."
  read -r "?Enter를 누르면 닫힙니다."
  exit 1
fi

".venv/bin/python" - <<'PY' 2>&1 | tee "genai_진단결과.txt"
import sys, traceback
print("실행 파이썬:", sys.executable)
print("파이썬 버전:", sys.version)
print("-" * 40)
try:
    from google import genai
    ver = getattr(genai, "__version__", "버전 미상")
    print("결과: google-genai 불러오기 성공 (버전:", ver, ")")
except BaseException:
    print("결과: 불러오기 실패 — 아래 오류 전문을 그대로 전달해 주세요.")
    print("-" * 40)
    traceback.print_exc()
print("-" * 40)
print("이 내용은 genai_진단결과.txt 파일로도 저장됐습니다.")
PY

open -e "genai_진단결과.txt" 2>/dev/null || true
read -r "?Enter를 누르면 닫힙니다."
