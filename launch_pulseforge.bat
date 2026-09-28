@echo off
REM ============================================================
REM PulseForge — one-click launcher (Windows).
REM
REM Every time you start the app, this checks the whole local
REM stack and installs whatever is missing (nothing is ever
REM reinstalled — each step skips what is already present):
REM   1. python deps      -> scripts\install_local.py
REM   2. ComfyUI + LTX    -> scripts\setup_comfyui.py
REM      (clones ComfyUI if absent, installs its requirements,
REM       downloads the LTX-Video model if no i2v model is found)
REM   3. starts ComfyUI on 127.0.0.1:8188 if it isn't listening
REM   4. starts the PulseForge app
REM
REM Just double-click this file after every `git pull`.
REM ============================================================
cd /d "%~dp0"
title PulseForge Launcher

where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python not found on PATH.
    echo         Install Python 3.10+ from https://www.python.org/downloads/
    echo         (tick "Add python.exe to PATH" during install), then retry.
    pause
    exit /b 1
)

echo.
echo === [1/4] Python dependencies (installs only what is missing) ===
python scripts\install_local.py

echo.
echo === [2/4] ComfyUI + LTX-Video (installs only what is missing) ===
python scripts\setup_comfyui.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [WARN] ComfyUI setup reported errors — the app will still start,
    echo        but AI video will show as offline until this is fixed.
    echo        Re-run this launcher after fixing (finished steps are skipped).
    echo.
    pause
)

echo.
echo === [3/4] ComfyUI server ===
python -c "import socket; socket.create_connection(('127.0.0.1',8188),timeout=3).close()" >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [*] ComfyUI is not listening on 127.0.0.1:8188 — starting it in a new window...
    start "PulseForge ComfyUI" "%~dp0start_comfyui.bat"
    echo [*] Waiting for ComfyUI to come up (up to 3 minutes)...
    python scripts\setup_comfyui.py --wait-for-port 127.0.0.1 8188 --timeout 180
    if %ERRORLEVEL% NEQ 0 (
        echo [WARN] ComfyUI did not come up in time — continuing anyway.
        echo        The app will report it as offline; check the ComfyUI window for errors.
    ) else (
        echo [ok] ComfyUI is up.
    )
) else (
    echo [--] ComfyUI already running on 127.0.0.1:8188.
)

echo.
echo === [4/4] Starting PulseForge app ===
echo      (keep this window open; close it to stop the app)
echo.
python app.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo App exited with code %ERRORLEVEL%.
    pause
)
