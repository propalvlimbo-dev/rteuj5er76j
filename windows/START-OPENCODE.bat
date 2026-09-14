@echo off
chcp 65001 >nul
title opencode + FreeCoder Router
cd /d "%~dp0.."

set "WS=%CD%"
if not "%~1"=="" set "WS=%~1"

echo.
echo  opencode will start in: %WS%
echo  Model: freecoder/auto  (Sonnet 4.6 via SmartAPI; /model smart = Opus, local = offline)
echo.

where opencode >nul 2>nul
if errorlevel 1 (
  echo [ERROR] opencode not found. Run: npm install -g opencode-ai
  pause
  exit /b 1
)

powershell -NoProfile -Command "try{ Invoke-WebRequest -Uri 'http://127.0.0.1:8788/health' -TimeoutSec 2 -UseBasicParsing | Out-Null; exit 0 } catch { exit 1 }" >nul 2>nul
if errorlevel 1 (
  echo [i] Router is not running. Starting it in a separate window...
  start "FreeCoder Router" /d "%~dp0.." cmd /c "windows\START-ROUTER.bat"
  timeout /t 3 /nobreak >nul
)

cd /d "%WS%"
opencode
pause
