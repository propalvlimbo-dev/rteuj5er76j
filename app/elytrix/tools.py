# -*- coding: utf-8 -*-
"""Инструменты агента: файлы, поиск, команды — и песочница вокруг рабочей папки.

Инструментов ровно шесть, и это осознанно: описания инструментов уезжают в каждый
запрос, поэтому лишний инструмент — это постоянный налог на контекст.

    ls     дерево файлов (компактно, без мусорных папок)
    read   чтение файла или его диапазона
    grep   поиск по содержимому (regex)
    write  создать/перезаписать файл
    edit   точечная замена фрагмента (главный способ править — самый дешёвый)
    bash   команда в папке проекта (тесты, сборка, git)

Каждая правка сначала копируется в .elytrix/backups/<сессия>/ — откат командой /undo.
"""

from __future__ import annotations

import difflib
import fnmatch
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

IGNORE_DIRS = {
    ".git", ".hg", ".svn", ".idea", ".vscode", "node_modules", "__pycache__", ".venv", "venv",
    "env", "dist", "build", "out", "target", ".next", ".nuxt", ".cache", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".tox", "coverage", "vendor", "bin", "obj", ".gradle",
    ".m2", ".cargo", ".elytrix", ".freecoder", ".turbo", ".parcel-cache", ".svelte-kit",
}
IGNORE_EXT = {
    ".pyc", ".pyo", ".exe", ".dll", ".so", ".dylib", ".bin", ".zip", ".tar", ".gz", ".7z",
    ".rar", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".pdf", ".mp3", ".mp4",
    ".mov", ".avi", ".woff", ".woff2", ".ttf", ".otf", ".eot", ".lock", ".sqlite", ".db",
    ".class", ".jar", ".war", ".pdf", ".psd", ".ai", ".svgz",
}
SECRET_PATTERNS = (".env", "id_rsa", "id_ed25519", ".pem", ".key", "credentials", ".netrc")

#: начало сообщения о несуществующем файле — по нему Toolbox помечает результат ошибкой
MISSING_PREFIX = "ФАЙЛА НЕТ"

DENY_COMMANDS = [
    r"\brm\s+-[a-z]*r[a-z]*f?\s+/(?:\s|$)", r"\brm\s+-rf\s+~", r"\bmkfs\b", r"\bdiskpart\b",
    r"\bformat\s+[a-z]:", r"\bshutdown\b", r"\breboot\b", r"\bpoweroff\b",
    r"\bdel\s+/[sq]\s+[a-z]:\\?$", r"rd\s+/s\s+/q\s+[a-z]:\\?$",
    r">\s*/dev/sd", r":\(\)\s*\{", r"\bgit\s+push\s+.*--force", r"\bgit\s+reset\s+--hard\s+HEAD~",
    r"\bnpm\s+publish\b", r"\bcurl\b[^|]*\|\s*(ba|z)?sh", r"\bwget\b[^|]*\|\s*(ba|z)?sh",
    r"\biwr\b[^|]*\|\s*iex", r"Remove-Item\s+-Recurse\s+-Force\s+[A-Z]:\\$",
    r"\bsudo\s+rm\b", r"\bchmod\s+-R\s+777\s+/",
]


@dataclass
class ToolResult:
    """Результат инструмента: отдельно текст для модели и короткое описание для интерфейса."""

    name: str = ""
    ok: bool = True
    text: str = ""              # уходит модели (уже обрезано по бюджету)
    summary: str = ""           # одна строка в ленте событий
    detail: str = ""            # что показать в режиме verbose / в карточке
    diff: str = ""              # для write/edit — что изменилось
    path: str = ""
    changed: bool = False
    elapsed: float = 0.0
    size: int = 0               # сколько символов результата отдали модели


@dataclass
class ToolSpec:
    name: str
    title: str                  # глагол для интерфейса: «читаю», «правлю»
    mutating: bool              # требует подтверждения в режиме ask
    description: str
    schema: Dict[str, Any]
    handler: Optional[Callable[..., ToolResult]] = None


# ---------------------------------------------------------------------------
# Схемы инструментов (Anthropic-формат; в OpenAI переводит gateway.to_openai)
# ---------------------------------------------------------------------------

TOOL_SPECS: List[ToolSpec] = [
    ToolSpec("ls", "смотрю", False,
             "Список файлов и папок проекта. path — подпапка, depth — глубина (1-3).",
             {"type": "object",
              "properties": {"path": {"type": "string"}, "depth": {"type": "integer"}}}),
    ToolSpec("read", "читаю", False,
             "Прочитать текстовый файл. offset — номер первой строки (с 1), limit — сколько "
             "строк отдать. Большие файлы читай диапазоном, а не целиком; "
             "уже прочитанное не перечитывай.",
             {"type": "object", "properties": {"path": {"type": "string"},
                                               "offset": {"type": "integer"},
                                               "limit": {"type": "integer"}},
              "required": ["path"]}),
    ToolSpec("grep", "ищу", False,
             "Поиск по содержимому файлов (regex). glob ограничивает имена файлов.",
             {"type": "object", "properties": {"pattern": {"type": "string"},
                                               "path": {"type": "string"},
                                               "glob": {"type": "string"},
                                               "i": {"type": "boolean"}},
              "required": ["pattern"]}),
    ToolSpec("write", "пишу", True,
             "Создать файл или перезаписать целиком (папки создаются сами). "
             "Для правки существующего файла используй edit.",
             {"type": "object", "properties": {"path": {"type": "string"},
                                               "content": {"type": "string"}},
              "required": ["path", "content"]}),
    ToolSpec("edit", "правлю", True,
             "Точечная замена: old -> new. Копируй old из файла ТОЧНО, с отступами. "
             "Дешевле, чем перезапись файла.",
             {"type": "object", "properties": {"path": {"type": "string"},
                                               "old": {"type": "string"},
                                               "new": {"type": "string"},
                                               "all": {"type": "boolean"}},
              "required": ["path", "old", "new"]}),
    ToolSpec("bash", "запускаю", True,
             "Выполнить команду в папке проекта (тесты, сборка, git). "
             "Одна команда — одна цель.",
             {"type": "object", "properties": {"command": {"type": "string"},
                                               "timeout": {"type": "integer"}},
              "required": ["command"]}),
    ToolSpec("map", "картирую", False,
             "Карта проекта: дерево папок и сигнатуры (классы/функции) файлов. "
             "Вызывай ВНАЧАЛЕ задачи вместо серии grep/read, чтобы понять, где что "
             "лежит; один вызов заменяет десяток блужданий.",
             {"type": "object", "properties": {"path": {"type": "string"}}}),
    ToolSpec("memo", "запоминаю", False,
             "Записать заметку-ориентир о проекте (какой файл за что отвечает, где "
             "какие классы/хуки). Заметки автоматически попадают в следующий промт — "
             "второй задаче не придётся искать заново.",
             {"type": "object", "properties": {"text": {"type": "string"}},
              "required": ["text"]}),
]

TOOL_BY_NAME: Dict[str, ToolSpec] = {t.name: t for t in TOOL_SPECS}
TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {"name": t.name, "description": t.description, "input_schema": t.schema} for t in TOOL_SPECS
]


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f}K"
    return f"{n / 1024 / 1024:.1f}M"


# ---------------------------------------------------------------------------
# Рабочая папка
# ---------------------------------------------------------------------------


class Workspace:
    """Файловые операции с защитой от выхода за пределы папки и с резервными копиями."""

    def __init__(self, root: str, backup: bool = True, limits: Optional[Dict[str, Any]] = None):
        self.root = os.path.abspath(os.path.expanduser(root or os.getcwd()))
        self.backup = backup
        self.limits = dict(limits or {})
        self.session = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        self.backup_dir = os.path.join(self.root, ".elytrix", "backups", self.session)
        self.touched: List[str] = []
        if not os.path.isdir(self.root):
            raise FileNotFoundError(f"рабочая папка не найдена: {self.root}")

    # --- пути ---

    def resolve(self, path: str, for_write: bool = False) -> str:
        raw = (path or "").strip().strip('"').strip("'")
        if not raw:
            raise ValueError("пустой путь")
        full = os.path.abspath(raw if os.path.isabs(raw) else os.path.join(self.root, raw))
        inside = os.path.commonpath([self.root, full]) == self.root
        if not inside and for_write:
            raise ValueError(f"запись вне рабочей папки запрещена: {path}")
        if not inside:
            # читать за пределами папки разрешаем (документация, соседний проект),
            # но только существующие файлы — иначе модель начнёт угадывать
            if not os.path.exists(full):
                raise ValueError(f"путь вне рабочей папки и не существует: {path}")
        return full

    def rel(self, full: str) -> str:
        try:
            return os.path.relpath(full, self.root).replace("\\", "/")
        except ValueError:                     # другой диск в Windows
            return full.replace("\\", "/")

    def walk(self, start: Optional[str] = None):
        base = start or self.root
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames
                                 if d not in IGNORE_DIRS and not d.startswith("."))
            yield dirpath, dirnames, sorted(filenames)

    # --- резервные копии ---

    #: суффикс метки «такого файла до сессии не было» — undo его удалит
    NEW_MARKER = ".new"

    def snapshot(self, full: str) -> None:
        """Запоминает исходное состояние файла ДО правки.

        Для нового файла резервной копии нет, поэтому кладём пустую метку: по ней
        /diff покажет файл как добавленный, а /undo — удалит.
        """
        if not self.backup:
            return
        rel = self.rel(full)
        try:
            if os.path.isfile(full):
                dst = os.path.join(self.backup_dir, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if not os.path.exists(dst):    # храним ПЕРВОначальное состояние файла
                    shutil.copy2(full, dst)
                return
            mark = os.path.join(self.backup_dir, rel + self.NEW_MARKER)
            os.makedirs(os.path.dirname(mark), exist_ok=True)
            if not os.path.exists(mark):
                with open(mark, "w", encoding="utf-8"):
                    pass
        except OSError:
            pass

    def undo(self) -> Tuple[int, List[str]]:
        """Возвращает файлы к состоянию на начало сессии; созданные агентом — удаляет."""
        if not os.path.isdir(self.backup_dir):
            return 0, []
        restored: List[str] = []
        for dirpath, _, filenames in os.walk(self.backup_dir):
            for name in sorted(filenames):
                src = os.path.join(dirpath, name)
                rel = os.path.relpath(src, self.backup_dir)
                created = rel.endswith(self.NEW_MARKER)
                if created:
                    rel = rel[:-len(self.NEW_MARKER)]
                dst = os.path.join(self.root, rel)
                try:
                    if created:
                        if os.path.isfile(dst):
                            os.remove(dst)
                            restored.append(rel.replace("\\", "/"))
                        continue
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                    restored.append(rel.replace("\\", "/"))
                except OSError:
                    continue
        return len(restored), restored

    def session_diff(self, max_lines: int = 400) -> str:
        """Diff всех файлов, тронутых в этой сессии (по резервным копиям)."""
        if not os.path.isdir(self.backup_dir):
            return ""
        out: List[str] = []
        for dirpath, _, filenames in os.walk(self.backup_dir):
            for name in sorted(filenames):
                src = os.path.join(dirpath, name)
                rel = os.path.relpath(src, self.backup_dir).replace("\\", "/")
                created = rel.endswith(self.NEW_MARKER)
                if created:
                    rel = rel[:-len(self.NEW_MARKER)]
                cur = os.path.join(self.root, rel)
                old = "" if created else _read_text(src)
                new = _read_text(cur) if os.path.isfile(cur) else ""
                diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(),
                                                 fromfile=f"a/{rel}", tofile=f"b/{rel}",
                                                 lineterm="", n=2))
                out.extend(diff)
                if len(out) > max_lines:
                    out.append("… (diff обрезан)")
                    return "\n".join(out)
        return "\n".join(out)

    # --- краткое описание проекта для системного промпта ---

    def fingerprint(self, max_entries: int = 26) -> str:
        """Одна строка о проекте: верхний уровень и ветка git.

        Полное дерево в системный промпт НЕ кладём: оно стоит сотни токенов на каждом
        шаге, а нужно модели от силы один-два раза — для этого есть ls.
        """
        try:
            entries = sorted(os.listdir(self.root))
        except OSError:
            return ""
        names: List[str] = []
        for name in entries:
            if name in IGNORE_DIRS or name.startswith("."):
                continue
            full = os.path.join(self.root, name)
            names.append(name + "/" if os.path.isdir(full) else name)
            if len(names) >= max_entries:
                names.append("…")
                break
        branch = ""
        git_head = os.path.join(self.root, ".git", "HEAD")
        if os.path.isfile(git_head):
            try:
                with open(git_head, "r", encoding="utf-8", errors="replace") as f:
                    line = f.read().strip()
                if line.startswith("ref:"):
                    branch = line.rsplit("/", 1)[-1]
            except OSError:
                branch = ""
        parts = [", ".join(names) or "(пусто)"]
        if branch:
            parts.append(f"git:{branch}")
        return " · ".join(parts)

    # --- операции ---

    def ls(self, path: str = "", depth: int = 2, max_lines: int = 120) -> str:
        start = self.resolve(path or ".")
        if not os.path.isdir(start):
            return f"это не папка: {self.rel(start)}"
        depth = max(1, min(3, int(depth or 2)))
        lines: List[str] = []
        total = 0

        def rec(current: str, level: int, prefix: str) -> None:
            nonlocal total
            try:
                entries = sorted(os.listdir(current), key=lambda n: (not os.path.isdir(os.path.join(current, n)), n.lower()))
            except OSError:
                return
            for name in entries:
                if name in IGNORE_DIRS:
                    continue
                full = os.path.join(current, name)
                is_dir = os.path.isdir(full)
                if name.startswith(".") and not is_dir:
                    continue
                total += 1
                if is_dir:
                    lines.append(f"{prefix}{name}/")
                    if level < depth:
                        rec(full, level + 1, prefix + "  ")
                else:
                    try:
                        size = human_size(os.path.getsize(full))
                    except OSError:
                        size = "?"
                    lines.append(f"{prefix}{name} ({size})")
                if len(lines) >= max_lines:
                    return

        rec(start, 1, "")
        head = f"# {self.rel(start) or '.'} — файлов и папок: {total}"
        if len(lines) >= max_lines:
            lines.append(f"… (показаны первые {max_lines}, дальше — ls с path)")
        return head + "\n" + "\n".join(lines)

    def read(self, path: str, offset: int = 1, limit: int = 0) -> Tuple[str, str, int]:
        """Возвращает (текст для модели, краткое описание, всего строк).

        ``offset`` — номер первой строки, считая с единицы; ``limit`` — сколько строк отдать.
        """
        full = self.resolve(path)
        rel = self.rel(full)
        if os.path.isdir(full):
            return self.ls(path), f"папка {rel}", 0
        if not os.path.isfile(full):
            hint = self._missing_hint(full, rel)
            return hint, f"нет файла {rel}", 0
        if _is_secret(rel):
            return (f"Файл {rel} похож на хранилище секретов — не показываю его содержимое "
                    f"модели. Если он действительно нужен, попросите пользователя "
                    f"вставить нужные строки в задачу.", f"секрет {rel}", 0)
        text = _read_text(full)
        lines = text.splitlines()
        total = len(lines)
        start = max(0, int(offset or 1) - 1)
        end = total if not limit else min(total, start + int(limit))
        chunk = lines[start:end]
        body = "\n".join(chunk)
        budget = int(self.limits.get("read_chars", 12000))
        cut = ""
        if len(body) > budget:
            shown = len(body.splitlines())
            body = body[:budget]
            cut = (f"\n…(обрезано на {budget} символах: всего {total} строк, {len(text)} символов; "
                   f"дальше — read с offset={start + shown + 1})")
        header = f"# {rel} ({start + 1}-{start + len(chunk)} из {total})"
        summary = f"{rel} · строк {len(chunk)}/{total}"
        return header + "\n" + body + cut, summary, total

    def _missing_hint(self, full: str, rel: str) -> str:
        parent = os.path.dirname(full)
        hint = ""
        if os.path.isdir(parent):
            twins = [f for f in os.listdir(parent) if f.lower() == os.path.basename(full).lower()]
            if twins:
                hint = f" Есть файл с таким именем в другом регистре: {twins[0]}."
            else:
                near = sorted(f for f in os.listdir(parent)
                              if os.path.isfile(os.path.join(parent, f)))[:8]
                if near:
                    hint = " В этой папке: " + ", ".join(near) + "."
        return (f"{MISSING_PREFIX}: {rel}.{hint} Если его нужно создать — вызови write "
                f"(папки создаются автоматически). Отсутствие файла — нормальное начало работы, "
                f"а не причина останавливать задачу.")

    def grep(self, pattern: str, path: str = "", glob: str = "", ignore_case: bool = False,
             max_hits: int = 40) -> str:
        try:
            rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
        except re.error:
            rx = re.compile(re.escape(pattern), re.IGNORECASE if ignore_case else 0)
        start = self.resolve(path) if path else self.root
        if os.path.isfile(start):
            files = [start]
            base = os.path.dirname(start)
        else:
            files = None
            base = start
        hits: List[str] = []
        files_hit = 0
        scanned = 0

        def scan(full: str) -> bool:
            nonlocal files_hit, scanned
            scanned += 1
            rel = self.rel(full)
            if _is_secret(rel):
                return False
            try:
                if os.path.getsize(full) > 2_000_000:
                    return False
                with open(full, "r", encoding="utf-8", errors="ignore") as fh:
                    found = False
                    for i, line in enumerate(fh, 1):
                        if i > 20000:
                            break
                        if rx.search(line):
                            if not found:
                                files_hit += 1
                                found = True
                            hits.append(f"{rel}:{i}: {line.strip()[:180]}")
                            if len(hits) >= max_hits:
                                return True
            except OSError:
                return False
            return False

        stop = False
        if files:
            stop = scan(files[0])
        else:
            for dirpath, _, filenames in self.walk(base):
                for name in filenames:
                    if os.path.splitext(name)[1].lower() in IGNORE_EXT:
                        continue
                    if glob and not fnmatch.fnmatch(name, glob):
                        continue
                    if scan(os.path.join(dirpath, name)):
                        stop = True
                        break
                if stop:
                    break
        if not hits:
            return f"Совпадений нет (проверено файлов: {scanned})."
        head = f"# grep «{pattern}» — совпадений {len(hits)} в {files_hit} файлах"
        body = "\n".join(hits)
        if stop:
            body += f"\n… (обрезано на {max_hits} совпадениях — уточни pattern или glob)"
        return head + "\n" + body

    def write(self, path: str, content: str) -> Tuple[str, str, str]:
        """(текст для модели, краткое описание, diff)."""
        full = self.resolve(path, for_write=True)
        rel = self.rel(full)
        old = _read_text(full) if os.path.isfile(full) else ""
        diff = _unified(old, content, rel)
        self.snapshot(full)
        os.makedirs(os.path.dirname(full) or self.root, exist_ok=True)
        _write_text(full, content)
        self.touched.append(rel)
        created = not old
        text = (f"{'Создан' if created else 'Перезаписан'} файл {rel}: {len(content)} символов, "
                f"{content.count(chr(10)) + 1} строк."
                + ("" if created else f" Было {len(old)} символов."))
        summary = f"{rel} · {len(content)} символов" + (" · новый" if created else "")
        return text, summary, diff

    def edit(self, path: str, old: str, new: str, replace_all: bool = False) -> Tuple[str, str, str]:
        full = self.resolve(path, for_write=True)
        rel = self.rel(full)
        if not os.path.isfile(full):
            raise ValueError(f"файл не найден: {rel} (создать — write)")
        text = _read_text(full)
        count = text.count(old)
        if count == 0:
            relaxed = _relaxed_match(text, old)
            if relaxed is None:
                nearby = _closest_snippet(text, old)
                raise ValueError(
                    f"фрагмент не найден в {rel}. Прочитай нужный кусок заново (read с offset) "
                    f"и скопируй текст точно, с отступами и переносами строк."
                    + (f" Похожий текст в файле: {nearby}" if nearby else ""))
            old = relaxed
            count = text.count(old)
        self.snapshot(full)
        result = text.replace(old, new) if replace_all else text.replace(old, new, 1)
        applied = count if replace_all else 1
        _write_text(full, result)
        self.touched.append(rel)
        diff = _unified(text, result, rel)
        summary = f"{rel} · замен {applied}" + (f" · {len(text)}→{len(result)}" if not replace_all else "")
        return (f"Готово: {rel}, заменено вхождений: {applied} "
                f"({len(text)} → {len(result)} символов)"), summary, diff

    def delete(self, path: str) -> Tuple[str, str]:
        full = self.resolve(path, for_write=True)
        rel = self.rel(full)
        if not os.path.isfile(full):
            raise ValueError(f"файл не найден: {rel}")
        self.snapshot(full)
        os.remove(full)
        self.touched.append(rel)
        return f"Удалён {rel} (копия в .elytrix/backups)", f"{rel} удалён"

    def bash(self, command: str, timeout: int = 120,
             cancel: Optional[threading.Event] = None) -> Tuple[str, str]:
        cmd = (command or "").strip()
        if not cmd:
            raise ValueError("пустая команда")
        for pat in DENY_COMMANDS:
            if re.search(pat, cmd, re.IGNORECASE):
                raise PermissionError(f"команда запрещена правилами безопасности: {cmd}")
        timeout = max(5, min(int(timeout or 120), 900))
        t0 = time.time()
        try:
            proc = subprocess.Popen(cmd, shell=True, cwd=self.root,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, encoding="utf-8", errors="replace")
        except OSError as e:
            raise RuntimeError(f"не удалось запустить команду: {e}") from e
        out = err = ""
        while True:
            try:
                out, err = proc.communicate(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                if cancel is not None and cancel.is_set():
                    proc.kill()
                    try:
                        proc.wait(2)
                    except subprocess.TimeoutExpired:  # noqa: BLE001
                        pass
                    return (f"Команда прервана пользователем (Esc): {cmd}", "остановлено")
                if time.time() - t0 > timeout:
                    proc.kill()
                    try:
                        proc.wait(2)
                    except subprocess.TimeoutExpired:  # noqa: BLE001
                        pass
                    return (f"Команда не завершилась за {timeout}с: {cmd}. "
                            f"Разбей её на части или добавь флаг неинтерактивного режима.",
                            f"таймаут {timeout}с")
        elapsed = time.time() - t0
        out = (out or "").replace("\r\n", "\n")
        err = (err or "").replace("\r\n", "\n")
        limit = int(self.limits.get("bash_output_chars", 4000))
        body = _truncate_middle(out, limit)
        if err.strip():
            body += "\n[stderr]\n" + _truncate_middle(err, max(500, limit // 3))
        head = f"$ {cmd}\n[код {proc.returncode} · {elapsed:.1f}с]"
        text = head + "\n" + (body.strip() or "(пустой вывод)")
        status = "ок" if proc.returncode == 0 else f"код {proc.returncode}"
        return text, f"{cmd[:60]} · {status} · {elapsed:.1f}с"


# ---------------------------------------------------------------------------
# Помощники
# ---------------------------------------------------------------------------


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
            return f.read()
    except OSError:
        return ""


def _write_text(path: str, text: str) -> None:
    """Пишет текст, сохраняя привычный стиль переносов строк файла."""
    newline = "\r\n" if "\r\n" in text else "\n"
    with open(path, "w", encoding="utf-8", newline=newline if newline == "\r\n" else "") as f:
        f.write(text)


def _is_secret(rel: str) -> bool:
    low = rel.lower().replace("\\", "/")
    base = low.rsplit("/", 1)[-1]
    return any(base == p or base.startswith(p + ".") or low.endswith(p) for p in SECRET_PATTERNS)


def _unified(old: str, new: str, rel: str, context: int = 2) -> str:
    return "\n".join(difflib.unified_diff(old.splitlines(), new.splitlines(),
                                          fromfile=f"a/{rel}", tofile=f"b/{rel}",
                                          lineterm="", n=context))


def _normalize(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text).strip()


def _relaxed_match(text: str, old: str) -> Optional[str]:
    """Ищет фрагмент, игнорируя лишние пробелы: экономит один лишний шаг модели."""
    target = _normalize(old)
    if not target:
        return None
    for line_count in range(old.count("\n") + 1, old.count("\n") + 3):
        lines = text.splitlines()
        for i in range(len(lines) - line_count + 1):
            window = "\n".join(lines[i:i + line_count])
            if _normalize(window).replace("\n ", "\n") == target.replace("\n ", "\n"):
                return window
    return None


def _closest_snippet(text: str, old: str, window: int = 120) -> str:
    """Показывает наиболее похожий кусок файла — модель исправит аргументы без перечитывания."""
    target = _normalize(old)
    if not target:
        return ""
    best, best_ratio = "", 0.0
    lines = text.splitlines()
    span = max(1, old.count("\n") + 1)
    for i in range(0, max(1, len(lines) - span + 1)):
        candidate = _normalize("\n".join(lines[i:i + span]))
        ratio = difflib.SequenceMatcher(None, target, candidate).ratio()
        if ratio > best_ratio:
            best, best_ratio = candidate, ratio
    if best_ratio < 0.5:
        return ""
    return best[:window] + ("…" if len(best) > window else "")


def _truncate_middle(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = int(limit * 0.6)
    tail = limit - head
    return (text[:head] + f"\n… пропущено {len(text) - limit} символов …\n"
            + text[-tail:])


# ---------------------------------------------------------------------------
# Коробка инструментов
# ---------------------------------------------------------------------------


class Toolbox:
    """Выполняет инструменты и оформляет результат одинаково для модели и интерфейса."""

    def __init__(self, ws: Workspace, limits: Optional[Dict[str, Any]] = None):
        self.ws = ws
        self.limits = dict(limits or {})
        self.cancel: Optional[threading.Event] = None   # ставит агент: Esc убивает команды
        self.calls = 0
        self.by_name: Dict[str, int] = {}

    # -- отдельные инструменты ---------------------------------------------

    def _ls(self, args: Dict[str, Any]) -> ToolResult:
        text = self.ws.ls(str(args.get("path") or ""), int(args.get("depth") or 2))
        count = max(0, text.count("\n"))
        return ToolResult(name="ls", text=text, summary=text.splitlines()[0][2:],
                          detail=f"{count} строк", size=len(text))

    def _read(self, args: Dict[str, Any]) -> ToolResult:
        path = str(args.get("path") or "")
        text, summary, total = self.ws.read(path, int(args.get("offset") or 1),
                                            int(args.get("limit") or 0))
        missing = text.startswith(MISSING_PREFIX)
        return ToolResult(name="read", ok=not missing, text=text, summary=summary, path=path,
                          size=len(text))

    def _grep(self, args: Dict[str, Any]) -> ToolResult:
        text = self.ws.grep(str(args.get("pattern") or ""), str(args.get("path") or ""),
                            str(args.get("glob") or ""), bool(args.get("i")),
                            max_hits=int(self.limits.get("grep_hits", 40)))
        first = text.splitlines()[0]
        return ToolResult(name="grep", text=text,
                          summary=first[2:] if first.startswith("# ") else first[:80],
                          detail=f"«{args.get('pattern')}»", size=len(text))

    SKIP_DIRS = {".git", "node_modules", "target", "build", "dist", "out",
                 "__pycache__", ".idea", ".vscode", "venv", ".venv", ".elytrix"}
    SIG_RE = re.compile(
        r"^\s*(?:export\s+|public\s+|private\s+|protected\s+|final\s+|abstract\s+|"
        r"static\s+)*(?:class|interface|enum|struct|trait|def|func|function)\s+\w+"
        r"|^\s*(?:public|protected|private)\s+[\w<>\[\], .?]+\s+\w+\s*\(")

    def notes_path(self) -> str:
        return os.path.join(self.ws.root, ".elytrix", "notes.md")

    def notes_text(self, limit: int = 1200) -> str:
        """Хвост заметок проекта — идёт в системный промт следующей задачи."""
        try:
            with open(self.notes_path(), encoding="utf-8", errors="replace") as f:
                lines = [ln.rstrip() for ln in f if ln.strip()][-24:]
        except OSError:
            return ""
        text = "\n".join(lines)
        return text[-limit:] if len(text) > limit else text

    def _signatures(self, full: str, cap: int = 8) -> List[str]:
        try:
            with open(full, encoding="utf-8", errors="replace") as f:
                out = []
                for i, ln in enumerate(f):
                    if i > 2000:
                        break
                    if self.SIG_RE.match(ln):
                        out.append(ln.strip()[:100])
                        if len(out) >= cap:
                            break
                return out
        except OSError:
            return []

    def _map(self, args: Dict[str, Any]) -> ToolResult:
        root = self.ws.root
        sub = str(args.get("path") or "")
        start = os.path.join(root, sub) if sub else root
        lines: List[str] = []
        files = 0
        for dirpath, dirnames, filenames in os.walk(start):
            dirnames[:] = sorted(d for d in dirnames
                                 if d not in self.SKIP_DIRS and not d.startswith("."))
            depth = os.path.relpath(dirpath, start).count(os.sep)
            ind = "  " * depth
            lines.append(f"{ind}{os.path.basename(dirpath) or '.'}/")
            for fn in sorted(filenames):
                if files >= 250 or len(lines) >= 350:
                    break
                full = os.path.join(dirpath, fn)
                try:
                    size = os.path.getsize(full)
                except OSError:
                    continue
                files += 1
                lines.append(f"{ind}  {fn} · {size} Б")
                if size < 400_000:
                    lines.extend(f"{ind}    {sig}" for sig in self._signatures(full))
        text = "\n".join(lines[:380]) or "(пусто)"
        return ToolResult(name="map", text=text, summary=f"карта: {files} файлов",
                          size=len(text))

    def _memo(self, args: Dict[str, Any]) -> ToolResult:
        line = str(args.get("text") or "").strip()
        if not line:
            raise ValueError("нужно text")
        path = self.notes_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return ToolResult(name="memo", text=f"записано: {line}",
                          summary="заметка сохранена", changed=True, size=len(line))

    def _write(self, args: Dict[str, Any]) -> ToolResult:
        path = str(args.get("path") or "")
        content = args.get("content")
        if content is None:
            raise ValueError("не передан content")
        text, summary, diff = self.ws.write(path, str(content))
        return ToolResult(name="write", text=text, summary=summary, diff=diff, path=path,
                          changed=True, size=len(text))

    def _edit(self, args: Dict[str, Any]) -> ToolResult:
        path = str(args.get("path") or "")
        old = args.get("old")
        new = args.get("new")
        if old is None or new is None:
            raise ValueError("нужны old и new")
        if old == new:
            raise ValueError("old и new совпадают — менять нечего")
        text, summary, diff = self.ws.edit(path, str(old), str(new), bool(args.get("all")))
        return ToolResult(name="edit", text=text, summary=summary, diff=diff, path=path,
                          changed=True, size=len(text))

    def _bash(self, args: Dict[str, Any]) -> ToolResult:
        cmd = str(args.get("command") or "")
        text, summary = self.ws.bash(cmd, int(args.get("timeout") or 120), self.cancel)
        ok = "[код 0" in text
        return ToolResult(name="bash", ok=ok, text=text, summary=summary, detail=cmd[:200],
                          size=len(text))

    # -- общий вход ---------------------------------------------------------

    def run(self, name: str, args: Optional[Dict[str, Any]]) -> ToolResult:
        args = args if isinstance(args, dict) else {}
        self.calls += 1
        self.by_name[name] = self.by_name.get(name, 0) + 1
        t0 = time.time()
        handlers = {"ls": self._ls, "read": self._read, "grep": self._grep,
                    "write": self._write, "edit": self._edit, "bash": self._bash,
                    "map": self._map, "memo": self._memo}
        handler = handlers.get(name)
        if handler is None:
            return ToolResult(name=name, ok=False,
                              text=f"ОШИБКА: нет инструмента «{name}». Доступны: "
                                   + ", ".join(handlers) + ".",
                              summary=f"неизвестный инструмент {name}")
        try:
            result = handler(args)
        except ValueError as e:
            result = ToolResult(name=name, ok=False, text=f"ОШИБКА: {e}", summary=str(e)[:100])
        except PermissionError as e:
            result = ToolResult(name=name, ok=False, text=f"ЗАПРЕЩЕНО: {e}", summary=str(e)[:100])
        except Exception as e:  # noqa: BLE001
            result = ToolResult(name=name, ok=False,
                                text=f"ОШИБКА {type(e).__name__}: {e}",
                                summary=f"{type(e).__name__}: {e}"[:100])
        result.elapsed = time.time() - t0
        # единый бюджет на результат: длинный вывод стоит токенов на каждом следующем шаге
        budget = int(self.limits.get("tool_result_chars", 6000))
        if len(result.text) > budget:
            result.text = _truncate_middle(result.text, budget)
        result.size = len(result.text)
        return result

    @staticmethod
    def title(name: str) -> str:
        return TOOL_BY_NAME[name].title if name in TOOL_BY_NAME else name

    @staticmethod
    def mutating(name: str) -> bool:
        return bool(TOOL_BY_NAME.get(name) and TOOL_BY_NAME[name].mutating)
