@echo off
title AGAM AI Studio
cd /d "%~dp0"

echo ========================================================
echo   AGAM AI Studio - starting...
echo   ComfyUI + Ollama will auto-start if not already running
echo   (set AGAM_NO_AUTOSTART=1 to disable auto-start)
echo ========================================================

where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python not found on PATH. Install Python 3.10+ and retry.
    pause
    exit /b 1
)

python app.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo App exited with code %ERRORLEVEL%.
    pause
)
