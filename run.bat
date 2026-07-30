@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 1) 가상환경(.venv)이 있으면 그걸로 실행
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" app.py
  goto :end
)

rem 2) py 런처가 있으면 그걸로 실행
where py >nul 2>nul
if %errorlevel%==0 (
  py app.py
  goto :end
)

rem 3) python 명령이 있으면 그걸로 실행
where python >nul 2>nul
if %errorlevel%==0 (
  python app.py
  goto :end
)

echo.
echo 파이썬을 찾을 수 없습니다.
echo python.org 에서 Python 3.12 이상을 설치한 뒤 다시 실행해 주세요.
echo (설치 시 "Add python.exe to PATH" 체크)

:end
if not "%errorlevel%"=="0" pause
