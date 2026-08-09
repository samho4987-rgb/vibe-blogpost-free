#!/bin/zsh
# 블로그자동화(vibe-blogpost) — 맥용 .app 빌드 (더블클릭)
#
#   1. 프로젝트 .venv (파이썬 3.14) 에 PyInstaller 설치
#      → 이 앱의 의존성(playwright·Pillow·google-genai·keyring)이 이미 그 안에 있다
#   2. /tmp 에서 빌드            ← 함정 1: ~/Documents 안에서는 서명이 안 된다
#   3. xattr -cr → codesign --force --deep --sign -
#   4. ~/Applications 설치 + 기존 사용자 데이터 이사(최초 1회)
#
# 근거: claude/40_UI배포/맥앱배포TCC함정_참고자료_20260726.md
set -u

SRC="${0:A:h}"
APP_NAME="블로그자동화"
BUILD="/tmp/blogpost_macbuild"
DEST="$HOME/Applications"
DATA_DEST="$HOME/Library/Application Support/vibe-blogpost"

print_step() { print -P "\n%F{cyan}▸ $1%f"; }
die() { print -P "\n%F{red}✗ $1%f"; print "\nEnter 를 누르면 창이 닫힙니다."; read -r _; exit 1; }

cd "$SRC" || die "소스 폴더로 이동 실패"
print -P "%F{green}== 블로그자동화 맥 앱 빌드 ==%f"
print "소스: $SRC"

# ── 0. 코어 확인 ────────────────────────────────────────────
CORE="${SRC:h}/vibe-blogcore"
[[ -d "$CORE" ]] || die "vibe-blogcore 를 못 찾았습니다: $CORE
  (2026-07-30 코어 분리 이후 이 폴더가 옆에 있어야 빌드됩니다)"

# ── 1. 가상환경 + PyInstaller ───────────────────────────────
print_step "1/5  .venv 확인 + PyInstaller 설치"
PY="$SRC/.venv/bin/python"
[[ -x "$PY" ]] || die ".venv 가 없습니다: $PY
  먼저 scripts/setup.command 로 가상환경을 만드세요."
"$PY" -c "import PIL, playwright, keyring, google.genai" >/dev/null 2>&1 \
  || die ".venv 에 의존성이 빠져 있습니다.
  '$PY -m pip install -r requirements.txt' 를 먼저 돌리세요."
"$PY" -m pip install --quiet --upgrade pip pyinstaller || die "PyInstaller 설치 실패 (인터넷 연결 확인)"
"$PY" -c "import sys;print('  파이썬', sys.version.split()[0])"
"$PY" -m PyInstaller --version | sed 's/^/  PyInstaller /'

# ── 2. 빌드 ─────────────────────────────────────────────────
print_step "2/5  PyInstaller 빌드 (몇 분 걸립니다)"
rm -rf "$BUILD/dist" "$BUILD/build"
"$PY" -m PyInstaller \
  --noconfirm --clean \
  --distpath "$BUILD/dist" --workpath "$BUILD/build" \
  "$SRC/vibe-blogpost_mac.spec" || die "빌드 실패 — 위 로그의 마지막 오류를 확인하세요."
[[ -d "$BUILD/dist/$APP_NAME.app" ]] || die "빌드는 끝났는데 $APP_NAME.app 이 없습니다."

# ── 3. 서명 ─────────────────────────────────────────────────
print_step "3/5  확장속성 제거 + ad-hoc 서명"
xattr -cr "$BUILD/dist/$APP_NAME.app" 2>/dev/null
codesign --force --deep --sign - "$BUILD/dist/$APP_NAME.app" \
  || die "codesign 실패 — /tmp 밖에서 빌드되지 않았는지 확인하세요(함정 1)."
codesign --verify --deep --strict "$BUILD/dist/$APP_NAME.app" 2>&1 | sed 's/^/  /'
print "  ✓ 서명 완료 (ad-hoc)"

# ── 4. 사용자 데이터 이사 (최초 1회) ────────────────────────
print_step "4/5  사용자 데이터 위치 맞추기"
mkdir -p "$DATA_DEST"
COPIED=0
for f in user_settings.json settings.yaml .env; do
  if [[ -f "$SRC/$f" && ! -e "$DATA_DEST/$f" ]]; then
    cp "$SRC/$f" "$DATA_DEST/$f" && COPIED=1
  fi
done
for d in data output; do
  if [[ -d "$SRC/$d" && ! -e "$DATA_DEST/$d" ]]; then
    cp -R "$SRC/$d" "$DATA_DEST/$d" && COPIED=1
  fi
done
if (( COPIED )); then
  print "  ✓ 기존 설정·로그인 세션을 $DATA_DEST 로 복사했습니다(원본은 그대로 둡니다)"
else
  print "  · 옮길 것이 없거나 이미 있습니다"
fi

# ── 5. 설치 ─────────────────────────────────────────────────
print_step "5/5  ~/Applications 설치"
mkdir -p "$DEST"
if [[ -d "$DEST/$APP_NAME.app" ]]; then
  rm -rf "$DEST/$APP_NAME.app.old"
  mv "$DEST/$APP_NAME.app" "$DEST/$APP_NAME.app.old" || die "기존 앱 밀어내기 실패"
  print "  · 기존 앱은 $APP_NAME.app.old 로 남겨 뒀습니다"
fi
cp -R "$BUILD/dist/$APP_NAME.app" "$DEST/" || die "설치 실패"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
  -f "$DEST/$APP_NAME.app" >/dev/null 2>&1
SIZE=$(du -sh "$DEST/$APP_NAME.app" | cut -f1)

print -P "\n%F{green}✅ 완료 — $DEST/$APP_NAME.app  ($SIZE)%f"
cat <<'EOF'

── 다음에 할 일 ──────────────────────────────────────────────
1. 처음 한 번은 우클릭 ▸ 열기 로 여세요(ad-hoc 서명이라 더블클릭은 막힐 수 있음).

2. 이 앱은 설치된 크롬(Chrome)으로 네이버를 자동화합니다.
   크롬이 없으면 발행 단계에서 멈춥니다.

3. 데이터 위치: ~/Library/Application Support/vibe-blogpost/
   (설정·로그인 세션·생성물. 앱 바깥이라 재빌드해도 보존됩니다)

4. 소스 실행(run.command)과 .app 은 이제 데이터 폴더가 다릅니다.
   둘을 섞어 쓰면 로그인 세션이 따로 놉니다 — 한쪽만 쓰시는 걸 권합니다.

5. 잘 뜨면 ~/Applications/블로그자동화.app.old 는 지우셔도 됩니다.
EOF
print "\nEnter 를 누르면 창이 닫힙니다."
read -r _
