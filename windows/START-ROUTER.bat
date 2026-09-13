@echo off
chcp 65001 >nul
title FreeCoder Router - free model gateway
cd /d "%~dp0.."

echo.
echo  ============================================================
echo   FreeCoder Router - starts on http://127.0.0.1:8788
echo   Dashboard: http://127.0.0.1:8788/
echo   Keep this window open while working in the agent.
echo  ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found. Run windows\install.ps1 first, or install from python.org
  pause
  exit /b 1
)

if not exist "router\providers.json" (
  echo [i] router\providers.json not found - copying the example.
  copy /y "router\providers.example.json" "router\providers.json" >nul
  echo [i] Open router\providers.json and paste your free API keys, then restart.
)

python "router\freecoder_router.py" --port 8788
pause
