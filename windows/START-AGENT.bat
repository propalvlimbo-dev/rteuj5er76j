@echo off
chcp 65001 >nul
title FreeCoder Agent
cd /d "%~dp0.."

echo.
echo  FreeCoder Agent - reads your files and edits them itself.
echo  Type a task in Russian, or /help for commands.
echo.

set "WS=%CD%"
if not "%~1"=="" set "WS=%~1"

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found. Run windows\install.ps1 first.
  pause
  exit /b 1
)

REM Check the router is alive; if not - warn (agent will show an error otherwise)
powershell -NoProfile -Command "try{ $r=Invoke-WebRequest -Uri 'http://127.0.0.1:8788/health' -TimeoutSec 2 -UseBasicParsing; exit 0 } catch { exit 1 }" >nul 2>nul
if errorlevel 1 (
  echo [i] Router is not running. Starting it in a separate window...
  start "FreeCoder Router" cmd /c "%~dp0START-ROUTER.bat"
  timeout /t 3 /nobreak >nul
)

python "agent\freecoder_agent.py" --workspace "%WS%"
pause
