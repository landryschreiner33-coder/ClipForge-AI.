@echo off
setlocal EnableExtensions
rem ClipFoundry GPU check - runs a real Whisper transcription in the normal ClipFoundry environment
rem (.venv, set up exactly like start.bat does) and reports whether it ran on the NVIDIA GPU or the CPU.
rem   Double-click for a quick test, or drag a video onto this file for a realistic one.
rem   From a terminal:  gpu-check.bat "C:\Videos\podcast.mp4" [--seconds 120]
cd /d "%~dp0"

rem ------------------------------------------- is this folder up to date?
set "STALE="
if not exist "clipfoundry\gpucheck.py" set "STALE=1"
"%SystemRoot%\System32\find.exe" "--setup-only" start.bat >nul 2>nul
if errorlevel 1 set "STALE=1"
if defined STALE (
  echo.
  echo   [!] This ClipFoundry folder is out of date - the GPU check needs newer app files.
  echo       Update the whole folder, not only this file: run "git pull" in this folder, or download
  echo       the branch ZIP again and copy its contents over this folder. Your data and .venv folders stay.
  echo.
  pause
  exit /b 1
)

rem ----------------- same environment as start.bat: .venv, dependencies, CUDA libs
call "%~dp0start.bat" --setup-only
if errorlevel 1 exit /b 1
if not exist ".venv\Scripts\python.exe" (
  echo   [!] .venv\Scripts\python.exe was not found. Run start.bat once, then try again.
  pause
  exit /b 1
)

rem ------------------------------------------------------------------ run
title ClipFoundry GPU check
".venv\Scripts\python.exe" -m clipfoundry gpu-check %*
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%
