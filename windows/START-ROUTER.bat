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

set "CFG=router\providers.json"
if not "%~1"=="" set "CFG=%~1"

REM SmartAPI: если запущено без аргументов, а ключ SMARTAPI_KEY уже есть -
REM берём готовый конфиг с дневным лимитом и бесплатным резервом.
if "%~1"=="" if not exist "router\providers.json" if defined SMARTAPI_KEY if exist "router\providers.smartapi.json" set "CFG=router\providers.smartapi.json"

if not exist "%CFG%" (
  echo [i] Config "%CFG%" not found - copying the example.
  copy /y "router\providers.example.json" "router\providers.json" >nul
  echo [i] Open router\providers.json and paste your API keys, then restart.
)

echo  Config: %CFG%
python "router\freecoder_router.py" --config "%CFG%" --port 8788
pause
