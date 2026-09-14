#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeCoder Agent — локальный ИИ-агент, который читает ваши файлы и сам вносит правки.

Чем отличается от обычного чата:
    · сам ходит по проекту (дерево файлов, поиск по содержимому, чтение кусков);
    · сам создаёт, правит и удаляет файлы — с показом diff до применения;
    · сам запускает команды (тесты, сборку, git) — с подтверждением;
    · делает резервные копии и умеет откатывать (/undo);
    · работает с ЛЮБОЙ OpenAI-совместимой моделью: бесплатные ключи через
      FreeCoder Router, локальная Ollama или ваш платный ключ — агенту всё равно.

Запуск:
    python freecoder_agent.py  "добавь в бота обработку команды /start"    # одна задача
    python freecoder_agent.py                                             # диалоговый режим
    python freecoder_agent.py --workspace C:\\Projects\\bot --model auto

Ключевые флаги:
    --yes            не спрашивать подтверждения на правки и команды
    --dry-run        показать, что агент собирается сделать, но ничего не менять
    --model smart    выбрать маршрут на роутере (auto / smart / fast / local / provider/model)
    --api-base URL   свой OpenAI-совместимый endpoint (по умолчанию роутер на 127.0.0.1:8788)
    --steps N        максимум шагов агента на задачу (по умолчанию 30)

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
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

VERSION = "1.0.0"
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
MAX_FILE_CHARS = 60000          # сколько символов файла отдаём модели целиком
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

    def tree(self, limit: int = 400) -> str:
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
            return f"ОШИБКА: файл не найден: {path}"
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
            truncated = f"\n... (файл обрезан, всего строк: {len(lines)})"
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
    def __init__(self, base: str, key: str, model: str, timeout: int = 300):
        self.base = base.rstrip("/")
        self.key = key
        self.model = model
        self.timeout = timeout
        self.tokens_in = 0
        self.tokens_out = 0
        self.last_provider = "?"

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
                    "Все бесплатные квоты заняты (HTTP 429). Панель роутера покажет, кто остывает "
                    f"и сколько ждать: {self.base.replace('/v1', '')}/. Детали: {detail}"
                ) from e
            if "does not exist" in detail or "not available" in detail or "model_not_found" in detail:
                raise RuntimeError(
                    f"Ошибка API HTTP {e.code}: {detail}\n"
                    f"    Похоже, ID модели не совпадает с каталогом шлюза. Откройте окно "
                    f"FreeCoder Router — там список доступных моделей; нужное имя впишите "
                    f"в router/providers.smartapi.json."
                ) from e
            raise RuntimeError(f"Ошибка API HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Не могу подключиться к {self.base}. Роутер запущен? "
                f"Запустите: python router/freecoder_router.py   ({e.reason})"
            ) from e

        obj = json.loads(body)
        usage = obj.get("usage") or {}
        self.tokens_in += int(usage.get("prompt_tokens") or 0)
        self.tokens_out += int(usage.get("completion_tokens") or 0)
        obj["_elapsed"] = time.time() - t0
        return obj


# ----------------------------------------------------------------------------
# Инструменты агента
# ----------------------------------------------------------------------------

TOOL_SPECS = [
    ("list_files", "Показать дерево файлов проекта. args: {path?: string, pattern?: string}"),
    ("read_file", "Прочитать файл с нумерацией строк. args: {path: string, start?: int, end?: int}"),
    ("search", "Поиск по содержимому всех файлов (regex). args: {query: string, glob?: string}"),
    ("write_file", "Создать файл или перезаписать целиком. args: {path: string, content: string}"),
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


def system_prompt(workspace: str, repo_tree: str, allow_cmd: bool, dry_run: bool) -> str:
    tools_txt = "\n".join(f"  · {n} — {d}" for n, d in TOOL_SPECS)
    mode = "РЕЖИМ ПРЕДПРОСМОТРА (ничего не меняется)" if dry_run else "Рабочий режим"
    return f"""Ты FreeCoder — автономный инженер-программист, работающий прямо в файлах пользователя.
Рабочая папка: {workspace}
{mode}

КАК ТЫ РАБОТАЕШЬ
1. Сначала осмотри проект (list_files, search, read_file) и пойми, как код устроен.
2. Дальше действуй: правь файлы по одному, после каждой правки сверяйся с кодом.
3. Для больших файлов НЕ переписывай их целиком — используй replace_in_file с точным фрагментом.
4. Если есть тесты или сборка — запусти их (run_command) и исправь ошибки.
5. Закончив, вызови final с отчётом.

ПРАВИЛА БЕЗОПАСНОСТИ (нарушать нельзя)
· Меняй только файлы внутри рабочей папки.
· Не выполняй разрушительные команды (rm -rf, format, установка системного ПО).
· Не трогай секреты и ключи (файлы .env, *.key, id_rsa) без прямой просьбы пользователя.
· Не выдумывай содержимое файлов: если не читал — прочитай.

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
    def __init__(self, repo: Repo, llm: LLM, yes: bool = False, max_steps: int = 30,
                 allow_cmd: bool = True):
        self.repo = repo
        self.llm = llm
        self.yes = yes
        self.max_steps = max_steps
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
            {"role": "system", "content": system_prompt(self.repo.root, tree, self.allow_cmd, self.repo.dry_run)},
            {"role": "user", "content": task},
        ]
        self.save_event({"type": "task", "task": task, "model": self.llm.model})

        for step in range(1, self.max_steps + 1):
            log(f"── шаг {step}/{self.max_steps} " + "─" * 30)
            try:
                resp = self.llm.chat(messages, tools=TOOLS_SCHEMA)
            except RuntimeError as e:
                log(f"⚠  {e}")
                return f"Ошибка модели: {e}"

            msg = (resp.get("choices") or [{}])[0].get("message") or {}
            content = msg.get("content") or ""
            tok = resp.get("usage") or {}
            provider = resp.get("x_freecoder_provider") or resp.get("model") or self.llm.model
            log(f"   модель: {provider} · {resp.get('_elapsed', 0):.1f}s · "
                f"токенов: {tok.get('total_tokens', '?')}")

            actions = actions_from_tool_calls(msg)
            if not actions:
                single = parse_action(content)
                if single:
                    actions = [single]

            if not actions:
                # модель ответила просто текстом — считаем это отчётом, но даём шанс продолжить
                if content.strip():
                    log(f"\n🤖 {content.strip()[:1500]}\n")
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
            for act in actions[:5]:
                thought = str(act.get("thought") or "")[:200]
                if thought:
                    log(f"   💭 {thought}")
                tool = act.get("tool")
                shown_args = {k: (v[:60] + '…' if isinstance(v, str) and len(v) > 60 else v)
                              for k, v in (act.get("args") or {}).items()}
                log(f"   🔧 {tool} {json.dumps(shown_args, ensure_ascii=False)}")

                r_txt, is_final = self.execute(act)
                results.append((act, r_txt, is_final))
                self.save_event({"type": "tool", "tool": tool, "args": redact(act.get("args")),
                                 "result": r_txt[:2000], "final": is_final})

                if is_final:
                    final_result = r_txt
                    break

                first_line = r_txt.splitlines()[0][:160] if r_txt else ""
                extra_lines = len(r_txt.splitlines()) - 1
                log(f"   ↳ {first_line}" + (f"  … (+{extra_lines} строк)" if extra_lines > 0 else ""))

            if final_result is not None:
                log(f"\n✅ {final_result}\n")
                log(f"📊 Итог сессии: токенов принято {human(self.llm.tokens_in)}, "
                    f"сгенерировано {human(self.llm.tokens_out)}. "
                    f"Изменённые файлы: {', '.join(sorted(set(self.repo.touched))) or 'нет'}")
                return final_result

            # Возвращаем результаты. Если модель использовала нативный tool calling —
            # отвечаем ролями tool с tool_call_id (так требуют Gemini/Groq/Mistral/OpenAI),
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

            if sum(len(str(m.get('content') or '')) for m in messages) > 220000:
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


def repl(agent: Agent) -> None:
    log(f"Рабочая папка: {agent.repo.root}")
    log("Пишите задачи обычным текстом, например: «исправь ошибку в api.py — падает на пустом ответе».")
    log("Команды: /help, /tree, /diff, /undo, /model <имя>, /cd <папка>, /pwd, /yes, /exit\n")
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
  перепиши README под текущий код
Команды:
  /tree   — дерево файлов      /diff   — что изменилось в этой сессии
  /undo   — откатить правки    /model  — какой маршрут моделей использовать
  /cd     — сменить рабочую папку (например /cd C:\Проекты\бот)
  /pwd    — какая папка рабочая сейчас
  /yes    — не спрашивать подтверждений (осторожно!)
  /exit   — выход""")
            elif cmd == "/tree":
                log(agent.repo.tree())
            elif cmd == "/diff":
                log(agent.repo.diff())
            elif cmd == "/undo":
                log(agent.repo.undo())
            elif cmd == "/yes":
                agent.yes = True
                agent.allow_cmd = True
                log("Подтверждения отключены.")
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
                    log(f"Модель: {rest}")
                else:
                    log(f"Текущая модель: {agent.llm.model}")
            else:
                log("Неизвестная команда. /help")
            continue
        agent.run_task(line)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="FreeCoder Agent — ИИ-агент, который сам правит ваши файлы",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Примеры:\n"
               '  python freecoder_agent.py "добавь логирование в main.py"\n'
               "  python freecoder_agent.py --workspace C:\\Projects\\bot --yes\n",
    )
    ap.add_argument("task", nargs="*", help="задача (если пусто — диалоговый режим)")
    ap.add_argument("--workspace", "-w", default=os.getcwd(), help="папка проекта (по умолчанию текущая)")
    ap.add_argument("--api-base", default=DEFAULT_API_BASE, help="OpenAI-совместимый endpoint")
    ap.add_argument("--api-key", default=DEFAULT_API_KEY, help="ключ (роутеру всё равно какой)")
    ap.add_argument("--model", "-m", default=DEFAULT_MODEL, help="auto | smart | fast | local | provider/model")
    ap.add_argument("--steps", type=int, default=30, help="максимум шагов на задачу")
    ap.add_argument("--yes", "-y", action="store_true", help="подтверждать всё автоматически")
    ap.add_argument("--dry-run", action="store_true", help="ничего не менять (только показать план)")
    ap.add_argument("--allow-cmd", action="store_true", help="разрешить запуск команд")
    ap.add_argument("--no-backup", action="store_true", help="не хранить резервные копии правок")
    ap.add_argument("--version", action="version", version=f"FreeCoder Agent {VERSION}")
    args = ap.parse_args(argv)

    ws_cfg = load_workspace_config(args.workspace)
    model = args.model or ws_cfg.get("model") or DEFAULT_MODEL
    api_base = args.api_base or ws_cfg.get("api_base") or DEFAULT_API_BASE
    api_key = ws_cfg.get("api_key") or args.api_key

    repo = Repo(args.workspace, dry_run=args.dry_run, backup=not args.no_backup)
    llm = LLM(api_base, api_key, model)
    agent = Agent(repo, llm, yes=args.yes, max_steps=args.steps, allow_cmd=args.allow_cmd)

    log(f"FreeCoder Agent {VERSION}")
    log(f"  папка:  {repo.root}")
    log(f"  модель: {model}  →  {api_base}")
    if args.dry_run:
        log("  режим:  ПРЕДПРОСМОТР (файлы не меняются)")
    if not args.yes:
        log("  правки и команды будут выполняться после подтверждения (--yes отключает)")

    cluster = " ".join(args.task).strip()
    if cluster:
        agent.run_task(cluster)
        return 0
    repl(agent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
