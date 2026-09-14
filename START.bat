@echo off
chcp 65001 >nul
title FreeCoder - агент на SmartAPI
cd /d "%~dp0"

echo.
echo   ==========================================================
echo     FreeCoder 2.0 - агент, который правит ваш код
echo     ключ SmartAPI ^> роутер ^> модель ^> папка ^> работа
echo   ==========================================================
echo.

REM Ищем Python: сначала python, потом py (лаунчер из Microsoft Store)
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY where py >nul 2>nul && set "PY=py"

if not defined PY (
  echo   [ОШИБКА] Python не найден.
  echo   Поставьте его с https://www.python.org/downloads/ и обязательно отметьте
  echo   галочку "Add Python to PATH", затем закройте это окно и запустите файл снова.
  echo.
  pause
  exit /b 1
)

"%PY%" "app\launch.py" %*

if errorlevel 1 (
  echo.
  echo   Если что-то не заработало - скопируйте текст выше и покажите мне.
  pause
)
