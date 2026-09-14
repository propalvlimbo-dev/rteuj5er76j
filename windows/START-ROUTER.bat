@echo off
chcp 65001 >nul
title FreeCoder Router - SmartAPI
cd /d "%~dp0.."

echo.
echo  ============================================================
echo   FreeCoder Router - http://127.0.0.1:8788
echo   Панель расхода: http://127.0.0.1:8788/
echo   Это окно должно оставаться открытым, пока вы работаете.
echo  ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [ОШИБКА] Python не найден. Поставьте с python.org с галочкой "Add Python to PATH".
  pause
  exit /b 1
)

if not defined SMARTAPI_KEY (
  echo [!] Переменная SMARTAPI_KEY не задана.
  echo     Запустите windows\START-SMARTAPI.bat - он спросит ключ и сам поднимет роутер.
  echo.
  pause
  exit /b 1
)

set "CFG=router\providers.smartapi.json"
if not "%~1"=="" set "CFG=%~1"

if not exist "%CFG%" (
  echo [ОШИБКА] Не найден "%CFG%" - файлы проекта распакованы полностью?
  pause
  exit /b 1
)

echo  Конфиг: %CFG%
python "router\freecoder_router.py" --config "%CFG%" --port 8788
pause
