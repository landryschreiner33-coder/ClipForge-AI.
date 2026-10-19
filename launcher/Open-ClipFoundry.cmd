@echo off
setlocal EnableExtensions DisableDelayedExpansion
title ClipFoundry - source setup
echo.
echo ClipFoundry - source setup
echo Keep this window open while setup and the app run.
echo.
if not exist "%~dp0setup.py" goto missing_files
if not exist "%~dp0app.zip" goto missing_files
rem Probes must not trigger the Python Install Manager's automatic install.
set "PYTHON_MANAGER_AUTOMATIC_INSTALL=false"
set "PYLAUNCHER_ALLOW_INSTALL="
py -3.12-64 "%~dp0setup.py" --check-python >nul 2>nul
if "%errorlevel%"=="0" goto use_py312
py -3.12 "%~dp0setup.py" --check-python >nul 2>nul
if "%errorlevel%"=="0" goto use_py312_default
py -3.11-64 "%~dp0setup.py" --check-python >nul 2>nul
if "%errorlevel%"=="0" goto use_py311
py -3.11 "%~dp0setup.py" --check-python >nul 2>nul
if "%errorlevel%"=="0" goto use_py311_default
python "%~dp0setup.py" --check-python >nul 2>nul
if "%errorlevel%"=="0" goto use_python
python3 "%~dp0setup.py" --check-python >nul 2>nul
if "%errorlevel%"=="0" goto use_python3
echo A compatible Python was not found.
echo ClipFoundry needs 64-bit x86-64 CPython 3.12 or 3.11.
echo Install the Windows installer ^(64-bit^) for Python 3.12 from:
echo https://www.python.org/downloads/release/python-31210/
echo Keep your other Python versions. Reopen this launcher after installation.
echo Your saved Brain, settings, accounts and clips have not been changed.
pause
exit /b 1

:use_py312
py -3.12-64 "%~dp0setup.py"
set "CF_SOURCE_SETUP_RESULT=%errorlevel%"
goto finished

:use_py311
py -3.11-64 "%~dp0setup.py"
set "CF_SOURCE_SETUP_RESULT=%errorlevel%"
goto finished

:use_py312_default
py -3.12 "%~dp0setup.py"
set "CF_SOURCE_SETUP_RESULT=%errorlevel%"
goto finished

:use_py311_default
py -3.11 "%~dp0setup.py"
set "CF_SOURCE_SETUP_RESULT=%errorlevel%"
goto finished

:use_python
python "%~dp0setup.py"
set "CF_SOURCE_SETUP_RESULT=%errorlevel%"
goto finished

:use_python3
python3 "%~dp0setup.py"
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
