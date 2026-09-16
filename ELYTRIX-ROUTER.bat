@echo off
chcp 65001 >nul
setlocal EnableExtensions
title ELYTRIX Router - 127.0.0.1:8789

REM ---------------------------------------------------------------------------
REM  Отдельное окно роутера - только если вы работаете в редакторе
REM  (Cline, Continue, Kilo Code, opencode, Cursor).
REM  Адрес для редактора:  http://127.0.0.1:8789/v1   ключ: любой (например elytrix)
REM  Самой консоли ELYTRIX роутер не нужен - она говорит со шлюзом напрямую.
REM  Внутри консоли роутер поднимается командой /router.
REM ---------------------------------------------------------------------------

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY where py >nul 2>nul && set "PY=py"
if not defined PY where python3 >nul 2>nul && set "PY=python3"

if not defined PY (
  echo   [ОШИБКА] Python не найден. Поставьте с python.org, галочка "Add Python to PATH".
  pause
  exit /b 1
)

set "PORT=8789"
if not "%~1"=="" set "PORT=%~1"

set "PYTHONPATH=%~dp0app;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"

echo.
echo   ELYTRIX Router - шлюз для редакторов на порту %PORT%
echo   Это окно не закрывайте, пока работаете в VS Code.
echo.

"%PY%" "%~dp0app\run.py" --router %PORT%
if errorlevel 1 (
  echo.
  echo   Роутер не запустился. Частая причина - ключ SMARTAPI_KEY не задан:
  echo   запустите сначала ELYTRIX.bat, он спросит ключ и сохранит его.
  echo.
  pause
)
endlocal
