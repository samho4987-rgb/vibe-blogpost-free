; ============================================================
;  vibe-blogpost-free  설치본(setup.exe) 생성 스크립트 (Inno Setup 6)
;  - 공통 설치 규약(설치 위치·시작 메뉴 그룹·권한·발행자 등)은
;    같은 폴더의 vibe_install_common.iss 를 #include 로 가져온다.
;    → 모든 '바이브소장' 프로그램이 같은 규칙으로 설치된다.
;  - 이 파일은 UTF-8 BOM 으로 저장한다(설치창 한글 표시용).
;  빌드: scripts\build_windows_installer.bat 가 ISCC 로 자동 컴파일한다.
; ============================================================

; 버전은 빌드 스크립트가 /DMyAppVersion=... 로 넘겨준다(없으면 아래 기본값).
#ifndef MyAppVersion
  #define MyAppVersion "1.0.1"
#endif

; --- 바이브 공통 값: 시작 메뉴 그룹·설치 부모 폴더·발행자에 함께 쓰인다 ---
#define VibeVendor "바이브소장"

; --- 이 프로그램 고유 값 ---
#define MyAppName "네이버 블로그 매물 자동화"
#define MyAppNameEN "vibe-blogpost-free"
#define MyAppExeName "vibe-blogpost-free.exe"

[Setup]
; AppId 는 프로그램마다 '고유'해야 한다(다른 vibe 프로그램과 절대 공유 금지).
AppId={{7B3D9C2E-6A41-4F58-9E2B-1A2B3C4D5E6F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
OutputDir=..\dist
OutputBaseFilename=vibe-blogpost-free-setup-{#MyAppVersion}
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
; ↓↓ 모든 vibe 프로그램 공통 설치 규약(설치 위치·그룹·권한 등) ↓↓
#include "vibe_install_common.iss"

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; GroupDescription: "추가 아이콘:"

[Files]
; PyInstaller 폴더형 결과(dist\vibe-blogpost-free\)를 통째로 담는다.
Source: "..\dist\{#MyAppNameEN}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
; 시작 메뉴 그룹(=바이브소장)에 실행/제거 바로가기 + 바탕화면 아이콘(선택)
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName} 제거"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "지금 실행"; Flags: nowait postinstall skipifsilent
