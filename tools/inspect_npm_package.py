#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inspect_npm_package.py — разбор чужого npm-пакета ДО установки.

Зачем: команда вида
    npm install -g https://чужой-сайт/пакет.tgz
скачивает и устанавливает пакет из интернета, при этом любые скрипты жизненного цикла
(preinstall / install / postinstall) выполняются СРАЗУ, с вашими правами, ещё до того, как
вы запустите саму программу. Такой скрипт может прочитать ~/.ssh, ~/.aws, .env, cookies
браузера, поставить автозапуск или увести переменные окружения на чужой сервер.

Этот инструмент ничего не запускает. Он только читает:
  · скачивает архив (или берёт локальный файл) и считает SHA-256;
  · безопасно распаковывает (отсекает абсолютные пути, '..', симлинки наружу);
  · показывает package.json: скрипты жизненного цикла, зависимости, точку входа;
  · ищет в коде опасные приёмы: запуск процессов, eval, доступ к секретам, сеть,
    автозапуск, обфускацию, запись в конфиги инструментов и в профили оболочки;
  · выдаёт вердикт и JSON-отчёт с точными строками-доказательствами.

Использование:
    python tools/inspect_npm_package.py https://site/pkg.tgz
    python tools/inspect_npm_package.py ./pkg.tgz --report pkg-report.json
    python tools/inspect_npm_package.py https://site/pkg.tgz --keep   # оставить распакованное

Только стандартная библиотека Python 3.8+.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

VERSION = "1.0.0"

TEXT_EXT = {".js", ".mjs", ".cjs", ".ts", ".json", ".sh", ".ps1", ".bat", ".cmd", ".py",
            ".yml", ".yaml", ".txt", ".md", ".env", ".toml", ".ini", ".cfg", ".lock"}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2", ".ttf",
            ".otf", ".mp3", ".mp4", ".zip", ".gz", ".tgz", ".exe", ".dll", ".so", ".node",
            ".wasm", ".map", ".pdf"}
MAX_FILE_BYTES = 3_000_000
MAX_FINDINGS_PER_RULE = 8

# ---------------------------------------------------------------------------
# Правила поиска. severity: crit | high | med | info
# ---------------------------------------------------------------------------

SENSITIVE_PATHS = [
    (r"\.ssh\b|id_rsa|id_ed25519|authorized_keys", "ключи SSH"),
    (r"\.aws[/\\](credentials|config)", "ключи AWS"),
    (r"\.(npmrc|git-credentials|netrc)\b", "учётные данные пакетных менеджеров/git"),
    (r"\.docker[/\\]config\.json|\bconfig\.json\b.*docker", "ключи Docker"),
    (r"wallet\.dat|MetaMask|keystore|electrum|phantom|seed ?phrase", "крипто-кошельки"),
    (r"(Chrome|Edge|Brave|Firefox|Opera)[/\\].*(Cookies|Login Data|Local State|key[34]\.db)",
     "cookies и пароли браузера"),
    (r"\.config[/\\](discord|telegram)|tdata\b|Telegram Desktop", "токены Discord/Telegram"),
    (r"\b\.env\b|dotenv", "файлы с секретами проекта"),
    (r"\.kube[/\\]config|\.azure[/\\]|\.gcloud[/\\]", "облачные конфиги"),
    (r"keychain|login\.keychain|Credential Manager|wincred", "системные хранилища паролей"),
]

RULES: List[Tuple[str, str, str, str]] = [
    # (id, severity, regex, описание)
    ("proc", "high", r"child_process|execSync\(|\bexec\(|spawnSync\(|\bspawn\(|\.exec\(|execFile",
     "запуск внешних процессов"),
    ("eval", "high", r"\beval\s*\(|new Function\s*\(|vm\.runIn|require\(['\"]child_process",
     "динамическое исполнение кода"),
    ("net", "med", r"https?\.request\(|https?\.get\(|axios|\bfetch\(|net\.connect|WebSocket\(",
     "исходящие сетевые запросы"),
    ("hard_ip", "high", r"https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?",
     "обращение по IP-адресу вместо домена"),
    ("plain_http", "high", r"http://(?!localhost|127\.0\.0\.1)[a-z0-9\-\.]+",
     "незашифрованный HTTP (данные видны по пути)"),
    ("env_dump", "crit", r"JSON\.stringify\(\s*process\.env|Object\.entries\(\s*process\.env"
                          r"|for\s*\(\s*(const|let|var)\s+\w+\s+in\s+process\.env",
     "сбор всего окружения (типичная подготовка к отправке наружу)"),
    ("exfil_hook", "crit", r"discord\.com/api/webhooks|api\.telegram\.org|t\.me/|pastebin|"
                            r"transfer\.sh|0x0\.st|webhook\.site|requestbin|ngrok",
     "отправка данных на публичный приёмник"),
    ("persist", "crit", r"crontab|systemd|LaunchAgents|schtasks|reg\s+add.*Run|"
                         r"CurrentVersion\\\\Run|Startup[/\\]|\.bashrc|\.zshrc|\.profile\b|"
                         r"Microsoft\.PowerShell_profile|shell_profile",
     "автозапуск или правка профиля оболочки"),
    ("obfusc", "high", r"atob\(|Buffer\.from\([^)]*['\"]base64|\\x[0-9a-f]{2}\\x[0-9a-f]{2}\\x[0-9a-f]{2}",
     "обфускация (декодирование скрытых данных)"),
    ("tool_cfg", "med", r"\.claude|\.codex|opencode|\.continue|cline|kilo|Cursor|settings\.json",
     "правка конфигов ИИ-инструментов"),
    ("destructive", "crit", r"rm\s+-rf\s+[~/]|rmSync\([^)]*recursive|rimraf\(.*homedir|"
                            r"format\s+[a-z]:|Remove-Item.*-Recurse.*-Force",
     "потенциально разрушительные операции с файлами"),
    ("telemetry", "med", r"analytics|telemetry|posthog|mixpanel|sentry|amplitude|segment",
     "телеметрия/аналитика"),
    ("dyn_require", "high", r"require\(\s*[^'\")\s]|import\(\s*[^'\")\s]",
     "подключение модулей по вычисляемому имени (маскировка)"),
    ("env_write", "high", r"fs\.(appendFile|writeFile)Sync?\([^)]*\.(bashrc|zshrc|profile|npmrc|ssh)",
     "запись в файлы оболочки или учётных данных"),
]

LIFECYCLE = ["preinstall", "install", "postinstall", "prepare", "prepublish", "prepublishOnly",
             "preuninstall", "postuninstall"]


@dataclass
class Finding:
    rule: str
    severity: str
    file: str
    line: int
    text: str
    what: str


@dataclass
class Report:
    source: str
    sha256: str = ""
    size: int = 0
    files: List[str] = field(default_factory=list)
    package_json: Dict[str, Any] = field(default_factory=dict)
    lifecycle_scripts: Dict[str, str] = field(default_factory=dict)
    findings: List[Finding] = field(default_factory=list)
    verdict: str = ""
    notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Скачивание и безопасная распаковка
# ---------------------------------------------------------------------------


def fetch(source: str, dest_dir: str) -> str:
    if re.match(r"^https?://", source):
        name = os.path.basename(source.split("?")[0]) or "package.tgz"
        path = os.path.join(dest_dir, name)
        print(f"  скачиваю: {source}")
        req = urllib.request.Request(source, headers={"User-Agent": f"inspect-npm/{VERSION}"})
        with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
            shutil.copyfileobj(r, f)
        print(f"  получено: {os.path.getsize(path):,} байт")
        return path
    if not os.path.isfile(source):
        raise SystemExit(f"Файл не найден: {source}")
    return os.path.abspath(source)


def is_safe_member(m: tarfile.TarInfo) -> bool:
    name = m.name.replace("\\", "/")
    if name.startswith("/") or name.startswith("../") or "/../" in name:
        return False
    if m.issym() or m.islnk():
        target = (m.linkname or "").replace("\\", "/")
        if target.startswith("/") or ".." in target.split("/"):
            return False
    if m.isdev():
        return False
    return True


def extract_safely(tgz: str, dest_dir: str) -> Tuple[List[str], List[str]]:
    """Возвращает (список файлов, предупреждения о небезопасных записях архива)."""
    warnings: List[str] = []
    with tarfile.open(tgz, "r:*") as tf:
        members = tf.getmembers()
        safe = []
        for m in members:
            if is_safe_member(m):
                safe.append(m)
            else:
                warnings.append(f"архив содержит небезопасный путь: {m.name} -> {m.linkname}")
        tf.extractall(dest_dir, members=safe)  # noqa: S202 — имена уже проверены
        names = [m.name for m in safe if m.isfile()]
    return names, warnings


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Разбор
# ---------------------------------------------------------------------------


def read_text(path: str) -> Optional[str]:
    ext = os.path.splitext(path)[1].lower()
    if ext in SKIP_EXT:
        return None
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return None
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def scan_file(rel: str, text: str, out: List[Finding]) -> None:
    lines = text.splitlines()
    per_rule: Dict[str, int] = {}
    # по строкам
    for i, line in enumerate(lines, 1):
        for rule, sev, rx, what in RULES:
            if per_rule.get(rule, 0) >= MAX_FINDINGS_PER_RULE:
                continue
            if re.search(rx, line, re.I):
                per_rule[rule] = per_rule.get(rule, 0) + 1
                out.append(Finding(rule, sev, rel, i, line.strip()[:200], what))
        # доступ к секретам — отдельный список
        for rx, what in SENSITIVE_PATHS:
            key = "secret:" + what
            if per_rule.get(key, 0) >= 4:
                continue
            if re.search(rx, line, re.I):
                per_rule[key] = per_rule.get(key, 0) + 1
                out.append(Finding("secret", "crit", rel, i, line.strip()[:200],
                                   f"обращение к «{what}»"))
    # длинные base64-блобы
    for m in re.finditer(r"[A-Za-z0-9+/=]{220,}", text):
        blob = m.group(0)
        if blob.count("=") > 0 or len(blob) > 220:
            line_no = text[:m.start()].count("\n") + 1
            out.append(Finding("obfusc_blob", "high", rel, line_no,
                               blob[:120] + f"...(всего {len(blob)} символов)",
                               "длинный закодированный блок — проверьте, что внутри"))


def check_combos(report: Report) -> None:
    """Отдельные приёмы безобидны, но их сочетание — нет."""
    by_file: Dict[str, List[Finding]] = {}
    for f in report.findings:
        by_file.setdefault(f.file, []).append(f)
    for file, finds in by_file.items():
        rules = {f.rule for f in finds}
        if ("obfusc" in rules or "obfusc_blob" in rules) and ("eval" in rules or "dyn_require" in rules):
            report.findings.append(Finding(
                "combo:obfusc+exec", "crit", file, 0,
                "скрытые данные + исполнение кода",
                "обфускация вместе с динамическим исполнением — классическая маскировка вредоносного кода"))
        if "secret" in rules and ("net" in rules or "exfil_hook" in rules or "env_dump" in rules):
            report.findings.append(Finding(
                "combo:secret+net", "crit", file, 0,
                "доступ к секретам + отправка в сеть",
                "код читает ваши ключи и умеет отправлять данные наружу — это кража данных"))
        if "env_dump" in rules and ("net" in rules or "exfil_hook" in rules):
            report.findings.append(Finding(
                "combo:env+net", "crit", file, 0,
                "всё окружение + сеть",
                "собирает переменные окружения и может отправить их наружу"))
        if "hard_ip" in rules and ("net" in rules or "proc" in rules):
            report.findings.append(Finding(
                "combo:ip+net", "high", file, 0, "IP + сеть/процессы",
                "обращается по голому IP и работает с сетью — типично для скрытых каналов"))


def check_lifecycle_risk(report: Report) -> None:
    """Главная проверка: что запустится само в момент установки."""
    scripts = report.lifecycle_scripts
    if not scripts:
        report.notes.append("Скриптов жизненного цикла нет — код начнёт работать "
                            "только когда вы сами запустите команду.")
        return
    for name, body in scripts.items():
        sev = "crit" if name in ("preinstall", "install", "postinstall") else "high"
        danger = bool(re.search(r"curl|wget|https?://|node\s+-e|bash\s+-c|sh\s+-c|"
                                r"Invoke-|iwr|npm\s+i", body, re.I))
        report.findings.append(Finding(
            f"lifecycle:{name}", "crit" if danger else sev, "package.json", 0, body[:200],
            f"скрипт «{name}» выполняется автоматически при установке"
            + (" и что-то скачивает/запускает — это классический вектор атаки" if danger else "")))


def verify_no_registry_provenance(report: Report, source: str) -> None:
    if source.startswith("http") and "registry.npmjs.org" not in source:
        report.notes.append(
            "Пакет ставится НЕ из официального реестра npm, а по прямой ссылке. "
            "Значит: нет публикации с историей, нет проверок npm, нет подписи provenance — "
            "и по тому же адресу в любой момент может лежать уже другой код.")


def verdict(report: Report) -> str:
    sev = {f.severity for f in report.findings}
    if "crit" in sev:
        report.verdict = "ОПАСНО"
    elif "high" in sev:
        report.verdict = "ПОДОЗРИТЕЛЬНО"
    elif "med" in sev:
        report.verdict = "ОСТОРОЖНО"
    else:
        report.verdict = "ЧИСТО"
    return report.verdict


def inspect(source: str, keep_dir: Optional[str] = None) -> Report:
    tmp = keep_dir or tempfile.mkdtemp(prefix="npm-inspect-")
    os.makedirs(tmp, exist_ok=True)
    print(f"\n=== Разбор пакета ===\nИсточник: {source}\n")

    tgz = fetch(source, tmp)
    rep = Report(source=source)
    rep.size = os.path.getsize(tgz)
    rep.sha256 = sha256_of(tgz)
    print(f"  SHA-256: {rep.sha256}")

    unpack = os.path.join(tmp, "unpacked")
    os.makedirs(unpack, exist_ok=True)
    names, warn = extract_safely(tgz, unpack)
    rep.files = sorted(names)
    for w in warn:
        rep.findings.append(Finding("archive", "crit", "(архив)", 0, w, "опасная запись в архиве"))
    print(f"  файлов внутри: {len(names)}")

    pkg_path = os.path.join(unpack, "package.json")
    if os.path.isfile(pkg_path):
        try:
            with open(pkg_path, encoding="utf-8", errors="replace") as f:
                rep.package_json = json.load(f)
        except Exception as e:  # noqa: BLE001
            rep.notes.append(f"package.json не разобрался: {e}")
        pkg = rep.package_json
        rep.lifecycle_scripts = {k: str(v) for k, v in (pkg.get("scripts") or {}).items()
                                 if k in LIFECYCLE}
        for k, v in (pkg.get("scripts") or {}).items():
            if k not in LIFECYCLE and re.search(r"curl|wget|https?://", str(v), re.I):
                rep.findings.append(Finding("script:" + k, "crit", "package.json", 0, str(v)[:200],
                                            f"команда «{k}» что-то скачивает из сети"))
    else:
        rep.notes.append("package.json не найден — это точно npm-пакет?")

    # обход файлов
    for root, _dirs, files in os.walk(unpack):
        for fn in files:
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, unpack).replace("\\", "/")
            text = read_text(full)
            if text:
                scan_file(rel, text, rep.findings)

    check_lifecycle_risk(rep)
    check_combos(rep)
    verify_no_registry_provenance(rep, source)
    verdict(rep)

    if not keep_dir:
        shutil.rmtree(tmp, ignore_errors=True)
    else:
        rep.notes.append(f"распакованные файлы оставлены в: {unpack}")
    return rep


# ---------------------------------------------------------------------------
# Вывод
# ---------------------------------------------------------------------------

SEV_LABEL = {"crit": "🔴 КРИТИЧНО", "high": "🟠 ВЫСОКИЙ", "med": "🟡 СРЕДНИЙ", "info": "⚪ инфо"}
VERDICT_LINE = {
    "ОПАСНО": "🔴 ВЕРДИКТ: ОПАСНО — не устанавливайте и не запускайте",
    "ПОДОЗРИТЕЛЬНО": "🟠 ВЕРДИКТ: ПОДОЗРИТЕЛЬНО — сначала разберитесь, потом решайте",
    "ОСТОРОЖНО": "🟡 ВЕРДИКТ: ОСТОРОЖНО — типичный код, но затрагивает ваши конфиги",
    "ЧИСТО": "🟢 ВЕРДИКТ: подозрительного не найдено",
}


def print_report(rep: Report) -> None:
    pkg = rep.package_json
    print("\n" + "=" * 72)
    print(f"Пакет: {pkg.get('name', '?')} {pkg.get('version', '')}")
    print(f"Описание: {str(pkg.get('description', ''))[:100]}")
    print(f"Лицензия: {pkg.get('license', '?')}   Файлов: {len(rep.files)}")
    if rep.lifecycle_scripts:
        print("\n⚙️  СКРИПТЫ, ЗАПУСКАЮЩИЕСЯ ПРИ УСТАНОВКЕ (выполнятся сами, с вашими правами):")
        for k, v in rep.lifecycle_scripts.items():
            print(f"   • {k}: {v[:200]}")
    else:
        print("\n⚙️  Автоматических скриптов при установке нет.")

    by_sev = {"crit": [], "high": [], "med": [], "info": []}
    for f in rep.findings:
        by_sev.setdefault(f.severity, []).append(f)

    for sev in ("crit", "high", "med"):
        items = by_sev.get(sev) or []
        if not items:
            continue
        print(f"\n{SEV_LABEL[sev]} — {len(items)} совпадени(й):")
        for f in items[:14]:
            loc = f"{f.file}:{f.line}" if f.line else f.file
            print(f"   • {f.what}")
            print(f"     {loc}: {f.text}")
        if len(items) > 14:
            print(f"   … и ещё {len(items) - 14}")

    if rep.notes:
        print("\nЗаметки:")
        for n in rep.notes:
            print(f"   · {n}")

    print("\n" + "=" * 72)
    print(VERDICT_LINE.get(rep.verdict, rep.verdict))
    print("=" * 72)


def to_json(rep: Report) -> Dict[str, Any]:
    return {
        "version": VERSION,
        "source": rep.source,
        "sha256": rep.sha256,
        "size_bytes": rep.size,
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "package": {k: rep.package_json.get(k) for k in ("name", "version", "license", "bin")},
        "lifecycle_scripts": rep.lifecycle_scripts,
        "files_count": len(rep.files),
        "files": rep.files[:500],
        "verdict": rep.verdict,
        "findings": [f.__dict__ for f in rep.findings],
        "notes": rep.notes,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Разбор чужого npm-пакета до установки (ничего не запускает)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Пример:\n"
               "  python tools/inspect_npm_package.py https://site/pkg.tgz --report pkg.json\n")
    ap.add_argument("source", help="URL или путь к .tgz")
    ap.add_argument("--report", default=None, help="сохранить JSON-отчёт")
    ap.add_argument("--keep", action="store_true", help="оставить распакованные файлы для изучения")
    ap.add_argument("--version", action="version", version=f"inspect_npm_package {VERSION}")
    args = ap.parse_args(argv)

    rep = inspect(args.source, keep_dir=tempfile.mkdtemp(prefix="npm-keep-") if args.keep else None)
    print_report(rep)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(to_json(rep), f, ensure_ascii=False, indent=2)
        print(f"Отчёт сохранён: {args.report}")
    return 2 if rep.verdict == "ОПАСНО" else (1 if rep.verdict == "ПОДОЗРИТЕЛЬНО" else 0)


if __name__ == "__main__":
    sys.exit(main())
