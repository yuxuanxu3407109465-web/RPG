@echo off
rem Fengcheng Day 7 - web version launcher (Windows)
rem Double-click this file to start the local server and open the game in your browser.
rem If the game is already running, this only prints the address: no second server,
rem and no extra browser tab (the page keeps the server alive with a heartbeat).
rem Keep this window open while playing; close it to stop the server, or use the
rem in-game "退出游戏" button, which stops the server for you.
rem Closing the browser page also ends the game and stops the server; in that case
rem this window closes itself (webui.py exit code 2, see the bottom of this file).
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 webui.py
) else (
  python webui.py
)

rem webui.py exit codes: 2 = the page was closed / quit (game over, server down),
rem 3 = the game was already running, so this window did nothing.
if errorlevel 3 goto autoclose
if errorlevel 2 goto autoclose

echo.
echo Server stopped. Press any key to close.
pause >nul
exit /b 0

:autoclose
rem Nothing left to do: show the last line for a moment, then close this window.
timeout /t 3 >nul 2>nul
exit /b 0
