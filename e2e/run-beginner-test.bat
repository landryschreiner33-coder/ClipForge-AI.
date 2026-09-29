@echo off
setlocal EnableExtensions
title ClipFoundry beginner-flow test (sandbox)
cd /d "%~dp0"

echo.
echo   ClipFoundry beginner-flow test
echo   ------------------------------
echo   Runs in a throwaway sandbox: its own temporary data, test connections to local stand-ins for
echo   YouTube and TikTok, and port 8799. Your real ClipFoundry, library and accounts are not touched,
echo   and it does not need to be running. Nothing is posted anywhere.
echo.

where npm >nul 2>nul
if errorlevel 1 (
  echo   [!] Node.js was not found. Install the LTS version from https://nodejs.org/
  echo       then run this file again.
  pause
  exit /b 1
)
if not exist "..\.venv\Scripts\python.exe" (
  echo   [!] ClipFoundry is not installed yet. Run start.bat once first.
  pause
  exit /b 1
)

if not exist "node_modules\@playwright\test" (
  echo   Installing Playwright - the first run takes a minute ...
  call npm install --no-audit --no-fund
  if errorlevel 1 (
    echo   [!] npm install failed. See the messages above.
    pause
    exit /b 1
  )
)
call npx playwright install chromium
if errorlevel 1 (
  echo   [!] Could not install Chromium for Playwright. See the messages above.
  pause
  exit /b 1
)

rem Extra arguments go to Playwright, e.g.  run-beginner-test.bat --headed
call npx playwright test -c playwright.sandbox.config.ts %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo   The beginner flow passed.
) else (
  echo   The test failed. The report with screenshots opens in your browser.
  if exist "playwright-report-sandbox\index.html" start "" "playwright-report-sandbox\index.html"
)
pause
exit /b %RC%
