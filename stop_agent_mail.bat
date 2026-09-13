@echo off
setlocal
cd /d "%~dp0"
taskkill /IM AgentMail.exe /F >nul 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_web.ps1"
pause
endlocal
