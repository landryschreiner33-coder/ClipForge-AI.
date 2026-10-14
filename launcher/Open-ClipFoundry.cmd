@echo off
setlocal EnableExtensions DisableDelayedExpansion
title ClipFoundry - source setup
echo.
echo ClipFoundry - source setup
echo Keep this window open while setup and the app run.
echo.
if not exist "%~dp0setup.py" goto missing_files
if not exist "%~dp0app.zip" goto missing_files
where py >nul 2>nul
if not errorlevel 1 goto use_py
where python >nul 2>nul
if not errorlevel 1 goto use_python
echo Python was not found. Install Python 3.11 or 3.12 from:
echo https://www.python.org/downloads/windows/
echo Choose Add python.exe to PATH, then reopen this launcher.
pause
exit /b 1

:use_py
py -3 "%~dp0setup.py"
set "CF_SOURCE_SETUP_RESULT=%errorlevel%"
goto finished

:use_python
python "%~dp0setup.py"
set "CF_SOURCE_SETUP_RESULT=%errorlevel%"
goto finished

:missing_files
echo Setup files are missing. Use Extract All on the downloaded ZIP first.
echo Keep Open-ClipFoundry.cmd, setup.py and app.zip together.
pause
exit /b 1

:finished
if not "%CF_SOURCE_SETUP_RESULT%"=="0" echo Setup did not finish. Keep the error above and reopen to retry.
echo Press any key to close this window.
pause >nul
exit /b %CF_SOURCE_SETUP_RESULT%
