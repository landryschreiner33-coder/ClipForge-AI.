@echo off
rem Checks that transcription really runs on the NVIDIA GPU.
rem Double-click it, or drag a video onto it for a realistic speed test.
call "%~dp0start.bat" gpu-check %*
