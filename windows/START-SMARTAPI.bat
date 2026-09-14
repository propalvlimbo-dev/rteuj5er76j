@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title FreeCoder - работа с моим кодом
cd /d "%~dp0.."

echo ============================================================
echo   FreeCoder: агент на вашем балансе SmartAPI
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [ОШИБКА] Python не найден. Поставьте с python.org и отметьте "Add Python to PATH".
  pause
  exit /b 1
)

REM ---------------------------------------------------------- ключ
if not defined SMARTAPI_KEY (
  echo Первый запуск: нужен ключ SmartAPI ^(sk-smart-...^) с сайта smartapi.shop/api-keys.
  echo.
  set /p "KEY=Вставьте ключ и нажмите Enter: "
  if "!KEY!"=="" (
    echo [ОШИБКА] Ключ не введён — работать не с чем.
    pause
    exit /b 1
  )
  set "SMARTAPI_KEY=!KEY!"
  setx SMARTAPI_KEY "!KEY!" >nul
  echo [i] Ключ сохранён в вашем профиле — в этот файл он не записан, в переписку не попадает.
  echo.
)

REM ---------------------------------------------------------- роутер
set "ROUTER_OK="
call :check_router
if defined ROUTER_OK (
  echo [i] Роутер уже работает.
) else (
  echo Шаг 1. Запускаю роутер ^(окно "FreeCoder Router"^)...
  start "FreeCoder Router" /d "%~dp0.." cmd /c "windows\START-ROUTER.bat router\providers.smartapi.json"
  call :wait_router
)
if not defined ROUTER_OK (
  echo.
  echo [!] Роутер не поднялся. Откройте окно "FreeCoder Router" — там написана причина.
  echo     Чаще всего: занят порт 8788 или ошибка в ключе.
  echo.
  pause
  exit /b 1
)
start "" http://127.0.0.1:8788/
echo [i] Панель расхода открыта в браузере ^(http://127.0.0.1:8788/^).
echo.

REM ---------------------------------------------------------- папка проекта
echo Шаг 2. В какой папке работать?
echo        Это папка с вашим кодом: агент сможет читать и править файлы только в ней.
echo        Можно вставить путь из проводника, Enter — оставить как предложено.
echo.
set "LASTFILE=%LOCALAPPDATA%\FreeCoder\last-workspace.txt"
set "WS="
if exist "!LASTFILE!" set /p WS=<"!LASTFILE!"
if not defined WS set "WS=%USERPROFILE%"

set "DIR="
set /p "DIR=Папка [!WS!]: "
if not "!DIR!"=="" set "WS=!DIR!"
set "WS=!WS:"=!"

if not exist "!WS!" (
  echo.
  echo [i] Папки "!WS!" нет. Создать? ^(агент будет работать в пустой папке^)
  set /p "MKD=Создать? [Y/n]: "
  if /i "!MKD!"=="n" (
    echo Отменено.
    pause
    exit /b 1
  )
  mkdir "!WS!" 2>nul
  if not exist "!WS!" (
    echo [ОШИБКА] Не удалось создать "!WS!" — проверьте путь.
    pause
    exit /b 1
  )
)

if not exist "%LOCALAPPDATA%\FreeCoder" mkdir "%LOCALAPPDATA%\FreeCoder" 2>nul
> "!LASTFILE!" echo !WS!
echo [i] Рабочая папка: !WS!
echo.

REM ---------------------------------------------------------- выбор модели
echo Шаг 3. Какой моделью работать?
echo    1) auto  — claude-sonnet-4-6  x2   рабочая лошадка, обычно её и хватает
echo    2) smart — claude-opus-4-8    x4   заметно умнее, расход вдвое больше
echo    3) max   — claude-opus-5      x5   самое сильное, для тяжёлых задач
echo    4) cheap — gpt-5.6-luna       x1.7 экономит баланс, простые правки
echo    5) выбрать в агенте: команда /model покажет полный список с ценами
echo.
set "MODEL=%FREECODER_MODEL%"
if not defined MODEL set "MODEL=auto"
set "PICK="
set /p "PICK=Номер [Enter = !MODEL!]: "
if "!PICK!"=="1" set "MODEL=auto"
if "!PICK!"=="2" set "MODEL=smart"
if "!PICK!"=="3" set "MODEL=max"
if "!PICK!"=="4" set "MODEL=cheap"
if not defined MODEL set "MODEL=auto"
set "FREECODER_MODEL=!MODEL!"
echo [i] Модель: !MODEL! ^(сменить в любой момент: /model^)
echo.

REM ---------------------------------------------------------- агент
echo Шаг 4. Агент. Пишите задачи словами прямо здесь:
echo          "исправь ошибку в api.py — падает на пустом ответе"
echo          "добавь в index.html секцию с ценами"
echo          "сделай папку demo с приветственной страницей"
echo        Каждую правку он покажет и спросит подтверждение ^(y^).
echo        Команды: /help, /diff, /undo, /model, /cd другая-папка, /exit
echo.
echo        Совет: если правите рабочий код — сначала сделайте в папке проекта
echo        git init и коммит, тогда откат возможен и через git.
echo.

python "agent\freecoder_agent.py" --workspace "!WS!" --model "!MODEL!"

echo.
echo ============================================================
echo   Работа окончена. Резервные копии правок: !WS!\.freecoder\
echo   Следующий раз — просто запустите этот файл снова.
echo ============================================================
pause
exit /b 0

REM ---------------------------------------------------------- подпрограммы
:check_router
python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8788/health',timeout=2).status==200 else 1)" >nul 2>nul
if not errorlevel 1 set "ROUTER_OK=1"
exit /b 0

:wait_router
set "ROUTER_OK="
for /l %%i in (1,1,25) do (
  if not defined ROUTER_OK (
    call :check_router
    if not defined ROUTER_OK timeout /t 1 /nobreak >nul
  )
)
exit /b 0
