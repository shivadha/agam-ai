@echo off
title PulseForge - ComfyUI AI Video Engine
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_comfyui.ps1"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Script ended with code %ERRORLEVEL%.
    pause
)
