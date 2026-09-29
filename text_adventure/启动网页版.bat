@echo off
rem Fengcheng Day 7 - web version launcher (Windows)
rem Double-click this file to start the local server and open the game in your browser.
rem Keep this window open while playing; close it to stop the server.
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 webui.py
) else (
  python webui.py
)

echo.
echo Server stopped. Press any key to close.
pause >nul
