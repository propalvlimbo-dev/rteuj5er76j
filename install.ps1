# -*- coding: utf-8 -*-
<#
    FreeCoder — установка на Windows 10/11. Работаем на ключе SmartAPI.

    Обязательный минимум — только Python. Всё остальное (Node.js, opencode,
    редакторы) ставится по желанию.

    Запуск (PowerShell от имени пользователя, админ не нужен):
        cd путь-к-папке-проекта
        powershell -ExecutionPolicy Bypass -File install.ps1

    Параметры:
        -SkipWinget   не ставить программы, только разложить конфиги
        -WithNode     дополнительно поставить Node.js и opencode (терминальный агент)
#>

[CmdletBinding()]
param(
    [switch]$SkipWinget,
    [switch]$WithNode
)

$ErrorActionPreference = "Continue"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Home_ = $env:USERPROFILE

function Say($t, $c = "Gray") { Write-Host $t -ForegroundColor $c }
function Step($n, $t) { Write-Host "`n[$n] $t" -ForegroundColor Cyan }
function Ok($t) { Write-Host "    ✓ $t" -ForegroundColor Green }
function Warn($t) { Write-Host "    ! $t" -ForegroundColor Yellow }
function Fail($t) { Write-Host "    ✗ $t" -ForegroundColor Red }
function Have($exe) { return [bool](Get-Command $exe -ErrorAction SilentlyContinue) }

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

Say " FreeCoder: установка (работаем на ключе SmartAPI)" "Cyan"
Say " Папка проекта: $RepoRoot" Gray

# ---------------------------------------------------------------- 1. программы
Step 1 "Программы"
if ($SkipWinget) {
    Say "    пропускаю установку (флаг -SkipWinget)"
} elseif (-not (Have winget)) {
    Warn "winget не найден. Поставьте Python вручную с python.org (галочка Add to PATH)"
    Warn "и запустите скрипт снова с -SkipWinget"
} else {
    Install-Pkg "Python.Python.3.12" "Python 3.12" "python" | Out-Null
    if ($WithNode) {
        Install-Pkg "OpenJS.NodeJS.LTS" "Node.js LTS" "node" | Out-Null
    } else {
        Say "    Node.js не ставлю (нужен только для opencode: запустите с -WithNode)" DarkGray
    }
    Warn "Новые программы появятся в PATH только в НОВОМ окне терминала."
}

# ---------------------------------------------------------------- 2. ключ
Step 2 "Ключ SmartAPI"
if ($env:SMARTAPI_KEY) {
    Ok "переменная SMARTAPI_KEY уже задана"
} else {
    Warn "SMARTAPI_KEY не задана"
    Say "    Ключ вводится один раз при запуске START.bat —" Yellow
    Say "    скрипт сохранит его в переменную окружения пользователя." Yellow
    Say "    Взять ключ: https://smartapi.shop/api-keys" Yellow
}

# ---------------------------------------------------------------- 3. конфиг
Step 3 "Конфиг роутера"
$cfg = Join-Path $RepoRoot "config\providers.json"
if (Test-Path $cfg) {
    Ok "config\providers.json на месте (модели и дневной лимит уже настроены)"
} else {
    Fail "не найден config\providers.json — файлы проекта распакованы полностью?"
}

# ---------------------------------------------------------------- 4. конфиги агентов
Step 4 "Конфиги для opencode и Continue (VS Code)"
foreach ($pair in @(
    @{ Src = "config\opencode.json";  Dst = ".config\opencode\opencode.json";  Name = "opencode" },
    @{ Src = "config\continue.yaml";  Dst = ".continue\config.yaml";           Name = "Continue" }
)) {
    $src = Join-Path $RepoRoot $pair.Src
    $dst = Join-Path $Home_ $pair.Dst
    New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
    if ((Test-Path $src) -and -not (Test-Path $dst)) {
        Copy-Item $src $dst
        Ok "$($pair.Name): $dst"
    } elseif (Test-Path $dst) {
        Ok "$($pair.Name) уже настроен: $dst (ваш файл не тронут)"
    }
}

# ---------------------------------------------------------------- 5. проверка
Step 5 "Проверка"
$checks = @(
    @{ Name = "Python";  Ok = (Have python) },
    @{ Name = "роутер";  Ok = (Test-Path (Join-Path $RepoRoot "app\router.py")) },
    @{ Name = "агент";   Ok = (Test-Path (Join-Path $RepoRoot "app\agent.py")) },
    @{ Name = "конфиг";  Ok = (Test-Path $cfg) }
)
foreach ($c in $checks) {
    if ($c.Ok) { Ok $c.Name } else { Warn "$($c.Name) — не найден" }
}

Say "`n============================================================" "Green"
Say " Готово. Как работать:" "Green"
Say "============================================================" "Green"
Say @"

 1) Двойной клик: START.bat
      · спросит ключ SmartAPI (один раз),
      · поднимет роутер с дневным лимитом,
      · спросит папку с вашим кодом и запустит агента в ней.

 2) Задачи пишутся словами в окне агента:
      · «исправь ошибку в api.py — падает на пустом ответе»
      · «добавь в index.html секцию с ценами»
    Правки применяются сразу, откат — /undo.

 3) Смена модели — команда /model в агенте (Claude, GPT, Codex с коэффициентами).
    Расход — команда /tokens; новая задача без старой истории — /clear.

 4) Для VS Code (Cline/Continue) отдельно: START-ROUTER.bat — роутер в своём окне.

 Инструкции: docs\01-БЫСТРЫЙ-СТАРТ.md, docs\07-РАБОТА-С-МОИМ-КОДОМ.md,
             docs\08-ЭКОНОМИЯ-ТОКЕНОВ.md (как тратить меньше)
"@ "White"
