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
rem A known Anthropic SDK filename adds 133 characters under this folder.
rem Roots of 127+ characters reach Windows' standard 260-character path limit.
rem Warn only when installing; do not block computers with long paths enabled.
set "CF_INSTALL_ROOT=%CD%"
set "CF_LONG_PATH_RISK="
if not "%CF_INSTALL_ROOT:~126,1%"=="" set "CF_LONG_PATH_RISK=1"

if not exist ".venv\Scripts\python.exe" (
  echo   Creating Python environment in .venv ...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo   [!] Could not create the virtual environment.
    if defined CF_LONG_PATH_RISK (
      echo       This folder may exceed Windows path limits during setup.
      echo       Put fresh ZIP contents in C:\CF14 with start.bat directly inside,
      echo       then run setup there. Keep your normal app/data untouched.
      echo       Do not move or copy the partially created .venv.
    )
    pause
    exit /b 1
  )
)
set "VPY=.venv\Scripts\python.exe"

fc /b requirements.txt ".venv\installed-requirements.txt" >nul 2>nul
if errorlevel 1 (
  if defined CF_LONG_PATH_RISK (
    echo   [!] This folder may be too deep for Windows dependency installation.
    echo       If Windows long paths are disabled, pip can fail with a missing-file error.
    echo       For a new ZIP/test copy, put the fresh ZIP contents in C:\CF14,
    echo       with C:\CF14\start.bat directly inside that folder.
    echo       Keep your normal app/data untouched. Do not move or copy an old .venv.
    echo       Setup will continue for computers that support long paths.
    echo.
  )
  echo   Installing dependencies - the first run takes a few minutes ...
  "%VPY%" -m pip install --upgrade pip >nul
  "%VPY%" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo   [!] Dependency installation failed. See the messages above.
    if defined CF_LONG_PATH_RISK (
      echo       If pip mentions Windows long paths or a long missing SDK filename,
      echo       extract a fresh copy into C:\CF14 and run setup there again.
      echo       Keep the normal installation/data intact; do not copy its .venv.
    )
    pause
    exit /b 1
  )
  copy /y requirements.txt ".venv\installed-requirements.txt" >nul
)

rem ------------------------------ NVIDIA GPU: CUDA libraries for Whisper
rem faster-whisper (CTranslate2) needs the CUDA 12 cuBLAS/cuDNN libraries, whatever CUDA Toolkit is
rem installed. They come from pip (requirements-gpu.txt) and are only installed when an NVIDIA GPU exists.
set "NVSMI="
where nvidia-smi >nul 2>nul && set "NVSMI=nvidia-smi"
if not defined NVSMI if exist "%SystemRoot%\System32\nvidia-smi.exe" set "NVSMI=%SystemRoot%\System32\nvidia-smi.exe"
if not defined NVSMI if exist "%ProgramFiles%\NVIDIA Corporation\NVSMI\nvidia-smi.exe" set "NVSMI=%ProgramFiles%\NVIDIA Corporation\NVSMI\nvidia-smi.exe"
if defined NVSMI (
  "%NVSMI%" -L >nul 2>nul
  if errorlevel 1 set "NVSMI="
)
if defined NVSMI (
  fc /b requirements-gpu.txt ".venv\installed-gpu-requirements.txt" >nul 2>nul
  if errorlevel 1 (
    echo   NVIDIA GPU found - installing the CUDA libraries for GPU transcription.
    echo   This is a one-time download of about 1 GB ...
    "%VPY%" -m pip install -r requirements-gpu.txt
    if errorlevel 1 (
      echo   [!] Could not install the GPU libraries - transcription will use the CPU.
      echo       Check your internet connection and run start.bat again.
    ) else (
      copy /y requirements-gpu.txt ".venv\installed-gpu-requirements.txt" >nul
    )
  )
) else (
  echo   No NVIDIA GPU found - transcription will run on the CPU.
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

rem gpu-check.bat calls "start.bat --setup-only" to prepare this same environment without starting the app.
if /i "%~1"=="--setup-only" exit /b 0

rem ------------------------------------------------------------------ run
rem The app prints "Transcription: GPU mode" or "CPU mode" (with the reason) before it starts.
"%VPY%" -m clipfoundry --open %*
echo.
pause
