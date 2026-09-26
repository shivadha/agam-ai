@echo off
REM ============================================================
REM  setup_agent.bat — one-time setup for the free-web background agent
REM  Run this ONCE on your Windows PC before start_agent.bat.
REM  Installs Playwright + a private Chromium, and Scrapling
REM  (stealth web fetching for the scout).
REM ============================================================
cd /d "%~dp0"
echo [1/3] Installing playwright python package...
python -m pip install --upgrade playwright
echo [2/3] Installing agent Chromium (this downloads ~170MB once)...
python -m playwright install chromium
echo [3/3] Installing scrapling (stealth fetching for the scout)...
python -m pip install --upgrade "scrapling[fetchers]"
echo     Downloading the stealth browser (a few hundred MB, one time)...
python -m scrapling install
if errorlevel 1 (
  echo     NOTE: stealth browser install failed - the scout will still work
  echo     in fast/legacy mode, just without Cloudflare bypass.
)
echo.
echo Done. Now run start_agent.bat to launch the invisible background agent.
pause
