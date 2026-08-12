@echo off
rem ==================================================================
rem   vibe-blogpost  -  Windows installer (setup.exe) builder
rem   2026-08-10: renamed build (was vibe-blogpost-free). Now builds
rem   from vibe-blogpost.spec so bundle assets come from the sibling
rem   ..\vibe-blogcore folder (core split, 2026-07-30).
rem   ASCII-only + goto-based (no parenthesized blocks) so it never
rem   silently closes. Do NOT add non-ASCII characters to this file.
rem ==================================================================
setlocal enableextensions
cd /d "%~dp0\.."

echo ==================================================
echo   vibe-blogpost : building setup.exe
echo ==================================================
echo.

if not exist "app.py" goto nowhere
if not exist "..\vibe-blogcore\config\blog_selectors.yaml" goto nocore

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

rem --- 3) PyInstaller onedir build (spec drives everything) --------
rem  The spec pulls config/templates from ..\vibe-blogcore (SPECPATH),
rem  so keep the two folders side by side when building.
echo [3/5] running PyInstaller (vibe-blogpost.spec) ...
"%VPY%" -m PyInstaller --noconfirm --clean vibe-blogpost.spec
if errorlevel 1 goto fail
if not exist "dist\vibe-blogpost\vibe-blogpost.exe" goto nodist

rem --- 5) locate Inno Setup compiler (ISCC.exe) --------------------
rem  (version is defined inside the .iss: #define MyAppVersion "1.1.0")
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
"%ISCC%" installer\vibe-blogpost.iss
if errorlevel 1 goto fail

echo.
echo [5/5] DONE
echo   Output is in the dist folder: dist\vibe-blogpost-setup-*.exe
echo   Distribute just that single setup file. Target PC needs Chrome.
goto end

:nowhere
echo [ERROR] app.py not found next to this script's parent folder.
echo         Put this .bat inside the project's scripts\ folder and run it there.
goto end

:nocore
echo [ERROR] sibling folder ..\vibe-blogcore not found (core split, 2026-07-30).
echo         The spec bundles config/templates from vibe-blogcore.
echo         Keep vibe-blogpost and vibe-blogcore side by side, then retry.
goto end

:nodist
echo [ERROR] PyInstaller finished but dist\vibe-blogpost\vibe-blogpost.exe is missing.
echo         Check the build log above.
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
echo        The onedir build is ready in: dist\vibe-blogpost\
goto end

:fail
echo.
echo [STOPPED] Build failed. Read the error message shown above.

:end
echo.
echo Press any key to close this window.
pause >nul
