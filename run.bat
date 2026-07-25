@echo off
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" app.py
  exit /b %errorlevel%
)

echo 가상환경이 없습니다. 먼저 scripts\setup.bat를 실행해 주세요.
pause
