@echo off
setlocal EnableExtensions
title ClipFoundry
cd /d "%~dp0"

echo.
echo   ClipFoundry - local AI clipping
echo   --------------------------------

rem ---------------------------------------------------------------- Python
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo   [!] Python 3.10+ was not found.
  echo       Install Python 3.11 or 3.12 from https://www.python.org/downloads/
  echo       and tick "Add python.exe to PATH", then run start.bat again.
  pause
  exit /b 1
)

rem ---------------------------------------------------------------- FFmpeg
where ffmpeg >nul 2>nul
if errorlevel 1 (
  if not exist "tools\ffmpeg\bin\ffmpeg.exe" (
    echo   [!] FFmpeg was not found. Install it with:
    echo         winget install Gyan.FFmpeg
    echo       or unzip an FFmpeg build so that tools\ffmpeg\bin\ffmpeg.exe exists.
    echo       The app will start, but cannot process video until FFmpeg is installed.
    echo.
  )
)

rem ------------------------------------------- virtual env + dependencies
if not exist ".venv\Scripts\python.exe" (
  echo   Creating Python environment in .venv ...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo   [!] Could not create the virtual environment.
    pause
    exit /b 1
  )
)
set "VPY=.venv\Scripts\python.exe"

fc /b requirements.txt ".venv\installed-requirements.txt" >nul 2>nul
if errorlevel 1 (
  echo   Installing dependencies - the first run takes a few minutes ...
  "%VPY%" -m pip install --upgrade pip >nul
  "%VPY%" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo   [!] Dependency installation failed. See the messages above.
    pause
    exit /b 1
  )
  copy /y requirements.txt ".venv\installed-requirements.txt" >nul
)

rem --------------------------------------- UI (prebuilt dist is committed)
if not exist "frontend\dist\index.html" (
  where npm >nul 2>nul
  if not errorlevel 1 (
    echo   Building the user interface ...
    pushd frontend
    call npm install
    call npm run build
    popd
  ) else (
    echo   [!] frontend\dist is missing and Node.js is not installed; only the API will be available.
  )
)

rem ------------------------------------------------------------------ run
"%VPY%" -m clipfoundry --open %*
echo.
pause
