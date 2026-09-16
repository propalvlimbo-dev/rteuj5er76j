#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты «ядра» интерфейса: цвет, перенос строк, клавиши, markdown, диалоги, настройки.

Запуск:  python dev/tests/test_core.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "app"))

from elytrix.config import (Catalog, Config, State, mask_key, read_key,  # noqa: E402
                            save_key)
from elytrix.dialogs import (ConfirmDialog, ListDialog, MessageDialog,  # noqa: E402
                             PromptDialog)
from elytrix.keys import KeyEvent, KeyParser, KeyReader  # noqa: E402
from elytrix import clip  # noqa: E402
from elytrix.render import (KIND_ASSISTANT, KIND_LOGO, KIND_TOOL, LOGO_ART,  # noqa: E402
                            Block, activity, header, render_tool, status_bar)
from elytrix.screen import (Palette, Style, pad, strip_ansi, terminal_size,  # noqa: E402
                            text_width, truncate, wrap_line, wrap_text)
from elytrix.theme import THEME_NAMES, Charset, Theme  # noqa: E402
from elytrix.widgets import (bar, box, human_number, inline, plural,  # noqa: E402
                             render_diff, render_markdown, seconds_text)


def theme(color: str = "none", name: str = "dark", unicode_ok: bool = True) -> Theme:
    return Theme(name, Palette(color), unicode_ok)


def row_text(line) -> str:
    """Текст одной строки без оформления."""
    return "".join(t for t, _ in line)


def texts(lines) -> list:
    """Тексты списка строк без оформления — для сравнений."""
    return [row_text(line) for line in lines]


# ---------------------------------------------------------------------------
# Экран: ширина, перенос, цвет
# ---------------------------------------------------------------------------


class TestScreen(unittest.TestCase):
    def test_width_counts_cjk_as_two(self):
        self.assertEqual(text_width("abc"), 3)
        self.assertEqual(text_width("привет"), 6)
        self.assertEqual(text_width("你好"), 4)

    def test_width_ignores_ansi(self):
        self.assertEqual(text_width("\x1b[1mжирный\x1b[0m"), 6)
        self.assertEqual(strip_ansi("\x1b[31mкрасный\x1b[0m"), "красный")

    def test_truncate(self):
        self.assertEqual(truncate("абвгдеж", 4), "абв…")
        self.assertEqual(truncate("кор", 10), "кор")
        self.assertEqual(truncate("абв", 0), "")

    def test_wrap_splits_on_spaces(self):
        st = Style()
        rows = wrap_line([("одно два три четыре пять", st)], 10)
        self.assertTrue(all(text_width("".join(t for t, _ in r)) <= 10 for r in rows))
        self.assertEqual("".join(texts(rows)).replace(" ", ""), "однодватричетырепять")

    def test_wrap_keeps_styles(self):
        bold, plain = Style(bold=True), Style()
        rows = wrap_line([("жирный ", bold), ("обычный текст подлиннее", plain)], 12)
        self.assertTrue(any(s.bold for r in rows for _t, s in r))
        self.assertTrue(any(not s.bold for r in rows for _t, s in r))

    def test_wrap_breaks_long_word(self):
        rows = wrap_line([("x" * 50, Style())], 10)
        self.assertEqual(len(rows), 5)

    def test_wrap_handles_newlines_and_indent(self):
        rows = wrap_line([("первая\nвторая", Style())], 20, indent="  ")
        self.assertEqual(len(rows), 2)
        self.assertTrue(texts(rows)[1].startswith("  "))

    def test_wrap_text_multiline(self):
        rows = wrap_text("а\nб\nв", 10)
        self.assertEqual(texts(rows), ["а", "б", "в"])

    def test_pad_fills_to_width(self):
        line = [("текст", Style())]
        out = pad(line, 12, Palette("none"))
        self.assertEqual(len(out), 12)

    def test_palette_modes(self):
        self.assertEqual(Palette("none").fg((255, 0, 0)), "")
        self.assertIn("38;2;255;0;0", Palette("truecolor").fg((255, 0, 0)))
        self.assertIn("38;5;", Palette("256").fg((255, 0, 0)))
        self.assertIn("31", Palette("16").fg((255, 0, 0)))

    def test_palette_bg_and_cache(self):
        pal = Palette("truecolor")
        first = pal.bg((0, 0, 0))
        self.assertEqual(first, pal.bg((0, 0, 0)), "кэш должен давать тот же код")
        self.assertIn("48;2", first)

    def test_style_prefix_without_color(self):
        self.assertEqual(Style(bold=True).prefix(Palette("none")), "")

    def test_detect_color_mode_respects_no_color(self):
        os.environ["NO_COLOR"] = "1"
        try:
            from elytrix.screen import detect_color_mode

            self.assertEqual(detect_color_mode(), "none")
        finally:
            os.environ.pop("NO_COLOR", None)

    def test_terminal_size_fallback(self):
        cols, rows = terminal_size((100, 30))
        self.assertGreaterEqual(cols, 20)
        self.assertGreaterEqual(rows, 8)

    def test_charset_fallback_to_ascii(self):
        self.assertEqual(Charset(False).h, "-")
        self.assertEqual(Charset(False).check, "v")
        self.assertEqual(Charset(True).h, "─")


# ---------------------------------------------------------------------------
# Клавиши
# ---------------------------------------------------------------------------


class TestKeys(unittest.TestCase):
    def parse(self, data: bytes):
        parser = KeyParser()
        events = parser.feed(data) + parser.flush()
        return [(e.name, e.text) for e in events]

    def test_plain_chars(self):
        self.assertEqual(self.parse(b"abc"), [("char", "a"), ("char", "b"), ("char", "c")])

    def test_cyrillic_and_utf8_split(self):
        parser = KeyParser()
        first = parser.feed(b"\xd0")
        second = parser.feed(b"\xbf")
        self.assertEqual([(e.name, e.text) for e in first + second], [("char", "п")])

    def test_arrows_and_modifiers(self):
        self.assertEqual(self.parse(b"\x1b[A"), [("up", "")])
        self.assertEqual(self.parse(b"\x1b[B"), [("down", "")])
        self.assertEqual(self.parse(b"\x1b[1;5C"), [("ctrl+right", "")])
        self.assertEqual(self.parse(b"\x1b[1;3A"), [("alt+up", "")])
        self.assertEqual(self.parse(b"\x1b[Z"), [("shift+tab", "")])

    def test_editing_keys(self):
        self.assertEqual(self.parse(b"\x7f"), [("backspace", "")])
        self.assertEqual(self.parse(b"\x08"), [("backspace", "")])
        self.assertEqual(self.parse(b"\x1b[3~"), [("delete", "")])
        self.assertEqual(self.parse(b"\t"), [("tab", "")])
        self.assertEqual(self.parse(b"\r"), [("enter", "")])
        self.assertEqual(self.parse(b"\x0a"), [("newline", "")])

    def test_ctrl_combinations(self):
        for byte, name in ((b"\x03", "ctrl+c"), (b"\x04", "ctrl+d"), (b"\x0c", "ctrl+l"),
                           (b"\x17", "ctrl+w"), (b"\x15", "ctrl+u"), (b"\x0b", "ctrl+k")):
            self.assertEqual(self.parse(byte), [(name, "")])

    def test_alt_enter_is_newline_shortcut(self):
        self.assertEqual(self.parse(b"\x1b\r"), [("alt+enter", "")])

    def test_bracketed_paste(self):
        events = self.parse(b"\x1b[200~\xd0\xbf\xd1\x80\xd0\xb8\xd0\xb2\xd0\xb5\xd1\x82\n"
                            b"\xd0\xb2\xd1\x82\xd0\xbe\xd1\x80\xd0\xb0\xd1\x8f\x1b[201~")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0], "paste")
        self.assertEqual(events[0][1], "привет\nвторая")

    def test_paste_split_across_reads(self):
        parser = KeyParser()
        first = parser.feed(b"\x1b[200~abc")
        second = parser.feed(b"def\x1b[201~tail")
        names = [(e.name, e.text) for e in first + second]
        self.assertEqual(names[0], ("paste", "abcdef"))
        self.assertIn(("char", "t"), names)

    def test_lone_esc_needs_timeout(self):
        import time

        parser = KeyParser()
        self.assertEqual(parser.feed(b"\x1b"), [])
        time.sleep(0.06)
        self.assertEqual([e.name for e in parser.feed(b"")], ["esc"])

    def test_broken_sequence_does_not_hang(self):
        parser = KeyParser()
        events = parser.feed(b"\x1b[") + parser.flush()
        self.assertIsInstance(events, list)

    def test_modify_other_keys_clipboard_combos(self):
        # CSI 27;мод;код~ — так терминал присылает Ctrl+Shift+C / Ctrl+Shift+V
        self.assertEqual(self.parse(b"\x1b[27;6;67~"), [("ctrl+shift+c", "")])
        self.assertEqual(self.parse(b"\x1b[27;6;86~"), [("ctrl+shift+v", "")])
        self.assertEqual(self.parse(b"\x1b[27;5;65~"), [("ctrl+a", "")])

    def test_kitty_protocol_clipboard_combos(self):
        self.assertEqual(self.parse(b"\x1b[99;6u"), [("ctrl+shift+c", "")])
        self.assertEqual(self.parse(b"\x1b[118;6u"), [("ctrl+shift+v", "")])

    def test_windows_burst_feed_typing_and_enter(self):
        events = KeyReader.feed_raw(list("задача\r"))
        self.assertEqual([e.name for e in events][-1], "enter")
        self.assertEqual("".join(e.text for e in events if e.is_char), "задача")

    def test_windows_burst_feed_multiline_paste(self):
        events = KeyReader.feed_raw(list("первая\r\nвторая\r\nтретья"))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].name, "paste")
        self.assertEqual(events[0].text, "первая\nвторая\nтретья")

    def test_windows_console_events_mapping(self):
        from elytrix.keys import win_key_events

        items = [(ch, 0, False, False, False) for ch in "привет"] + [("\r", 0, False, False, False)]
        events = win_key_events(items)
        self.assertEqual([e.name for e in events][-1], "enter")
        self.assertEqual("".join(e.text for e in events if e.is_char), "привет")

    def test_windows_console_clipboard_combos(self):
        from elytrix.keys import win_key_events

        events = win_key_events([("\x03", 67, True, True, False),
                                 ("\x16", 86, True, True, False)])
        self.assertEqual([e.name for e in events], ["ctrl+shift+c", "ctrl+shift+v"])

    def test_windows_console_arrows_and_alt(self):
        from elytrix.keys import win_key_events

        events = win_key_events([("", 0x25, True, False, False),
                                 ("\r", 0, False, False, True)])
        self.assertEqual([e.name for e in events], ["ctrl+left", "alt+enter"])

    def test_windows_console_multiline_paste_burst(self):
        from elytrix.keys import win_key_events

        events = win_key_events([(ch, 0, False, False, False) for ch in "а\r\nб"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].name, "paste")

    def test_reader_is_safe_without_tty(self):
        reader = KeyReader()
        reader.open()
        events = reader.read(0.01)
        self.assertEqual(events, [])
        reader.close()

    def test_key_event_equality(self):
        self.assertEqual(KeyEvent("char", "a"), KeyEvent("char", "a"))
        self.assertNotEqual(KeyEvent("char", "a"), KeyEvent("enter"))
        self.assertTrue(KeyEvent("char", "a").is_char)


# ---------------------------------------------------------------------------
# Виджеты: markdown, diff, шкалы
# ---------------------------------------------------------------------------


class TestWidgets(unittest.TestCase):
    def test_markdown_heading_and_paragraph(self):
        th = theme()
        rows = render_markdown("# Заголовок\n\nОбычный текст.", th, 60)
        joined = "\n".join(texts(rows))
        self.assertIn("Заголовок", joined)
        self.assertIn("Обычный текст.", joined)
        self.assertTrue(any(s.bold for r in rows for _t, s in r))

    def test_markdown_list(self):
        rows = render_markdown("- первый\n- второй\n  - вложенный", theme(), 60)
        self.assertEqual(len([r for r in rows if row_text(r).strip()]), 3)
        self.assertTrue(row_text(rows[-1]).startswith("  "), "вложенный пункт — с отступом")

    def test_markdown_code_block_is_framed(self):
        rows = render_markdown("```python\ndef f():\n    return 1\n```", theme(), 60)
        joined = texts(rows)
        self.assertIn("def f():", " ".join(joined))
        self.assertTrue(any("python" in t for t in joined))
        self.assertTrue(all(text_width(t) <= 60 for t in joined))

    def test_markdown_inline_styles(self):
        line = inline("это **жирный** и `код` и [ссылка](http://x)", theme())
        text = "".join(t for t, _ in line)
        self.assertIn("жирный", text)
        self.assertIn("код", text)
        self.assertNotIn("**", text)
        self.assertNotIn("`", text)

    def test_markdown_table_is_aligned(self):
        rows = render_markdown("| a | bb |\n|---|---|\n| 1 | 22 |", theme(), 60)
        widths = {text_width(row_text(r)) for r in rows}
        self.assertEqual(len(widths), 1, "строки таблицы должны быть одной ширины")

    def test_markdown_quote_and_rule(self):
        rows = render_markdown("> цитата\n\n---", theme(), 40)
        self.assertIn("цитата", " ".join(texts(rows)))

    def test_markdown_respects_width(self):
        text = "слово " * 100
        for width in (30, 60, 120):
            rows = render_markdown(text, theme(), width)
            self.assertTrue(all(text_width("".join(t for t, _ in r)) <= width for r in rows))

    def test_diff_colors(self):
        rows = render_diff("--- a\n+++ b\n@@ -1 +1 @@\n-старое\n+новое", theme(), 60)
        self.assertEqual(len(rows), 5)

    def test_diff_is_limited(self):
        diff = "\n".join(f"+строка {i}" for i in range(100))
        rows = render_diff(diff, theme(), 60, max_lines=10)
        self.assertLessEqual(len(rows), 11)
        self.assertIn("ещё", " ".join(texts(rows)))

    def test_bar(self):
        line = bar(0.5, 10, theme())
        self.assertEqual(text_width("".join(t for t, _ in line)), 10)
        self.assertEqual(bar(2.0, 10, theme()), bar(1.0, 10, theme()))

    def test_box_wraps_content(self):
        rows = box([[("очень длинный текст который не влезает в рамку", Style())]],
                   theme(), 30, title="заголовок")
        self.assertTrue(all(text_width("".join(t for t, _ in r)) <= 30 for r in rows))
        self.assertIn("заголовок", texts(rows)[0])

    def test_human_number(self):
        self.assertEqual(human_number(999), "999")
        self.assertEqual(human_number(1500), "1.5K")
        self.assertEqual(human_number(12000), "12K")
        self.assertEqual(human_number(2_500_000), "2.5M")
        self.assertEqual(human_number(0), "0")

    def test_plural(self):
        self.assertEqual(plural(1, "шаг", "шага", "шагов"), "шаг")
        self.assertEqual(plural(2, "шаг", "шага", "шагов"), "шага")
        self.assertEqual(plural(5, "шаг", "шага", "шагов"), "шагов")
        self.assertEqual(plural(11, "шаг", "шага", "шагов"), "шагов")
        self.assertEqual(plural(21, "шаг", "шага", "шагов"), "шаг")

    def test_seconds_text(self):
        self.assertEqual(seconds_text(1.234), "1.2с")
        self.assertEqual(seconds_text(45), "45с")
        self.assertEqual(seconds_text(125), "2м05с")

    def test_highlight_does_not_crash_on_odd_input(self):
        from elytrix.widgets import highlight

        for lang in ("python", "js", "", "brainfuck"):
            rows = highlight("def x(:\n  'unterminated\n# comment", lang, theme(), 40)
            self.assertTrue(rows)


# ---------------------------------------------------------------------------
# Блоки ленты
# ---------------------------------------------------------------------------


class TestRender(unittest.TestCase):
    def test_block_caches_until_touched(self):
        block = Block(KIND_ASSISTANT, "текст")
        first = block.lines(theme(), 60)
        block.text = "другой текст"
        self.assertEqual(texts(block.lines(theme(), 60)), texts(first),
                         "без touch() кэш остаётся — это осознанно")
        block.touch()
        self.assertIn("другой текст", texts(block.lines(theme(), 60))[0])

    def test_append_text_invalidates_cache(self):
        block = Block(KIND_ASSISTANT, "раз ")
        block.lines(theme(), 60)
        block.append_text("два")
        self.assertIn("два", " ".join(texts(block.lines(theme(), 60))))

    def test_tool_block_states(self):
        th = theme()
        running = render_tool({"name": "read", "state": "run", "target": "a.py"}, th, 60)
        done = render_tool({"name": "read", "state": "done", "ok": True,
                            "target": "a.py", "summary": "10 строк", "elapsed": 0.2}, th, 60)
        failed = render_tool({"name": "bash", "state": "done", "ok": False,
                              "target": "pytest", "summary": "код 1"}, th, 60)
        self.assertIn(th.charset.play, texts(running)[0])
        self.assertIn(th.charset.check, texts(done)[0])
        self.assertIn(th.charset.cross_mark, texts(failed)[0])
        self.assertIn("0.2с", texts(done)[0])

    def test_tool_block_verbose_shows_diff(self):
        th = theme()
        meta = {"name": "edit", "state": "done", "ok": True, "target": "a.py",
                "summary": "замен 1", "diff": "--- a\n+++ b\n@@\n-старое\n+новое"}
        short = render_tool(meta, th, 80, verbose=False)
        long = render_tool(meta, th, 80, verbose=True)
        self.assertEqual(len(short), 1)
        self.assertGreater(len(long), 1)
        self.assertIn("новое", " ".join(texts(long)))

    def test_header_fits_width(self):
        th = theme()
        for width in (40, 60, 120):
            rows = header(th, width, "ELYTRIX", "3.0",
                          [("claude-sonnet-4-6 ×2", "accent2"), ("проект", "dim")])
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(text_width("".join(t for t, _ in r)) <= width for r in rows))

    def test_status_bar_fits_width(self):
        th = theme()
        row = status_bar(th, 60, [("ask", "warn"), ("ctx 12%", "dim")], 0.35, "45K/400K")
        self.assertLessEqual(text_width(row_text(row)), 60)

    def test_activity_line(self):
        th = theme()
        busy = activity(th, 60, True, 3, "думаю", "шаг 1/24")
        idle = activity(th, 60, False, 0, "✓ готово за 2.0с", "")
        self.assertIn("думаю", row_text(busy))
        self.assertIn("шаг 1/24", row_text(busy))
        self.assertIn("готово", row_text(idle))


# ---------------------------------------------------------------------------
# Диалоги
# ---------------------------------------------------------------------------


class TestDialogs(unittest.TestCase):
    def test_list_dialog_navigation(self):
        items = [("модель A", "a", "дешёвая"), ("модель B", "b", "дорогая")]
        dialog = ListDialog("Модель", items)
        th = theme()
        self.assertEqual(dialog.selected, 0)
        dialog.key(KeyEvent("down"), th, 80, 20)
        self.assertEqual(dialog.selected, 1)
        self.assertEqual(dialog.key(KeyEvent("enter"), th, 80, 20), "b")
        dialog.key(KeyEvent("up"), th, 80, 20)
        self.assertEqual(dialog.selected, 0)

    def test_list_dialog_wraps_around(self):
        dialog = ListDialog("x", [("a", 1, ""), ("b", 2, "")])
        dialog.key(KeyEvent("up"), theme(), 80, 20)
        self.assertEqual(dialog.selected, 1)

    def test_list_dialog_digit_selection(self):
        items = [(f"модель {i}", i, "") for i in range(1, 13)]
        dialog = ListDialog("Модель", items)
        th = theme()
        for ch in "12":
            dialog.key(KeyEvent("char", ch), th, 80, 30)
        self.assertEqual(dialog.selected, 11)
        self.assertEqual(dialog.key(KeyEvent("enter"), th, 80, 30), 12)

    def test_list_dialog_text_filter(self):
        items = [("claude-opus-5", "opus", ""), ("gpt-5.6-luna", "luna", "")]
        dialog = ListDialog("Модель", items, allow_text=True)
        th = theme()
        for ch in "gpt":
            dialog.key(KeyEvent("char", ch), th, 80, 20)
        self.assertEqual(dialog.selected, 1)

    def test_list_dialog_render_width(self):
        dialog = ListDialog("Очень длинный заголовок диалога",
                            [("пункт", "v", "пояснение к пункту")])
        rows, height = dialog.render(theme(), 60, 20)
        self.assertEqual(height, len(rows))
        self.assertTrue(all(text_width("".join(t for t, _ in r)) <= 60 for r in rows))

    def test_prompt_dialog_editing(self):
        dialog = PromptDialog("Ключ", default="abc")
        th = theme()
        dialog.key(KeyEvent("char", "d"), th, 80, 20)
        self.assertEqual(dialog.value, "abcd")
        dialog.key(KeyEvent("backspace"), th, 80, 20)
        self.assertEqual(dialog.value, "abc")
        dialog.key(KeyEvent("home"), th, 80, 20)
        dialog.key(KeyEvent("char", "z"), th, 80, 20)
        self.assertEqual(dialog.value, "zabc")
        dialog.key(KeyEvent("ctrl+u"), th, 80, 20)
        self.assertEqual(dialog.value, "")
        self.assertEqual(dialog.key(KeyEvent("esc"), th, 80, 20), False)

    def test_prompt_dialog_paste_and_submit(self):
        dialog = PromptDialog("Путь")
        th = theme()
        dialog.key(KeyEvent("paste", "C:\\Projects\\bot\n"), th, 80, 20)
        self.assertEqual(dialog.key(KeyEvent("enter"), th, 80, 20), "C:\\Projects\\bot")

    def test_prompt_dialog_validation(self):
        dialog = PromptDialog("Лимит", default="", validate=lambda v: "" if v.isdigit() else "нужно число")
        th = theme()
        dialog.key(KeyEvent("char", "x"), th, 80, 20)
        self.assertIsNone(dialog.key(KeyEvent("enter"), th, 80, 20))
        self.assertIn("нужно число", dialog.error)
        dialog.key(KeyEvent("ctrl+u"), th, 80, 20)
        for ch in "500":
            dialog.key(KeyEvent("char", ch), th, 80, 20)
        self.assertEqual(dialog.key(KeyEvent("enter"), th, 80, 20), "500")

    def test_prompt_dialog_hides_secret(self):
        dialog = PromptDialog("Ключ", secret=True, default="sk-smart-secret")
        rows = dialog.body(theme(), 60)
        self.assertNotIn("sk-smart-secret", " ".join(texts(rows)))
        self.assertTrue(dialog.cursor_pos)

    def test_confirm_dialog_keys(self):
        dialog = ConfirmDialog("edit", "правка main.py", detail="+1 −1",
                               diff="--- a\n+++ b\n@@\n-x\n+y")
        th = theme()
        self.assertEqual(dialog.key(KeyEvent("char", "y"), th, 100, 30), "yes")
        self.assertEqual(dialog.key(KeyEvent("char", "a"), th, 100, 30), "always")
        self.assertEqual(dialog.key(KeyEvent("char", "n"), th, 100, 30), "no")
        self.assertEqual(dialog.key(KeyEvent("char", "s"), th, 100, 30), "stop")
        self.assertEqual(dialog.key(KeyEvent("char", "д"), th, 100, 30), "yes")
        self.assertEqual(dialog.key(KeyEvent("esc"), th, 100, 30), "no")

    def test_confirm_dialog_shows_diff(self):
        dialog = ConfirmDialog("edit", "правка", diff="--- a\n+++ b\n@@\n-старое\n+новое")
        rows = dialog.body(theme(), 80)
        self.assertIn("новое", " ".join(texts(rows)))

    def test_message_dialog_scrolls(self):
        dialog = MessageDialog("Длинный текст", "\n".join(f"строка {i}" for i in range(80)))
        th = theme()
        rows, height = dialog.render(th, 60, 15)
        self.assertLessEqual(height, 15)
        dialog.key(KeyEvent("pagedown"), th, 60, 15)
        self.assertGreater(dialog.scroll, 0)
        dialog.key(KeyEvent("up"), th, 60, 15)
        dialog.key(KeyEvent("esc"), th, 60, 15)

    def test_dialog_render_is_rectangular(self):
        for dialog in (MessageDialog("t", "текст\nвторой"),
                       ListDialog("t", [("a", 1, "b")]),
                       PromptDialog("t", default="x"),
                       ConfirmDialog("edit", "s", diff="-a\n+b")):
            rows, height = dialog.render(theme(), 70, 20)
            self.assertEqual(height, len(rows))
            widths = {text_width(row_text(r)) for r in rows}
            self.assertEqual(len(widths), 1, f"{type(dialog).__name__}: рамка должна быть ровной")


# ---------------------------------------------------------------------------
# Настройки, каталог, состояние
# ---------------------------------------------------------------------------


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="elytrix-cfg-")
        os.environ["ELYTRIX_HOME"] = self.home

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        os.environ.pop("ELYTRIX_HOME", None)
        os.environ.pop("SMARTAPI_KEY", None)

    def test_defaults_are_present_without_file(self):
        cfg = Config.load(os.path.join(self.home, "нет-такого.json"))
        self.assertEqual(cfg.get("gateway.base_url"), "https://api.smartapi.shop")
        self.assertEqual(cfg.get("limits.daily_tokens"), 400000)
        self.assertEqual(cfg.get("ui.theme"), "rose")

    def test_project_config_is_loaded(self):
        cfg = Config.load()
        self.assertEqual(cfg.get("gateway.base_url"), "https://api.smartapi.shop")
        self.assertIn("claude-sonnet-4-6", cfg.get("models.catalog"))

    def test_user_values_override_defaults(self):
        cfg = Config({"limits": {"daily_tokens": 12345}, "ui": {"theme": "mono"}})
        self.assertEqual(cfg.get("limits.daily_tokens"), 12345)
        self.assertEqual(cfg.get("ui.theme"), "mono")
        self.assertEqual(cfg.get("limits.max_steps"), 24, "остальные значения остаются")

    def test_set_and_save(self):
        path = os.path.join(self.home, "cfg.json")
        cfg = Config({}, path)
        cfg.set("ui.theme", "night")
        self.assertTrue(cfg.save())
        again = Config.load(path)
        self.assertEqual(again.get("ui.theme"), "night")

    def test_get_missing_returns_default(self):
        cfg = Config({})
        self.assertEqual(cfg.get("нет.такого.пути", "дефолт"), "дефолт")

    def test_catalog_aliases(self):
        catalog = Catalog(dict(Config({}).get("models")))
        self.assertEqual(catalog.resolve("auto"), "claude-sonnet-4-6")
        self.assertEqual(catalog.resolve("cheap"), "gpt-5.6-luna")
        self.assertEqual(catalog.resolve("smart"), "claude-opus-4-8")
        self.assertEqual(catalog.resolve("max"), "claude-opus-5")
        self.assertEqual(catalog.resolve("gpt-6-astra"), "gpt-6-astra")
        self.assertTrue(catalog.is_alias("auto"))
        self.assertFalse(catalog.is_alias("gpt-6-astra"))

    def test_catalog_multipliers(self):
        catalog = Catalog(dict(Config({}).get("models")))
        self.assertEqual(catalog.multiplier("gpt-5.6-luna"), 1.7)
        self.assertEqual(catalog.multiplier("claude-fable-5"), 10.0)
        self.assertEqual(catalog.multiplier("неизвестная"), 1.0)
        self.assertEqual(catalog.price_word(1.7), "дёшево")
        self.assertEqual(catalog.price_word(10.0), "не тратить зря")

    def test_catalog_families_and_sorting(self):
        catalog = Catalog(dict(Config({}).get("models")))
        self.assertEqual(catalog.family("claude-opus-5"), "Claude")
        self.assertEqual(catalog.family("gpt-5.6-sol"), "GPT")
        self.assertEqual(catalog.family("codex-auto-review"), "Codex")
        models = catalog.all_models()
        self.assertEqual(models[0], "gpt-5.6-luna")

    def test_catalog_adds_unknown_models(self):
        catalog = Catalog(dict(Config({}).get("models")))
        added = catalog.add_models(["brand-new-model", "claude-opus-5"])
        self.assertEqual(added, 1)
        self.assertIn("brand-new-model", catalog.all_models())

    def test_key_roundtrip(self):
        os.environ.pop("SMARTAPI_KEY", None)
        self.assertEqual(read_key(), ("", ""))
        path = save_key("sk-smart-abcdef123456", persistent=False)
        self.assertTrue(os.path.isfile(path))
        os.environ.pop("SMARTAPI_KEY", None)   # save_key дублирует ключ в окружение процесса
        key, source = read_key()
        self.assertEqual(key, "sk-smart-abcdef123456")
        self.assertEqual(source, "file")
        if os.name != "nt":
            mode = os.stat(path).st_mode & 0o777
            self.assertEqual(mode, 0o600, "файл ключа не должен читаться всеми")

    def test_env_key_wins(self):
        save_key("sk-smart-from-file", persistent=False)
        os.environ["SMARTAPI_KEY"] = "sk-smart-from-env"
        key, source = read_key()
        self.assertEqual(key, "sk-smart-from-env")
        self.assertEqual(source, "env")

    def test_mask_key(self):
        self.assertEqual(mask_key(""), "(нет ключа)")
        masked = mask_key("sk-smart-0123456789abcdef")
        self.assertIn("…", masked)
        self.assertNotIn("0123456789abcdef", masked)

    def test_state_record_and_roll(self):
        state = State()
        charged = state.record("claude-sonnet-4-6", 1000, 200, 2.0, cache_read=500)
        self.assertEqual(charged, 2400)
        self.assertEqual(state.tokens_day, 2400)
        self.assertEqual(state.requests_day, 1)
        self.assertEqual(state.by_model()["claude-sonnet-4-6"]["cache_read"], 500)
        state.data["day"] = "2000-01-01"
        state.save()
        fresh = State()
        self.assertEqual(fresh.tokens_day, 0)
        self.assertEqual(len(fresh.history()), 1)

    def test_state_get_set(self):
        state = State()
        state.set("last_workspace", "/tmp/x")
        self.assertEqual(State().get("last_workspace"), "/tmp/x")
        self.assertIsNone(state.get("нет"))
        self.assertEqual(state.get("нет", "дефолт"), "дефолт")

    def test_state_file_is_valid_json(self):
        state = State()
        state.record("gpt-5.6-luna", 10, 10, 1.7)
        with open(state.path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("by_model", data)
        self.assertIn("day", data)


class TestLogo(unittest.TestCase):
    def test_logo_is_centered_as_one_column(self):
        rows = Block(KIND_LOGO, LOGO_ART).lines(theme(), 100)
        self.assertEqual(len(rows), 6)
        lefts = {row_text(r).index("█") if "█" in row_text(r) else -1
                 for r in rows}
        texts = [row_text(r) for r in rows]
        pads = {len(t) - len(t.lstrip(" ")) for t in texts}
        self.assertEqual(len(pads), 1, "все строки логотипа начинаются с одной колонки")

    def test_logo_fits_narrow_terminal(self):
        rows = Block(KIND_LOGO, LOGO_ART).lines(theme(), 30)
        self.assertEqual(len(rows), 1)
        self.assertIn("ELYTRIX", row_text(rows[0]).replace(" ", ""))

    def test_logo_keeps_gradient_styles(self):
        rows = Block(KIND_LOGO, LOGO_ART).lines(Theme("rose"), 100)
        first = rows[0][1][1].fg
        last = rows[-1][1][1].fg
        self.assertNotEqual(first, last, "градиент от белого к розовому")
        self.assertGreater(first[0], 200)


class TestClip(unittest.TestCase):
    def tearDown(self):
        clip.reset()

    def test_internal_fallback_roundtrip(self):
        backend = clip.copy("привет мир", system=False, osc=False)
        self.assertEqual(backend, "внутренний")
        text, source = clip.paste(system=False)
        self.assertEqual(text, "привет мир")
        self.assertEqual(source, "внутренний")

    def test_osc52_payload_is_base64(self):
        import base64
        import io
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            backend = clip.copy("abc", system=False, osc=True)
        self.assertEqual(backend, "терминал")
        out = buf.getvalue()
        self.assertIn("\x1b]52;c;", out)
        payload = out.split(";c;")[1].split("\x07")[0]
        self.assertEqual(base64.b64decode(payload).decode(), "abc")

    def test_paste_empty_without_buffers(self):
        clip.reset()
        text, source = clip.paste(system=False)
        self.assertEqual(text, "")
        self.assertEqual(source, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
