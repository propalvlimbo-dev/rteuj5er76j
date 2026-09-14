# -*- coding: utf-8 -*-
<#
    FreeCoder — установка ИИ-агента на Windows 10/11 (работает на ключе SmartAPI).
    Ставит: Git, Python, Node.js, Ollama, opencode (терминальный агент) и Gemini CLI,
    раскладывает конфиги. Установщик НЕ обязателен: для работы на купленном балансе
    достаточно Python и windows\START-SMARTAPI.bat.

    Запуск (PowerShell от имени пользователя, НЕ обязательно админ):
        cd путь-к-папке-проекта
        powershell -ExecutionPolicy Bypass -File windows\install.ps1

    Полезные параметры:
        -SkipWinget       не ставить программы, только конфиги (если всё уже есть)
        -SkipLocalModel   не скачивать локальную модель (~5 ГБ)
        -ModelName "qwen2.5-coder:7b"
#>

[CmdletBinding()]
param(
    [switch]$SkipWinget,
    [switch]$SkipLocalModel,
    [string]$ModelName = "qwen2.5-coder:7b"
)

$ErrorActionPreference = "Continue"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Home_ = $env:USERPROFILE

function Say($text, $color = "Gray") { Write-Host $text -ForegroundColor $color }
function Step($n, $text) { Write-Host "`n[$n] $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "    ✓ $text" -ForegroundColor Green }
function Warn($text) { Write-Host "    ! $text" -ForegroundColor Yellow }
function Fail($text) { Write-Host "    ✗ $text" -ForegroundColor Red }

function Have($exe) {
    return [bool](Get-Command $exe -ErrorAction SilentlyContinue)
}

function Install-Pkg($id, $friendly, $exe) {
    if ($exe -and (Have $exe)) { Ok "$friendly уже установлен"; return $true }
    try {
        Say "    ставлю $friendly ($id)…" DarkGray
        winget install --id $id --source winget --accept-package-agreements --accept-source-agreements --silent | Out-Null
        Ok "$friendly установлен"
        return $true
    } catch {
        Warn "$friendly не установился автоматически — поставьте вручную"
        return $false
    }
}

Say "============================================================" "Cyan"
Say " FreeCoder: установка ИИ-агента для Windows (основной режим — ключ SmartAPI)" "Cyan"
Say "============================================================" "Cyan"
Say " Папка проекта: $RepoRoot"

# ---------------------------------------------------------------- 1. программ
Step 1 "Проверяю и ставлю необходимые программы (через winget)"

if (-not $SkipWinget) {
    if (-not (Have winget)) {
        Fail "winget не найден (нет App Installer из Microsoft Store)."
        Warn "Поставьте программы вручную: Git, Python 3.12+, Node.js LTS, Ollama — и запустите скрипт снова с -SkipWinget"
    } else {
        Install-Pkg "Git.Git" "Git" "git" | Out-Null
        Install-Pkg "Python.Python.3.12" "Python 3.12" "python" | Out-Null
        Install-Pkg "OpenJS.NodeJS.LTS" "Node.js LTS" "node" | Out-Null
        Install-Pkg "Ollama.Ollama" "Ollama (локальные модели)" "ollama" | Out-Null
        Warn "Новые программы появятся в PATH только в НОВОМ окне терминала. Если что-то не найдено — закройте это окно и запустите скрипт ещё раз."
    }
} else {
    Say "    пропускаю установку (флаг -SkipWinget)"
}

# Проверяем, что ключевые вещи доступны в текущем окне
$missing = @()
foreach ($pair in @(@("python", "Python"), @("node", "Node.js"), @("git", "Git"))) {
    if (-not (Have $pair[0])) { $missing += $pair[1] }
}
if ($missing.Count -gt 0) {
    Warn ("Не найдены в PATH: " + ($missing -join ", "))
    Warn "Закройте окно PowerShell, откройте новое и запустите: powershell -ExecutionPolicy Bypass -File windows\install.ps1 -SkipWinget"
}

# ---------------------------------------------------------------- 2. агенты
Step 2 "Ставлю терминальные агенты (opencode и Gemini CLI)"
if (Have node) {
    try {
        npm install -g opencode-ai | Out-Null
        Ok "opencode установлен (команда: opencode)"
    } catch { Warn "не удалось поставить opencode: $_" }
    try {
        npm install -g "@google/gemini-cli" | Out-Null
        Ok "Gemini CLI установлен (команда: gemini)"
    } catch { Warn "не удалось поставить Gemini CLI (не критично)" }
} else {
    Warn "Node.js не найден — пропускаю установку агентов. Поставьте Node.js LTS и повторите."
}

# ---------------------------------------------------------------- 3. ключи
Step 3 "Конфиг провайдеров (router\providers.json)"
$providersFile = Join-Path $RepoRoot "router\providers.json"
$exampleFile = Join-Path $RepoRoot "router\providers.example.json"
if (-not (Test-Path $providersFile)) {
    if (Test-Path $exampleFile) {
        Copy-Item $exampleFile $providersFile
        Ok "создан router\providers.json"
    } else {
        Fail "не найден router\providers.example.json — файлы проекта распакованы полностью?"
    }
} else {
    Ok "router\providers.json уже существует (не трогаю — там ваши ключи)"
}
Say "    Если работаете на купленном балансе SmartAPI — этот шаг можно пропустить:" "Yellow"
Say "    ключ читается из переменной окружения SMARTAPI_KEY, а конфиг уже готов —" "Yellow"
Say "    windows\START-SMARTAPI.bat. Здесь же настраивается резерв на бесплатных моделях." "Yellow"
Say "    Сейчас откроется Блокнот: вставьте ключи в поля \"keys\": [...] у нужных провайдеров." "Yellow"
Say "    Как получить бесплатные ключи — docs\архив\02-КЛЮЧИ-БЕСПЛАТНО.md" "Yellow"
Say "    Можно закрыть Блокнот без изменений и заполнить позже." "Yellow"
Start-Process notepad.exe -ArgumentList "`"$providersFile`"" -Wait

# ---------------------------------------------------------------- 4. конфиги агентов
Step 4 "Раскладываю конфиги для агентов и VS Code"

# opencode
$ocDir = Join-Path $Home_ ".config\opencode"
New-Item -ItemType Directory -Force -Path $ocDir | Out-Null
$ocSrc = Join-Path $RepoRoot "opencode\opencode.json"
$ocDst = Join-Path $ocDir "opencode.json"
if ((Test-Path $ocSrc) -and -not (Test-Path $ocDst)) {
    Copy-Item $ocSrc $ocDst
    Ok "opencode: $ocDst"
} elseif (Test-Path $ocDst) {
    Ok "opencode уже настроен: $ocDst (ваш файл не тронут)"
}

# Continue (VS Code / JetBrains)
$contDir = Join-Path $Home_ ".continue"
New-Item -ItemType Directory -Force -Path $contDir | Out-Null
$contSrc = Join-Path $RepoRoot "vscode\continue-config.yaml"
$contDst = Join-Path $contDir "config.yaml"
if ((Test-Path $contSrc) -and -not (Test-Path $contDst)) {
    Copy-Item $contSrc $contDst
    Ok "Continue: $contDst"
} elseif (Test-Path $contDst) {
    Ok "Continue уже настроен: $contDst (ваш файл не тронут)"
}

# ---------------------------------------------------------------- 5. локальная модель
Step 5 "Локальная модель (последний рубеж: работает без интернета и без лимитов)"
if ($SkipLocalModel) {
    Say "    пропускаю (флаг -SkipLocalModel)"
} elseif (Have ollama) {
    Say "    скачиваю $ModelName — это ~5 ГБ, один раз. Можно прервать: модель не обязательна."
    try {
        & ollama pull $ModelName
        Ok "локальная модель готова: $ModelName"
    } catch { Warn "не удалось скачать модель: $_   (позже: ollama pull $ModelName)" }
} else {
    Warn "Ollama не найдена. Поставьте её позже и выполните: ollama pull $ModelName"
}

# ---------------------------------------------------------------- 6. проверка
Step 6 "Проверяю, что всё на месте"
$checks = @(
    @{ Name = "Python";   Ok = (Have python) },
    @{ Name = "Node.js";  Ok = (Have node) },
    @{ Name = "Git";      Ok = (Have git) },
    @{ Name = "opencode"; Ok = (Have opencode) },
    @{ Name = "Ollama";   Ok = (Have ollama) },
    @{ Name = "роутер";   Ok = (Test-Path (Join-Path $RepoRoot "router\freecoder_router.py")) },
    @{ Name = "агент";    Ok = (Test-Path (Join-Path $RepoRoot "agent\freecoder_agent.py")) },
    @{ Name = "ключи";    Ok = (Test-Path $providersFile) }
)
foreach ($c in $checks) {
    if ($c.Ok) { Ok $c.Name } else { Warn "$($c.Name) — не найден" }
}

Say "`n============================================================" "Green"
Say " Готово. Как запускать:" "Green"
Say "============================================================" "Green"
Say @"

 1) Двойной клик: windows\START-ROUTER.bat     ← держите это окно открытым
 2) Затем:
      · свой агент:      windows\START-AGENT.bat  "исправь ошибку в main.py"
      · opencode (TUI):  windows\START-OPENCODE.bat
      · VS Code:         поставьте расширения Cline и Kilo Code,
                         провайдер = "OpenAI Compatible",
                         Base URL = http://127.0.0.1:8788/v1
                         API Key  = freecoder,  Model = smart

 Панель роутера (кто сколько квоты съел): http://127.0.0.1:8788/

 Проверка без ключей: windows\START-ROUTER.bat с ключом --mock (в файле запуска
 добавьте --mock в конец строки с python) — агент заработает на заглушке.

 Если что-то не так — docs\01-БЫСТРЫЙ-СТАРТ.md, раздел «Если не заработало».
"@ "White"
