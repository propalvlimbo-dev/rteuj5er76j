@echo off
chcp 65001 >nul
title FreeCoder Router - 127.0.0.1:8788
cd /d "%~dp0"

echo.
echo   ==========================================================
echo     FreeCoder Router - шлюз к SmartAPI
echo     Адрес для редакторов: http://127.0.0.1:8788/v1
echo     Это окно не закрывайте, пока работаете в VS Code.
echo     Расход печатается после каждого запроса.
echo   ==========================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo   [ОШИБКА] Python не найден. Поставьте с python.org с галочкой "Add Python to PATH".
  pause
  exit /b 1
)

if not defined SMARTAPI_KEY (
  echo   [!] Переменная SMARTAPI_KEY не задана.
  echo       Запустите START.bat - он спросит ключ и сам поднимет роутер.
  echo.
  pause
  exit /b 1
)

set "CFG=config\providers.json"
if not "%~1"=="" set "CFG=%~1"

if not exist "%CFG%" (
  echo   [ОШИБКА] не найден "%CFG%" - файлы проекта распакованы полностью?
  pause
  exit /b 1
)

echo   Конфиг: %CFG%
echo.
python "app\router.py" --config "%CFG%" --port 8788
pause
