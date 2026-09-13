@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title FreeCoder + SmartAPI
cd /d "%~dp0.."

echo ============================================================
echo   FreeCoder + SmartAPI: запускаю всё, что нужно
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [ОШИБКА] Python не найден. Установите с python.org и поставьте галочку "Add to PATH".
  pause
  exit /b 1
)

REM --- Проверяем или спрашиваем ключ (сохраняем в переменную окружения) ---
if not defined SMARTAPI_KEY (
  echo Учетная переменная SMARTAPI_KEY пока не задана.
  echo.
  set /p "KEY=Шаг 1. Вставьте ваш ключ sk-smart-... и нажмите Enter: "
  if "!KEY!"=="" (
    echo [ОШИБКА] Ключ не введён - запускать нечего.
    pause
    exit /b 1
  )
  set "SMARTAPI_KEY=!KEY!"
  setx SMARTAPI_KEY "!KEY!" >nul
  echo [i] Ключ сохранён в вашем профиле ^(в следующий раз спрашивать не буду^).
  echo.
)

REM --- Шаг 2. Роутер + дневной лимит расхода ---
echo Шаг 2. Запускаю роутер на http://127.0.0.1:8788 ...
start "FreeCoder Router (SmartAPI)" /d "%~dp0.." cmd /c "windows\START-ROUTER.bat router\providers.smartapi.json"

set "UP="
for /l %%i in (1,1,20) do (
  if not defined UP (
    powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'http://127.0.0.1:8788/health' -TimeoutSec 2 -UseBasicParsing ^| Out-Null; exit 0 } catch { exit 1 }" >nul 2>nul
    if not errorlevel 1 set "UP=1"
  )
)

if defined UP (
  echo [i] Роутер работает. Панель расхода открыта в браузере.
  start "" http://127.0.0.1:8788/
) else (
  echo [!] Роутер не ответил за 40 секунд. Посмотрите его окно - там написана причина.
)

REM --- Шаг 3. Папка для сайта ---
echo.
echo Шаг 3. Куда положить сайт?
set "SITE=%USERPROFILE%\site"
set /p "DIR=Папка [Enter = !SITE!]: "
if not "!DIR!"=="" set "SITE=!DIR!"
if not exist "!SITE!" mkdir "!SITE!" 2>nul
echo [i] Сайт будет здесь: !SITE!
echo.

REM --- Шаг 4. Агент: делает первую версию сайта ---
echo Шаг 4. Запускаю агента. Он сам создаст файлы в этой папке.
echo       Первую задачу он выполняет автоматически, дальше решаете вы.
echo.

python "agent\freecoder_agent.py" --workspace "!SITE!" --yes "сделай тёмный адаптивный сайт: index.html и style.css, аккуратный минималистичный дизайн"

echo.
echo ============================================================
echo   Первая версия готова: !SITE!\index.html
echo   Открыть: двойной клик по файлу index.html в проводнике.
echo ============================================================
echo.
echo Шаг 5. Дальше можно продолжать прямо здесь: пишите задачу словами,
echo       например "добавь секцию с контактами" или "сделай меню сверху".
echo       Каждую правку агент покажет и спросит подтверждение ^(y/n^).
echo       Выйти - команда /exit.
echo.

python "agent\freecoder_agent.py" --workspace "!SITE!"

pause
