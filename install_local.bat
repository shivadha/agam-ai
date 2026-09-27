@echo off
REM AGAM AI Studio — one-command local setup (Windows).
REM Run this after every `git pull`.
cd /d "%~dp0"
python scripts\install_local.py %*
if errorlevel 1 (
    echo.
    echo Setup reported errors — see above.
    pause
)
