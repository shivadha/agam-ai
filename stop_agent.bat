@echo off
REM ============================================================
REM  stop_agent.bat — stop the invisible background agent.
REM ============================================================
cd /d "%~dp0"
if not exist "data\agent.pid" (
    echo No agent PID file found — the agent is probably not running.
    pause
    exit /b 0
)
set /p AGENTPID=<"data\agent.pid"
echo Stopping background agent (PID %AGENTPID%)...
taskkill /PID %AGENTPID% /F >nul 2>&1
del "data\agent.pid" >nul 2>&1
del "data\agent_heartbeat.json" >nul 2>&1
echo Stopped.
pause
