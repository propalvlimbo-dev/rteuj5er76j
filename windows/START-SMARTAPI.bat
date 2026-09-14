@echo off
chcp 65001 >nul
title FreeCoder - SmartAPI
cd /d "%~dp0.."

REM Находим Python: сначала python, потом py (лаунчер из Microsoft Store)
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY where py >nul 2>nul && set "PY=py"

if not defined PY (
  echo.
  echo  [ОШИБКА] Python не найден.
  echo  Поставьте его с https://www.python.org/downloads/ и ОБЯЗАТЕЛЬНО отметьте
  echo  галочку "Add Python to PATH", затем закройте это окно и запустите файл снова.
  echo.
  pause
  exit /b 1
)

"%PY%" "windows\launch.py" %*

if errorlevel 1 (
  echo.
  echo  Если что-то не заработало — скопируйте текст выше и покажите мне.
  pause
)
