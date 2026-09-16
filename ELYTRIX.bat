@echo off
chcp 65001 >nul
setlocal EnableExtensions
title ELYTRIX - агент на SmartAPI

REM ---------------------------------------------------------------------------
REM  ELYTRIX - запуск одним двойным кликом.
REM  Что делает: ищет Python, добавляет app\ в пути, открывает консоль агента.
REM  Ключ спросит сам при первом запуске и сохранит в профиль Windows.
REM ---------------------------------------------------------------------------

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY where py >nul 2>nul && set "PY=py"
if not defined PY where python3 >nul 2>nul && set "PY=python3"

if not defined PY (
  echo.
  echo   [ОШИБКА] Python не найден.
  echo.
  echo   Поставьте его с https://www.python.org/downloads/ и ОБЯЗАТЕЛЬНО отметьте
  echo   галочку "Add Python to PATH". Затем закройте это окно и запустите файл снова.
  echo.
  pause
  exit /b 1
)

set "PYTHONPATH=%~dp0app;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"

"%PY%" "%~dp0app\run.py" %*
set "CODE=%ERRORLEVEL%"

if not "%CODE%"=="0" (
  echo.
  echo   Завершилось с кодом %CODE%. Если что-то не заработало - покажите мне текст выше.
  echo   Быстрая проверка: "%PY%" "%~dp0app\run.py" --doctor
  echo.
  pause
)
endlocal
exit /b %CODE%
