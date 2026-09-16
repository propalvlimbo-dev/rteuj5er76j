# -*- coding: utf-8 -*-
"""Цикл агента: задача -> шаги с инструментами -> ответ, плюс сжатие контекста.

Главная статья расхода у любого агента — не ответы модели, а история, которая
пересылается заново на каждом шаге. Поэтому здесь:

    · системный промпт ~250 токенов: без дерева проекта и без простыней правил
      (для осмотра есть инструмент ls — он нужен один раз, а не в каждом запросе);
    · результаты инструментов обрезаются по бюджету сразу, как получены;
    · старые результаты заменяются одной строкой-пометкой (файл уже на диске —
      держать его содержимое в контексте незачем);
    · при превышении порога история сжимается: остаётся системный промпт, задача,
      «журнал» сделанного (собирается локально, без платного запроса к модели)
      и несколько последних шагов;
    · память сессии — по две строки на прошлую задачу, чтобы «добавь ещё кнопку»
      понималось без повторов;
    · prompt caching (gateway) — неизменная часть контекста тарифицируется как кэш.

Нативные инструменты: ответ без tool_use = задача закончена, отдельный инструмент
``final`` не нужен (это минус один круг и минус токены на его описание).
"""

from __future__ import annotations

import json
import os
import platform
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple

from .config import Catalog, Config, State
from .gateway import Cancelled, GatewayError, SmartAPI, Turn, Usage, estimate_tokens, messages_tokens
from .tools import Toolbox, ToolResult, TOOL_SCHEMAS

#: сколько символов результата оставляем в истории после сжатия
SQUEEZE_CHARS = 160
#: сколько задач сессии держим в памяти
MEMORY_TASKS = 6
MEMORY_TASK_CHARS = 220
MEMORY_RESULT_CHARS = 320

SYSTEM_TEMPLATE = """Ты ELYTRIX — инженер-программист, работающий прямо в файлах пользователя.
Папка: {root}
Среда: {os} · {date}
Проект: {fingerprint}

КАК РАБОТАТЬ
1. Осмотрись (ls, read, grep), пойми устройство кода — и действуй.
2. Правь точечно через edit. write — только новый файл или полная перепись.
3. Нужного файла нет — создай его (write). Отсутствие файла не повод останавливать задачу.
4. Есть тесты или сборка — запусти (bash) и исправь ошибки.
5. Независимые действия вызывай несколькими инструментами в одном ответе — это быстрее.
6. Сделал — ответь обычным текстом без инструментов: короткий итог по-русски
   (что изменено, какие файлы, как проверить).

ЭКОНОМИЯ ТОКЕНОВ (пользователь платит за каждый шаг)
· История пересылается заново каждый шаг: рассуждай в одну-две строки, не пересказывай файлы.
· Большой файл читай диапазоном (offset/limit), а не целиком; уже прочитанное не перечитывай.
· Папки создаются сами при write (родители автоматически) — после записи файл обратно не читай.
· В чат не дублируй код из write: итог — две-три строки, код живёт в файлах.
· Вывод команд не цитируй — только вывод и решение.
· Лимит на задачу: {max_steps} шагов. Решил задачу — заканчивай сразу.

БЕЗОПАСНОСТЬ
· Пиши только внутри рабочей папки. Секреты (.env, *.key, id_rsa) не читай и не правь.
· Разрушительные команды (rm -rf, format, push --force) не выполняй.
· Не выдумывай содержимое файлов: правя файл, опирайся на то, что прочитал.
{memory}"""

TEXT_PROTOCOL = """

РЕЖИМ БЕЗ ИНСТРУМЕНТОВ (шлюз их не поддержал): отвечай строго одним JSON-объектом.
Действие: {"thought":"зачем","tool":"read","args":{"path":"main.py"}}
Доступно: ls{path?,depth?}, read{path,offset?,limit?}, grep{pattern,path?,glob?,i?},
write{path,content}, edit{path,old,new,all?}, bash{command}
Готово: {"thought":"итог","done":true,"answer":"что сделано"}
Ничего кроме JSON не пиши."""


@dataclass
class ConfirmRequest:
    """Запрос подтверждения правки или команды — интерфейс рисует по нему диалог."""

    tool: str
    summary: str
    detail: str = ""
    diff: str = ""
    path: str = ""
    command: str = ""
    args: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StepInfo:
    index: int
    usage: Usage
    tools: List[str] = field(default_factory=list)
    text_len: int = 0


@dataclass
class Report:
    """Итог одной задачи."""

    answer: str = ""
    steps: int = 0
    files: List[str] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    cached_tokens: int = 0
    cancelled: bool = False
    error: str = ""
    squeezed_tokens: int = 0
    tool_calls: int = 0
    elapsed: float = 0.0


class Agent:
    """Агент: держит историю, гоняет шаги, сжимает контекст, спрашивает подтверждения."""

    #: куда интерфейс подписывается на события
    EVENT_TEXT = "text"
    EVENT_TOOL = "tool"
    EVENT_RESULT = "result"
    EVENT_STEP = "step"
    EVENT_STATUS = "status"
    EVENT_COMPACT = "compact"

    def __init__(self, gateway: SmartAPI, toolbox: Toolbox, cfg: Config,
                 catalog: Catalog, state: State,
                 emit: Optional[Callable[[str, Dict[str, Any]], None]] = None,
                 confirm: Optional[Callable[[ConfirmRequest], str]] = None):
        self.gw = gateway
        self.tools = toolbox
        self.cfg = cfg
        self.catalog = catalog
        self.state = state
        self.emit = emit or (lambda kind, data: None)
        self.confirm = confirm or (lambda req: "yes")
        self.model = catalog.default
        self.max_steps = int(cfg.get("limits.max_steps", 24))
        self.confirm_mode = str(cfg.get("ui.confirm", "ask"))      # ask | auto | readonly
        self.allowed: set = set()                                  # инструменты, разрешённые навсегда
        self.messages: List[Dict[str, Any]] = []
        self.memory: List[Dict[str, str]] = []
        self.journal: List[str] = []
        self.text_protocol = False
        self.cancel = threading.Event()
        self.busy = False
        self.squeezed_total = 0
        self.steps_history: List[StepInfo] = []
        self.last_task = ""
        self.compact_threshold = float(cfg.get("economy.compact_at", 0.55))

    # ------------------------------------------------------------------ сервис

    def _send(self, kind: str, **data: Any) -> None:
        try:
            self.emit(kind, data)
        except Exception:  # noqa: BLE001  интерфейс не должен ронять агента
            pass

    def system_prompt(self) -> str:
        memory = ""
        if self.memory:
            lines = ["", "СЕССИЯ (прошлые задачи этого окна — продолжения относятся к ним):"]
            for item in self.memory[-MEMORY_TASKS:]:
                lines.append(f"· {item['task']} → {item['result']}")
            memory = "\n".join(lines)
        prompt = SYSTEM_TEMPLATE.format(
            root=self.tools.ws.root,
            os=f"{platform.system()} {platform.release()} · python {platform.python_version()}",
            date=date.today().isoformat(),
            fingerprint=self.tools.ws.fingerprint() or "(пусто)",
            max_steps=self.max_steps,
            memory=memory,
        )
        if self.text_protocol:
            prompt += TEXT_PROTOCOL
        return prompt

    def prompt_tokens(self) -> int:
        return messages_tokens(self.messages, self.system_prompt(), TOOL_SCHEMAS)

    def context_budget(self) -> int:
        """Порог сжатия: доля контекста модели, после которой историю пора ужимать."""
        ctx = self.catalog.context(self.catalog.resolve(self.model))
        return max(4000, int(ctx * self.compact_threshold))

    def clear(self, keep_memory: bool = False) -> None:
        self.messages = []
        self.journal = []
        self.steps_history = []
        if not keep_memory:
            self.memory = []
        self.squeezed_total = 0

    def set_model(self, model: str) -> str:
        self.model = model or self.catalog.default
        # контекст другой модели стоит других денег — старую историю не тащим
        self.clear(keep_memory=True)
        return self.catalog.resolve(self.model)

    # ------------------------------------------------------------------ задача

    def run_task(self, task: str) -> Report:
        """Одна задача пользователя: сколько нужно шагов, столько и сделаем."""
        report = Report()
        self.last_task = task
        self.busy = True
        self.cancel.clear()
        t0 = time.time()
        touched_before = set(self.tools.ws.touched)
        session_before = Usage(self.gw.session.tokens_in, self.gw.session.tokens_out,
                               0, 0, self.gw.session.charged)

        if not self.messages:
            self.messages = []
        self.messages.append({"role": "user",
                              "content": [{"type": "text", "text": task.strip()}]})
        self._send(self.EVENT_STATUS, text="думаю")

        try:
            for step in range(1, self.max_steps + 1):
                if self.cancel.is_set():
                    report.cancelled = True
                    break
                self._auto_compact()
                try:
                    turn = self._step(step)
                except Cancelled:
                    report.cancelled = True
                    break
                except GatewayError as e:
                    report.error = str(e)
                    self._send("error", text=str(e))
                    break

                self._absorb(turn, step)
                report.steps = step
                if not turn.tool_calls:
                    report.answer = turn.text.strip()
                    break
                if self.cancel.is_set():
                    report.cancelled = True
                    break
                stop = self._execute_tools(turn, step)
                if stop:
                    report.answer = turn.text.strip() or "Остановлено пользователем."
                    report.cancelled = True
                    break
            else:
                report.answer = ("Достигнут предел шагов ({n}). Что успел — сделал; "
                                 "продолжить: «продолжай» или подними лимит: /steps {m}"
                                 .format(n=self.max_steps, m=self.max_steps + 8))
        finally:
            self.busy = False

        report.elapsed = time.time() - t0
        report.files = sorted(set(self.tools.ws.touched) - touched_before)
        report.usage = Usage(
            tokens_in=self.gw.session.tokens_in - session_before.tokens_in,
            tokens_out=self.gw.session.tokens_out - session_before.tokens_out,
            cache_read=self.gw.session.cache_read,
            charged=self.gw.session.charged - session_before.charged,
            elapsed=report.elapsed,
        )
        report.cached_tokens = self.gw.session_cache_read
        report.squeezed_tokens = self.squeezed_total
        report.tool_calls = sum(len(s.tools) for s in self.steps_history)
        self._remember(task, report)
        return report

    def _step(self, step: int) -> Turn:
        """Один запрос к модели (со стримингом текста в интерфейс)."""
        self.messages = sanitize_history(self.messages)
        self._send(self.EVENT_STEP, index=step, phase="start")
        acc = {"n": 0}

        def on_text(piece: str) -> None:
            acc["n"] += len(piece)
            self._send(self.EVENT_TEXT, text=piece, total=acc["n"])

        def on_tool(name: str, info: Dict[str, Any]) -> None:
            if info.get("start"):
                self._send("tool_announce", name=name)

        tools = None if self.text_protocol else TOOL_SCHEMAS
        try:
            note = lambda t: self._send("note", text=t, kind="warn")  # noqa: E731
            turn = self.gw.chat(self.model, self.system_prompt(), self.messages,
                                tools=tools, on_text=on_text, on_tool=on_tool,
                                cancel=self.cancel, on_note=note)
        except GatewayError as e:
            if not self.text_protocol and _tools_rejected(e):
                # шлюз не поддержал инструменты — переходим на текстовый протокол
                self.text_protocol = True
                self._send(self.EVENT_STATUS, text="шлюз без tools — переключаюсь на JSON-протокол")
                turn = self.gw.chat(self.model, self.system_prompt(), self.messages,
                                    tools=None, on_text=on_text, cancel=self.cancel,
                                    on_note=note)
                parsed = parse_text_action(turn.text)
                if parsed:
                    from .gateway import ToolCall
                    if parsed.get("done"):
                        turn.text = str(parsed.get("answer") or turn.text)
                        turn.tool_calls = []
                    else:
                        turn.tool_calls = [ToolCall(id=f"txt_{step}", name=str(parsed.get("tool")),
                                                    args=dict(parsed.get("args") or {}))]
            else:
                raise
        self._send(self.EVENT_STEP, index=step, phase="done", usage=turn.usage,
                   tools=[c.name for c in turn.tool_calls], text_len=len(turn.text))
        self.steps_history.append(StepInfo(step, turn.usage,
                                           [c.name for c in turn.tool_calls], len(turn.text)))
        return turn

    def _absorb(self, turn: Turn, step: int) -> None:
        """Кладёт ответ модели в историю в родном для шлюза формате."""
        blocks: List[Dict[str, Any]] = []
        if turn.text.strip():
            blocks.append({"type": "text", "text": turn.text})
        for call in turn.tool_calls:
            blocks.append({"type": "tool_use", "id": call.id or f"call_{step}",
                           "name": call.name, "input": call.args})
        if not blocks:
            blocks = [{"type": "text", "text": ""}]
        self.messages.append({"role": "assistant", "content": blocks})

    def _execute_tools(self, turn: Turn, step: int) -> bool:
        """Выполняет инструменты ответа. Возвращает True, если задачу надо прервать.

        Независимые чтения идут параллельно (быстрее), правки — последовательно и
        только после подтверждения (безопаснее).
        """
        calls = turn.tool_calls
        results: List[Tuple[Any, ToolResult]] = []
        read_batch = [c for c in calls if not Toolbox.mutating(c.name)]
        write_batch = [c for c in calls if Toolbox.mutating(c.name)]
        aborted = False

        if read_batch:
            if len(read_batch) > 1:
                with ThreadPoolExecutor(max_workers=min(4, len(read_batch))) as pool:
                    futures = [(c, pool.submit(self.tools.run, c.name, c.args)) for c in read_batch]
                    for call, future in futures:
                        results.append((call, future.result()))
            else:
                for call in read_batch:
                    results.append((call, self.tools.run(call.name, call.args)))

        for call in write_batch:
            if self.cancel.is_set():
                results.append((call, ToolResult(name=call.name, ok=False,
                                                 text="Остановлено пользователем.",
                                                 summary="отменено")))
                aborted = True
                continue
            decision = self._ask(call)
            if decision == "no":
                results.append((call, ToolResult(
                    name=call.name, ok=False,
                    text=("Пользователь отклонил это действие. Предложи другой вариант "
                          "или спроси, что именно не так."),
                    summary="отклонено пользователем")))
                continue
            if decision == "stop":
                results.append((call, ToolResult(name=call.name, ok=False,
                                                 text="Задача остановлена пользователем.",
                                                 summary="стоп")))
                aborted = True
                continue
            results.append((call, self.tools.run(call.name, call.args)))

        # порядок результатов должен совпадать с порядком tool_use в ответе модели
        by_id = {id(call): (call, res) for call, res in results}
        ordered = [by_id[id(c)] for c in calls if id(c) in by_id]

        blocks: List[Dict[str, Any]] = []
        for call, res in ordered:
            self._journal(call, res)
            self._send(self.EVENT_RESULT, name=res.name, ok=res.ok, summary=res.summary,
                       detail=res.detail, diff=res.diff, path=res.path, size=res.size,
                       elapsed=res.elapsed, args=_redact(call.args), text=res.text)
            blocks.append({"type": "tool_result", "tool_use_id": call.id or "call_0",
                           "content": res.text, "is_error": not res.ok})
        self.messages.append({"role": "user", "content": blocks})
        return aborted

    def _ask(self, call: Any) -> str:
        """Спрашивает разрешение на правку/команду. yes | no | stop."""
        name = call.name
        if self.confirm_mode == "auto" or name in self.allowed:
            return "yes"
        if self.confirm_mode == "readonly":
            self._send(self.EVENT_STATUS,
                       text=f"режим «только чтение»: {name} не выполнен")
            return "no"
        req = ConfirmRequest(tool=name, summary=_summary_of(call), path=str(call.args.get("path") or ""),
                             command=str(call.args.get("command") or ""),
                             args=_redact(call.args))
        if name in ("write", "edit"):
            req.detail, req.diff = _diff_preview(self.tools, name, call.args)
        answer = self.confirm(req) or "yes"
        if answer == "always":
            self.allowed.add(name)
            return "yes"
        return answer

    def _journal(self, call: Any, res: ToolResult) -> None:
        """Строка в локальный журнал: при сжатии истории модель увидит его вместо файлов."""
        args = call.args or {}
        target = str(args.get("path") or args.get("pattern") or args.get("command") or "")
        mark = "+" if res.ok else "!"
        self.journal.append(f"{mark} {res.name} {target[:70]}"
                            + (f" → {res.summary[:60]}" if res.summary else ""))
        self.journal = self.journal[-60:]

    def _remember(self, task: str, report: Report) -> None:
        """Две строки памяти на задачу: продолжения вроде «а теперь то же во втором файле»
        работают без пересылки всей переписки."""
        answer = re.sub(r"\s+", " ", report.answer or "").strip()
        if report.error:
            answer = f"ошибка: {report.error[:120]}"
        elif report.cancelled and not answer:
            answer = "остановлено пользователем"
        files = ", ".join(report.files) or "без изменений файлов"
        result = answer[:MEMORY_RESULT_CHARS]
        if len(answer) > MEMORY_RESULT_CHARS:
            result += "…"
        self.memory.append({"task": task.strip()[:MEMORY_TASK_CHARS],
                            "result": f"{result} [{files}]"})
        self.memory = self.memory[-MEMORY_TASKS:]

    # ------------------------------------------------------------------ сжатие

    def _auto_compact(self) -> None:
        budget = self.context_budget()
        size = self.prompt_tokens()
        if size <= budget:
            return
        before = size
        saved = self.compact()
        if saved:
            self._send(self.EVENT_COMPACT, before=before, after=self.prompt_tokens(), saved=saved)

    def compact(self, aggressive: bool = False) -> int:
        """Сжимает историю. Возвращает, сколько токенов примерно сэкономили.

        Три ступени, применяются по необходимости:
            1. старые результаты инструментов -> одна строка-пометка;
            2. содержимое файлов в старых вызовах write/edit -> пометка о размере;
            3. если всё ещё много — середина истории заменяется «журналом» (локальная
               сборка, без платного запроса к модели).
        """
        keep = int(self.cfg.get("economy.keep_recent", 2))
        before = self.prompt_tokens()

        # карта tool_use_id -> (имя, цель) — из неё делаем пометки
        meta: Dict[str, str] = {}
        for msg in self.messages:
            if msg.get("role") != "assistant":
                continue
            for block in msg.get("content") or []:
                if block.get("type") == "tool_use":
                    args = block.get("input") or {}
                    target = str(args.get("path") or args.get("pattern")
                                 or args.get("command") or "")
                    meta[block.get("id") or ""] = f"{block.get('name')} {target}".strip()

        # 1) результаты инструментов
        tool_msgs = [i for i, m in enumerate(self.messages) if _has_tool_result(m)]
        for i in tool_msgs[:-keep] if keep else tool_msgs:
            msg = self.messages[i]
            new_blocks = []
            for block in msg.get("content") or []:
                if block.get("type") == "tool_result" and len(str(block.get("content") or "")) > SQUEEZE_CHARS:
                    label = meta.get(block.get("tool_use_id") or "", "инструмент")
                    content = str(block.get("content") or "")
                    first = content.splitlines()[0][:SQUEEZE_CHARS] if content else ""
                    block = {**block, "content": f"[сжато: {label} · {len(content)} симв. · {first}]"}
                new_blocks.append(block)
            self.messages[i] = {**msg, "content": new_blocks}

        # 2) содержимое файлов в старых вызовах write/edit
        assistant_idx = [i for i, m in enumerate(self.messages) if m.get("role") == "assistant"]
        for i in assistant_idx[:-keep] if keep else assistant_idx:
            msg = self.messages[i]
            new_blocks = []
            for block in msg.get("content") or []:
                if block.get("type") == "tool_use":
                    args = dict(block.get("input") or {})
                    changed = False
                    for key in ("content", "old", "new"):
                        value = args.get(key)
                        if isinstance(value, str) and len(value) > 200:
                            args[key] = f"<{len(value)} символов: файл уже на диске>"
                            changed = True
                    if changed:
                        block = {**block, "input": args}
                new_blocks.append(block)
            self.messages[i] = {**msg, "content": new_blocks}

        after = self.prompt_tokens()
        if after <= self.context_budget() and not aggressive:
            self.squeezed_total += max(0, before - after)
            return max(0, before - after)

        # 3) выбрасываем середину, оставляя задачу и последние шаги
        if len(self.messages) > 6:
            head = self.messages[:1]
            tail = self.messages[-4:]
            journal = "\n".join(self.journal[-25:]) or "(журнал пуст)"
            note = ("[середина истории сжата для экономии токенов]\n"
                    "Журнал сделанного:\n" + journal +
                    "\nФайлы на диске в актуальном состоянии; при необходимости "
                    "прочитай их заново — это дешевле, чем держать в контексте.")
            middle = [{"role": "user", "content": [{"type": "text", "text": note}]}]
            # хвост должен начинаться не с tool_result без пары — проверяем
            self.messages = head + middle + tail
        # после сжатия история обязана оставаться валидной для шлюза:
        # пары tool_use/tool_result и чередование ролей
        self.messages = sanitize_history(self.messages)
        after = self.prompt_tokens()
        saved = max(0, before - after)
        self.squeezed_total += saved
        return saved

    # ------------------------------------------------------------------ справка

    def stats(self) -> Dict[str, Any]:
        ctx = self.catalog.context(self.catalog.resolve(self.model))
        size = self.prompt_tokens()
        return {
            "model": self.catalog.resolve(self.model),
            "alias": self.model,
            "multiplier": self.catalog.multiplier(self.catalog.resolve(self.model)),
            "prompt_tokens": size,
            "context": ctx,
            "context_used": round(size * 100 / ctx) if ctx else 0,
            "messages": len(self.messages),
            "memory_tasks": len(self.memory),
            "tokens_in": self.gw.session.tokens_in,
            "tokens_out": self.gw.session.tokens_out,
            "cache_read": self.gw.session.cache_read,
            "charged": self.gw.session.charged,
            "day_tokens": self.state.tokens_day,
            "day_limit": self.gw.daily_limit,
            "squeezed": self.squeezed_total,
            "tool_calls": self.tools.calls,
            "steps": len(self.steps_history),
            "cache_enabled": self.gw.cache_enabled and self.gw.cache_supported,
        }


# ---------------------------------------------------------------------------
# Помощники
# ---------------------------------------------------------------------------


def _has_tool_result(msg: Dict[str, Any]) -> bool:
    content = msg.get("content")
    if not isinstance(content, list):
        return False
    return any(b.get("type") == "tool_result" for b in content)


def sanitize_history(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Приводит историю к требованиям шлюза Anthropic.

    Нужно после сжатия: tool_use без tool_result (и наоборот) — это гарантированный
    HTTP 400, то есть потраченный впустую шаг и токены. Роли обязаны чередоваться,
    а первое сообщение должно быть от пользователя.
    """
    if not messages:
        return messages
    use_ids, result_ids = set(), set()
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                use_ids.add(block.get("id"))
            elif block.get("type") == "tool_result":
                result_ids.add(block.get("tool_use_id"))
    orphan_uses = use_ids - result_ids
    orphan_results = result_ids - use_ids
    if not orphan_uses and not orphan_results:
        return messages

    out: List[Dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        blocks: List[Dict[str, Any]] = []
        for block in content or []:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "tool_use" and block.get("id") in orphan_uses:
                continue
            if kind == "tool_result" and block.get("tool_use_id") in orphan_results:
                continue
            blocks.append(block)
        if not blocks:
            if role == "assistant":
                blocks = [{"type": "text", "text": "[шаг сжат]"}]
            else:
                continue
        if out and out[-1].get("role") == role:
            out[-1] = {"role": role, "content": list(out[-1].get("content") or []) + blocks}
            continue
        out.append({"role": role, "content": blocks})
    if out and out[0].get("role") != "user":
        out.insert(0, {"role": "user",
                       "content": [{"type": "text", "text": "[начало истории сжато]"}]})
    return out


def _tools_rejected(err: GatewayError) -> bool:
    text = str(err).lower()
    return ("tools" in text or "tool_choice" in text or "tool_use" in text
            or "инструмент" in text)


def _redact(args: Dict[str, Any]) -> Dict[str, Any]:
    """Аргументы для интерфейса: длинное содержимое файлов не дублируем на экране."""
    out: Dict[str, Any] = {}
    for key, value in (args or {}).items():
        if isinstance(value, str) and len(value) > 400:
            out[key] = value[:400] + f"… (+{len(value) - 400} символов)"
        else:
            out[key] = value
    return out


def _summary_of(call: Any) -> str:
    args = call.args or {}
    name = call.name
    if name == "bash":
        return f"команда: {str(args.get('command') or '')[:120]}"
    if name == "write":
        return f"записать {args.get('path')} ({len(str(args.get('content') or ''))} символов)"
    if name == "edit":
        return f"правка {args.get('path')}"
    return f"{name} {args.get('path') or args.get('pattern') or ''}"


def _diff_preview(toolbox: Toolbox, name: str, args: Dict[str, Any]) -> Tuple[str, str]:
    """Показывает, что изменится — ДО применения (для диалога подтверждения)."""
    from .tools import _read_text, _unified

    ws = toolbox.ws
    try:
        full = ws.resolve(str(args.get("path") or ""), for_write=True)
    except ValueError as e:
        return str(e), ""
    rel = ws.rel(full)
    before = _read_text(full) if os.path.isfile(full) else ""
    if name == "write":
        after = str(args.get("content") or "")
    else:
        old = str(args.get("old") or "")
        after = before.replace(old, str(args.get("new") or ""), 1) if old in before else before
    diff = _unified(before, after, rel)
    added = sum(1 for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in diff.splitlines() if ln.startswith("-") and not ln.startswith("---"))
    detail = (f"{rel}: +{added} −{removed} строк"
              + (" · новый файл" if not before else ""))
    return detail, diff


_JSON_RE = re.compile(r"\{.*\}", re.S)


def parse_text_action(text: str) -> Optional[Dict[str, Any]]:
    """Разбор JSON-протокола (запасной режим, если шлюз не поддержал tools)."""
    if not text:
        return None
    fence = re.findall(r"```(?:json)?\s*(.+?)```", text, re.S)
    candidates = list(fence) + [text]
    for cand in candidates:
        m = _JSON_RE.search(cand)
        if not m:
            continue
        try:
            obj = json.loads(m.group())
        except ValueError:
            continue
        if isinstance(obj, dict) and (obj.get("tool") or obj.get("done")):
            obj.setdefault("args", {})
            if not isinstance(obj["args"], dict):
                obj["args"] = {}
            return obj
    return None
