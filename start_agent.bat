@echo off
REM ============================================================
REM  start_agent.bat — launch the free-web background agent INVISIBLY.
REM  No console window, no browser window. It polls the job queue
REM  every few seconds and drives websites headlessly.
REM
REM  First run ever?  Run setup_agent.bat once, then log in once per site:
REM      python -m src.agent.agent --show-login chatgpt_go
REM      python -m src.agent.agent --show-login gemini_web
REM      python -m src.agent.agent --show-login veo_web
REM ============================================================
cd /d "%~dp0"
start "" pythonw -m src.agent.agent
echo Background agent starting invisibly (check Free AI tab for status)...
timeout /t 3 >nul
