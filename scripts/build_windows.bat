@echo off
setlocal
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
  echo 먼저 scripts\setup.bat를 실행해 주세요.
  exit /b 1
)

".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
if errorlevel 1 exit /b 1

".venv\Scripts\pyinstaller.exe" ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --name "네이버블로그매물자동화" ^
  --add-data "config;config" ^
  --add-data "templates;templates" ^
  --collect-all playwright ^
  --collect-all keyring ^
  --collect-all PIL ^
  app.py
if errorlevel 1 exit /b 1

echo.
echo 폴더형 빌드 완료. zip으로 압축합니다...
powershell -NoProfile -Command "Compress-Archive -Path 'dist\네이버블로그매물자동화\*' -DestinationPath 'dist\네이버블로그매물자동화.zip' -Force"

echo.
echo dist\네이버블로그매물자동화\  (실행 폴더)
echo dist\네이버블로그매물자동화.zip (배포용 압축본)
echo 받는 사람은 압축을 풀고 폴더 안 '네이버블로그매물자동화.exe'를 실행하면 됩니다. (크롬 필요)
pause
