@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found in PATH.
    echo Install Python 3.10+ and try again.
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_agent_mail.ps1"
if errorlevel 1 (
    echo.
    echo Agent Mail failed to start. Check data\web.log.
    pause
)
endlocal
