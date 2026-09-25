@echo off
REM ============================================================
REM  setup_agent.bat — one-time setup for the free-web background agent
REM  Run this ONCE on your Windows PC before start_agent.bat.
REM  Installs Playwright + a private Chromium for the agent.
REM ============================================================
cd /d "%~dp0"
echo [1/2] Installing playwright python package...
python -m pip install --upgrade playwright
echo [2/2] Installing agent Chromium (this downloads ~170MB once)...
python -m playwright install chromium
echo.
echo Done. Now run start_agent.bat to launch the invisible background agent.
pause
