@echo off
setlocal EnableExtensions
title ClipForge unattended
cd /d "%~dp0"

rem Reuse the normal setup; its own data/port environment variables remain selected.
call start.bat --setup-only
if errorlevel 1 exit /b 1

echo.
echo   ClipForge unattended mode
echo   Keep this window open. Ctrl+C stops the app and its workers.
echo   Open the address in your browser when you want to check its status.
echo.
".venv\Scripts\python.exe" -m clipfoundry --unattended %*
exit /b %errorlevel%
