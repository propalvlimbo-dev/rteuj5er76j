#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты консоли ELYTRIX: поле ввода, подсказки, команды, отрисовка, диалоги, обычный режим.

Всё работает без терминала: App создаётся напрямую, кадры пишутся в StringIO,
а последний тест гоняет настоящую консоль через pty (только POSIX).

Запуск:  python dev/tests/test_tui.py
"""

from __future__ import annotations

import io
import os
import shutil
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mockapi import MockGateway, Stack, call, make_workspace, text, tool  # noqa: E402

from elytrix import clip  # noqa: E402
from elytrix.dialogs import (ConfirmDialog, ListDialog, MessageDialog,  # noqa: E402
                             PromptDialog)
from elytrix.keys import KeyEvent  # noqa: E402
from elytrix.screen import Palette, text_width  # noqa: E402
from elytrix.theme import Theme  # noqa: E402
from elytrix.tui import (COMMANDS, App, Completion, InputBuffer, PlainUI,  # noqa: E402
                         KIND_ASSISTANT, KIND_CUSTOM, KIND_ERROR, KIND_INFO, KIND_LOGO,
                         KIND_SPACER, KIND_TOOL, KIND_USER)


def key(name: str, ch: str = "") -> KeyEvent:
    return KeyEvent(name, ch)


def typed(chars: str):
    """События для набора строки с клавиатуры."""
    return [key("char", ch) for ch in chars]


ANSI_RE = re.compile(
    r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"     # OSC: заголовок окна
    r"|\x1b\[[0-9;?]*[\-./]*[@-~]"              # CSI: цвет, курсор, стирание
    r"|\x1b[@-Z\\\-_]"                          # прочие двухсимвольные
)


def frame_text(frame: str) -> str:
    """Текст кадра без управляющих последовательностей — так его видит человек."""
    return ANSI_RE.sub("", frame).replace("\r", "")


def wait_for(predicate, timeout: float = 8.0, step: float = 0.02) -> bool:
    """Ждёт условия — так тесты не зависят от скорости машины."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


class ConsoleCase(unittest.TestCase):
    """Общая обвязка: mock-шлюз, агент и App без терминала."""

    SIZE = (100, 30)

    def setUp(self):
        self.mock = MockGateway()
        self.mock.start()
        self.ws = make_workspace("elytrix-tui-")
        self.stack = Stack(self.mock, self.ws)
        self.agent = self.stack.agent
        self.theme = Theme("dark", Palette("none"), True)
        os.environ["COLUMNS"] = str(self.SIZE[0])
        os.environ["LINES"] = str(self.SIZE[1])
        self.app = App(self.stack.cfg, self.stack.catalog, self.stack.state, self.stack.gw,
                       self.stack.toolbox, self.agent, self.theme, key_source="env")
        # события пишем и в ленту App, и в журнал Stack — так удобнее проверять
        self.stack_events = self.stack.events
        self.agent.emit = lambda kind, data: (self.stack_events.append((kind, data)),
                                              self.app.post(kind, data))

    def tearDown(self):
        self.agent.cancel.set()
        if self.app.worker and self.app.worker.is_alive():
            self.app.worker.join(timeout=3)
        router = getattr(self.app, "router_httpd", None)
        if router is not None:
            try:
                router.shutdown()
            except Exception:  # noqa: BLE001
                pass
        self.mock.stop()
        self.stack.cleanup()
        shutil.rmtree(self.ws, ignore_errors=True)
        os.environ.pop("COLUMNS", None)
        os.environ.pop("LINES", None)

    # -- помощники ----------------------------------------------------------

    def keys(self, *events: KeyEvent):
        for ev in events:
            self.app.on_key(ev)
        self.app.drain()

    def type_text(self, s: str):
        self.keys(*typed(s))

    def draw(self, size=None) -> str:
        """Рисует кадр и возвращает его текстом."""
        if size:
            os.environ["COLUMNS"], os.environ["LINES"] = str(size[0]), str(size[1])
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.app.draw()
        return buf.getvalue()

    def pump(self, predicate, timeout: float = 10.0):
        """Ждёт условия, попутно разбирая очередь событий воркера (как это делает run())."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.app.drain()
            if predicate():
                return True
            time.sleep(0.02)
        self.app.drain()
        return bool(predicate())

    def run_task(self, task: str = "сделай что-нибудь", timeout: float = 15.0):
        """Отправляет задачу через ввод с клавиатуры и ждёт завершения."""
        self.type_text(task)
        self.keys(key("enter"))
        self.assertTrue(self.pump(lambda: not self.app.busy, timeout),
                        "задача не завершилась вовремя")

    def block_texts(self, kind: str = ""):
        out = []
        for block in self.app.blocks:
            if kind and block.kind != kind:
                continue
            rows = block.lines(self.theme, 100)
            out.append("\n".join("".join(t for t, _ in r) for r in rows))
        return out


# ---------------------------------------------------------------------------
# Поле ввода
# ---------------------------------------------------------------------------


class TestInputBuffer(unittest.TestCase):
    def setUp(self):
        self.buf = InputBuffer()

    def test_insert_and_cursor(self):
        self.buf.insert("привет")
        self.assertEqual(self.buf.text, "привет")
        self.assertEqual(self.buf.col, 6)
        self.buf.left()
        self.buf.insert("!")
        self.assertEqual(self.buf.text, "приве!т")

    def test_backspace_and_delete(self):
        self.buf.insert("abc")
        self.buf.backspace()
        self.assertEqual(self.buf.text, "ab")
        self.buf.home()
        self.buf.delete()
        self.assertEqual(self.buf.text, "b")

    def test_home_end(self):
        self.buf.insert("строка")
        self.buf.home()
        self.assertEqual(self.buf.col, 0)
        self.buf.end()
        self.assertEqual(self.buf.col, 6)

    def test_kill_shortcuts(self):
        self.buf.insert("раз два три")
        self.buf.kill_word()
        self.assertEqual(self.buf.text, "раз два ")
        self.buf.kill_to_start()
        self.assertEqual(self.buf.text, "")
        self.buf.insert("abc")
        self.buf.home()
        self.buf.right()
        self.buf.kill_line()
        self.assertEqual(self.buf.text, "a")

    def test_multiline(self):
        self.buf.insert("первая")
        self.buf.newline()
        self.buf.insert("вторая")
        self.assertEqual(self.buf.text, "первая\nвторая")
        self.assertEqual(self.buf.row, 1)
        self.buf.up()
        self.assertEqual(self.buf.row, 0)

    def test_set_text_and_clear(self):
        self.buf.set_text("готовый текст")
        self.assertEqual(self.buf.text, "готовый текст")
        self.assertFalse(self.buf.is_empty())
        self.buf.clear()
        self.assertTrue(self.buf.is_empty())
        self.assertEqual(self.buf.text, "")

    def test_history(self):
        self.buf.push_history("первая")
        self.buf.push_history("вторая")
        self.buf.history_prev()
        self.assertEqual(self.buf.text, "вторая")
        self.buf.history_prev()
        self.assertEqual(self.buf.text, "первая")
        self.buf.history_prev()
        self.assertEqual(self.buf.text, "первая", "старее первой не уходим")
        self.buf.history_next()
        self.assertEqual(self.buf.text, "вторая")
        self.buf.history_next()
        self.assertEqual(self.buf.text, "", "в конце истории — пустая строка")

    def test_history_keeps_draft(self):
        self.buf.push_history("старое")
        self.buf.insert("черновик")
        self.buf.history_prev()
        self.assertEqual(self.buf.text, "старое")
        self.buf.history_next()
        self.assertEqual(self.buf.text, "черновик")

    def test_history_limit(self):
        buf = InputBuffer(history_limit=3)
        for i in range(10):
            buf.push_history(f"строка {i}")
        self.assertEqual(len(buf.history), 3)
        self.assertEqual(buf.history[-1], "строка 9")

    def test_history_ignores_duplicates(self):
        self.buf.push_history("одно")
        self.buf.push_history("одно")
        self.assertEqual(len(self.buf.history), 1)

    def test_up_down_move_cursor_inside_multiline(self):
        self.buf.insert("первая")
        self.buf.newline()
        self.buf.insert("вторая")
        self.buf.push_history("история")
        self.assertTrue(self.buf.up())            # переход на строку выше
        self.assertEqual(self.buf.row, 0)
        self.assertTrue(self.buf.down())
        self.assertEqual(self.buf.row, 1)
        self.assertTrue(self.buf.up())            # строка 1 → 0
        self.assertFalse(self.buf.up())           # выше некуда — взяли историю
        self.assertEqual(self.buf.text, "история")
        self.buf.history_next()                   # и вернули черновик
        self.assertEqual(self.buf.text, "первая\nвторая")

    def test_kill_word_splits_paths(self):
        self.buf.insert("прочитай src/app/main.py")
        self.buf.kill_word()
        self.assertEqual(self.buf.text, "прочитай src/app/")
        self.buf.kill_word()
        self.assertEqual(self.buf.text, "прочитай src/")


# ---------------------------------------------------------------------------
# Подсказки
# ---------------------------------------------------------------------------


class TestCompletion(ConsoleCase):
    def test_command_prefix(self):
        comp = Completion()
        buf = InputBuffer()
        buf.set_text("/mod")
        comp.update_command(buf)
        self.assertTrue(comp.active)
        labels = [item[0] for item in comp.items]
        self.assertIn("/model", labels)
        self.assertIn("/models", labels)
        self.assertNotIn("/help", labels)

    def test_slash_lists_everything(self):
        comp = Completion()
        buf = InputBuffer()
        buf.set_text("/")
        comp.update_command(buf)
        self.assertEqual(len(comp.items), len(COMMANDS))

    def test_no_completion_for_plain_text(self):
        comp = Completion()
        buf = InputBuffer()
        buf.set_text("почини тесты")
        comp.update_command(buf)
        self.assertFalse(comp.active)

    def test_no_completion_after_space(self):
        comp = Completion()
        buf = InputBuffer()
        buf.set_text("/model auto")
        comp.update_command(buf)
        self.assertFalse(comp.active)

    def test_accept_inserts_command(self):
        comp = Completion()
        buf = InputBuffer()
        buf.set_text("/cle")
        comp.update_command(buf)
        comp.accept(buf)
        self.assertEqual(buf.text, "/clear ")
        self.assertFalse(comp.active)

    def test_move_wraps(self):
        comp = Completion()
        buf = InputBuffer()
        buf.set_text("/")
        comp.update_command(buf)
        comp.move(1)
        self.assertEqual(comp.index, 1)
        comp.move(-1)
        comp.move(-1)
        self.assertEqual(comp.index, len(comp.items) - 1)

    def test_file_completion_by_at(self):
        with open(os.path.join(self.ws, "main.py"), "w", encoding="utf-8") as f:
            f.write("print(1)\n")
        os.makedirs(os.path.join(self.ws, "pkg"), exist_ok=True)
        comp = Completion()
        buf = InputBuffer()
        buf.set_text("посмотри @ma")
        comp.update_file(buf, self.stack.ws)
        self.assertTrue(comp.active, "подсказка файлов должна открыться")
        comp.accept(buf)
        self.assertIn("main.py", buf.text)

    def test_tab_accepts_completion_in_app(self):
        self.type_text("/comp")
        self.assertTrue(self.app.completion.active)
        self.keys(key("tab"))
        self.assertEqual(self.app.input.text, "/compact ")


# ---------------------------------------------------------------------------
# Отрисовка
# ---------------------------------------------------------------------------


class TestRendering(ConsoleCase):
    def test_frame_has_header_input_and_status(self):
        self.app.add(KIND_ASSISTANT, "ответ модели")
        frame = frame_text(self.draw())
        self.assertIn("ELYTRIX", frame)
        self.assertIn("ответ модели", frame)
        self.assertIn(self.catalog_model(), frame)

    def catalog_model(self):
        return self.stack.catalog.resolve(self.agent.model)

    def test_frame_width_is_limited(self):
        self.app.add(KIND_ASSISTANT, "очень длинный текст " * 40)
        frame = frame_text(self.draw((80, 24)))
        for line in frame.split("\n"):
            self.assertLessEqual(text_width(line), 80, f"строка шире кадра: {line!r}")

    def test_narrow_terminal_shows_hint(self):
        frame = frame_text(self.draw((30, 10)))
        self.assertTrue(frame.strip(), "кадр не должен быть пустым")

    def test_colored_frame_contains_ansi(self):
        self.app.theme = Theme("dark", Palette("truecolor"), True)
        self.app.add(KIND_ASSISTANT, "цветной ответ")
        self.app.invalidate_blocks()
        frame = self.draw()
        self.assertIn("\x1b[", frame)

    def test_ascii_theme_survives(self):
        self.app.theme = Theme("mono", Palette("none"), False)
        self.app.add(KIND_TOOL, "", {"name": "read", "state": "done", "ok": True,
                                     "target": "a.py", "summary": "10 строк"})
        self.app.invalidate_blocks()
        frame = frame_text(self.draw())
        self.assertNotIn("─", frame)
        self.assertIn("read", frame)

    def test_scroll_moves_view(self):
        for i in range(60):
            self.app.add(KIND_ASSISTANT, f"строка ответа {i}")
        bottom = frame_text(self.draw())
        self.assertIn("строка ответа 59", bottom, "по умолчанию видим конец ленты")
        self.app.scroll_page(-1)
        middle = frame_text(self.draw())
        self.assertNotIn("строка ответа 59", middle)
        self.assertIn("ещё", middle, "показываем, сколько строк осталось выше и ниже")
        self.app.scroll_page(-1)
        self.app.scroll_page(-1)
        top = frame_text(self.draw())
        self.assertIn("строка ответа 0", top, "долистали до начала")
        self.app.scroll_page(1)
        self.assertNotEqual(top, frame_text(self.draw()))

    def test_input_box_shows_cursor(self):
        self.type_text("привет")
        rows, cursor = self.app.input_box(100)
        self.assertTrue(rows)
        self.assertIsNotNone(cursor)
        row, col = cursor
        self.assertLess(row, len(rows) + 4)
        self.assertLess(col, 100)

    def test_input_wraps_long_line(self):
        self.type_text("длинная строка " * 20)
        rows, _cursor = self.app.input_box(60)
        self.assertGreater(len(rows), 1)

    def test_multiline_input(self):
        self.keys(*typed("первая"), key("alt+enter"), *typed("вторая"))
        rows, _cursor = self.app.input_box(100)
        joined = "\n".join("".join(t for t, _ in r) for r in rows)
        self.assertIn("первая", joined)
        self.assertIn("вторая", joined)

    def test_completion_popup_drawn(self):
        self.type_text("/mo")
        frame = frame_text(self.draw())
        self.assertIn("/model", frame)

    def test_verbose_toggle_shows_tool_body(self):
        self.app.add(KIND_TOOL, "", {"name": "read", "state": "done", "ok": True,
                                     "target": "a.py", "summary": "2 строки",
                                     "text": "содержимое файла"})
        short = frame_text(self.draw())
        self.assertNotIn("содержимое файла", short)
        self.app.toggle_verbose()
        long = frame_text(self.draw())
        self.assertIn("содержимое файла", long)

    def test_status_shows_day_usage(self):
        self.stack.state.record("gpt-5.6-luna", 1000, 100, 1.7)
        self.app.dirty_stats = True
        frame = frame_text(self.draw())
        self.assertIn("K", frame)

    def test_tip_rotates(self):
        first = self.app.tip_index
        self.app.tip_at = 0.0
        self.app.tip_index += 1
        self.assertNotEqual(first, self.app.tip_index)


# ---------------------------------------------------------------------------
# Команды
# ---------------------------------------------------------------------------


class TestCommands(ConsoleCase):
    def test_help_lists_commands(self):
        self.app.command("/help")
        self.assertIsInstance(self.app.dialog, MessageDialog)
        body = "\n".join("".join(t for t, _ in r)
                         for r in self.app.dialog.body(self.theme, 80))
        for name, _desc in COMMANDS:
            self.assertIn(name, body)
        self.keys(key("esc"))
        self.assertIsNone(self.app.dialog)

    def test_unknown_command(self):
        self.app.command("/нет-такой")
        self.assertTrue(any("нет команды" in t for t in self.block_texts(KIND_INFO)))

    def test_model_dialog_and_choice(self):
        self.app.command("/model")
        self.assertIsInstance(self.app.dialog, ListDialog)
        labels = [item[0] for item in self.app.dialog.items]
        self.assertTrue(any("auto" in m for m in labels), "маршруты должны быть в списке")
        self.assertTrue(any("gpt-5.6-luna" in m for m in labels))
        self.keys(*typed("gpt-5.6-luna"))      # фильтр по тексту
        self.keys(key("enter"))
        self.assertIsNone(self.app.dialog)
        self.assertEqual(self.agent.model, "gpt-5.6-luna")
        self.assertEqual(self.agent.messages, [], "смена модели очищает историю")

    def test_model_dialog_alias_by_substring(self):
        self.app.command("/model")
        self.keys(*typed("luna"))              # «luna» находит маршрут cheap → gpt-5.6-luna
        self.keys(key("enter"))
        self.assertEqual(self.stack.catalog.resolve(self.agent.model), "gpt-5.6-luna")

    def test_model_by_argument(self):
        self.app.command("/model max")
        self.assertEqual(self.agent.model, "max")
        self.assertEqual(self.stack.catalog.resolve(self.agent.model), "claude-opus-5")

    def test_tokens_dialog(self):
        self.stack.state.record("claude-sonnet-4-6", 1000, 500, 2.0)
        self.app.command("/tokens")
        self.assertIsInstance(self.app.dialog, MessageDialog)
        body = "\n".join("".join(t for t, _ in r)
                         for r in self.app.dialog.body(self.theme, 80))
        self.assertIn("claude-sonnet-4-6", body)

    def test_clear_resets_history(self):
        self.mock.queue(text("ответ"))
        self.run_task("задача")
        self.assertTrue(self.agent.messages)
        self.app.command("/clear")
        self.assertEqual(self.agent.messages, [])
        self.assertEqual(self.agent.memory, [])
        self.assertTrue(all(b.kind in (KIND_INFO, KIND_SPACER, KIND_LOGO, KIND_CUSTOM)
                            for b in self.app.blocks),
                        f"лента очищается, остаётся шапка: {[b.kind for b in self.app.blocks]}")
        self.assertNotIn("ответ", " ".join(self.block_texts()))

    def test_compact_shrinks_history(self):
        self.mock.queue(text("ответ"))
        self.run_task("задача")
        self.agent.messages.extend({"role": "user", "content": "мусор " * 500} for _ in range(5))
        before = self.agent.prompt_tokens()
        self.app.command("/compact")
        self.assertLess(self.agent.prompt_tokens(), before)

    def test_diff_and_undo(self):
        target = os.path.join(self.ws, "a.txt")
        with open(target, "w", encoding="utf-8") as f:
            f.write("старое\n")
        self.mock.queue(tool(call("edit", path="a.txt", old="старое", new="новое")),
                        text("готово"))
        self.run_task("поправь файл")
        self.assertEqual(open(target, encoding="utf-8").read(), "новое\n")
        self.app.command("/diff")
        self.assertIsInstance(self.app.dialog, MessageDialog)
        body = "\n".join("".join(t for t, _ in r)
                         for r in self.app.dialog.body(self.theme, 100))
        self.assertIn("новое", body)
        self.keys(key("esc"))
        self.app.command("/undo")
        self.assertEqual(open(target, encoding="utf-8").read(), "старое\n")

    def test_diff_of_new_file(self):
        self.mock.queue(tool(call("write", path="new.txt", content="данные")), text("готово"))
        self.run_task("создай файл")
        self.assertTrue(os.path.isfile(os.path.join(self.ws, "new.txt")))
        self.app.command("/diff")
        self.assertIsInstance(self.app.dialog, MessageDialog)
        self.keys(key("esc"))
        self.app.command("/undo")
        self.assertFalse(os.path.exists(os.path.join(self.ws, "new.txt")),
                         "созданный файл undo должен удалить")

    def test_tree(self):
        os.makedirs(os.path.join(self.ws, "pkg"), exist_ok=True)
        with open(os.path.join(self.ws, "pkg", "mod.py"), "w", encoding="utf-8") as f:
            f.write("x = 1\n")
        self.app.command("/tree")
        self.assertIsInstance(self.app.dialog, MessageDialog)
        body = "\n".join("".join(t for t, _ in r)
                         for r in self.app.dialog.body(self.theme, 80))
        self.assertIn("mod.py", body)

    def test_session_dialog(self):
        self.agent.memory.append({"task": "сделал a.txt", "result": "файл записан",
                                  "files": "a.txt"})
        self.app.command("/session")
        self.assertIsInstance(self.app.dialog, MessageDialog)
        body = "\n".join("".join(t for t, _ in r)
                         for r in self.app.dialog.body(self.theme, 80))
        self.assertIn("a.txt", body)

    def test_steps_and_limit(self):
        self.app.command("/steps 7")
        self.assertEqual(self.agent.max_steps, 7)
        self.app.command("/limit 12345")
        self.assertEqual(self.app.gw.daily_limit, 12345)
        self.assertEqual(self.app.cfg.get("limits.daily_tokens"), 12345)
        self.app.command("/limit 0")        # снять лимит
        self.assertEqual(self.app.gw.daily_limit, 0)
        self.app.command("/steps")          # без аргумента — показать текущее
        self.assertTrue(self.app.blocks)

    def test_confirm_mode(self):
        self.app.command("/confirm readonly")
        self.assertEqual(self.agent.confirm_mode, "readonly")
        self.app.command("/confirm ask")
        self.assertEqual(self.agent.confirm_mode, "ask")
        self.app.command("/confirm auto")
        self.assertEqual(self.agent.confirm_mode, "auto")

    def test_theme_switch(self):
        self.app.command("/theme light")
        self.assertEqual(self.app.theme.name, "light")
        self.app.command("/theme")
        self.assertIsInstance(self.app.dialog, ListDialog)
        self.keys(key("esc"))

    def test_verbose_command(self):
        self.app.command("/verbose on")
        self.assertTrue(self.app.verbose)
        self.app.command("/verbose off")
        self.assertFalse(self.app.verbose)

    def test_cd_changes_workspace(self):
        other = tempfile.mkdtemp(prefix="elytrix-cd-")
        try:
            self.app.command(f"/cd {other}")
            self.assertEqual(os.path.realpath(self.app.ws.root), os.path.realpath(other))
            self.assertEqual(self.stack.state.get("last_workspace"), other)
        finally:
            shutil.rmtree(other, ignore_errors=True)

    def test_cd_without_argument_opens_dialog(self):
        self.app.command("/cd")
        self.assertIsInstance(self.app.dialog, (ListDialog, PromptDialog))

    def test_key_command_opens_prompt(self):
        self.app.command("/key")
        self.assertIsInstance(self.app.dialog, PromptDialog)
        self.keys(key("esc"))
        self.assertIsNone(self.app.dialog)

    def test_doctor_dialog(self):
        self.mock.queue(text("ок"))
        self.app.command("/doctor")
        self.assertTrue(self.pump(lambda: isinstance(self.app.dialog, MessageDialog), 10))
        body = "\n".join("".join(t for t, _ in r)
                         for r in self.app.dialog.body(self.theme, 80))
        self.assertTrue(body.strip())
        self.keys(key("esc"))

    def test_models_reload(self):
        self.app.command("/models reload")
        self.assertTrue(self.pump(lambda: any("модел" in t for t in self.block_texts(KIND_INFO)), 10))

    def test_router_starts_and_stops(self):
        self.app.command("/router 0")
        self.assertTrue(self.pump(lambda: bool(self.app.router_url), 10))
        self.assertRegex(self.app.router_url, r"^http://127\.0\.0\.1:[1-9]\d*$")
        self.assertTrue(any("/v1" in t for t in self.block_texts(KIND_INFO)))
        self.app.command("/router")          # повторный запуск — просто напомнить адрес
        self.assertTrue(any("уже работает" in t for t in self.block_texts(KIND_INFO)))
        self.app.command("/router stop")
        self.assertIsNone(self.app.router_thread)
        self.app.command("/router stop")     # второй раз — не падаем
        self.assertTrue(any("не запущен" in t for t in self.block_texts(KIND_INFO)))

    def test_exit_sets_code(self):
        self.app.command("/exit")
        self.assertEqual(self.app.exit_code, 0)


# ---------------------------------------------------------------------------
# Клавиши и живой цикл задачи
# ---------------------------------------------------------------------------


class TestInteraction(ConsoleCase):
    def test_task_shows_question_and_answer(self):
        self.mock.queue(text("всё готово"))
        self.run_task("почини тесты")
        blocks = self.block_texts()
        self.assertTrue(any("почини тесты" in b for b in blocks))
        self.assertTrue(any("всё готово" in b for b in blocks))
        self.assertFalse(self.app.busy)

    def test_tool_block_appears(self):
        self.mock.queue(tool(call("write", path="a.txt", content="данные")), text("готово"))
        self.run_task("создай файл")
        kinds = [b.kind for b in self.app.blocks]
        self.assertIn(KIND_TOOL, kinds)
        self.assertTrue(os.path.isfile(os.path.join(self.ws, "a.txt")))

    def test_error_block_on_gateway_failure(self):
        self.mock.fail_with = (500, "шлюз лёг")
        self.mock.fail_once = False
        self.mock.queue(text("не дойдёт"))
        self.run_task("задача", timeout=25)
        errors = self.block_texts(KIND_ERROR)
        self.assertTrue(errors, f"блоки: {self.block_texts()}")
        self.assertIn("500", errors[0])
        self.assertFalse(self.app.busy)

    def test_streaming_updates_block(self):
        self.mock.queue(text("часть вторая третья"))
        self.type_text("задача")
        self.keys(key("enter"))
        self.assertTrue(self.pump(lambda: not self.app.busy, 10))
        self.app.drain()
        pieces = self.stack.of("text")
        self.assertGreater(len(pieces), 1, "ответ должен приходить потоком, а не одним куском")
        self.assertTrue(any("часть вторая третья" in b for b in self.block_texts(KIND_ASSISTANT)))

    def test_second_task_while_busy_is_rejected(self):
        self.mock.stall = 0.6
        self.mock.queue(text("медленный ответ"))
        self.type_text("первая")
        self.keys(key("enter"))
        self.assertTrue(self.app.busy)
        self.app.start_task("вторая")
        self.assertTrue(any("ещё работает" in b for b in self.block_texts(KIND_INFO)))
        self.assertTrue(self.pump(lambda: not self.app.busy, 12))

    def test_esc_cancels_task(self):
        self.mock.stall = 1.0
        self.mock.queue(text("долгий ответ"))
        self.type_text("задача")
        self.keys(key("enter"))
        self.keys(key("esc"))
        self.assertTrue(self.agent.cancel.is_set())
        self.assertTrue(self.pump(lambda: not self.app.busy, 12))

    def test_ctrl_c_twice_quits(self):
        self.keys(key("ctrl+c"))
        self.assertIsNone(self.app.exit_code)
        self.keys(key("ctrl+c"))
        self.assertEqual(self.app.exit_code, 0)

    def test_ctrl_d_on_empty_input_quits(self):
        self.keys(key("ctrl+d"))
        self.assertEqual(self.app.exit_code, 0)

    def test_ctrl_d_clears_input_first(self):
        self.type_text("текст")
        self.keys(key("ctrl+d"))
        self.assertIsNone(self.app.exit_code)
        self.assertEqual(self.app.input.text, "")

    def test_esc_clears_input(self):
        self.type_text("текст")
        self.keys(key("esc"))
        self.assertEqual(self.app.input.text, "")

    def test_history_with_arrows(self):
        self.mock.queue(text("раз"), text("два"))
        self.run_task("первая задача")
        self.run_task("вторая задача")
        self.keys(key("up"))
        self.assertEqual(self.app.input.text, "вторая задача")
        self.keys(key("up"))
        self.assertEqual(self.app.input.text, "первая задача")
        self.keys(key("down"))
        self.assertEqual(self.app.input.text, "вторая задача")

    def test_paste_multiline_does_not_submit(self):
        self.keys(key("paste", "первая строка\nвторая строка"))
        self.assertIn("\n", self.app.input.text)
        self.assertFalse(self.app.busy)

    def test_empty_enter_does_nothing(self):
        self.keys(key("enter"))
        self.assertFalse(self.app.busy)
        self.assertEqual(self.app.blocks, [])

    def test_confirm_dialog_flow(self):
        self.agent.confirm_mode = "ask"
        self.mock.queue(tool(call("write", path="a.txt", content="данные")), text("готово"))
        self.type_text("создай файл")
        self.keys(key("enter"))
        self.assertTrue(self.pump(lambda: isinstance(self.app.dialog, ConfirmDialog), 8),
                        "диалог подтверждения не открылся")
        self.keys(key("char", "y"))
        self.assertTrue(self.pump(lambda: not self.app.busy, 8))
        self.assertIsNone(self.app.dialog)
        self.assertTrue(os.path.isfile(os.path.join(self.ws, "a.txt")))

    def test_confirm_dialog_reject(self):
        self.agent.confirm_mode = "ask"
        self.mock.queue(tool(call("write", path="a.txt", content="данные")), text("не сделал"))
        self.type_text("создай файл")
        self.keys(key("enter"))
        self.assertTrue(self.pump(lambda: isinstance(self.app.dialog, ConfirmDialog), 8))
        self.keys(key("char", "n"))
        self.assertTrue(self.pump(lambda: not self.app.busy, 8))
        self.assertFalse(os.path.exists(os.path.join(self.ws, "a.txt")))

    def test_dialog_swallows_keys(self):
        self.app.command("/help")
        self.type_text("не должно попасть в ввод")   # диалог открыт — ввод не работает
        self.assertEqual(self.app.input.text, "")
        self.keys(key("esc"))
        self.type_text("теперь работает")
        self.assertEqual(self.app.input.text, "теперь работает")

    def test_resize_marks_dirty(self):
        self.app.dirty = False
        self.keys(key("resize"))
        self.assertTrue(self.app.dirty)

    def test_ctrl_l_redraws(self):
        self.app.dirty = False
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.keys(key("ctrl+l"))
        self.assertTrue(self.app.dirty)

    def test_ctrl_r_shows_tokens(self):
        self.keys(key("ctrl+r"))
        self.assertIsInstance(self.app.dialog, MessageDialog)

    def test_pageup_scrolls_while_busy(self):
        for i in range(40):
            self.app.add(KIND_ASSISTANT, f"строка {i}")
        self.app.busy = True
        self.keys(key("pageup"))
        self.assertGreater(self.app.scroll, 0)
        self.app.busy = False


# ---------------------------------------------------------------------------
# Обычный (не полноэкранный) режим
# ---------------------------------------------------------------------------


class TestPlainUI(ConsoleCase):
    def test_run_task_prints_answer_and_summary(self):
        self.mock.queue(tool(call("write", path="a.txt", content="данные")), text("готово"))
        ui = PlainUI(self.agent, self.theme)
        buf = io.StringIO()
        with redirect_stdout(buf):
            report = ui.run_task("создай файл")
        out = buf.getvalue()
        self.assertEqual(report.answer, "готово")
        self.assertIn("готово", out)
        self.assertIn("write", out)
        self.assertIn("итог:", out)
        self.assertIn("a.txt", out)

    def test_error_is_printed(self):
        self.mock.fail_with = (500, "шлюз лёг")
        self.mock.fail_once = False
        ui = PlainUI(self.agent, self.theme)
        buf = io.StringIO()
        with redirect_stdout(buf):
            ui.run_task("задача")
        self.assertIn("ОШИБКА", buf.getvalue())

    def test_no_stream_prints_answer_at_end(self):
        self.mock.queue(text("ответ целиком"))
        ui = PlainUI(self.agent, self.theme, stream=False)
        buf = io.StringIO()
        with redirect_stdout(buf):
            ui.run_task("задача")
        self.assertIn("ответ целиком", buf.getvalue())

    def test_confirm_reads_stdin(self):
        from elytrix.agent import ConfirmRequest

        ui = PlainUI(self.agent, self.theme)
        request = ConfirmRequest(tool="edit", summary="правка a.txt", path="a.txt",
                                 diff="-старое\n+новое")
        import builtins

        original = builtins.input
        builtins.input = lambda prompt="": "y"
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(ui.confirm(request), "yes")
        finally:
            builtins.input = original
        self.assertIn("новое", buf.getvalue())


# ---------------------------------------------------------------------------
# Настоящая консоль через pty (POSIX)
# ---------------------------------------------------------------------------


@unittest.skipIf(os.name == "nt", "pty есть только в POSIX")
class TestPtySmoke(unittest.TestCase):
    """Гоняет весь путь: запуск run.py, альтернативный экран, задача, выход."""

    def setUp(self):
        self.mock = MockGateway()
        self.mock.start()
        self.ws = make_workspace("elytrix-pty-")
        self.home = tempfile.mkdtemp(prefix="elytrix-pty-home-")
        self.cfg_path = os.path.join(self.home, "cfg.json")
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            import json

            json.dump({
                "gateway": {"base_url": self.mock.base_url,
                            "openai_base_url": self.mock.openai_url,
                            "timeout": 10, "connect_timeout": 5},
                "limits": {"daily_tokens": 100000, "max_steps": 4, "max_output_tokens": 256},
                "ui": {"stream": True, "confirm": "auto"},
            }, f)

    def tearDown(self):
        self.mock.stop()
        shutil.rmtree(self.ws, ignore_errors=True)
        shutil.rmtree(self.home, ignore_errors=True)

    def run_console(self, keys_to_send, expect, timeout=25):
        import pty

        master, slave = pty.openpty()
        env = dict(os.environ)
        env.update({
            "ELYTRIX_HOME": self.home,
            "SMARTAPI_KEY": "sk-smart-test-key",
            "COLUMNS": "100",
            "LINES": "30",
            "TERM": "xterm-256color",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
        })
        proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "app", "run.py"),
             "--config", self.cfg_path, "-w", self.ws, "-m", "auto"],
            stdin=slave, stdout=slave, stderr=slave, env=env, cwd=ROOT)
        os.close(slave)
        output = []
        deadline = time.time() + timeout
        sent = False
        try:
            import select

            while time.time() < deadline:
                ready, _, _ = select.select([master], [], [], 0.2)
                if ready:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    output.append(chunk.decode("utf-8", "replace"))
                joined = "".join(output)
                if not sent and "ELYTRIX" in joined:
                    time.sleep(0.3)
                    os.write(master, keys_to_send)
                    sent = True
                if sent and all(word in frame_text(joined) for word in expect):
                    break
                if proc.poll() is not None and not ready:
                    break
            # выходим по-человечески и дочитываем хвост — так видно ALT_OFF
            try:
                os.write(master, "/exit\r".encode("utf-8"))
            except OSError:
                pass
            end = time.time() + 6
            while time.time() < end:
                ready, _, _ = select.select([master], [], [], 0.3)
                if not ready:
                    if proc.poll() is not None:
                        break
                    continue
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                output.append(chunk.decode("utf-8", "replace"))
                if "\x1b[?1049l" in "".join(output):
                    break
            return "".join(output), sent
        finally:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            os.close(master)

    def test_console_answers_task(self):
        self.mock.queue(text("файл создан и тесты зелёные"))
        out, sent = self.run_console("почини\r".encode("utf-8"), ["файл создан"])
        frame = frame_text(out)
        self.assertTrue(sent, "консоль не нарисовала шапку")
        self.assertIn("ELYTRIX", frame)
        self.assertIn("файл создан и тесты зелёные", frame)
        self.assertIn("почини", frame)
        self.assertIn("готово за", frame)

    def test_console_leaves_alternate_screen(self):
        self.mock.queue(text("ответ"))
        out, _sent = self.run_console(b"", ["ELYTRIX"])
        self.assertIn("\x1b[?1049h", out, "должен включаться альтернативный экран")
        self.assertIn("\x1b[?2004h", out, "bracketed paste должен включаться")
        self.assertIn("\x1b[?1049l", out, "при выходе экран должен возвращаться")
        self.assertIn("\x1b[?25h", out, "курсор должен возвращаться")

    def test_console_survives_broken_key(self):
        """Неизвестная escape-последовательность не должна ронять консоль."""
        self.mock.queue(text("жив"))
        out, _sent = self.run_console(b"\x1b\x1b[9~\r", ["ELYTRIX"])
        self.assertIn("ELYTRIX", frame_text(out))


class TestStartupBanner(ConsoleCase):
    """Стартовый экран: логотип и две строки сути вместо стены текста."""

    def test_banner_is_logo_and_centered_tagline(self):
        self.app.banner()
        kinds = [b.kind for b in self.app.blocks]
        self.assertEqual(kinds[0], KIND_LOGO)
        self.assertEqual(kinds[1], KIND_CUSTOM, "под логотипом — центрированный подзаголовок")
        frame = frame_text(self.draw())
        self.assertIn("режим", frame)
        self.assertIn("напишите задачу и Enter", frame)
        self.assertNotIn("• папка", frame, "служебных «простыней» слева на старте нет")

    def test_frame_shows_logo_art(self):
        self.app.banner()
        frame = frame_text(self.draw())
        self.assertIn("███", frame)
        self.assertIn("напишите задачу и Enter", frame)


class TestApiKey(ConsoleCase):
    """/api: ключ из диалога, строкой или из файла; ошибка не дублируется."""

    def setUp(self):
        super().setUp()
        self.home = tempfile.mkdtemp(prefix="elytrix-api-")
        os.environ["ELYTRIX_HOME"] = self.home

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        os.environ.pop("ELYTRIX_HOME", None)
        super().tearDown()

    def test_api_command_reads_key_from_file(self):
        path = os.path.join(self.ws, "key.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("sk-smart-test1234567890\n")
        self.app.command("/api key.txt")
        self.assertEqual(self.app.gw.key, "sk-smart-test1234567890")
        self.assertTrue(any("ключ сохранён" in t for t in self.block_texts(KIND_INFO)))

    def test_api_command_accepts_key_directly(self):
        self.app.command("/api sk-smart-abcdef")
        self.assertEqual(self.app.gw.key, "sk-smart-abcdef")

    def test_api_without_arg_opens_dialog(self):
        self.app.command("/api")
        self.assertIsNotNone(self.app.dialog)
        self.app.close_dialog(False)

    def test_error_not_duplicated_in_task_report(self):
        import types

        self.app.post("error", {"text": "boom error"})
        self.app.drain()
        report = types.SimpleNamespace(error="boom error", cancelled=False, answer="",
                                       usage=None, files=[], elapsed=0.1, steps=1,
                                       squeezed_tokens=0)
        self.app.post("task_done", {"report": report})
        self.app.drain()
        errors = [b.text for b in self.app.blocks
                  if b.kind == KIND_ERROR and b.text == "boom error"]
        self.assertEqual(len(errors), 1, "одна и та же ошибка печатается один раз")


class TestBigPrompts(ConsoleCase):
    """Большие промты: /prompt грузит файл в строку, cli читает задачу из файла."""

    def test_prompt_command_loads_file_into_input(self):
        path = os.path.join(self.ws, "spec.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("первая строка\nвторая строка")
        self.app.command("/prompt spec.md")
        self.assertEqual(self.app.input.lines, ["первая строка", "вторая строка"])

    def test_prompt_missing_file_reports_error(self):
        self.app.command("/prompt нет-такого.md")
        self.assertTrue(any("не удалось" in t for t in self.block_texts(KIND_ERROR)))

    def test_cli_resolve_task_reads_file(self):
        from elytrix.cli import resolve_task

        path = os.path.join(self.ws, "task.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("задача из файла")

        class Args:
            task = [path]

        self.assertEqual(resolve_task(Args()), "задача из файла")

        class Words:
            task = ["просто", "слова"]

        self.assertEqual(resolve_task(Words()), "просто слова")


class TestFrameDiff(ConsoleCase):
    """Кадр перерисовывается дифференциально — без мерцания всего экрана."""

    def test_second_draw_repaints_only_changed_rows(self):
        self.app.banner()
        first = self.draw()
        self.assertIn("ELYTRIX 3.3.0", frame_text(first))
        self.type_text("привет")
        second = self.draw()
        self.assertNotIn("ELYTRIX 3.3.0", frame_text(second),
                         "шапка не изменилась — не перерисовывается")
        self.assertIn("привет", frame_text(second))

    def test_idle_frame_without_changes_is_empty(self):
        self.app.banner()
        self.draw()
        third = self.draw()
        self.assertEqual(frame_text(third).strip(), "",
                         "ничего не изменилось — в канал ничего не пишем")

    def test_dialog_has_no_background_slab(self):
        self.app.command("/cd")
        frame = self.draw()
        self.assertNotIn("\x1b[48", frame, "вокруг диалога не должно быть цветной подложки")


class TestTypeahead(ConsoleCase):
    """Пока агент работает, ввод не теряется: печать идёт в строку заранее."""

    def test_chars_typed_while_busy_are_kept(self):
        self.mock.queue(text("думаю…"))
        self.type_text("задача")
        self.keys(key("enter"))
        self.assertTrue(self.app.busy)
        self.type_text("следующая")
        self.keys(key("backspace"))
        self.assertIn("следующ", self.app.input.text, "печать во время работы попадает в строку")
        self.keys(key("enter"))
        self.assertTrue(self.app.busy, "Enter во время работы не отправляет задачу")
        self.assertTrue(self.pump(lambda: not self.app.busy))
        self.assertIn("следующ", self.app.input.text, "текст дожидается отправки")


class TestClipboard(ConsoleCase):
    """Ctrl+Shift+C / Ctrl+Shift+V и команды /copy, /paste."""

    def tearDown(self):
        clip.reset()
        super().tearDown()

    def test_copy_input_then_paste_back(self):
        self.type_text("текст для буфера")
        self.keys(key("ctrl+shift+c"))
        self.assertIn("скопировано", self.app.activity_text)
        self.keys(key("esc"))                     # очистить строку ввода
        self.assertTrue(self.app.input.is_empty())
        self.keys(key("ctrl+shift+v"))
        self.assertEqual(self.app.input.text, "текст для буфера")
        self.assertIn("вставлено", self.app.activity_text)

    def test_copy_last_answer_when_input_empty(self):
        self.app.add(KIND_ASSISTANT, "ответ модели для копии")
        self.keys(key("ctrl+shift+c"))
        text, _source = clip.paste(system=False)
        self.assertEqual(text, "ответ модели для копии")

    def test_copy_nothing_reports_warn(self):
        self.keys(key("ctrl+shift+c"))
        self.assertIn("копировать нечего", self.app.activity_text)

    def test_paste_empty_reports_warn(self):
        self.keys(key("ctrl+shift+v"))
        self.assertIn("буфер обмена пуст", self.app.activity_text)

    def test_slash_commands_mirror_keys(self):
        self.type_text("через команду")
        self.app.command("/copy")
        self.app.input.clear()
        self.app.command("/paste")
        self.assertEqual(self.app.input.text, "через команду")

    def test_multiline_paste_keeps_lines(self):
        clip.copy("первая\nвторая", system=False, osc=False)
        self.keys(key("ctrl+shift+v"))
        self.assertEqual(self.app.input.lines, ["первая", "вторая"])

    def test_copy_and_paste_are_in_commands_list(self):
        names = [name for name, _note in COMMANDS]
        self.assertIn("/copy", names)
        self.assertIn("/paste", names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
