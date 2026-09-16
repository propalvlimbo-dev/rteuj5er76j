# -*- coding: utf-8 -*-
"""Полноэкранный интерфейс ELYTRIX — как в opencode: лента событий, поле ввода, статус.

Устройство:
    · главный поток читает клавиши и рисует кадры (20-30 в секунду, только когда что-то
      изменилось — процессор в простое не грузим);
    · задача агента выполняется в рабочем потоке и присылает события в очередь:
      текст ответа печатается по мере генерации, инструменты появляются в ленте сразу;
    · подтверждения правок — модальный диалог: рабочий поток ждёт ответа, интерфейс
      показывает diff и ждёт клавишу;
    · если вывод не в консоль (файл, канал) или задан --plain, включается плоский режим:
      тот же агент, но без полноэкранной отрисовки.
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import __version__
from .config import Catalog, Config, State, mask_key, project_root, save_key
from .dialogs import ConfirmDialog, Dialog, ListDialog, MessageDialog, PromptDialog
from .gateway import Cancelled, GatewayError, SmartAPI
from .keys import KeyEvent, KeyReader
from . import clip
from .render import (KIND_ASSISTANT, KIND_CUSTOM, KIND_ERROR, KIND_INFO, KIND_LOGO,
                      KIND_SPACER, KIND_TOOL, KIND_USER, LOGO_ART, Block, activity,
                      header, status_bar)
from .screen import (ALT_OFF, ALT_ON, BRACKETED_OFF, BRACKETED_ON, CLEAR, ERASE_DOWN,
                     HOME, HIDE_CURSOR, Line, SHOW_CURSOR, move, pad, supports_unicode,
                     terminal_size, text_width, truncate, wrap_line)
from .theme import Theme, THEME_NAMES
from .tools import Toolbox, Workspace
from .widgets import human_number, plural, render_markdown, seconds_text

TIPS = [
    "задачу пишите словами: «в api.py падает get_user на пустом ответе — исправь»",
    "/model — выбрать модель, /tokens — куда уходят токены, /undo — откатить правки",
    "Ctrl+Shift+C — скопировать ответ, Ctrl+Shift+V — вставить из буфера (/copy, /paste)",
    "Alt+Enter — перенос строки, @ — подставить путь к файлу, Tab — продолжить команду",
    "Esc — остановить задачу, /clear — новая тема без старой истории (дешевле)",
    "/confirm auto — править без вопросов, /confirm ask — спрашивать на каждую правку",
    "чем конкретнее задача (файлы, ожидаемое поведение), тем меньше шагов и токенов",
    "/cd — сменить рабочую папку без перезапуска консоли",
]


# ---------------------------------------------------------------------------
# Поле ввода
# ---------------------------------------------------------------------------


class InputBuffer:
    """Многострочное поле ввода с курсором и историей."""

    def __init__(self, history_limit: int = 200):
        self.lines: List[str] = [""]
        self.row = 0
        self.col = 0
        self.history: List[str] = []
        self.history_limit = history_limit
        self._hist_index = -1
        self._hist_draft = ""
        self.scroll = 0

    # -- доступ к тексту --

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def is_empty(self) -> bool:
        return not self.text.strip()

    def set_text(self, text: str) -> None:
        self.lines = (text or "").split("\n") or [""]
        self.row = len(self.lines) - 1
        self.col = len(self.lines[-1])

    def clear(self) -> None:
        self.lines = [""]
        self.row = self.col = 0
        self.scroll = 0

    def push_history(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if self.history and self.history[-1] == text:
            return
        self.history.append(text)
        if len(self.history) > self.history_limit:
            self.history = self.history[-self.history_limit:]

    # -- правка --

    def insert(self, text: str) -> None:
        if not text:
            return
        parts = text.split("\n")
        line = self.lines[self.row]
        if len(parts) == 1:
            self.lines[self.row] = line[:self.col] + parts[0] + line[self.col:]
            self.col += len(parts[0])
            return
        first = line[:self.col] + parts[0]
        last = parts[-1] + line[self.col:]
        middle = parts[1:-1]
        self.lines[self.row:self.row + 1] = [first] + middle + [last]
        self.row += len(middle) + 1
        self.col = len(parts[-1])

    def newline(self) -> None:
        self.insert("\n")

    def backspace(self) -> None:
        if self.col > 0:
            line = self.lines[self.row]
            self.lines[self.row] = line[:self.col - 1] + line[self.col:]
            self.col -= 1
        elif self.row > 0:
            prev = self.lines[self.row - 1]
            cur = self.lines.pop(self.row)
            self.row -= 1
            self.col = len(prev)
            self.lines[self.row] = prev + cur

    def delete(self) -> None:
        line = self.lines[self.row]
        if self.col < len(line):
            self.lines[self.row] = line[:self.col] + line[self.col + 1:]
        elif self.row + 1 < len(self.lines):
            self.lines[self.row] = line + self.lines.pop(self.row + 1)

    def left(self) -> None:
        if self.col > 0:
            self.col -= 1
        elif self.row > 0:
            self.row -= 1
            self.col = len(self.lines[self.row])

    def right(self) -> None:
        if self.col < len(self.lines[self.row]):
            self.col += 1
        elif self.row + 1 < len(self.lines):
            self.row += 1
            self.col = 0

    def up(self) -> bool:
        """Стрелка вверх: строка выше или (в первой строке) история. False — взяли историю."""
        if self.row > 0:
            self.row -= 1
            self.col = min(self.col, len(self.lines[self.row]))
            return True
        self.history_prev()
        return False

    def down(self) -> bool:
        if self.row + 1 < len(self.lines):
            self.row += 1
            self.col = min(self.col, len(self.lines[self.row]))
            return True
        self.history_next()
        return False

    def history_prev(self) -> None:
        if not self.history:
            return
        if self._hist_index == -1:
            self._hist_draft = self.text
            self._hist_index = len(self.history) - 1
        elif self._hist_index > 0:
            self._hist_index -= 1
        self.set_text(self.history[self._hist_index])

    def history_next(self) -> None:
        if self._hist_index == -1:
            return
        if self._hist_index + 1 < len(self.history):
            self._hist_index += 1
            self.set_text(self.history[self._hist_index])
        else:
            self._hist_index = -1
            self.set_text(self._hist_draft)

    def reset_history_cursor(self) -> None:
        self._hist_index = -1
        self._hist_draft = ""

    def home(self) -> None:
        self.col = 0

    def end(self) -> None:
        self.col = len(self.lines[self.row])

    def kill_line(self) -> None:
        self.lines[self.row] = self.lines[self.row][:self.col]
        self.col = len(self.lines[self.row])

    def kill_to_start(self) -> None:
        self.lines[self.row] = self.lines[self.row][self.col:]
        self.col = 0

    def kill_word(self) -> None:
        """Ctrl+W: стереть слово перед курсором (путь режем по сегментам «/»)."""
        line = self.lines[self.row]
        head = line[:self.col]
        idx = len(head)
        while idx > 0 and head[idx - 1] in " \t":
            idx -= 1
        while idx > 0 and head[idx - 1] in "/\\":     # висячий разделитель — тоже стираем
            idx -= 1
        while idx > 0 and not (head[idx - 1].isspace() or head[idx - 1] in "/\\"):
            idx -= 1
        self.lines[self.row] = head[:idx] + line[self.col:]
        self.col = idx


# ---------------------------------------------------------------------------
# Автодополнение
# ---------------------------------------------------------------------------

COMMANDS: List[Tuple[str, str]] = [
    ("/help", "справка: команды и клавиши"),
    ("/model", "выбрать модель (с коэффициентом расхода)"),
    ("/tokens", "куда уходят токены: контекст, кэш, расход за сутки"),
    ("/clear", "новая тема: забыть историю и память сессии"),
    ("/compact", "сжать историю вручную (дешевле следующий шаг)"),
    ("/diff", "что изменилось в файлах за сессию"),
    ("/undo", "откатить правки сессии"),
    ("/tree", "дерево файлов проекта"),
    ("/session", "что агент помнит о прошлых задачах"),
    ("/steps", "лимит шагов на задачу: /steps 12"),
    ("/limit", "дневной лимит зачётных токенов: /limit 600000"),
    ("/confirm", "режим правок: ask | auto | readonly"),
    ("/verbose", "показывать содержимое результатов инструментов"),
    ("/api", "загрузить ключ SmartAPI: /api — диалог, /api sk-smart-… или /api ключ.txt"),
    ("/prompt", "загрузить большой промт из файла в строку ввода: /prompt spec.md"),
    ("/copy", "копировать строку ввода или последний ответ в буфер обмена"),
    ("/paste", "вставить буфер обмена в строку ввода"),
    ("/theme", "тема оформления"),
    ("/cd", "сменить рабочую папку"),
    ("/key", "синоним /api: загрузить ключ SmartAPI"),
    ("/doctor", "диагностика: ключ, шлюз, модели, лимиты"),
    ("/models", "обновить каталог моделей шлюза: /models reload"),
    ("/router", "поднять OpenAI-совместимый шлюз для редакторов"),
    ("/exit", "выход"),
]


class Completion:
    """Подсказки: команды по «/» и пути к файлам по «@»."""

    def __init__(self) -> None:
        self.active = False
        self.kind = ""            # command | file
        self.items: List[Tuple[str, str, str]] = []   # (метка, что вставить, пояснение)
        self.index = 0
        self.start = 0            # позиция в тексте, откуда идёт дополнение
        self.row = 0

    def close(self) -> None:
        self.active = False
        self.items = []
        self.index = 0

    def update_command(self, buffer: InputBuffer) -> None:
        text = buffer.text
        if not text.startswith("/"):
            self.close()
            return
        head = text.split("\n")[0]
        if " " in head:
            self.close()
            return
        prefix = head.lower()
        items = [(name, name + " ", note) for name, note in COMMANDS if name.startswith(prefix)]
        if not items:
            self.close()
            return
        self.kind, self.items, self.active = "command", items, True
        self.index = min(self.index, len(items) - 1)

    def update_file(self, buffer: InputBuffer, ws: Workspace) -> None:
        text = buffer.lines[buffer.row][:buffer.col]
        at = text.rfind("@")
        if at < 0:
            if self.kind == "file":
                self.close()
            return
        frag = text[at + 1:]
        if " " in frag or len(frag) > 60:
            if self.kind == "file":
                self.close()
            return
        matches = _file_candidates(ws, frag, limit=9)
        if not matches:
            self.close()
            return
        self.kind = "file"
        self.items = [(name, "@" + rel + " ", rel) for name, rel in matches]
        self.active = True
        self.start = at
        self.row = buffer.row
        self.index = min(self.index, len(self.items) - 1)

    def accept(self, buffer: InputBuffer) -> None:
        if not self.active or not self.items:
            return
        label, insert, _note = self.items[self.index]
        if self.kind == "command":
            buffer.set_text(insert)
        else:
            line = buffer.lines[buffer.row]
            buffer.lines[buffer.row] = line[:self.start] + insert + line[buffer.col:]
            buffer.col = self.start + len(insert)
        self.close()

    def move(self, delta: int) -> None:
        if self.items:
            self.index = (self.index + delta) % len(self.items)


def _file_candidates(ws: Workspace, fragment: str, limit: int = 9) -> List[Tuple[str, str]]:
    """Быстрый поиск файлов по подстроке (для подстановки @путь)."""
    frag = fragment.lower().lstrip("./\\")
    out: List[Tuple[str, str]] = []
    frag_dir, _, frag_name = frag.rpartition("/")
    try:
        if frag_dir:
            base = ws.resolve(frag_dir)
            if not os.path.isdir(base):
                return []
            for name in sorted(os.listdir(base)):
                if name.lower().startswith(frag_name):
                    full = os.path.join(base, name)
                    rel = ws.rel(full)
                    out.append((name + ("/" if os.path.isdir(full) else ""), rel))
                    if len(out) >= limit:
                        return out
            return out
        for dirpath, dirnames, filenames in ws.walk(ws.root):
            depth = dirpath[len(ws.root):].count(os.sep)
            if depth > 3:
                dirnames[:] = []
            for name in filenames:
                if frag_name and frag_name not in name.lower():
                    continue
                full = os.path.join(dirpath, name)
                out.append((name, ws.rel(full)))
                if len(out) >= limit:
                    return out
            if len(out) >= limit:
                break
    except (OSError, ValueError):
        return out
    return out


# ---------------------------------------------------------------------------
# Приложение
# ---------------------------------------------------------------------------


class App:
    """Полноэкранная консоль ELYTRIX."""

    def __init__(self, cfg: Config, catalog: Catalog, state: State, gateway: SmartAPI,
                 toolbox: Toolbox, agent: Any, theme: Theme, key_source: str = ""):
        self.cfg = cfg
        self.catalog = catalog
        self.state = state
        self.gw = gateway
        self.toolbox = toolbox
        self.agent = agent
        self.theme = theme
        self.key_source = key_source
        self.ws = toolbox.ws

        self.blocks: List[Block] = []
        self.scroll = 0
        self.input = InputBuffer()
        self.completion = Completion()
        self.dialog: Optional[Dialog] = None
        self.dialog_cb: Optional[Callable[[Any], None]] = None
        self.queue: "queue.Queue[Tuple[str, Dict[str, Any]]]" = queue.Queue()
        self.reader = KeyReader()
        self.busy = False
        self.dirty = True
        self.exit_code: Optional[int] = None
        self.size = (0, 0)
        self.spin = 0
        self.last_frame = 0.0
        self.started = time.time()
        self.activity_text = "готов к работе"
        self.activity_extra = ""
        self.step_index = 0
        self.step_tokens: Dict[str, int] = {}
        self.verbose = bool(cfg.get("ui.verbose", False))
        self.tip_index = 0
        self.tip_at = 0.0
        self.ctrl_c_at = 0.0
        self.worker: Optional[threading.Thread] = None
        self._pending_tools: List[Block] = []
        self._current: Optional[Block] = None
        self.alt_screen = False
        self.task_started_at = 0.0
        self.tasks_done = 0
        self._shown_error = ""
        self.router_thread: Optional[threading.Thread] = None
        self.router_url = ""
        self._stats_cache: Optional[Dict[str, Any]] = None
        self._stats_at = 0.0
        self.dirty_stats = True
        self._last_lines: Optional[List[str]] = None   # прошлый кадр для диф-отрисовки
        self._force_full = True
        self._log = None                                 # журнал при ELYTRIX_LOG
        self._write_ema = 0.0                            # средняя цена кадра в консоли
        self._slow_console = False

        agent.emit = self.post
        agent.confirm = self.confirm_async

    # ------------------------------------------------------------------ запуск

    def banner(self) -> None:
        """Стартовый экран: логотип и две строки сути — без стены текста."""
        ws = self.ws
        model = self.catalog.resolve(self.agent.model)
        mult = self.catalog.multiplier(model)
        self.add(KIND_LOGO, LOGO_ART)

        def tagline(theme: Theme, width: int) -> List[Line]:
            """Подзаголовок под логотипом, по центру — как стартовый экран opencode."""
            first = f"{os.path.basename(ws.root) or ws.root} · {model} ×{mult:g} · " \
                    f"режим «{self.agent.confirm_mode}»"
            second = "напишите задачу и Enter · /help — команды · " \
                     "Ctrl+Shift+C/V — копировать/вставить"
            out: List[Line] = []
            for text, role in ((first, "dim"), (second, "faint")):
                text = truncate(text, width)
                left = max(0, (width - text_width(text)) // 2)
                out.append([(" " * left, theme.style("fg")),
                            (text, theme.style(role))])
            return out

        self.add(KIND_CUSTOM, renderer=tagline)
        spend = self.state.tokens_day
        if spend:
            limit = self.gw.daily_limit
            line = f"за сегодня {human_number(spend)} зачётных токенов"
            if limit:
                line += f" из {human_number(limit)} ({round(spend * 100 / limit)}%)"
            self.add(KIND_INFO, line)
        self.add(KIND_SPACER)

    def run(self) -> int:
        self.start_screen()
        self.banner()
        self.onboard()
        log_path = os.environ.get("ELYTRIX_LOG") or ""
        self._log = None
        if log_path:
            try:
                self._log = open(log_path, "a", encoding="utf-8", buffering=1)
                self._log.write(f"\n=== запуск {time.strftime('%H:%M:%S')} ===\n")
            except OSError:
                self._log = None
        try:
            while self.exit_code is None:
                events = self._read_keys()
                for ev in events:
                    self._log_event(f"key {ev.name}" + (f" {ev.text!r}" if ev.text else ""))
                    self.on_key(ev)
                    if self.exit_code is not None:
                        break
                self.drain()
                now = time.time()
                need = self.dirty
                if self.busy and now - self.last_frame > 0.06:
                    need = True
                if now - self.tip_at > 12:
                    self.tip_index += 1
                    self.tip_at = now
                    need = True
                if need:
                    # чаще 20 кадров/с не перерисовываем: классическая консоль
                    # Windows не успевает за перерисовкой на каждое нажатие,
                    # и ввод ощущается рывками; dirty остаётся — докадрим чуть позже
                    interval = 0.05 if self._write_ema < 0.08 else 0.12
                    if self.dirty and now - self.last_frame < interval:
                        need = False
                    else:
                        self.draw()
                        self.dirty = False
        except KeyboardInterrupt:
            self.exit_code = 0
        finally:
            self._log_event("выход")
            if self._log is not None:
                try:
                    self._log.close()
                except OSError:
                    pass
                self._log = None
            self.stop_screen()
        return self.exit_code or 0

    def _log_event(self, text: str) -> None:
        """Строчка в журнал диагностики (только если задан ELYTRIX_LOG)."""
        if self._log is None:
            return
        try:
            self._log.write(f"{time.time():.3f} {text}\n")
        except OSError:
            self._log = None

    def start_screen(self) -> None:
        try:
            sys.stdout.write(ALT_ON + HIDE_CURSOR + BRACKETED_ON + CLEAR)
            sys.stdout.flush()
            self.alt_screen = True
            self._force_full = True
            self._last_lines = None
        except Exception:  # noqa: BLE001
            self.alt_screen = False
        self.reader.open()

    def stop_screen(self) -> None:
        try:
            self.reader.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            sys.stdout.write(BRACKETED_OFF + SHOW_CURSOR + (ALT_OFF if self.alt_screen else "")
                             + "\x1b[0m\n")
            sys.stdout.flush()
        except Exception:  # noqa: BLE001
            pass

    def _read_keys(self) -> List[KeyEvent]:
        try:
            return self.reader.read(0.05)
        except Exception:  # noqa: BLE001
            return []

    # ------------------------------------------------------------------ онбординг

    def onboard(self) -> None:
        """Первый запуск: спрашиваем ключ, затем — в какой папке работать."""
        if not self.gw.key:
            self.ask_key(first_run=True)
            return
        self.maybe_ask_workspace()

    def maybe_ask_workspace(self) -> None:
        """Если папку ещё не запоминали — спрашиваем (двойной клик по ELYTRIX.bat
        открывает консоль в собственной папке программы, а код пользователя обычно
        лежит в другом месте)."""
        if self.state.get("last_workspace"):
            return
        if self.ws.root == project_root():
            self.cmd_cd("")
        else:
            self.state.set("last_workspace", self.ws.root)

    def ask_key(self, first_run: bool = False) -> None:
        note = ("Ключ создаётся в кабинете https://smartapi.shop/api-keys и выглядит как "
                "sk-smart-… Он сохраняется в вашем профиле (файл с правами 600) и в "
                "переменную окружения SMARTAPI_KEY.")
        dialog = PromptDialog(
            "Ключ SmartAPI" if not first_run else "Первый запуск: ключ SmartAPI",
            hint="Вставьте ключ и нажмите Enter. Символы не отображаются — это нормально.",
            default="", secret=True, note=note,
            validate=lambda v: "" if v.strip() else "ключ не может быть пустым")
        self.open_dialog(dialog, self._on_key_entered)

    def _on_key_entered(self, value: Any) -> None:
        if not value:
            if not self.gw.key:
                self.add(KIND_ERROR, "без ключа агент работать не может: "
                                     "загрузите его командой /api")
            return
        self._set_key(value)
        self.maybe_ask_workspace()

    def _set_key(self, value: str) -> None:
        self.gw.key = value
        path = save_key(value)
        self.key_source = "file"
        self.add(KIND_INFO, f"ключ сохранён: {path or 'в переменные окружения'} · {mask_key(value)}")
        self.check_key_async()

    def cmd_api(self, arg: str) -> None:
        """/api — загрузить ключ: диалог, сам ключ или файл с ключом."""
        arg = (arg or "").strip().strip('"').strip("'")
        if not arg:
            self.ask_key()
            return
        path = arg if os.path.isabs(arg) else os.path.join(self.ws.root, arg)
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    arg = next((ln.strip() for ln in f if ln.strip()), "")
            except OSError as e:
                self.add(KIND_ERROR, f"не удалось прочитать файл с ключом: {e}")
                return
            if not arg:
                self.add(KIND_ERROR, f"в файле {path} ключ не найден (пусто)")
                return
        self._set_key(arg)

    def check_key_async(self) -> None:
        """Проверяет связь со шлюзом в фоне — интерфейс не подвисает."""
        def work() -> None:
            self.gw.warm()          # греем оба эндпоинта, пока идёт проверка
            try:
                ids = self.gw.fetch_models(timeout=10)
            except Exception as e:  # noqa: BLE001
                self.post("note", {"text": f"шлюз не ответил на проверку: {e}", "kind": "warn"})
                return
            if ids:
                added = self.catalog.add_models(ids)
                self.post("note", {"text": f"шлюз отвечает, моделей в каталоге: {len(ids)}"
                                          + (f", добавлено новых: {added}" if added else ""),
                                   "kind": "ok"})
            else:
                self.post("note", {"text": "шлюз не отдаёт каталог моделей — работаем по "
                                          "конфигу (это не ошибка)", "kind": "info"})
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------ лента

    def add(self, kind: str, text: str = "", meta: Optional[Dict[str, Any]] = None,
            renderer: Optional[Callable[[Theme, int], List[Line]]] = None) -> Block:
        block = Block(kind, text, meta, renderer)
        self.blocks.append(block)
        if len(self.blocks) > 400:
            self.blocks = self.blocks[-300:]
        self.dirty = True
        self._follow()
        return block

    def _follow(self) -> None:
        """Если пользователь не листал вверх — остаёмся прижатыми к низу."""
        if self.scroll == 0:
            return
        self.scroll = 0

    def invalidate_blocks(self) -> None:
        for block in self.blocks:
            block.touch()

    # ------------------------------------------------------------------ события агента

    def post(self, kind: str, data: Dict[str, Any]) -> None:
        """Вызывается из рабочего потока: складываем событие в очередь."""
        try:
            self.queue.put_nowait((kind, data))
        except Exception:  # noqa: BLE001
            pass

    def drain(self) -> None:
        for _ in range(500):
            try:
                kind, data = self.queue.get_nowait()
            except queue.Empty:
                return
            self.handle_event(kind, data)

    def handle_event(self, kind: str, data: Dict[str, Any]) -> None:
        if kind in ("step", "compact", "task_done", "result"):
            self.dirty_stats = True
        if kind == "text":
            self._on_text(str(data.get("text") or ""))
        elif kind == "tool_announce":
            self._on_tool_announce(str(data.get("name") or "?"))
        elif kind == "result":
            self._on_result(data)
        elif kind == "step":
            self._on_step(data)
        elif kind == "status":
            self.activity_text = str(data.get("text") or "")
            self.dirty = True
        elif kind == "compact":
            before = int(data.get("before") or 0)
            after = int(data.get("after") or 0)
            self.add(KIND_INFO, f"история сжата: {human_number(before)} → "
                                f"{human_number(after)} токенов на входе "
                                f"(−{human_number(max(0, before - after))})")
        elif kind == "error":
            self._shown_error = str(data.get("text") or "ошибка")
            self.add(KIND_ERROR, self._shown_error)
            self.activity_text = "ошибка"
        elif kind == "note":
            style_kind = str(data.get("kind") or "info")
            text = str(data.get("text") or "")
            if style_kind == "error":
                self.add(KIND_ERROR, text)
            else:
                self.add(KIND_INFO, text)
        elif kind == "dialog":
            self.open_dialog(MessageDialog(str(data.get("title") or "ELYTRIX"),
                                           str(data.get("text") or "")))
        elif kind == "confirm":
            self._open_confirm(data)
        elif kind == "task_done":
            self._on_done(data)
        elif kind == "crash":
            self.busy = False
            self.add(KIND_ERROR, str(data.get("error") or "сбой"))
            self.activity_text = "сбой"
        self.dirty = True

    def _on_text(self, piece: str) -> None:
        if self._current is None or self._current.kind != KIND_ASSISTANT or self._current.closed:
            self._current = self.add(KIND_ASSISTANT, "")
        self._current.append_text(piece)
        self._follow()

    def _on_tool_announce(self, name: str) -> None:
        if self._current is not None:
            self._current.closed = True
            self._current = None
        block = self.add(KIND_TOOL, "", {"name": name, "state": "run", "ok": True,
                                         "target": "", "summary": "выполняется"})
        self._pending_tools.append(block)
        self.activity_text = f"{Toolbox.title(name)} …"

    def _on_result(self, data: Dict[str, Any]) -> None:
        name = str(data.get("name") or "?")
        block: Optional[Block] = None
        for pending in self._pending_tools:
            if pending.meta.get("name") == name and pending.meta.get("state") == "run":
                block = pending
                break
        if block is None:
            block = self.add(KIND_TOOL, "")
        if self._current is not None:
            self._current.closed = True
            self._current = None
        if block in self._pending_tools:
            self._pending_tools.remove(block)
        block.meta.update({
            "name": name,
            "state": "done",
            "ok": bool(data.get("ok", True)),
            "target": str(data.get("path") or (data.get("args") or {}).get("command")
                          or (data.get("args") or {}).get("pattern") or ""),
            "summary": str(data.get("summary") or ""),
            "detail": str(data.get("detail") or ""),
            "diff": str(data.get("diff") or ""),
            "text": str(data.get("text") or "")[:2000],
            "elapsed": float(data.get("elapsed") or 0.0),
            "size": int(data.get("size") or 0),
        })
        block.touch()
        self.activity_text = f"{Toolbox.title(name)}: {block.meta['target'] or name}"

    def _on_step(self, data: Dict[str, Any]) -> None:
        if data.get("phase") == "start":
            self.step_index = int(data.get("index") or 1)
            self.activity_text = "думаю"
        else:
            usage = data.get("usage")
            if usage is not None:
                self.step_tokens = {"in": getattr(usage, "tokens_in", 0),
                                    "out": getattr(usage, "tokens_out", 0),
                                    "cache": getattr(usage, "cache_read", 0),
                                    "ttfb": getattr(usage, "ttfb", 0.0)}
            tools = data.get("tools") or []
            self.activity_text = "думаю" if not tools else f"{len(tools)} " + \
                plural(len(tools), "действие", "действия", "действий")

    def _on_done(self, data: Dict[str, Any]) -> None:
        report = data.get("report")
        self.busy = False
        self._pending_tools.clear()
        self._current = None
        self.tasks_done += 1
        if report is None:
            self.activity_text = "готово"
            return
        usage = getattr(report, "usage", None)
        files = list(getattr(report, "files", []) or [])
        if getattr(report, "error", ""):
            # ту же ошибку уже напечатали событием error — второй раз не надо
            if report.error != self._shown_error:
                self.add(KIND_ERROR, report.error)
            self._shown_error = ""
            self.activity_text = "ошибка"
        elif getattr(report, "cancelled", False):
            self.activity_text = "! остановлено"
            if not report.answer:
                self.add(KIND_INFO, "задача остановлена; что успело измениться — /diff, откат — /undo")
        else:
            parts = [f"готово за {seconds_text(getattr(report, 'elapsed', 0.0))}",
                     f"{report.steps} " + plural(report.steps, "шаг", "шага", "шагов")]
            if usage is not None:
                parts.append(f"вх {human_number(usage.tokens_in)} · вых {human_number(usage.tokens_out)}")
                if getattr(usage, "charged", 0):
                    parts.append(f"списано {human_number(usage.charged)} зачётных")
            if getattr(report, "squeezed_tokens", 0):
                parts.append(f"сжато {human_number(report.squeezed_tokens)}")
            self.activity_text = "✓ " + " · ".join(parts)
            if files:
                self.add(KIND_INFO, "файлы: " + ", ".join(files[:12])
                         + (f" … ещё {len(files) - 12}" if len(files) > 12 else ""))
        self.state.set("tasks_done", int(self.state.get("tasks_done", 0)) + 1)

    # ------------------------------------------------------------------ подтверждения

    def confirm_async(self, request: Any) -> str:
        """Вызывается из рабочего потока: ждём, пока пользователь ответит в диалоге."""
        answer: Dict[str, str] = {}
        done = threading.Event()
        self.post("confirm", {"request": request, "answer": answer, "done": done})
        while not done.wait(0.15):
            if self.exit_code is not None or self.agent.cancel.is_set():
                return "stop"
        return answer.get("value", "yes")

    def _open_confirm(self, data: Dict[str, Any]) -> None:
        request = data.get("request")
        answer_box = data.get("answer")
        done = data.get("done")

        def finish(value: Any) -> None:
            answer_box["value"] = value if isinstance(value, str) else "no"
            done.set()

        dialog = ConfirmDialog(tool=getattr(request, "tool", "?"),
                               summary=getattr(request, "summary", ""),
                               detail=getattr(request, "detail", ""),
                               diff=getattr(request, "diff", ""),
                               command=getattr(request, "command", ""))
        self.open_dialog(dialog, finish)

    def open_dialog(self, dialog: Dialog, callback: Optional[Callable[[Any], None]] = None) -> None:
        self.dialog = dialog
        self.dialog_cb = callback
        self.dirty = True

    def close_dialog(self, result: Any = None) -> None:
        dialog, self.dialog = self.dialog, None
        callback, self.dialog_cb = self.dialog_cb, None
        self.dirty = True
        if callback is not None:
            try:
                callback(result)
            except Exception as e:  # noqa: BLE001
                self.add(KIND_ERROR, f"сбой в диалоге: {type(e).__name__}: {e}")

    # ------------------------------------------------------------------ клавиши

    def on_key(self, ev: KeyEvent) -> None:
        self.dirty = True          # любое нажатие меняет картинку — перерисуем в этом же кадре
        if self.dialog is not None:
            if ev.name == "ctrl+shift+v":
                text, _backend = clip.paste()
                if text:
                    ev = KeyEvent("paste", text)      # вставка прямо в поле диалога
            self._dialog_key(ev)
            return
        if ev.name == "resize":
            self.dirty = True
            return
        if ev.name == "ctrl+l":
            sys.stdout.write(CLEAR)
            self._force_full = True
            self._last_lines = None
            self.dirty = True
            return
        if ev.name in ("ctrl+d",):
            if self.input.is_empty():
                self.quit()
            else:
                self.input.clear()
                self.dirty = True
            return
        if ev.name == "ctrl+c":
            self._ctrl_c()
            return
        if ev.name == "ctrl+shift+c":
            self.do_copy()
            return
        if ev.name == "ctrl+shift+v":
            if not self.busy:
                self.do_paste()
            return
        if self.busy:
            self._busy_key(ev)
            return
        self._idle_key(ev)

    def _ctrl_c(self) -> None:
        now = time.time()
        if self.busy:
            if self.agent.cancel.is_set():
                self.add(KIND_INFO, "останавливаю: жду ответа от шлюза…")
            else:
                self.agent.cancel.set()
                self.gw.close()      # закрыть сокет — блокирующее чтение умрёт сразу
                self.activity_text = "останавливаю (Esc/Ctrl+C ещё раз — немедленно)"
            self.dirty = True
            return
        if now - self.ctrl_c_at < 1.5:
            self.quit()
            return
        self.ctrl_c_at = now
        self.activity_text = "ещё раз Ctrl+C — выход"
        self.dirty = True

    # ------------------------------------------------------------------ буфер обмена

    def do_copy(self) -> None:
        """Ctrl+Shift+C / /copy: строка ввода, а если пуста — последний ответ модели."""
        text = self.input.text if not self.input.is_empty() else self._last_assistant()
        text = text.strip("\n")
        if not text.strip():
            self.activity_text = "! копировать нечего: строка пуста и ответа ещё нет"
            self.dirty = True
            return
        backend = clip.copy(text)
        self.activity_text = (f"✓ скопировано {human_number(len(text))} символов · "
                              f"буфер: {backend}")
        self.dirty = True

    def _last_assistant(self) -> str:
        for block in reversed(self.blocks):
            if block.kind == KIND_ASSISTANT and block.text.strip():
                return block.text.strip()
        return ""

    def do_paste(self) -> None:
        """Ctrl+Shift+V / /paste: вставить буфер обмена в строку ввода."""
        text, backend = clip.paste()
        if not text:
            self.activity_text = "! буфер обмена пуст"
            self.dirty = True
            return
        self.input.insert(text)
        self._refresh_completion()
        self.activity_text = (f"✓ вставлено {human_number(len(text))} символов · "
                              f"буфер: {backend}")
        self.dirty = True

    def _busy_key(self, ev: KeyEvent) -> None:
        """Пока задача работает: прокрутка, остановка — и ввод не теряется.

        Символы печатаются в строку заранее (typeahead, как в opencode): когда
        агент освободится, текст уже на месте и Enter отправит его сразу.
        """
        if ev.name == "esc":
            self._ctrl_c()
            return
        if ev.name in ("pageup", "ctrl+up"):
            self.scroll_page(-1)
            return
        if ev.name in ("pagedown", "ctrl+down"):
            self.scroll_page(1)
            return
        if ev.name == "ctrl+v":
            self.toggle_verbose()
            return
        if ev.name == "ctrl+shift+c":
            self.do_copy()
            return
        if ev.name == "ctrl+shift+v":
            self.do_paste()
            return
        if ev.name == "enter":
            if not self.input.is_empty():
                self.add(KIND_INFO, "агент работает: текст в строке, Enter отправит его, "
                                    "когда агент освободится (Esc — остановить)")
            else:
                self.add(KIND_INFO, "агент ещё работает — Esc, чтобы остановить")
            self.dirty = True
            return
        if self._input_edit(ev):
            return

    def _input_edit(self, ev: KeyEvent) -> bool:
        """Клавиши правки строки ввода — общие для покоя и typeahead."""
        name = ev.name
        if name == "char":
            self.input.insert(ev.text)
            self.input.reset_history_cursor()
            self._refresh_completion()
            return True
        if name == "paste":
            self.input.insert(ev.text)
            self._refresh_completion()
            return True
        if name in ("alt+enter", "newline", "ctrl+j"):
            self.input.newline()
            self.dirty = True
            return True
        if name == "backspace":
            self.input.backspace()
            self._refresh_completion()
            return True
        if name == "delete":
            self.input.delete()
            return True
        if name == "left":
            self.input.left()
            return True
        if name == "right":
            self.input.right()
            return True
        if name in ("home", "ctrl+a"):
            self.input.home()
            return True
        if name in ("end", "ctrl+e"):
            self.input.end()
            return True
        if name == "ctrl+u":
            self.input.kill_to_start()
            return True
        if name == "ctrl+k":
            self.input.kill_line()
            return True
        if name == "ctrl+w":
            self.input.kill_word()
            return True
        return False

    def _idle_key(self, ev: KeyEvent) -> None:
        name = ev.name
        if self.completion.active:
            if name in ("up", "ctrl+p"):
                self.completion.move(-1)
                self.dirty = True
                return
            if name in ("down", "ctrl+n"):
                self.completion.move(1)
                self.dirty = True
                return
            if name in ("tab", "enter"):
                self.completion.accept(self.input)
                self.dirty = True
                if name == "enter":
                    self.submit()
                return
            if name == "esc":
                self.completion.close()
                self.dirty = True
                return

        if name == "enter":
            self.submit()
            return
        if name == "tab":
            if self.completion.active:
                self.completion.accept(self.input)
            else:
                self._refresh_completion(force=True)
            self.dirty = True
            return
        if name == "up":
            self.input.up()
            return
        if name == "down":
            self.input.down()
            return
        if self._input_edit(ev):
            return
        if name == "esc":
            if not self.input.is_empty():
                self.input.clear()
                self.completion.close()
            self.dirty = True
            return
        if name == "pageup":
            self.scroll_page(-1)
            return
        if name == "pagedown":
            self.scroll_page(1)
            return
        if name == "ctrl+v":
            self.toggle_verbose()
            return
        if name == "ctrl+r":
            self.command("/tokens")
            return

    def _dialog_key(self, ev: KeyEvent) -> None:
        dialog = self.dialog
        if dialog is None:
            return
        width, height = terminal_size()
        area_h = max(6, height - 7)
        try:
            result = dialog.key(ev, self.theme, width, area_h)
        except Exception as e:  # noqa: BLE001
            self.close_dialog(False)
            self.add(KIND_ERROR, f"диалог сломался: {type(e).__name__}: {e}")
            return
        if result is None:
            self.dirty = True
            return
        self.close_dialog(result)

    def _refresh_completion(self, force: bool = False) -> None:
        """Обновляет подсказки: команды по «/», пути к файлам по «@»."""
        self.completion.update_command(self.input)
        if not self.completion.active:
            self.completion.update_file(self.input, self.ws)
        if force and not self.completion.active:
            self.completion.update_command(self.input)
        self.dirty = True

    def scroll_page(self, direction: int) -> None:
        _width, height = terminal_size()
        page = max(4, height - 10)
        total = self._total_lines(max(40, _width))
        self.scroll = max(0, min(max(0, total - page), self.scroll - direction * page))
        self.dirty = True

    def toggle_verbose(self) -> None:
        self.verbose = not self.verbose
        self.agent.cfg.set("ui.verbose", self.verbose)
        self.invalidate_blocks()
        self.add(KIND_INFO, f"подробный вывод {'включён' if self.verbose else 'выключен'} "
                            f"(содержимое результатов инструментов)")
        self.dirty = True

    def quit(self, code: int = 0) -> None:
        if self.busy:
            self.agent.cancel.set()
        self.exit_code = code
        self.dirty = True

    # ------------------------------------------------------------------ отправка задачи

    def submit(self) -> None:
        text = self.input.text.strip()
        if not text:
            return
        self.completion.close()
        self.input.clear()
        self.input.reset_history_cursor()
        self.input.push_history(text)
        self.scroll = 0
        if text.startswith("/"):
            self.command(text)
            return
        self.start_task(text)

    def start_task(self, text: str) -> None:
        if self.busy:
            self.add(KIND_INFO, "агент ещё работает над прошлой задачей — Esc, чтобы остановить")
            return
        self.add(KIND_USER, text)
        self.busy = True
        self.agent.cancel.clear()
        self.task_started_at = time.time()
        self.step_index = 0
        self.step_tokens = {}
        self.activity_text = "думаю"
        self.worker = threading.Thread(target=self._worker, args=(text,), daemon=True)
        self.worker.start()
        self.dirty = True

    def _worker(self, text: str) -> None:
        try:
            report = self.agent.run_task(text)
            self.post("task_done", {"report": report})
        except Cancelled:
            self.post("task_done", {"report": None})
        except GatewayError as e:
            self.post("error", {"text": str(e)})
            self.post("task_done", {"report": None})
        except Exception as e:  # noqa: BLE001
            import traceback

            self.post("crash", {"error": f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}"})
            self.post("task_done", {"report": None})

    # ------------------------------------------------------------------ команды

    def command(self, line: str) -> None:
        parts = line.strip().split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""
        handlers: Dict[str, Callable[[str], None]] = {
            "/help": self.cmd_help, "/h": self.cmd_help, "/?": self.cmd_help,
            "/model": self.cmd_model, "/models": self.cmd_models,
            "/tokens": self.cmd_tokens, "/cost": self.cmd_tokens, "/ctx": self.cmd_tokens,
            "/clear": self.cmd_clear, "/new": self.cmd_clear,
            "/compact": self.cmd_compact,
            "/diff": self.cmd_diff, "/undo": self.cmd_undo, "/revert": self.cmd_undo,
            "/tree": self.cmd_tree, "/ls": self.cmd_tree,
            "/session": self.cmd_session, "/history": self.cmd_session,
            "/steps": self.cmd_steps, "/limit": self.cmd_limit,
            "/confirm": self.cmd_confirm, "/verbose": self.cmd_verbose,
            "/api": self.cmd_api, "/key": self.cmd_api,
            "/copy": self.cmd_copy, "/paste": self.cmd_paste,
            "/prompt": self.cmd_prompt,
            "/theme": self.cmd_theme, "/cd": self.cmd_cd,
            "/doctor": self.cmd_doctor, "/router": self.cmd_router,
            "/exit": lambda a: self.quit(), "/quit": lambda a: self.quit(),
            "/q": lambda a: self.quit(),
        }
        handler = handlers.get(cmd)
        if handler is None:
            near = [name for name in handlers if name.startswith(cmd[:3])]
            self.add(KIND_INFO, f"нет команды {cmd}" + (f" — похоже на: {', '.join(near[:4])}"
                                                        if near else " · /help"))
            self.dirty = True
            return
        try:
            handler(arg)
        except Exception as e:  # noqa: BLE001
            self.add(KIND_ERROR, f"{cmd}: {type(e).__name__}: {e}")
        self.dirty = True

    # -- отдельные команды --

    def cmd_help(self, _arg: str) -> None:
        rows = ["# Команды", ""]
        for name, note in COMMANDS:
            rows.append(f"- **{name}** — {note}")
        rows += ["", "# Клавиши", "",
                 "- **Enter** — отправить задачу, **Alt+Enter** / **Ctrl+J** — перенос строки",
                 "- **Tab** — дописать команду или путь (после **@**)",
                 "- **Esc** / **Ctrl+C** — остановить задачу; дважды Ctrl+C в покое — выход",
                 "- **↑ ↓** — история задач и прокрутка ленты, **PageUp/PageDown** — листать",
                 "- **Ctrl+Shift+C / Ctrl+Shift+V** — копировать (строку или ответ) и "
                 "вставить из буфера; то же — `/copy` и `/paste`",
                 "- **Ctrl+V** — подробный вывод результатов инструментов",
                 "- **Ctrl+L** — перерисовать экран, **Ctrl+D** — выход",
                 "- **Ctrl+W / Ctrl+U / Ctrl+K** — стереть слово / до курсора / после курсора",
                 "", "# Как платить меньше токенов", "",
                 "- одна задача — одна тема: `/clear` перед новой задачей;",
                 "- называйте файлы в задаче: агент не тратит шаги на поиск;",
                 "- `/model cheap` для мелочей, сильная модель — только для сложного;",
                 "- `/compact`, если лента выросла, а задача ещё не закончена.",
                 ]
        self.open_dialog(MessageDialog("Справка ELYTRIX", "\n".join(rows)))

    def cmd_model(self, arg: str) -> None:
        if arg:
            self._apply_model(arg)
            return
        items: List[Tuple[str, Any, str]] = []
        current = self.agent.model
        for alias, info in self.catalog.aliases.items():
            model = str(info.get("model") or alias)
            note = f"×{self.catalog.multiplier(model):g} · {info.get('note', '')}"
            items.append((f"{alias} → {model}", alias, note))
        items.append(("— все модели шлюза —", "", ""))
        for model in self.catalog.all_models():
            mult = self.catalog.multiplier(model)
            note = f"×{mult:g} · {self.catalog.price_word(mult)}"
            extra = self.catalog.note(model)
            if extra:
                note += f" · {extra}"
            items.append((model, model, note))
        selected = 0
        for i, (_label, value, _note) in enumerate(items):
            if value == current:
                selected = i
                break
        self.open_dialog(ListDialog("Модель (× — коэффициент расхода баланса)", items,
                                    hint="↑↓ или цифры · Enter — выбрать · Esc — оставить как есть",
                                    selected=selected, allow_text=True),
                         lambda value: self._apply_model(str(value)) if value else None)

    def _apply_model(self, value: str) -> None:
        resolved = self.catalog.resolve(value)
        self.agent.set_model(value)
        self.cfg.set("models.default", value)
        self.state.set("model", value)
        self.add(KIND_INFO, f"модель: {resolved} ×{self.catalog.multiplier(resolved):g}"
                            f" (история очищена — за старый контекст не платим)")
        self.dirty = True

    def cmd_models(self, arg: str) -> None:
        if arg and arg.lower() not in ("reload", "update", "list"):
            self.add(KIND_INFO, "/models reload — обновить каталог шлюза")
            return
        self.add(KIND_INFO, "спрашиваю каталог моделей у шлюза…")

        def work() -> None:
            try:
                ids = self.gw.fetch_models(timeout=15)
            except Exception as e:  # noqa: BLE001
                self.post("note", {"text": f"каталог не получен: {e}", "kind": "error"})
                return
            if not ids:
                self.post("note", {"text": "шлюз не отдаёт список моделей — работаем по конфигу",
                                   "kind": "info"})
                return
            added = self.catalog.add_models(ids)
            self.post("note", {"text": f"моделей у шлюза: {len(ids)}"
                                      + (f", добавлено в меню: {added}" if added else
                                         " (все уже в меню)"), "kind": "ok"})
        threading.Thread(target=work, daemon=True).start()

    def cmd_tokens(self, _arg: str) -> None:
        stats = self.agent.stats()
        mult = stats["multiplier"]
        lines = [
            "# Следующий запрос",
            f"- контекст: **{human_number(stats['prompt_tokens'])}** токенов из "
            f"{human_number(stats['context'])} ({stats['context_used']}%)",
            f"- сообщений в истории: {stats['messages']} · задач в памяти: {stats['memory_tasks']}",
            f"- системный промпт: ~{human_number(_estimate(self.agent.system_prompt()))} токенов"
            " (дерево проекта в него не кладём — для этого есть ls)",
            "",
            "# Сессия",
            f"- вход: **{human_number(stats['tokens_in'])}** · выход: "
            f"**{human_number(stats['tokens_out'])}**",
            f"- кэш промпта прочитан: {human_number(stats['cache_read'])} токенов "
            f"({'включён' if stats['cache_enabled'] else 'выключен — шлюз не поддержал'})",
            f"- сжато истории: {human_number(stats['squeezed'])} токенов",
            f"- вызовов инструментов: {stats['tool_calls']} · шагов: {stats['steps']}",
            "",
            "# Расход",
            f"- за сегодня: **{human_number(stats['day_tokens'])}** зачётных токенов"
            + (f" из {human_number(stats['day_limit'])}" if stats["day_limit"] else " (лимит выключен)"),
            f"- текущая модель: {stats['model']} ×{mult:g} — "
            f"{self.catalog.price_word(mult)}",
        ]
        by_model = self.state.by_model()
        if by_model:
            lines += ["", "# По моделям за сегодня"]
            for model, row in sorted(by_model.items(), key=lambda kv: -kv[1].get("tokens", 0)):
                lines.append(f"- {model}: {human_number(row.get('tokens', 0))} зачётных, "
                             f"{row.get('requests', 0)} "
                             + plural(int(row.get('requests', 0)), "запрос", "запроса", "запросов"))
        lines += ["", "# Как тратить меньше",
                  "- `/clear` перед новой задачей — история не пересылается заново;",
                  "- `/compact` — сжать текущую историю;",
                  "- `/steps 8` — короче сессии;",
                  "- в задаче называйте конкретные файлы;",
                  "- `/model cheap` для мелких правок."]
        self.open_dialog(MessageDialog("Токены и расход", "\n".join(lines)))

    def cmd_clear(self, _arg: str) -> None:
        tasks = len(self.agent.memory)
        self.agent.clear()
        self.blocks = []
        self._current = None
        self._pending_tools.clear()
        self.add(KIND_INFO, f"история очищена (забыто задач: {tasks}) — следующий запрос "
                            f"уйдёт с чистого листа, это дешевле")
        self.banner()

    def cmd_compact(self, _arg: str) -> None:
        before = self.agent.prompt_tokens()
        saved = self.agent.compact(aggressive=True)
        after = self.agent.prompt_tokens()
        self.add(KIND_INFO, f"сжато: {human_number(before)} → {human_number(after)} токенов "
                            f"(−{human_number(saved)})")

    def cmd_diff(self, _arg: str) -> None:
        diff = self.ws.session_diff()
        if not diff:
            self.add(KIND_INFO, "в этой сессии файлы ещё не менялись")
            return
        self.open_dialog(MessageDialog("Изменения сессии", "```diff\n" + diff + "\n```",
                                       hint="Esc — закрыть · откатить — /undo", max_width=120))

    def cmd_undo(self, _arg: str) -> None:
        count, files = self.ws.undo()
        if not count:
            self.add(KIND_INFO, "откатывать нечего: в этой сессии правок не было")
            return
        self.add(KIND_INFO, f"откачено файлов: {count} — " + ", ".join(files[:10])
                            + (f" … ещё {len(files) - 10}" if len(files) > 10 else ""))

    def cmd_tree(self, arg: str) -> None:
        text = self.ws.ls(arg, depth=2, max_lines=200)
        self.open_dialog(MessageDialog("Файлы проекта", "```\n" + text + "\n```",
                                       markdown=True))

    def cmd_session(self, _arg: str) -> None:
        memory = self.agent.memory
        if not memory:
            self.add(KIND_INFO, "в этой сессии задач ещё не было — память пуста")
            return
        rows = ["# Память сессии", ""]
        for i, item in enumerate(memory, 1):
            rows.append(f"{i}. **{item['task']}**")
            rows.append(f"   → {item['result']}")
            rows.append("")
        rows.append("Память стоит десятки токенов на задачу: продолжения вроде «а теперь то же "
                    "во втором файле» понимаются без пересылки всей переписки. Забыть — /clear.")
        self.open_dialog(MessageDialog("Что помнит агент", "\n".join(rows)))

    def cmd_steps(self, arg: str) -> None:
        if arg.isdigit() and 1 <= int(arg) <= 200:
            self.agent.max_steps = int(arg)
            self.cfg.set("limits.max_steps", int(arg))
            self.add(KIND_INFO, f"шагов на задачу: {arg}")
        else:
            self.add(KIND_INFO, f"сейчас шагов на задачу: {self.agent.max_steps}. "
                                f"Изменить: /steps 12")

    def cmd_limit(self, arg: str) -> None:
        if arg.isdigit():
            value = int(arg)
            self.gw.daily_limit = value
            self.cfg.set("limits.daily_tokens", value)
            self.cfg.save()
            self.add(KIND_INFO, f"дневной лимит: {human_number(value) if value else 'выключен'} "
                                f"зачётных токенов (расход за сегодня "
                                f"{human_number(self.state.tokens_day)})")
        else:
            self.add(KIND_INFO, f"дневной лимит сейчас: "
                                f"{human_number(self.gw.daily_limit) if self.gw.daily_limit else 'выключен'}"
                                f". Изменить: /limit 600000, снять: /limit 0")

    def cmd_confirm(self, arg: str) -> None:
        modes = {"ask": "спрашивать на каждую правку",
                 "auto": "править сразу (откат — /undo)",
                 "readonly": "только чтение: файлы не меняются"}
        if arg in modes:
            self._set_confirm(arg)
            return
        items = [(f"{name} — {note}", name, "") for name, note in modes.items()]
        self.open_dialog(ListDialog("Режим правок", items, selected=list(modes).index(
            self.agent.confirm_mode) if self.agent.confirm_mode in modes else 0),
            lambda value: self._set_confirm(str(value)) if value else None)

    def _set_confirm(self, mode: str) -> None:
        self.agent.confirm_mode = mode
        self.cfg.set("ui.confirm", mode)
        self.cfg.save()
        self.state.set("confirm", mode)
        if mode == "auto":
            self.agent.allowed.clear()
        self.add(KIND_INFO, f"режим правок: {mode}")

    def cmd_verbose(self, arg: str) -> None:
        wanted = {"on": True, "off": False, "1": True, "0": False}.get(arg.lower())
        if wanted is None:
            self.toggle_verbose()
        elif wanted != self.verbose:
            self.toggle_verbose()

    def cmd_prompt(self, arg: str) -> None:
        """/prompt файл — большой промт из файла прямо в строку ввода."""
        if not arg:
            self.add(KIND_INFO, "/prompt <файл> — загрузить текст промта из файла "
                                "в строку ввода (правьте и жмите Enter)")
            return
        path = arg.strip()
        if not os.path.isabs(path):
            path = os.path.join(self.ws.root, path)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read(200000)
        except OSError as e:
            self.add(KIND_ERROR, f"не удалось прочитать файл: {e}")
            return
        self.input.set_text(text.strip("\n"))
        self.add(KIND_INFO,
                 f"промт из {os.path.basename(path)} в строке ввода "
                 f"({human_number(len(text))} символов) — правьте и жмите Enter")

    def cmd_copy(self, _arg: str) -> None:
        self.do_copy()

    def cmd_paste(self, _arg: str) -> None:
        self.do_paste()

    def cmd_theme(self, arg: str) -> None:
        if arg in THEME_NAMES:
            self._set_theme(arg)
            return
        items = [(name, name, _theme_note(name)) for name in THEME_NAMES]
        self.open_dialog(ListDialog("Тема оформления", items,
                                    selected=list(THEME_NAMES).index(self.theme.name)
                                    if self.theme.name in THEME_NAMES else 0),
                         lambda value: self._set_theme(str(value)) if value else None)

    def _set_theme(self, name: str) -> None:
        self.theme = Theme(name, self.theme.palette, self.theme.charset.ellipsis == "…")
        self.cfg.set("ui.theme", name)
        self.cfg.save()
        self.state.set("theme", name)
        self.invalidate_blocks()
        self.add(KIND_INFO, f"тема: {name}")

    def cmd_cd(self, arg: str) -> None:
        if arg:
            self._set_workspace(arg)
            return
        items: List[Tuple[str, Any, str]] = []
        last = str(self.state.get("last_workspace") or "")
        recent = [p for p in (self.state.get("recent_workspaces") or []) if os.path.isdir(p)]
        if last and os.path.isdir(last):
            items.append((last, last, "последняя папка"))
        for path in recent[:8]:
            if path != last:
                items.append((path, path, "недавняя"))
        items.append((os.getcwd(), os.getcwd(), "текущая папка"))
        items.append(("ввести путь…", "?", "вставить путь из проводника"))
        self.open_dialog(ListDialog(
            "Рабочая папка — где лежит ваш код?", items, allow_text=True,
            hint="↑↓ + Enter — выбрать · или впишите путь · Esc — остаться здесь"),
            self._on_workspace_choice)

    def _on_workspace_choice(self, value: Any) -> None:
        if not value:
            self.state.set("last_workspace", self.ws.root)
            self.add(KIND_INFO, f"остаёмся в папке {self.ws.root} (сменить — /cd)")
            return
        if value == "?":
            self.open_dialog(PromptDialog("Путь к папке проекта",
                                          hint=f"Сейчас: {self.ws.root} · вставьте путь "
                                               f"из проводника или напишите свой",
                                          default=""),
                             lambda v: self._set_workspace(v) if v else None)
            return
        self._set_workspace(str(value))

    def _set_workspace(self, path: str) -> None:
        target = os.path.abspath(os.path.expanduser(path.strip().strip('"').strip("'")))
        if not os.path.isdir(target):
            self.open_dialog(PromptDialog("Такой папки нет — введите путь",
                                          hint=f"Не найдено: {target}", default=target),
                             lambda v: self._set_workspace(v) if v else None)
            return
        if target == self.ws.root:
            self.state.set("last_workspace", target)
            self.add(KIND_INFO, f"уже работаем здесь: {target}")
            return
        limits = dict(self.cfg.get("economy", {}) or {})
        try:
            ws = Workspace(target, limits=limits)
        except (OSError, FileNotFoundError) as e:
            self.add(KIND_ERROR, f"не удалось открыть папку: {e}")
            return
        self.ws = ws
        self.toolbox = Toolbox(ws, limits)
        self.agent.tools = self.toolbox
        self.agent.clear()
        self.blocks = []
        self.state.set("last_workspace", target)
        recent = [p for p in (self.state.get("recent_workspaces") or []) if p != target]
        recent.insert(0, target)
        self.state.set("recent_workspaces", recent[:8])
        self.banner()

    def cmd_key(self, arg: str) -> None:
        self.cmd_api(arg)

    def cmd_doctor(self, _arg: str) -> None:
        self.add(KIND_INFO, "диагностика: ключ, шлюз, каталог моделей, лимиты…")

        def work() -> None:
            lines: List[str] = ["# Диагностика ELYTRIX", ""]
            lines += [f"- версия: {__version__} · python {sys.version.split()[0]} · "
                      f"{sys.platform}",
                      f"- терминал: {self._terminal_name()}",
                      f"- ключ: {mask_key(self.gw.key) or '(нет)'} · источник: "
                      f"{self.key_source or 'не задан'}",
                      f"- шлюз (Anthropic): {self.gw.base_url}",
                      f"- шлюз (OpenAI): {self.gw.oai_url}",
                      f"- рабочая папка: {self.ws.root}",
                      f"- модель: {self.catalog.resolve(self.agent.model)} "
                      f"×{self.catalog.multiplier(self.catalog.resolve(self.agent.model)):g}",
                      ""]
            try:
                ids = self.gw.fetch_models(timeout=12)
            except Exception as e:  # noqa: BLE001
                ids = []
                lines.append(f"- каталог моделей: **не получен** ({type(e).__name__}: {e})")
            if ids:
                added = self.catalog.add_models(ids)
                lines.append(f"- каталог моделей: получен, {len(ids)} шт."
                             + (f" (добавлено новых: {added})" if added else ""))
                lines.append(f"- первые: {', '.join(ids[:8])}")
            ok, detail = self.gw.probe(self.agent.model, max_tokens=8)
            lines.append(f"- контрольный запрос: {'**прошёл**' if ok else '**не прошёл**'} — {detail}")
            lines.append(f"- кэш промпта: {'поддерживается' if self.gw.cache_supported else 'шлюз отверг пометки'}"
                         f" · настройка: {'вкл' if self.gw.cache_enabled else 'выкл'}")
            limit = self.gw.daily_limit
            lines.append(f"- расход за сегодня: {human_number(self.state.tokens_day)}"
                         + (f" из {human_number(limit)}" if limit else " (лимит выключен)"))
            lines.append(f"- состояние: {self.state.path}")
            lines.append(f"- журнал сессий: {os.path.join(self.ws.root, '.elytrix')}")
            self.post("dialog", {"title": "Диагностика", "text": "\n".join(lines)})
        threading.Thread(target=work, daemon=True).start()

    def _terminal_name(self) -> str:
        """Какой терминал нас рисует: от этого зависит плавность отрисовки."""
        if os.name != "nt":
            return os.environ.get("TERM_PROGRAM") or os.environ.get("TERM") or "posix"
        if os.environ.get("WT_SESSION"):
            return "Windows Terminal"
        if os.environ.get("ConEmuPID"):
            return "ConEmu"
        return ("классическая консоль (conhost) — отрисовка медленнее, чем в "
                "Windows Terminal")

    def cmd_router(self, arg: str) -> None:
        """Поднимает OpenAI-совместимый шлюз для редакторов (Cline, Continue, opencode)."""
        from .router import serve_in_thread

        if arg.lower() == "stop":
            httpd = getattr(self, "router_httpd", None)
            if httpd is None:
                self.add(KIND_INFO, "роутер не запущен")
                return
            try:
                httpd.shutdown()
            except Exception:  # noqa: BLE001
                pass
            self.router_httpd = None
            self.router_thread = None
            self.add(KIND_INFO, "роутер остановлен")
            return
        if self.router_thread and self.router_thread.is_alive():
            self.add(KIND_INFO, f"роутер уже работает: {self.router_url}")
            return
        port = int(arg) if arg.isdigit() else int(self.cfg.get("router.port", 8789))
        try:
            httpd, thread, url = serve_in_thread(self.cfg, self.catalog, self.state,
                                                 self.gw, port=port)
        except OSError as e:
            self.add(KIND_ERROR, f"роутер не поднялся: {e}")
            return
        self.router_thread = thread
        self.router_httpd = httpd
        self.router_url = url
        self.add(KIND_INFO, f"роутер для редакторов: {url}/v1 · модель — любая из /model · "
                            f"остановить — /router stop")

    # ------------------------------------------------------------------ отрисовка

    def _total_lines(self, width: int) -> int:
        total = 0
        for block in self.blocks:
            total += max(1, len(block.lines(self.theme, width, self.verbose)))
        return total

    def render_blocks(self, width: int, height: int) -> List[Line]:
        all_lines: List[Line] = []
        for block in self.blocks:
            all_lines.extend(block.lines(self.theme, width, self.verbose))
        if not all_lines:
            all_lines = [[("", self.theme.style("fg"))]]
        total = len(all_lines)
        if self.scroll == 0:
            window = all_lines[-height:] if total > height else all_lines
        else:
            end = max(0, total - self.scroll)
            start = max(0, end - height)
            window = all_lines[start:end]
        if len(window) < height:
            window = [[("", self.theme.style("fg"))]] * (height - len(window)) + window
        if self.scroll > 0:
            below = self.scroll
            above = max(0, total - self.scroll - len(window))
            note = f"↑ ещё {above} · ↓ ещё {below} (PageDown — к концу)"
            window = window[:-1] + [[("  " + truncate(note, width - 2),
                                      self.theme.style("faint"))]]
        return window

    def input_box(self, width: int) -> Tuple[List[Line], Optional[Tuple[int, int]]]:
        """Рамка поля ввода. Второе значение — (строка, колонка) курсора относительно
        строки активности (0 = сама строка активности)."""
        cs = self.theme.charset
        border = self.theme.style("border_active" if self.busy else "border")
        prompt_style = self.theme.style("accent", bold=True)
        text_style = self.theme.style("fg")
        inner = max(10, width - 8)
        max_rows = 6

        physical: List[Tuple[int, Line]] = []
        for li, line_text in enumerate(self.input.lines):
            wrapped = wrap_line([(line_text, text_style)], inner) or [[("", text_style)]]
            for wl in wrapped:
                physical.append((li, wl))
        if not physical:
            physical = [(0, [("", text_style)])]

        # где физически стоит курсор
        target = text_width(self.input.lines[self.input.row][:self.input.col])
        cursor_phys, col_in, acc = 0, 0, 0
        for idx, (li, wl) in enumerate(physical):
            if li != self.input.row:
                continue
            row_w = sum(text_width(t) for t, _ in wl)
            if acc + row_w >= target:
                cursor_phys, col_in = idx, target - acc
                break
            acc += row_w
        else:
            for idx, (li, wl) in enumerate(physical):
                if li == self.input.row:
                    cursor_phys = idx
                    col_in = sum(text_width(t) for t, _ in wl)

        start = 0
        if len(physical) > max_rows:
            start = max(0, min(cursor_phys - max_rows + 1, len(physical) - max_rows))
        window = physical[start:start + max_rows]

        rows: List[Line] = []
        rows.append([(" " + cs.tl + cs.h * max(0, width - 4) + cs.tr, border)])
        for li, wl in window:
            rows.append([("  ", text_style), (cs.v + " ", border),
                         ("> " if li == 0 else "  ", prompt_style if li == 0 else text_style)]
                        + wl)
        hint = ("Esc — остановить" if self.busy else
                "Enter — отправить · Alt+Enter — строка · /help")
        bottom = " " + cs.bl + cs.h * 2 + f" {hint} "
        bottom += cs.h * max(0, width - 5 - text_width(hint)) + cs.br
        rows.append([(truncate(bottom, width), border)])
        cursor_rc = (2 + (cursor_phys - start), 6 + col_in)
        return rows, cursor_rc

    def completion_popup(self, width: int) -> List[Line]:
        if not self.completion.active or not self.completion.items:
            return []
        border = self.theme.style("border_active")
        rows: List[Line] = []
        items = self.completion.items
        start = max(0, min(self.completion.index - 4, len(items) - 7))
        for i in range(start, min(len(items), start + 7)):
            label, _insert, note = items[i]
            active = i == self.completion.index
            style = self.theme.style("accent", bold=True) if active else self.theme.style("fg")
            row: Line = [("  ", self.theme.style("fg")), (truncate(label, 26), style)]
            if note:
                row.append(("  ", self.theme.style("fg")))
                row.append((truncate(note, max(10, width - 40)), self.theme.style("dim")))
            rows.append(row)
        return rows

    def draw(self) -> None:
        width, height = terminal_size()
        if (width, height) != self.size:
            self.size = (width, height)
            self.invalidate_blocks()
            self._force_full = True
        if width < 40 or height < 12:
            self._draw_too_small(width, height)
            self._force_full = True
            self._last_lines = None
            return

        model = self.catalog.resolve(self.agent.model)
        short_model = model.split("/")[-1]
        head_right = [
            (f"{truncate(short_model, 24)} ×{self.catalog.multiplier(model):g}", "accent2"),
            (truncate(os.path.basename(self.ws.root) or self.ws.root, 22), "dim"),
            (self.agent.confirm_mode, "warn" if self.agent.confirm_mode == "ask" else "ok"),
        ]
        rows: List[Line] = header(self.theme, width, "ELYTRIX", __version__, head_right)

        input_rows, cursor_rc = self.input_box(width)
        act_row = activity(self.theme, width, self.busy, self.spin,
                           self.activity_text, self._activity_extra())
        stats = self._stats()
        status = status_bar(self.theme, width, self._status_parts(stats),
                            self._day_fraction(), self._day_text())

        fixed = len(rows) + 1 + len(input_rows) + 1
        body_h = max(3, height - fixed)
        body = self.render_blocks(width, body_h)
        rows.extend(body)

        # подсказки автодополнения — поверх последних строк ленты
        popup = self.completion_popup(width)
        if popup:
            top = len(rows) - len(popup)
            rows = self._overlay(rows, popup, top, 2, width)

        rows.append(act_row)
        rows.extend(input_rows)
        rows.append(status)

        # диалог — по центру ленты
        self._dialog_placement = None
        if self.dialog is not None:
            try:
                dialog_rows, _h = self.dialog.render(self.theme, width, body_h)
            except Exception:  # noqa: BLE001
                dialog_rows = []
            if dialog_rows:
                box_w = max(sum(text_width(t) for t, _ in r) for r in dialog_rows)
                top = max(2, min(len(rows) - len(input_rows) - 2,
                                 2 + (body_h - len(dialog_rows)) // 2))
                left = max(0, (width - box_w) // 2)
                self._dialog_placement = (top, left)
                rows = self._overlay(rows, dialog_rows, top, left, width)

        self._emit(rows[:height], width, cursor_rc, len(rows) - len(input_rows) - 1)
        self.last_frame = time.time()
        self.spin += 1

    def _emit(self, rows: List[Line], width: int, cursor_rc: Optional[Tuple[int, int]],
              cursor_base: int) -> None:
        """Дифференциальный вывод: перерисовываются только изменившиеся строки.

        Полная перерисовка всего кадра на каждое нажатие — это мерцание на
        классической консоли Windows и лишние десятки килобайт в канал; здесь
        же кадр «доедает» только то, что реально изменилось (строка ввода,
        активность, новая строка ленты).
        """
        palette = self.theme.palette
        lines = [pad(row, width, palette) for row in rows]
        last = self._last_lines
        forced = self._force_full or last is None or len(last) != len(lines)
        out: List[str] = []
        if forced:
            out.append(HOME)
            out.append(ERASE_DOWN)
        for i, ln in enumerate(lines):
            if forced or last[i] != ln:
                out.append(move(i + 1, 1))
                out.append(ln)
                out.append("\x1b[K")
                if i != len(lines) - 1:
                    out.append("\r\n")   # кроме последней строки: иначе экран уедет
        self._last_lines = lines
        self._force_full = False
        cursor_at = None
        if self.dialog is not None:
            cursor_at = self._dialog_cursor(rows, width, body_top=0)
        elif cursor_rc is not None:
            cursor_at = (cursor_base + cursor_rc[0], cursor_rc[1])
        if cursor_at is not None:
            row, col = cursor_at
            if 1 <= row <= len(rows):
                out.append(move(row, max(1, col + 1)))
                out.append(SHOW_CURSOR)
        out.append("\x1b[0m")
        self._log_event(f"draw {sum(len(p) for p in out)} байт")
        t0 = time.time()
        try:
            sys.stdout.write("".join(out))
            sys.stdout.flush()
        except (BrokenPipeError, ValueError):
            self.exit_code = 0
        dt = time.time() - t0
        self._write_ema = dt if not self._write_ema else 0.7 * self._write_ema + 0.3 * dt
        if self._write_ema > 0.08 and not self._slow_console:
            # консоль не успевает рисовать (conhost на слабой машине): сами
            # снижаем темп кадров, чтобы ввод не стоял в очереди на отрисовку
            self._slow_console = True
            self.add(KIND_INFO,
                     f"консоль рисует кадр ~{int(self._write_ema * 1000)} мс — снижаю темп "
                     "перерисовки; в Windows Terminal будет заметно плавнее "
                     "(какой терминал обнаружен — /doctor)")

    def _dialog_cursor(self, rows: List[Line], width: int, body_top: int) -> Optional[Tuple[int, int]]:
        """Курсор для диалога ввода (PromptDialog): где мигает каретка."""
        dialog = self.dialog
        pos = getattr(dialog, "cursor_pos", None)
        placement = getattr(self, "_dialog_placement", None)
        if not pos or not placement:
            return None
        top, left = placement
        row_index, col_index = pos
        row_index -= int(getattr(dialog, "scroll", 0) or 0)
        if row_index < 0:
            return None
        return (top + 1 + row_index, left + 3 + col_index)

    def _overlay(self, rows: List[Line], overlay: List[Line], top: int, left: int,
                 width: int) -> List[Line]:
        out = list(rows)
        for i, orow in enumerate(overlay):
            index = top + i
            if index < 0 or index >= len(out):
                continue
            base = out[index]
            ow = sum(text_width(t) for t, _ in orow)
            prefix_w = min(left, max(0, width - ow))
            filler = max(0, width - prefix_w - ow)
            out[index] = ([(" " * prefix_w, self.theme.style("fg"))]
                          + orow
                          + [(" " * filler, self.theme.style("fg"))])
        return out

    def _draw_too_small(self, width: int, height: int) -> None:
        message = f"окно слишком маленькое ({width}×{height}) — нужно хотя бы 40×12"
        try:
            sys.stdout.write(HOME + ERASE_DOWN + message + "\r\n")
            sys.stdout.flush()
        except Exception:  # noqa: BLE001
            pass

    # -- строки статуса --

    def _activity_extra(self) -> str:
        parts: List[str] = []
        if self.busy:
            elapsed = time.time() - self.task_started_at
            parts.append(f"шаг {self.step_index}/{self.agent.max_steps}")
            parts.append(seconds_text(elapsed))
            if self.step_tokens:
                parts.append(f"вх {human_number(self.step_tokens.get('in', 0))}")
                if self.step_tokens.get("cache"):
                    parts.append(f"кэш {human_number(self.step_tokens['cache'])}")
                if self.step_tokens.get("ttfb"):
                    parts.append(f"отклик {self.step_tokens['ttfb']:.1f}с")
        else:
            parts.append(TIPS[self.tip_index % len(TIPS)])
        return " · ".join(parts)

    def _stats(self) -> Dict[str, Any]:
        """Статистика с кэшем на полсекунды: считать токены истории 30 раз в секунду дорого."""
        now = time.time()
        if self._stats_cache is not None and now - self._stats_at < 0.5 and not self.dirty_stats:
            return self._stats_cache
        stats = self.agent.stats()
        stats["tokens_in"] = self.gw.session.tokens_in
        stats["tokens_out"] = self.gw.session.tokens_out
        self._stats_cache, self._stats_at, self.dirty_stats = stats, now, False
        return stats

    def _status_parts(self, stats: Dict[str, Any]) -> List[Tuple[str, str]]:
        parts = [
            (f"ctx {stats.get('context_used', 0)}%", "dim"),
            (f"вх {human_number(stats.get('tokens_in', 0))}", "fg"),
            (f"вых {human_number(stats.get('tokens_out', 0))}", "fg"),
        ]
        if stats.get("cache_read"):
            parts.append((f"кэш {human_number(stats['cache_read'])}", "ok"))
        if self.state.requests_day:
            parts.append((f"{self.state.requests_day} "
                          + plural(self.state.requests_day, "запрос", "запроса", "запросов")
                          + " за день", "faint"))
        if not self.busy:
            parts.append((f"×{stats.get('multiplier', 1):g}", "accent2"))
        return parts

    def _day_fraction(self) -> Optional[float]:
        limit = self.gw.daily_limit
        if not limit:
            return None
        return min(1.0, self.state.tokens_day / limit)

    def _day_text(self) -> str:
        limit = self.gw.daily_limit
        if not limit:
            return f"{human_number(self.state.tokens_day)} (без лимита)"
        return f"{human_number(self.state.tokens_day)}/{human_number(limit)}"

    def set_title(self, text: str) -> None:
        try:
            sys.stdout.write(f"\x1b]0;{text}\x07")
            sys.stdout.flush()
        except Exception:  # noqa: BLE001
            pass


def _theme_note(name: str) -> str:
    return {"dark": "тёмная, по умолчанию",
            "night": "мягкие пастельные цвета",
            "light": "для светлого терминала",
            "mono": "без цвета — только яркость"}.get(name, "")


def _estimate(text: str) -> int:
    from .gateway import estimate_tokens

    return estimate_tokens(text)


# ---------------------------------------------------------------------------
# Плоский режим (вывод не в консоль)
# ---------------------------------------------------------------------------


class PlainUI:
    """Тот же агент без полноэкранной отрисовки: для `elytrix run «задача»` и для файла.

    Печатает ответ модели потоком, по одной строке на инструмент, в конце — итог.
    """

    def __init__(self, agent: Any, theme: Theme, stream: bool = True):
        self.agent = agent
        self.theme = theme
        self.stream = stream
        self._last_tool = ""
        agent.emit = self.emit
        agent.confirm = self.confirm

    def emit(self, kind: str, data: Dict[str, Any]) -> None:
        if kind == "text":
            sys.stdout.write(data.get("text") or "")
            sys.stdout.flush()
        elif kind == "result":
            mark = "✓" if data.get("ok") else "✗"
            print(f"\n  {mark} {data.get('name')} {data.get('target') or ''} · "
                  f"{data.get('summary') or ''}")
        elif kind == "error":
            print(f"\n  ОШИБКА: {data.get('text')}")
        elif kind == "compact":
            print(f"\n  · история сжата: −{human_number(int(data.get('saved') or 0))} токенов")

    def confirm(self, request: Any) -> str:
        print(f"\n  ? {request.summary}")
        if request.diff:
            print("\n".join("    " + ln for ln in request.diff.splitlines()[:40]))
        try:
            answer = input("  применить? [y/N/a=всегда] ").strip().lower()
        except EOFError:
            return "no"
        if answer in ("a", "always", "в"):
            return "always"
        return "yes" if answer in ("y", "yes", "д", "да") else "no"

    def run_task(self, task: str) -> Any:
        report = self.agent.run_task(task)
        if report.answer and not self.stream:
            print(report.answer)
        usage = report.usage
        print(f"\n  итог: шагов {report.steps} · вх {human_number(usage.tokens_in)} · "
              f"вых {human_number(usage.tokens_out)} · списано {human_number(usage.charged)} "
              f"зачётных · {seconds_text(report.elapsed)}")
        if report.files:
            print("  файлы: " + ", ".join(report.files))
        if report.error:
            print("  ошибка: " + report.error)
        return report
