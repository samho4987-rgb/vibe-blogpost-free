@echo off
setlocal
cd /d "%~dp0\.."

py -3 -m venv .venv
if errorlevel 1 exit /b 1

".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

echo.
echo 설치가 끝났습니다. run.bat를 실행하세요.
pause
