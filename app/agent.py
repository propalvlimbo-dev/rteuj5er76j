#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeCoder Agent — локальный ИИ-агент, который читает ваши файлы и сам вносит правки.

Чем отличается от обычного чата:
    · сам ходит по проекту (дерево файлов, поиск по содержимому, чтение кусков);
    · сам создаёт, правит и удаляет файлы — с показом diff до применения;
    · сам запускает команды (тесты, сборку, git) — с подтверждением;
    · делает резервные копии и умеет откатывать (/undo);
    · работает с любой OpenAI-совместимой моделью; проект настроен на шлюз SmartAPI
      (ключ sk-smart-... в переменной SMARTAPI_KEY, конфиг config/providers.json).

Запуск:
    python app/agent.py  "добавь в бота обработку команды /start"    # одна задача
    python app/agent.py                                             # диалоговый режим
    python app/agent.py --workspace C:\\Projects\\bot --model auto

Ключевые флаги:
    --yes            не спрашивать подтверждения на правки и команды
    --dry-run        показать, что агент собирается сделать, но ничего не менять
    --model smart    маршрут (auto / cheap / smart / max) или точное имя: gpt-5.6-luna,
                     claude-opus-4-8 — список даёт команда /model в диалоге
    --api-base URL   свой OpenAI-совместимый endpoint (по умолчанию роутер на 127.0.0.1:8788)
    --steps N        максимум шагов агента на задачу (по умолчанию 15)

Экономия токенов (подробно — docs/08-ЭКОНОМИЯ-ТОКЕНОВ.md):
    · в диалоге /tokens покажет, из чего складывается следующий запрос;
    · /clear — новая задача без старой истории;  /steps 8 — короче сессии;
    · каждый шаг пересылает историю заново, поэтому в задачах лучше называть
      конкретные файлы, а не просить «посмотреть проект».

Только стандартная библиотека Python 3.8+. Лицензия MIT.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.request
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

VERSION = "2.0.0"
DEFAULT_API_BASE = os.environ.get("FREECODER_API_BASE", "http://127.0.0.1:8788/v1")
DEFAULT_API_KEY = os.environ.get("FREECODER_API_KEY", "freecoder")
DEFAULT_MODEL = os.environ.get("FREECODER_MODEL", "auto")

IGNORE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", "out", "target", ".next", ".nuxt", ".cache", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "coverage", ".idea", ".vscode", "vendor",
    "bin", "obj", ".freecoder",
}
IGNORE_EXT = {
    ".pyc", ".pyo", ".exe", ".dll", ".so", ".dylib", ".bin", ".zip", ".tar", ".gz",
    ".7z", ".rar", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".mp3",
    ".mp4", ".mov", ".woff", ".woff2", ".ttf", ".otf", ".lock", ".sqlite", ".db",
}
MAX_FILE_CHARS = 8000           # сколько символов файла отдаём модели за одно чтение
MAX_TREE_LINES = 120            # сколько строк дерева попадает в системный промпт
HISTORY_TOOL_KEEP = 1           # сколько последних результатов инструментов держим целиком
HISTORY_TOOL_CHARS = 500        # остальные сжимаются до этой длины (экономия контекста)
HISTORY_STEP_KEEP = 1           # сколько последних шагов модели держим целиком
HISTORY_STEP_CHARS = 700        # старые шаги (правки с содержимым файлов) сжимаются
DEFAULT_MAX_STEPS = 15          # предел шагов на задачу: меньше шагов — меньше повторов контекста
CHARS_PER_TOKEN = 3.5           # грубая оценка для расчёта размера запроса
TEXT_EXT_HINT = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".md", ".txt", ".html", ".css",
    ".scss", ".vue", ".svelte", ".go", ".rs", ".java", ".kt", ".c", ".h", ".cpp",
    ".hpp", ".cs", ".rb", ".php", ".sh", ".ps1", ".bat", ".cmd", ".yml", ".yaml",
    ".toml", ".ini", ".cfg", ".sql", ".env", ".gitignore", ".dockerfile", ".xml",
}

DENY_COMMAND_PATTERNS = [
    r"\brm\s+-rf\s+/", r"\brm\s+-rf\s+~", r"\bdel\s+/s\s+/q\s+[a-z]:\\?$",
    r"format\s+[a-z]:", r"\bmkfs\b", r"diskpart", r":\(\)\s*\{", r"\bshutdown\b",
    r"\breboot\b", r"\bpoweroff\b", r">\s*/dev/sd", r"Remove-Item\s+-Recurse\s+-Force\s+C:\\",
    r"curl[^|]*\|\s*(ba)?sh", r"wget[^|]*\|\s*(ba)?sh", r"iwr[^|]*\|\s*iex",
    r"npm\s+publish", r"git\s+push\s+--force", r"git\s+reset\s+--hard\s+HEAD~",
]


def log(*parts: Any) -> None:
    print(*parts, flush=True)


def human(n: int) -> str:
    for unit in ("", "K", "M", "G"):
        if abs(n) < 1000:
            return f"{n:.0f}{unit}" if unit == "" else f"{n:.1f}{unit}"
        n /= 1000.0  # type: ignore
    return f"{n:.1f}T"


# ----------------------------------------------------------------------------
# Работа с файлами проекта
# ----------------------------------------------------------------------------


class Repo:
    """Файловые операции, ограниченные рабочей папкой (sandbox)."""

    def __init__(self, root: str, dry_run: bool = False, backup: bool = True):
        self.root = os.path.abspath(root)
        self.dry_run = dry_run
        self.backup = backup
        self.session_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        self.backup_dir = os.path.join(self.root, ".freecoder", "backups", self.session_id)
        self.touched: List[str] = []
        if not os.path.isdir(self.root):
            raise SystemExit(f"Рабочая папка не найдена: {self.root}")

    # --- безопасность путей ---

    def resolve(self, path: str) -> str:
        p = (path or "").strip().strip('"').strip("'")
        if not p:
            raise ValueError("пустой путь")
        if os.path.isabs(p):
            full = os.path.abspath(p)
        else:
            full = os.path.abspath(os.path.join(self.root, p))
        if os.path.commonpath([self.root, full]) != self.root:
            raise ValueError(f"путь вне рабочей папки запрещён: {path}")
        return full

    def rel(self, full: str) -> str:
        return os.path.relpath(full, self.root).replace("\\", "/")

    # --- чтение ---

    def tree(self, limit: int = MAX_TREE_LINES) -> str:
        lines: List[str] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if d not in IGNORE_DIRS and not d.startswith("."))
            for f in sorted(filenames):
                if os.path.splitext(f)[1].lower() in IGNORE_EXT:
                    continue
                full = os.path.join(dirpath, f)
                try:
                    size = os.path.getsize(full)
                except OSError:
                    continue
                lines.append(f"{self.rel(full)}  ({human(size)})")
                if len(lines) >= limit:
                    lines.append(f"... и ещё (обрезано на {limit} файлах)")
                    return "\n".join(lines)
        return "\n".join(lines) or "(папка пуста)"

    def read(self, path: str, start: int = 1, end: int = 0) -> str:
        full = self.resolve(path)
        if not os.path.isfile(full):
            hint = ""
            parent = os.path.dirname(full)
            if os.path.isdir(parent):
                twins = [f for f in os.listdir(parent) if f.lower() == os.path.basename(full).lower()]
                if twins:
                    hint = f" Есть файл с похожим именем: {twins[0]}"
                else:
                    near = [f for f in os.listdir(parent) if os.path.isfile(os.path.join(parent, f))][:8]
                    if near:
                        hint = " В этой папке лежат: " + ", ".join(near)
            return (f"ФАЙЛА ПОКА НЕТ: {path}.{hint} "
                    f"Если его нужно создать — вызови write_file с полным содержимым "
                    f"(папки создаются автоматически). Не сообщай пользователю «файла нет» как результат задачи.")
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            return f"ОШИБКА чтения {path}: {e}"
        lines = text.splitlines()
        if end and end > 0:
            chunk = lines[max(0, start - 1):end]
        elif start > 1:
            chunk = lines[start - 1:]
        else:
            chunk = lines
        body = "\n".join(chunk)
        truncated = ""
        if len(body) > MAX_FILE_CHARS:
            body = body[:MAX_FILE_CHARS]
            truncated = (f"\n…(показаны не все строки: файл {len(lines)} строк. "
                         f"Продолжение — read_file с start/end, целиком его пересылать не нужно)")
        numbered = "\n".join(f"{i + start:>4} | {ln}" for i, ln in enumerate(body.split("\n")))
        return f"# {self.rel(full)} (строки {start}-{start + len(chunk) - 1} из {len(lines)})\n{numbered}{truncated}"

    def search(self, query: str, glob: str = "*", max_hits: int = 60) -> str:
        import fnmatch

        hits: List[str] = []
        try:
            rx = re.compile(query, re.IGNORECASE)
        except re.error:
            rx = re.compile(re.escape(query), re.IGNORECASE)
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
            for f in filenames:
                if os.path.splitext(f)[1].lower() in IGNORE_EXT:
                    continue
                if not fnmatch.fnmatch(f, glob):
                    continue
                full = os.path.join(dirpath, f)
                try:
                    with open(full, "r", encoding="utf-8", errors="ignore") as fh:
                        for i, line in enumerate(fh, 1):
                            if rx.search(line):
                                hits.append(f"{self.rel(full)}:{i}: {line.strip()[:160]}")
                                if len(hits) >= max_hits:
                                    return "\n".join(hits) + "\n... (обрезано)"
                except OSError:
                    continue
        return "\n".join(hits) if hits else "Совпадений не найдено."

    # --- запись ---

    def _backup_file(self, full: str) -> None:
        if not self.backup or not os.path.isfile(full):
            return
        rel = self.rel(full)
        dst = os.path.join(self.backup_dir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            with open(full, "rb") as src, open(dst, "wb") as out:
                out.write(src.read())
        except OSError:
            pass

    def write(self, path: str, content: str) -> str:
        full = self.resolve(path)
        if self.dry_run:
            return f"[dry-run] записал бы {self.rel(full)} ({len(content)} символов)"
        old = ""
        if os.path.isfile(full):
            self._backup_file(full)
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                old = f.read()
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        self.touched.append(self.rel(full))
        if old:
            return f"Файл перезаписан: {self.rel(full)} ({len(old)} → {len(content)} символов)"
        return f"Файл создан: {self.rel(full)} ({len(content)} символов)"

    def mkdir(self, path: str) -> str:
        full = self.resolve(path)
        if os.path.isdir(full):
            return f"Папка уже есть: {self.rel(full)}"
        if self.dry_run:
            return f"[dry-run] создал бы папку {self.rel(full)}"
        os.makedirs(full, exist_ok=True)
        return f"Папка создана: {self.rel(full)}"

    def replace(self, path: str, old: str, new: str, count: int = 0,
                replace_all: bool = False) -> str:
        full = self.resolve(path)
        if not os.path.isfile(full):
            return f"ОШИБКА: файл не найден: {path}"
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        if old not in text:
            return (f"ОШИБКА: фрагмент не найден в {self.rel(full)}. "
                    f"Прочитай файл заново (read_file) и скопируй текст ТОЧНО, включая отступы.")
        n = text.count(old)
        if self.dry_run:
            return f"[dry-run] заменил бы {n} вхождение(й) в {self.rel(full)}"
        self._backup_file(full)
        if replace_all:
            new_text = text.replace(old, new)
        elif count and count > 0:
            new_text = text.replace(old, new, count)
        else:
            new_text = text.replace(old, new, 1)
        with open(full, "w", encoding="utf-8", newline="\n") as f:
            f.write(new_text)
        self.touched.append(self.rel(full))
        return f"Готово: заменено {n if replace_all else (count or 1)} вхождение(й) в {self.rel(full)}"

    def delete(self, path: str) -> str:
        full = self.resolve(path)
        if not os.path.isfile(full):
            return f"ОШИБКА: файл не найден: {path}"
        if self.dry_run:
            return f"[dry-run] удалил бы {self.rel(full)}"
        self._backup_file(full)
        os.remove(full)
        self.touched.append(self.rel(full))
        return f"Удалён файл: {self.rel(full)} (копия в .freecoder/backups)"

    def undo(self) -> str:
        if not os.path.isdir(self.backup_dir):
            return "Откатывать нечего."
        restored = 0
        for dirpath, _, filenames in os.walk(self.backup_dir):
            for f in filenames:
                src = os.path.join(dirpath, f)
                rel = os.path.relpath(src, self.backup_dir)
                dst = os.path.join(self.root, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(src, "rb") as s, open(dst, "wb") as d:
                    d.write(s.read())
                restored += 1
        return f"Откат выполнен, восстановлено файлов: {restored}"

    def diff(self) -> str:
        if not os.path.isdir(self.backup_dir):
            return "Изменений в этой сессии нет."
        out: List[str] = []
        for dirpath, _, filenames in os.walk(self.backup_dir):
            for f in filenames:
                src = os.path.join(dirpath, f)
                rel = os.path.relpath(src, self.backup_dir)
                cur = os.path.join(self.root, rel)
                try:
                    with open(src, "r", encoding="utf-8", errors="replace") as fh:
                        old = fh.read().splitlines()
                except OSError:
                    continue
                new = []
                if os.path.isfile(cur):
                    with open(cur, "r", encoding="utf-8", errors="replace") as fh:
                        new = fh.read().splitlines()
                d = difflib.unified_diff(old, new, fromfile=f"a/{rel}", tofile=f"b/{rel}", lineterm="")
                out.extend(list(d))
        return "\n".join(out) if out else "Изменений нет."

    # --- команды ---

    def run(self, command: str, timeout: int = 300) -> str:
        cmd = (command or "").strip()
        if not cmd:
            return "ОШИБКА: пустая команда"
        low = cmd.lower()
        for pat in DENY_COMMAND_PATTERNS:
            if re.search(pat, low):
                return f"ЗАПРЕЩЕНО (опасная команда): {cmd}"
        if self.dry_run:
            return f"[dry-run] выполнил бы: {cmd}"
        try:
            proc = subprocess.run(
                cmd, shell=True, cwd=self.root, capture_output=True, text=True,
                timeout=timeout, errors="replace",
            )
        except subprocess.TimeoutExpired:
            return f"ОШИБКА: команда не завершилась за {timeout}s: {cmd}"
        except OSError as e:
            return f"ОШИБКА запуска: {e}"
        out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
        out = out.strip()
        if len(out) > 8000:
            out = out[:8000] + f"\n... (вывод обрезан, всего {len(out)} символов)"
        return f"$ {cmd}\n[код {proc.returncode}]\n{out or '(пустой вывод)'}"


# ----------------------------------------------------------------------------
# Клиент модели (любой OpenAI-совместимый, включая FreeCoder Router)
# ----------------------------------------------------------------------------


class LLM:
    last_usage: Dict[str, int]

    def __init__(self, base: str, key: str, model: str, timeout: int = 300):
        self.base = base.rstrip("/")
        self.key = key
        self.model = model
        self.timeout = timeout
        self.tokens_in = 0
        self.tokens_out = 0
        self.last_usage: Dict[str, int] = {}
        self.last_provider = "?"
        self._spend_cache: Tuple[float, str] = (0.0, "")

    def spend_line(self, ttl: float = 2.0) -> str:
        """«сегодня 45 678/400 000 (11%)» — статистика прямо в строке шага, без второго окна."""
        now = time.time()
        if self._spend_cache and now - self._spend_cache[0] < ttl:
            return self._spend_cache[1]
        url = self.base[:-3].rstrip("/") + "/status.json" if self.base.endswith("/v1") \
            else self.base.rstrip("/") + "/status.json"
        line = ""
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            spent = 0
            limit = 0
            for prov in data.get("providers", []):
                if prov.get("kind") == "mock" or not prov.get("keys"):
                    continue
                spent += sum(int(k.get("tokens_day") or 0) for k in prov.get("keys", []))
                limit = max(limit, int((prov.get("limits") or {}).get("tpd") or 0))
            if spent or limit:
                line = f"сегодня {spent / 1000:.1f}K" + (f"/{limit / 1000:.0f}K" if limit else "")
        except Exception:  # noqa: BLE001
            line = ""
        self._spend_cache = (now, line)
        return line

    def catalog(self) -> List[Dict[str, Any]]:
        """Список моделей у роутера: алиасы и модели шлюза с коэффициентами расхода."""
        url = self.base.rstrip("/") + "/models"
        try:
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.key}"})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                f"Не могу получить список моделей от {url} ({type(e).__name__}). "
                f"Роутер запущен? Это делает START.bat."
            ) from e
        return [m for m in (data.get("data") or []) if isinstance(m, dict) and m.get("id")]

    def chat(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None,
             temperature: float = 0.2) -> Dict[str, Any]:
        import urllib.error
        import urllib.request

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.base + "/chat/completions",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.key}",
                "User-Agent": f"FreeCoderAgent/{VERSION}",
            },
            method="POST",
        )
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", "replace")
                self.last_provider = resp.headers.get("x-freecoder-provider", self.model)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:500]
            except Exception:
                pass
            if e.code == 429:
                raise RuntimeError(
                    "Дневной лимит расхода выбран (HTTP 429). Панель роутера покажет, кто остывает "
                    f"и сколько ждать: {self.base.replace('/v1', '')}/. Детали: {detail}"
                ) from e
            if "does not exist" in detail or "not available" in detail or "model_not_found" in detail:
                raise RuntimeError(
                    f"Ошибка API HTTP {e.code}: {detail}\n"
                    f"    Похоже, ID модели не совпадает с каталогом шлюза. Откройте окно "
                    f"FreeCoder Router — там список доступных моделей; нужное имя впишите "
                    f"в config/providers.json."
                ) from e
            raise RuntimeError(f"Ошибка API HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Не могу подключиться к {self.base}. Роутер запущен? "
                f"Запустите: python app/router.py   ({e.reason})"
            ) from e

        obj = json.loads(body)
        usage = obj.get("usage") or {}
        pin = int(usage.get("prompt_tokens") or 0)
        pout = int(usage.get("completion_tokens") or 0)
        self.tokens_in += pin
        self.tokens_out += pout
        self.last_usage = {"in": pin, "out": pout, "total": pin + pout}
        obj["_elapsed"] = time.time() - t0
        return obj


# ----------------------------------------------------------------------------
# Инструменты агента
# ----------------------------------------------------------------------------

TOOL_SPECS = [
    ("list_files", "Показать дерево файлов проекта. args: {path?: string, pattern?: string}"),
    ("read_file", "Прочитать файл с нумерацией строк. args: {path: string, start?: int, end?: int}"),
    ("search", "Поиск по содержимому всех файлов (regex). args: {query: string, glob?: string}"),
    ("write_file", "Создать файл (папки создаются автоматически) или перезаписать целиком. args: {path: string, content: string}"),
    ("make_dir", "Создать пустую папку. args: {path: string}"),
    ("replace_in_file", "Точечная правка: заменить фрагмент. args: {path: string, old: string, new: string, replace_all?: bool}"),
    ("delete_file", "Удалить файл. args: {path: string}"),
    ("run_command", "Выполнить команду в папке проекта (тесты, сборка, git). args: {command: string}"),
    ("diff", "Показать diff всех изменений текущей сессии. args: {}"),
]

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": desc.split(". args:")[0],
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                    "query": {"type": "string"},
                    "glob": {"type": "string"},
                    "pattern": {"type": "string"},
                    "command": {"type": "string"},
                    "start": {"type": "integer"},
                    "end": {"type": "integer"},
                    "replace_all": {"type": "boolean"},
                },
            },
        },
    }
    for name, desc in TOOL_SPECS
] + [{
    "type": "function",
    "function": {
        "name": "final",
        "description": "Задача выполнена. Короткий отчёт по-русски: что сделано, какие файлы изменены.",
        "parameters": {"type": "object", "properties": {"summary": {"type": "string"}},
                       "required": ["summary"]},
    },
}]


def system_prompt(workspace: str, repo_tree: str, allow_cmd: bool, dry_run: bool,
                  max_steps: int = DEFAULT_MAX_STEPS) -> str:
    tools_txt = "\n".join(f"  · {n} — {d}" for n, d in TOOL_SPECS)
    mode = "РЕЖИМ ПРЕДПРОСМОТРА (ничего не меняется)" if dry_run else "Рабочий режим"
    return f"""Ты FreeCoder — автономный инженер-программист, работающий прямо в файлах пользователя.
Рабочая папка: {workspace}
{mode}

КАК ТЫ РАБОТАЕШЬ
1. Сначала осмотри проект (list_files, search, read_file) и пойми, как код устроен.
2. Дальше действуй: правь файлы по одному, после каждой правки сверяйся с кодом.
3. НОВЫЕ ФАЙЛЫ И ПАПКИ — твоя работа, а не повод отказаться. Если нужного файла нет,
   просто создай его через write_file (вложенные папки создаются автоматически;
   пустая папка — make_dir). НИКОГДА не отвечай пользователю «файла index.html нет»
   и не заканчивай задачу из-за отсутствующего файла: отсутствие файла — это нормальное
   начало работы. Пример: задача «сделай сайт» → write_file index.html, затем write_file style.css.
3. Для больших файлов НЕ переписывай их целиком — используй replace_in_file с точным фрагментом.
4. Если есть тесты или сборка — запусти их (run_command) и исправь ошибки.
5. Работай до готового результата: не сдавайся после первой ошибки инструмента,
   а исправляй её и продолжай.
6. Закончив, вызови final с отчётом: что сделано и какие файлы созданы/изменены.

ЭКОНОМИЯ ТОКЕНОВ (пользователь платит за каждый шаг, поэтому контекст не раздуваем)
· Каждый шаг заново пересылает всю историю — чем короче сессия, тем дешевле. Лимит: {max_steps} шагов.
· Не перечитывай файл, который уже читал, и не читай файл, который только что создал.
· Меняется часть файла — replace_in_file с маленьким фрагментом; write_file только для новых
  файлов или полной переписки. Не вставляй в аргументы то, что не изменилось.
· В thought — одна строка. Не пересказывай содержимое файлов и не повторяй задание.
· Длинный файл читай по частям (start/end), а не целиком.
· Если содержимое старого файла понадобилось снова — прочитай его заново: это дешевле,
  чем тащить все файлы в истории до конца задачи.
· Как только задача решена — сразу final. Никаких «на всякий случай проверю ещё раз».

ПРАВИЛА БЕЗОПАСНОСТИ (нарушать нельзя)
· Меняй только файлы внутри рабочей папки.
· Не выполняй разрушительные команды (rm -rf, format, установка системного ПО).
· Не трогай секреты и ключи (файлы .env, *.key, id_rsa) без прямой просьбы пользователя.
· Не выдумывай содержимое существующих файлов: если правишь файл — сначала прочитай.
· Но если файла ещё нет, выдумывать нечего — он твой, создавай целиком.

ДОСТУПНЫЕ ИНСТРУМЕНТЫ
{tools_txt}

ФОРМАТ ОТВЕТА — строго один JSON-объект и ничего больше:
{{"thought": "кратко, зачем это действие", "tool": "read_file", "args": {{"path": "main.py"}}}}
или, когда всё готово:
{{"thought": "итог", "tool": "final", "args": {{"summary": "что сделано"}}}}

Отвечай по-русски. Будь краток в thought, но точным в аргументах.

СТРУКТУРА ПРОЕКТА (может быть обрезана)
{repo_tree}
"""


ACTION_ICONS = {
    "read_file": "читаю",
    "write_file": "пишу",
    "replace_in_file": "правлю",
    "delete_file": "удаляю",
    "make_dir": "создаю папку",
    "list_files": "смотрю файлы",
    "search": "ищу",
    "run_command": "запускаю",
    "diff": "сверяю изменения",
    "final": "готово",
}


def human_action(tool: str, args: Dict[str, Any]) -> str:
    """Короткое описание действия вместо дампа JSON с путями."""
    args = args or {}
    name = ACTION_ICONS.get(tool, tool or "?")
    path = str(args.get("path") or "").replace("\\", "/")
    if tool == "read_file":
        rng = ""
        if args.get("start") or args.get("end"):
            rng = f" строки {args.get('start') or 1}-{args.get('end') or '…'}"
        return f"{name} {path}{rng}"
    if tool == "write_file":
        size = len(str(args.get("content") or ""))
        return f"{name} {path} ({size} символов)"
    if tool == "replace_in_file":
        return f"{name} {path}"
    if tool in ("make_dir", "delete_file"):
        return f"{name} {path}"
    if tool == "search":
        return f"{name} «{args.get('query', '')}»"
    if tool == "run_command":
        return f"{name}: {str(args.get('command', ''))[:80]}"
    if tool == "final":
        return "готово"
    return name


def human_result(tool: str, text: str) -> str:
    """Одна строка результата: без простыней и без «Изменений нет»."""
    text = (text or "").strip()
    if not text:
        return ""
    first = text.splitlines()[0].strip()
    if tool == "read_file":
        # «# index.html (строки 1-20 из 60)»
        return first.lstrip("# ").strip()
    if tool == "diff" and "Изменений" in first:
        return ""                      # нечего показывать — молчим
    if tool == "list_files":
        return f"файлов: {len(text.splitlines())}"
    return first[:140]


KEEP_ARG_KEYS = ("path", "start", "end", "query", "command", "glob", "pattern",
                 "replace_all", "why")


def compact_action_args(args_json: str, limit: int = HISTORY_STEP_CHARS) -> str:
    """Оставляет от аргументов действия только «скелет»: путь, диапазон строк, команду.

    Главная статья расхода — содержимое файлов в истории: записал файл на 12 КБ — и оно
    пересылается модели на каждом следующем шаге. Сам файл уже на диске, поэтому в контексте
    от него остаётся только пометка.
    """
    try:
        parsed = json.loads(args_json)
    except Exception:  # noqa: BLE001
        return args_json if len(args_json) <= limit else args_json[:limit] + "…(сокращено)"
    if not isinstance(parsed, dict):
        return args_json
    small: Dict[str, Any] = {}
    for key, value in parsed.items():
        if isinstance(value, str) and len(value) > 200:
            small[key] = f"<{len(value)} символов убрано из контекста: файл уже на диске>"
        elif key in KEEP_ARG_KEYS or len(str(value)) <= 200:
            small[key] = value
    return json.dumps(small, ensure_ascii=False)


def compact_history(messages: List[Dict[str, Any]], keep: int = HISTORY_TOOL_KEEP,
                    limit: int = HISTORY_TOOL_CHARS, step_keep: int = HISTORY_STEP_KEEP,
                    step_limit: int = HISTORY_STEP_CHARS) -> int:
    """Сжимает всё, что пересылается заново: старые результаты инструментов и старые шаги модели.

    Возвращает, сколько символов удалось сэкономить на следующем запросе.
    """
    saved = 0

    # 1. Результаты инструментов: последние keep — целиком, остальные — коротко.
    tool_idx = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    for i in tool_idx[:-keep] if keep else tool_idx:
        content = messages[i].get("content") or ""
        if len(content) > limit:
            saved += len(content) - limit
            messages[i] = {**messages[i], "content": content[:limit] + "\n…(сокращено)"}

    # 2. Старые шаги модели: именно там лежат целые файлы (write_file / replace_in_file).
    step_idx = [i for i, m in enumerate(messages) if m.get("role") == "assistant"]
    for i in step_idx[:-step_keep] if step_keep else step_idx:
        msg = messages[i]
        changed = False
        for call in (msg.get("tool_calls") or []):
            fn = call.get("function") or {}
            args = str(fn.get("arguments") or "")
            if len(args) > step_limit:
                fn["arguments"] = compact_action_args(args, step_limit)
                saved += len(args) - len(fn["arguments"])
                changed = True
        content = str(msg.get("content") or "")
        if len(content) > step_limit:
            action = parse_action(content)
            if action:
                name = action.get("tool") or "?"
                body = compact_action_args(json.dumps(action.get("args") or {}, ensure_ascii=False))
                try:
                    compact_args = json.loads(body)
                except Exception:  # noqa: BLE001
                    compact_args = {}
                content = json.dumps({"thought": "шаг выполнен", "tool": name,
                                      "args": compact_args}, ensure_ascii=False)
            else:
                content = content[:step_limit] + "…(сокращено)"
            saved += len(str(msg.get("content") or "")) - len(content)
            msg = {**msg, "content": content}
            changed = True
        if changed:
            messages[i] = msg
    return saved


def parse_action(text: str) -> Optional[Dict[str, Any]]:
    """Достаёт действие из ответа модели. Терпимо к мусору вокруг JSON."""
    if not text:
        return None
    text = text.strip()
    candidates: List[str] = []
    fence = re.findall(r"```(?:json)?\s*(.+?)```", text, re.S)
    candidates.extend(fence)
    candidates.append(text)
    # первый сбалансированный объект
    depth, start = 0, -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                candidates.append(text[start:i + 1])
                start = -1
    for cand in candidates:
        cand = cand.strip()
        if not cand.startswith("{"):
            continue
        try:
            obj = json.loads(cand)
        except Exception:
            try:
                obj = json.loads(cand.replace("'", '"'))
            except Exception:
                continue
        if isinstance(obj, dict) and ("tool" in obj or "args" in obj or "action" in obj):
            if "tool" not in obj and "action" in obj:
                obj["tool"] = obj.pop("action")
            obj.setdefault("args", {})
            # некоторые модели кладут аргументы на верхний уровень
            for field in ("path", "content", "old", "new", "command", "query", "glob"):
                if field in obj and field not in obj["args"]:
                    obj["args"][field] = obj[field]
            return obj
    return None


def actions_from_tool_calls(msg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Разбирает нативные tool_calls (может быть несколько в одном ответе)."""
    out: List[Dict[str, Any]] = []
    for c in msg.get("tool_calls") or []:
        fn = c.get("function") or {}
        name = fn.get("name")
        if not name:
            continue
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except Exception:
            args = {}
        if not isinstance(args, dict):
            args = {}
        if name == "final":
            out.append({"tool": "final", "args": {"summary": args.get("summary", "готово")},
                        "_call_id": c.get("id")})
        else:
            out.append({"tool": name, "args": args, "_call_id": c.get("id")})
    return out


# ----------------------------------------------------------------------------
# Цикл агента
# ----------------------------------------------------------------------------


class Agent:
    def __init__(self, repo: Repo, llm: LLM, yes: bool = False,
                 max_steps: int = DEFAULT_MAX_STEPS, allow_cmd: bool = True):
        self.repo = repo
        self.llm = llm
        self.yes = yes
        self.max_steps = max_steps or DEFAULT_MAX_STEPS
        self.last_messages: List[Dict[str, Any]] = []
        self.allow_cmd = allow_cmd or yes
        self.history: List[Dict[str, Any]] = []
        self.session_dir = os.path.join(repo.root, ".freecoder", "sessions")
        os.makedirs(self.session_dir, exist_ok=True)

    # --- журнал ---

    def save_event(self, event: Dict[str, Any]) -> None:
        try:
            path = os.path.join(self.session_dir, f"{self.repo.session_id}.jsonl")
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": time.time(), **event}, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # --- подтверждения ---

    def confirm(self, question: str, preview: str = "") -> bool:
        if self.yes:
            return True
        if preview:
            log(preview)
        try:
            ans = input(f"{question} [y/N/a=всё] ").strip().lower()
        except EOFError:
            return False
        if ans in ("a", "all", "в", "все"):
            self.yes = True
            return True
        return ans in ("y", "yes", "д", "да")

    # --- выполнение инструмента ---

    def execute(self, action: Dict[str, Any]) -> Tuple[str, bool]:
        tool = (action.get("tool") or "").strip()
        args = action.get("args") or {}
        if not isinstance(args, dict):
            args = {}
        repo = self.repo

        try:
            if tool == "final":
                return str(args.get("summary") or "Задача выполнена."), True

            if tool == "list_files":
                return repo.tree(), False

            if tool == "read_file":
                return repo.read(str(args.get("path", "")),
                                 int(args.get("start") or 1), int(args.get("end") or 0)), False

            if tool == "search":
                return repo.search(str(args.get("query", "")), str(args.get("glob") or "*")), False

            if tool == "diff":
                return repo.diff(), False

            if tool == "make_dir":
                path = str(args.get("path", ""))
                if not path:
                    return "ОШИБКА: не передан path", False
                return repo.mkdir(path), False

            if tool in ("write_file", "replace_in_file", "delete_file"):
                if tool == "write_file":
                    path = str(args.get("path", ""))
                    content = args.get("content")
                    if content is None:
                        return "ОШИБКА: не передан content", False
                    preview = snippet_diff(repo, path, str(content))
                elif tool == "replace_in_file":
                    path = str(args.get("path", ""))
                    old = str(args.get("old") or "")
                    new = str(args.get("new") or "")
                    if not old:
                        return "ОШИБКА: не передан old (что заменять)", False
                    preview = snippet_diff(repo, path, None, old, new)
                else:
                    path = str(args.get("path", ""))
                    preview = f"УДАЛИТЬ: {path}"
                if not self.confirm(f"Применить правку {path}?", preview):
                    return "Пользователь отклонил это изменение. Предложи другой вариант.", False
                if tool == "write_file":
                    return repo.write(str(args["path"]), str(args["content"])), False
                if tool == "replace_in_file":
                    return repo.replace(str(args["path"]), str(args["old"]), str(args["new"]),
                                        int(args.get("count") or 0),
                                        bool(args.get("replace_all"))), False
                return repo.delete(str(args["path"])), False

            if tool == "run_command":
                cmd = str(args.get("command") or "")
                if not self.allow_cmd:
                    return "Команды запрещены (запустите с --allow-cmd)", False
                if not self.confirm(f"Выполнить команду: {cmd}?", ""):
                    return "Пользователь отклонил команду.", False
                return repo.run(cmd), False

            return (f"ОШИБКА: неизвестный инструмент '{tool}'. Доступны: "
                    + ", ".join(n for n, _ in TOOL_SPECS) + ", final"), False
        except ValueError as e:
            return f"ОШИБКА: {e}", False
        except Exception as e:  # noqa: BLE001
            return f"ОШИБКА выполнения {tool}: {type(e).__name__}: {e}", False

    # --- одна задача ---

    def run_task(self, task: str, quiet: bool = False) -> str:
        log(f"\n🎯 Задача: {task}\n")
        tree = self.repo.tree()
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt(self.repo.root, tree, self.allow_cmd,
                                                        self.repo.dry_run, self.max_steps)},
            {"role": "user", "content": task},
        ]
        self.last_messages = messages
        self.save_event({"type": "task", "task": task, "model": self.llm.model})

        for step in range(1, self.max_steps + 1):
            if compact_history(messages):
                self.save_event({"type": "compact"})
            try:
                resp = self.llm.chat(messages, tools=TOOLS_SCHEMA)
            except RuntimeError as e:
                log(f"⚠  {e}")
                return f"Ошибка модели: {e}"

            msg = (resp.get("choices") or [{}])[0].get("message") or {}
            content = msg.get("content") or ""
            tok = resp.get("usage") or {}
            provider = (resp.get("x_freecoder_provider") or resp.get("model")
                        or self.llm.model).split("/")[-1]
            elapsed = resp.get("_elapsed", 0.0)

            def step_line(what: str) -> None:
                """Одна компактная строка: что делаю · время · вход/выход · расход за сутки.

                «вход» — это вся история, которую модель читает заново на каждом шаге;
                именно она делает счёт в конце месяца. «выход» — то, что модель написала.
                """
                used = self.llm.last_usage or {}
                parts = [f"[{step}/{self.max_steps}] {what}", f"{elapsed:.1f}с"]
                if used:
                    parts.append(f"вход {human(int(used.get('in', 0)))}"
                                 f" / выход {human(int(used.get('out', 0)))}")
                spend = self.llm.spend_line()
                if spend:
                    parts.append(spend)
                log("  " + " · ".join(p for p in parts if p))

            actions = actions_from_tool_calls(msg)
            if not actions:
                single = parse_action(content)
                if single:
                    actions = [single]

            if not actions:
                # модель ответила просто текстом — считаем это отчётом, но даём шанс продолжить
                if content.strip():
                    step_line("ответ")
                    log(f"     {content.strip()[:1500]}")
                    self.save_event({"type": "text", "content": content})
                    if step == 1 and len(content) < 1500:
                        return content.strip()
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content":
                                     "Ответь строго JSON-действием или вызови final. "
                                     "Если работа не закончена — продолжай правки."})
                    continue
                messages.append({"role": "user", "content": "Пустой ответ. Ответь JSON-действием."})
                continue

            results: List[Tuple[Dict[str, Any], str, bool]] = []
            final_result: Optional[str] = None
            actions = [a for a in actions if (a.get("tool") or "") != "diff"] or actions
            for idx, act in enumerate(actions[:5]):
                tool = act.get("tool")
                args = act.get("args") or {}
                if idx == 0:
                    step_line(human_action(tool, args))
                else:
                    log(f"     {human_action(tool, args)}")

                r_txt, is_final = self.execute(act)
                results.append((act, r_txt, is_final))
                self.save_event({"type": "tool", "tool": tool, "args": redact(args),
                                 "result": r_txt[:2000], "final": is_final})

                if is_final:
                    final_result = r_txt
                    break

                line = human_result(tool, r_txt)
                if line:
                    log(f"       {line}")

            if final_result is not None:
                log("")
                log(f"✅ {final_result}")
                files = ", ".join(sorted(set(self.repo.touched))) or "нет"
                log(f"   файлы: {files}")
                log(f"   шагов: {step} из {self.max_steps} · "
                    f"токенов: вход {human(self.llm.tokens_in)}, выход {human(self.llm.tokens_out)}"
                    + (f" · {self.llm.spend_line()}" if self.llm.spend_line() else ""))
                log("")
                return final_result

            # Возвращаем результаты. Если модель использовала нативный tool calling —
            # отвечаем результатами инструментов с tool_call_id — так требует протокол OpenAI,
            # иначе — текстовым протоколом.
            if any(act.get("_call_id") for act, _, _ in results):
                answer: Dict[str, Any] = {"role": "assistant", "content": content or None,
                                          "tool_calls": msg.get("tool_calls")}
                messages.append(answer)
                for act, r_txt, _ in results:
                    messages.append({"role": "tool",
                                     "tool_call_id": act.get("_call_id") or "call_0",
                                     "content": r_txt})
            else:
                messages.append({"role": "assistant",
                                 "content": content or json.dumps(actions[0], ensure_ascii=False)})
                messages.append({"role": "user", "content": "\n\n".join(
                    f"РЕЗУЛЬТАТ {act.get('tool')}:\n{r_txt}" for act, r_txt, _ in results)})

            if sum(len(str(m.get('content') or '')) for m in messages) > 140000:
                messages = trim_history(messages)

        return "Достигнут предел шагов. Что успел — сделал, посмотрите diff."


def redact(args: Any) -> Any:
    if not isinstance(args, dict):
        return args
    out = {}
    for k, v in args.items():
        if isinstance(v, str) and len(v) > 800:
            out[k] = v[:800] + f"...(+{len(v) - 800})"
        else:
            out[k] = v
    return out


def trim_history(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Убирает серединные результаты инструментов, сохраняя system, задачу и последние шаги."""
    if len(messages) <= 6:
        return messages
    head = messages[:2]
    tail = messages[-6:]
    return head + [{"role": "user", "content": "(часть истории обрезана для экономии контекста)"}] + tail


def snippet_diff(repo: Repo, path: str, content: Optional[str],
                 old: Optional[str] = None, new: Optional[str] = None) -> str:
    """Показывает, что именно изменится — до применения."""
    try:
        full = repo.resolve(path)
    except ValueError as e:
        return f"ОШИБКА: {e}"
    before = ""
    if os.path.isfile(full):
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            before = f.read()
    if content is not None:
        after = content
    else:
        after = before.replace(old or "", new or "", 1)
    lines = list(difflib.unified_diff(before.splitlines(), after.splitlines(),
                                      fromfile=f"a/{path}", tofile=f"b/{path}", lineterm=""))
    if not lines:
        return f"(изменений в {path} не будет)"
    body = "\n".join(lines[:120])
    if len(lines) > 120:
        body += f"\n... (diff обрезан, всего {len(lines)} строк)"
    return body


# ----------------------------------------------------------------------------
# Интерфейс
# ----------------------------------------------------------------------------


def load_workspace_config(workspace: str) -> Dict[str, Any]:
    path = os.path.join(workspace, ".freecoder", "config.json")
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


MODEL_FAMILIES = (("Claude", "claude"), ("GPT", "gpt"), ("Codex", "codex"))


def model_family(model_id: str) -> str:
    """Семейство модели — чтобы список читался как у людей: Claude, GPT, Codex."""
    short = model_id.split("/")[-1].lower()
    for title, prefix in MODEL_FAMILIES:
        if short.startswith(prefix):
            return title
    return "Прочее"


def fmt_mult(mult: float) -> str:
    """Коэффициент без хвоста: 2, а не 2,0."""
    number = float(mult)
    return str(int(number)) if number == int(number) else str(number).replace(".", ",")


def price_note(mult: float) -> str:
    if mult <= 2:
        return "дёшево"
    if mult <= 3:
        return "средне"
    if mult <= 4:
        return "дорого"
    return "очень дорого"


def pick_model(agent: Agent) -> None:
    """Показывает маршруты и все модели шлюза — Claude, GPT и Codex — с коэффициентами расхода."""
    try:
        items = agent.llm.catalog()
    except RuntimeError as e:
        log(f"⚠  {e}")
        return
    routes = [m for m in items if m.get("alias")]
    direct = [m for m in items if not m.get("alias")]
    direct.sort(key=lambda m: (model_family(str(m["id"])), float(m.get("multiplier") or 0)))
    if not routes and not direct:
        log("Роутер не вернул список моделей.")
        return

    numbered: List[Tuple[str, float]] = []
    lines = ["", f"Текущая модель: {agent.llm.model}", "", "Маршруты (самый простой выбор):"]
    for m in routes:
        mid = str(m["id"])
        numbered.append((mid, float(m.get("multiplier") or 1)))
        mark = "  ← сейчас" if agent.llm.model == mid else ""
        lines.append(f"  {len(numbered):>3}) {mid:<8} ×{fmt_mult(m.get('multiplier') or 1):<5} "
                     f"{m.get('description', '')}{mark}")

    if direct:
        lines.append("")
        lines.append("Все модели шлюза (работать прямо на этой):")
        family = ""
        for m in direct:
            mid = str(m["id"])
            short = mid.split("/")[-1]
            fam = model_family(mid)
            if fam != family:
                family = fam
                lines.append(f"   {fam}:")
            numbered.append((mid, float(m.get("multiplier") or 1)))
            mark = "  ← сейчас" if agent.llm.model in (mid, short) else ""
            lines.append(f"  {len(numbered):>3}) {short:<22} ×{fmt_mult(m.get('multiplier') or 1):<5} "
                         f"{price_note(float(m.get('multiplier') or 1))}{mark}")

    lines.append("")
    lines.append("× — во сколько раз дороже обычного токена: ×1,7 — дешевле всего, ×5 и выше — только для тяжёлого.")
    lines.append("Можно вписать имя и руками: /model gpt-5.6-luna")
    lines.append("")
    log("\n".join(lines))

    try:
        ans = input("Номер модели (Enter — оставить как есть): ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if not ans:
        return
    if ans.isdigit():
        idx = int(ans)
        if 1 <= idx <= len(numbered):
            agent.llm.model = numbered[idx - 1][0]
            agent.history = []
            log(f"Модель: {agent.llm.model}. История очищена — за старый контекст платить не нужно.")
        else:
            log("Нет такого номера.")
        return
    agent.llm.model = ans
    agent.history = []
    log(f"Модель: {ans}. История очищена.")


def context_report(agent: Agent) -> str:
    """Разбор запроса: из чего складываются токены, которые уедут на следующем шаге."""
    def size_of(msg: Dict[str, Any]) -> int:
        total = len(str(msg.get("content") or ""))
        for call in (msg.get("tool_calls") or []):
            total += len(str((call.get("function") or {}).get("arguments") or ""))
        return total

    msgs = agent.last_messages or []
    lines: List[str] = []
    if msgs:
        system = size_of(msgs[0])
        rest = sum(size_of(m) for m in msgs[1:])
        lines.append(f"Следующий запрос: ~{human(int((system + rest) / CHARS_PER_TOKEN))} токенов "
                     f"на входе, {len(msgs)} сообщений в истории")
        lines.append(f"   системный промпт и структура проекта: ~{human(int(system / CHARS_PER_TOKEN))}")
        lines.append(f"   задача и прошлые шаги: ~{human(int(rest / CHARS_PER_TOKEN))}")
        heavy = sorted(((size_of(m), m) for m in msgs[1:]), reverse=True, key=lambda x: x[0])[:3]
        for size, msg in heavy:
            if size < 1000:
                break
            name = ""
            for call in (msg.get("tool_calls") or []):
                name = (call.get("function") or {}).get("name") or ""
                break
            lines.append(f"   самое тяжёлое: {msg.get('role', '?')} {name} — {human(size)} символов")
    else:
        lines.append("В этой сессии задач ещё не было: истории нет, запрос будет дешёвым.")
    lines.append(f"За сессию: вход {human(agent.llm.tokens_in)}, выход {human(agent.llm.tokens_out)}")
    spend = agent.llm.spend_line()
    if spend:
        lines.append(f"За сутки: {spend}")
    lines.append("Как платить меньше: /clear перед новой задачей (история не пересылается заново),")
    lines.append("/steps 8 — короче сессии, дешёвая модель — /model (×1,7 вместо ×2),")
    lines.append("в задаче указывать конкретные файлы, а не «посмотри проект».")
    return "\n".join(lines)


def repl(agent: Agent) -> None:
    mode = "правки сразу (откат — /undo)" if agent.yes else "правки с подтверждением"
    spend = agent.llm.spend_line()
    log(f"папка:  {agent.repo.root}")
    log(f"модель: {agent.llm.model} · {mode} · шагов на задачу: {agent.max_steps}"
        + (f" · {spend}" if spend else ""))
    log("задача пишется словами · /help команды · /model модели (Claude и GPT) · /tokens расход\n")
    while True:
        try:
            line = input("freecoder> ").strip()
        except (EOFError, KeyboardInterrupt):
            log("\nВыход.")
            return
        if not line:
            continue
        if line.startswith("/"):
            cmd, _, rest = line.partition(" ")
            rest = rest.strip()
            if cmd in ("/exit", "/quit", "/q"):
                return
            if cmd == "/help":
                log("""Задачи пишутся обычным текстом, например:
  исправь ошибку в api.py — падает на пустом ответе
  добавь тесты для функции parse_date
  сделай в папке demo index.html и style.css

Команды:
  /model            выбрать модель: Claude, GPT, Codex — с коэффициентами расхода
  /tokens           разбор расхода: сколько уйдёт на следующий шаг и почему
  /steps 8          сколько шагов разрешено на задачу (сейчас {agent.max_steps})
  /clear            очистить историю сессии (новая задача — дешевле)
  /undo             откатить правки этой сессии      /diff — что изменилось
  /tree             файлы проекта
  /confirm on|off   подтверждать правки или применять сразу
  /cd <папка>       сменить рабочую папку            /pwd — где я сейчас
  /exit             выход""")
            elif cmd == "/tree":
                log(agent.repo.tree())
            elif cmd == "/diff":
                log(agent.repo.diff())
            elif cmd == "/undo":
                log(agent.repo.undo())
            elif cmd in ("/yes", "/confirm"):
                if cmd == "/confirm" and rest:
                    arg = rest.lower()
                    if arg in ("off", "выкл", "0", "нет", "no"):
                        agent.yes = False
                        agent.allow_cmd = False
                        log("Подтверждения включены: правка показывается до применения.")
                        continue
                    if arg in ("on", "вкл", "1", "да", "yes"):
                        agent.yes = True
                        agent.allow_cmd = True
                        log("Подтверждения выключены: правки применяются сразу (откат — /undo).")
                        continue
                if cmd == "/confirm":
                    state = "выключены" if agent.yes else "включены"
                    log(f"Подтверждения {state}. Переключить: /confirm on | /confirm off")
                    continue
                agent.yes = True
                agent.allow_cmd = True
                log("Подтверждения отключены: правки применяются сразу (откат — /undo).")
            elif cmd in ("/cd", "/pwd"):
                if cmd == "/pwd":
                    log(f"Рабочая папка: {agent.repo.root}")
                elif not rest:
                    log("Укажите папку: /cd C:\\Проекты\\мой-проект")
                else:
                    target = rest.strip().strip('"').strip("'")
                    if not os.path.isdir(target):
                        log(f"Папка не найдена: {target}")
                    else:
                        repo = Repo(target, dry_run=agent.repo.dry_run, backup=agent.repo.backup)
                        agent.repo = repo
                        agent.session_dir = os.path.join(repo.root, ".freecoder", "sessions")
                        os.makedirs(agent.session_dir, exist_ok=True)
                        agent.history = []          # история чужого проекта больше не нужна
                        log(f"Рабочая папка теперь: {repo.root}")
                        log("История диалога очищена — начинаем с чистого листа в новой папке.")
            elif cmd == "/model":
                if rest:
                    agent.llm.model = rest
                    agent.history = []
                    log(f"Модель: {rest}. История очищена — за старый контекст платить не нужно.")
                else:
                    pick_model(agent)
            elif cmd == "/tokens":
                log(context_report(agent))
            elif cmd == "/clear":
                agent.history = []
                agent.last_messages = []
                agent.llm.tokens_in = 0
                agent.llm.tokens_out = 0
                agent.llm.last_usage = {}
                log("История очищена. Следующая задача уйдёт без прошлого контекста — это дешевле.")
            elif cmd == "/steps":
                if rest.isdigit() and 1 <= int(rest) <= 60:
                    agent.max_steps = int(rest)
                    log(f"Шагов на задачу: {agent.max_steps}")
                else:
                    log(f"Сейчас шагов на задачу: {agent.max_steps}. Поставить другое: /steps 10")
            else:
                log("Неизвестная команда. /help")
            continue
        agent.run_task(line)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="FreeCoder Agent — ИИ-агент, который сам правит ваши файлы",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Примеры:\n"
               '  python app/agent.py "добавь логирование в main.py"\n'
               "  python app/agent.py --workspace C:\\Projects\\bot --yes\n",
    )
    ap.add_argument("task", nargs="*", help="задача (если пусто — диалоговый режим)")
    ap.add_argument("--workspace", "-w", default=os.getcwd(), help="папка проекта (по умолчанию текущая)")
    ap.add_argument("--api-base", default=DEFAULT_API_BASE, help="OpenAI-совместимый endpoint")
    ap.add_argument("--api-key", default=DEFAULT_API_KEY, help="ключ (роутеру всё равно какой)")
    ap.add_argument("--model", "-m", default=DEFAULT_MODEL, help="auto | smart | fast | local | provider/model")
    ap.add_argument("--steps", type=int, default=DEFAULT_MAX_STEPS, help="максимум шагов на задачу")
    ap.add_argument("--yes", "-y", action="store_true", help="подтверждать всё автоматически")
    ap.add_argument("--dry-run", action="store_true", help="ничего не менять (только показать план)")
    ap.add_argument("--allow-cmd", action="store_true", help="разрешить запуск команд")
    ap.add_argument("--no-backup", action="store_true", help="не хранить резервные копии правок")
    ap.add_argument("--quiet", action="store_true", help="без шапки (когда запускает launch.py)")
    ap.add_argument("--version", action="version", version=f"FreeCoder Agent {VERSION}")
    args = ap.parse_args(argv)

    ws_cfg = load_workspace_config(args.workspace)
    model = args.model or ws_cfg.get("model") or DEFAULT_MODEL
    api_base = args.api_base or ws_cfg.get("api_base") or DEFAULT_API_BASE
    api_key = ws_cfg.get("api_key") or args.api_key

    repo = Repo(args.workspace, dry_run=args.dry_run, backup=not args.no_backup)
    llm = LLM(api_base, api_key, model)
    agent = Agent(repo, llm, yes=args.yes, max_steps=args.steps, allow_cmd=args.allow_cmd)

    if not getattr(args, "quiet", False):
        log(f"FreeCoder Agent {VERSION} · {repo.root}")
        log(f"  модель: {model} → {api_base} · шагов на задачу: {agent.max_steps}"
            + (" · ПРЕДПРОСМОТР (файлы не меняются)" if args.dry_run else "")
            + ("" if args.yes else " · правки с подтверждением"))
        log("  /help команды · /tokens расход · /model модели (Claude и GPT)")

    cluster = " ".join(args.task).strip()
    if cluster:
        agent.run_task(cluster)
        return 0
    repl(agent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
