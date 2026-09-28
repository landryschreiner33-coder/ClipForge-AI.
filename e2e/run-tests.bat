@echo off
setlocal EnableExtensions
title ClipFoundry browser tests
cd /d "%~dp0"

echo.
echo   ClipFoundry browser tests (read only: nothing in the app is changed)
echo   ---------------------------------------------------------------------
echo   ClipFoundry must already be running - start it with start.bat first.
echo.

where npm >nul 2>nul
if errorlevel 1 (
  echo   [!] Node.js was not found. Install the LTS version from https://nodejs.org/
  echo       then run this file again.
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

rem Downloads Chromium for Playwright once; later runs only check it is there.
call npx playwright install chromium
if errorlevel 1 (
  echo   [!] Could not install Chromium for Playwright. See the messages above.
  pause
  exit /b 1
)

rem Extra arguments go to Playwright, e.g.  run-tests.bat --headed   or   run-tests.bat tests/create.spec.ts
call npx playwright test %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo   All tests passed.
) else (
  echo   Some tests failed. The report with screenshots opens in your browser.
  echo   For step-by-step traces run:  npm run report   in this folder.
  if exist "playwright-report\index.html" start "" "playwright-report\index.html"
)
pause
exit /b %RC%
