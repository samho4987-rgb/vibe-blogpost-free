@echo off
rem ==================================================================
rem   vibe-blogpost-free  -  Windows installer (setup.exe) builder
rem   ASCII-only + goto-based (no parenthesized blocks) so it never
rem   silently closes. Do NOT add non-ASCII characters to this file.
rem ==================================================================
setlocal enableextensions
cd /d "%~dp0\.."

echo ==================================================
echo   vibe-blogpost-free : building setup.exe
echo ==================================================
echo.

if not exist "app.py" goto nowhere

rem --- 1) find Python -----------------------------------------------
set "PY=py -3"
%PY% --version >nul 2>nul && goto havepy
set "PY=python"
%PY% --version >nul 2>nul && goto havepy
goto nopy
:havepy

rem --- 2) build-only virtual environment ---------------------------
if exist ".build-venv\Scripts\python.exe" goto havevenv
echo [1/5] creating build venv .build-venv ...
%PY% -m venv .build-venv
if errorlevel 1 goto fail
:havevenv
set "VPY=.build-venv\Scripts\python.exe"

echo [2/5] installing dependencies (this can take a few minutes) ...
"%VPY%" -m pip install --upgrade pip >nul
"%VPY%" -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto fail

rem --- 3) PyInstaller onedir build ---------------------------------
echo [3/5] running PyInstaller ...
"%VPY%" -m PyInstaller --noconfirm --clean --windowed --name "vibe-blogpost-free" --add-data "config\blog_selectors.yaml;config" --add-data "config\sample_property.json;config" --add-data "templates;templates" --collect-all playwright --collect-all greenlet --collect-all pyee --collect-all PIL --collect-all keyring --collect-all win32ctypes --collect-all google.genai --collect-all pydantic --copy-metadata keyring --copy-metadata google-genai app.py
if errorlevel 1 goto fail

rem --- 5) locate Inno Setup compiler (ISCC.exe) --------------------
rem  (version is defined inside the .iss: #define MyAppVersion "1.0.1")
rem  Look in common folders (all-users AND per-user), then the
rem  Windows registry (finds it even in a custom install folder),
rem  then PATH. This is why a normal Inno Setup 6 install is found.
set "ISCC="
for %%D in ("%ProgramFiles%\Inno Setup 7" "%ProgramFiles(x86)%\Inno Setup 7" "%LOCALAPPDATA%\Programs\Inno Setup 7" "%ProgramFiles(x86)%\Inno Setup 6" "%ProgramFiles%\Inno Setup 6" "%LOCALAPPDATA%\Programs\Inno Setup 6") do if not defined ISCC if exist "%%~D\ISCC.exe" set "ISCC=%%~D\ISCC.exe"
if not defined ISCC for /f "tokens=2,*" %%A in ('reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 7_is1" /v InstallLocation 2^>nul ^| find "InstallLocation"') do if exist "%%~B\ISCC.exe" set "ISCC=%%~B\ISCC.exe"
if not defined ISCC for /f "tokens=2,*" %%A in ('reg query "HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 7_is1" /v InstallLocation 2^>nul ^| find "InstallLocation"') do if exist "%%~B\ISCC.exe" set "ISCC=%%~B\ISCC.exe"
if not defined ISCC for /f "tokens=2,*" %%A in ('reg query "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 7_is1" /v InstallLocation 2^>nul ^| find "InstallLocation"') do if exist "%%~B\ISCC.exe" set "ISCC=%%~B\ISCC.exe"
if not defined ISCC for /f "tokens=2,*" %%A in ('reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1" /v InstallLocation 2^>nul ^| find "InstallLocation"') do if exist "%%~B\ISCC.exe" set "ISCC=%%~B\ISCC.exe"
if not defined ISCC for /f "tokens=2,*" %%A in ('reg query "HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1" /v InstallLocation 2^>nul ^| find "InstallLocation"') do if exist "%%~B\ISCC.exe" set "ISCC=%%~B\ISCC.exe"
if not defined ISCC for %%I in (ISCC.exe) do if not "%%~$PATH:I"=="" set "ISCC=%%~$PATH:I"
if not defined ISCC goto noinno

echo [4/5] running Inno Setup ...
echo        using: %ISCC%
"%ISCC%" installer\vibe-blogpost-free.iss
if errorlevel 1 goto fail

echo.
echo [5/5] DONE
echo   Output is in the dist folder: dist\vibe-blogpost-free-setup-*.exe
echo   Distribute just that single setup file. Target PC needs Chrome.
goto end

:nowhere
echo [ERROR] app.py not found next to this script's parent folder.
echo         Put this .bat inside the project's scripts\ folder and run it there.
goto end

:nopy
echo [ERROR] Python not found.
echo         Install Python 3.12+ from https://www.python.org
echo         and tick "Add python.exe to PATH" during setup.
goto end

:noinno
echo.
echo [INFO] Inno Setup compiler (ISCC.exe) was not found (looked for v6 and v7).
echo        If NOT installed: get it from https://jrsoftware.org/isdl.php
echo        If already installed to a custom folder, tell me that folder
echo        and I will point the build at it directly.
echo        The onedir build is ready in: dist\vibe-blogpost-free\
goto end

:fail
echo.
echo [STOPPED] Build failed. Read the error message shown above.

:end
echo.
echo Press any key to close this window.
pause >nul
