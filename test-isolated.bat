@echo off
setlocal EnableExtensions
title ClipFoundry - isolated PR 14 test
cd /d "%~dp0"
rem Always override inherited data/videos/port settings: this copy must not open the normal installation's data.
set "CLIPFOUNDRY_DATA=%~dp0data\pr14-test"
set "CLIPFOUNDRY_VIDEOS=%~dp0data\pr14-test\videos"
set "CLIPFOUNDRY_WORKERS=in_app"
set "CLIPFOUNDRY_PORT=8899"
echo.
echo   Separate test copy: http://127.0.0.1:8899
echo   Test data: %CLIPFOUNDRY_DATA%
echo   Keep the normal ClipFoundry closed while testing the GPU.
echo   Do not copy your normal data here or connect real posting accounts.
echo   Use a COPY of one of your own videos for the local workflow check.
echo.
call start.bat --port 8899
endlocal
