# -*- coding: utf-8 -*-
"""Диалоги поверх ленты: справки, списки, ввод текста, подтверждения правок.

Диалог — это объект, который умеет нарисовать себя в коробке по центру экрана и
обработать нажатие. Возврат из ``key()``: ``None`` — диалог остаётся открытым,
любое другое значение — результат (строка, номер, ``True/False``), диалог закрывается.
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Sequence, Tuple

from .keys import KeyEvent
from .render import visible
from .screen import Line, text_width, truncate, wrap_line, wrap_text
from .theme import Theme
from .widgets import render_diff, render_markdown


class Dialog:
    """Общий каркас: коробка, прокрутка, подсказка внизу."""

    def __init__(self, title: str, hint: str = "", max_width: int = 96, role: str = "border_active"):
        self.title = title
        self.hint = hint
        self.max_width = max_width
        self.role = role
        self.scroll = 0
        self.result: Any = None
        self.closed = False

    # -- что рисуем внутри --------------------------------------------------

    def body(self, theme: Theme, width: int) -> List[Line]:
        return []

    @property
    def chrome(self) -> int:
        """Сколько строк занимают рамки и подсказки — их надо вычесть из высоты экрана."""
        return 2 + (2 if self.hint else 0)

    def render(self, theme: Theme, width: int, height: int) -> Tuple[List[Line], int]:
        """Возвращает (строки диалога, высота). Высота нужна, чтобы отцентровать."""
        cs = theme.charset
        box_w = max(30, min(self.max_width, width - 4))
        inner = box_w - 5      # рамка + два пробела слева + текст + пробел + рамка
        rows = self.body(theme, inner)
        avail = max(3, height - self.chrome)
        if len(rows) > avail:
            self.scroll = max(0, min(self.scroll, len(rows) - avail))
            rows = rows[self.scroll:self.scroll + avail]
        else:
            self.scroll = 0
        border = theme.style(self.role)
        head_text = f" {self.title} "
        head = cs.tl + cs.h + head_text
        head += cs.h * max(0, box_w - text_width(head) - 1) + cs.tr
        out: List[Line] = [[(head, border)]]
        pad_left = (" " * 2, theme.style("fg"))
        pad_right = (" ", theme.style("fg"))
        for row in rows:
            gap = max(0, inner - visible(row))
            out.append([(cs.v, border), pad_left] + row
                       + [(" " * gap, theme.style("fg")), pad_right, (cs.v, border)])
        if self.hint:
            hint_rows = wrap_line([(self.hint, theme.style("faint"))], inner)
            for row in hint_rows[:2]:
                gap = max(0, inner - visible(row))
                out.append([(cs.v, border), pad_left] + row
                           + [(" " * gap, theme.style("fg")), pad_right, (cs.v, border)])
        foot = cs.bl + cs.h * max(0, box_w - 2) + cs.br
        out.append([(foot, border)])
        return out, len(out)

    # -- ввод ---------------------------------------------------------------

    def key(self, ev: KeyEvent, theme: Theme, width: int, height: int) -> Any:
        """None — остаёмся открытыми, иначе результат."""
        rows = len(self.body(theme, max(30, min(self.max_width, width - 4)) - 5))
        avail = max(3, height - self.chrome)
        if ev.name in ("up", "ctrl+p"):
            self.scroll = max(0, self.scroll - 1)
            return None
        if ev.name in ("down", "ctrl+n"):
            self.scroll = min(max(0, rows - avail), self.scroll + 1)
            return None
        if ev.name == "pageup":
            self.scroll = max(0, self.scroll - avail)
            return None
        if ev.name == "pagedown":
            self.scroll = min(max(0, rows - avail), self.scroll + avail)
            return None
        if ev.name in ("esc", "ctrl+c", "enter", "q"):
            return self.cancel_value()
        return None

    def cancel_value(self) -> Any:
        return False


class MessageDialog(Dialog):
    """Текстовая панель: справка, статистика, журнал, ошибки."""

    def __init__(self, title: str, text: str, hint: str = "Esc — закрыть",
                 markdown: bool = True, role: str = "border_active", max_width: int = 96):
        super().__init__(title, hint, max_width=max_width, role=role)
        self.text = text
        self.markdown = markdown

    def body(self, theme: Theme, width: int) -> List[Line]:
        if self.markdown:
            return render_markdown(self.text, theme, width)
        out: List[Line] = []
        for raw in self.text.split("\n"):
            out.extend(wrap_line([(raw, theme.style("fg"))], width))
        return out


class ListDialog(Dialog):
    """Список с выбором: модели, темы, папки, режимы.

    ``items`` — последовательность (метка, значение, пояснение). Выбор стрелками,
    цифрами или вводом начала метки; Enter возвращает значение.
    """

    def __init__(self, title: str, items: Sequence[Tuple[str, Any, str]],
                 hint: str = "↑↓ выбор · Enter — взять · Esc — отмена",
                 selected: int = 0, allow_text: bool = False):
        super().__init__(title, hint)
        self.items = list(items)
        self.selected = max(0, min(selected, len(self.items) - 1)) if self.items else 0
        self.allow_text = allow_text
        self.typed = ""          # текстовый фильтр
        self.number = ""         # набираемый номер

    def visible_items(self) -> int:
        return max(3, len(self.items))

    def body(self, theme: Theme, width: int) -> List[Line]:
        out: List[Line] = []
        if self.typed:
            out.extend(wrap_line([("фильтр: ", theme.style("dim")),
                                  (self.typed, theme.style("accent", bold=True))], width))
        if self.number:
            out.extend(wrap_line([("номер: ", theme.style("dim")),
                                  (self.number, theme.style("accent", bold=True))], width))
        for i, (label, _value, note) in enumerate(self.items):
            active = i == self.selected
            marker = "❯ " if active else "  "
            label_style = theme.style("accent", bold=True) if active else theme.style("fg")
            row: Line = [(marker, theme.style("accent") if active else theme.style("faint")),
                         (f"{i + 1:>2}. ", theme.style("faint")),
                         (truncate(label, max(6, int(width * 0.42))), label_style)]
            if note:
                room = max(6, width - visible(row) - 2)
                row.append(("  ", theme.style("fg")))
                row.append((truncate(note, room), theme.style("dim")))
            out.append(row)
        return out

    def _filtered_index(self, text: str) -> Optional[int]:
        """Сначала совпадение по началу метки, потом — по вхождению («luna» находит модель)."""
        low = text.lower()
        for i, (label, value, _note) in enumerate(self.items):
            if label.lower().startswith(low) or str(value).lower().startswith(low):
                return i
        for i, (label, value, _note) in enumerate(self.items):
            if low in label.lower() or low in str(value).lower():
                return i
        return None

    def key(self, ev: KeyEvent, theme: Theme, width: int, height: int) -> Any:
        if ev.name in ("up", "ctrl+p", "shift+tab"):
            self.selected = (self.selected - 1) % max(1, len(self.items))
            self._keep_visible(height)
            return None
        if ev.name in ("down", "ctrl+n", "tab"):
            self.selected = (self.selected + 1) % max(1, len(self.items))
            self._keep_visible(height)
            return None
        if ev.name in ("pageup", "pagedown"):
            step = max(3, height - 4)
            self.selected = max(0, min(len(self.items) - 1,
                                       self.selected + (-step if ev.name == "pageup" else step)))
            self._keep_visible(height)
            return None
        if ev.name == "home":
            self.selected = 0
            return None
        if ev.name == "end":
            self.selected = max(0, len(self.items) - 1)
            return None
        # цифры листают список, пока не начали набирать текст: иначе в именах моделей
        # вроде gpt-5.6-luna цифры съедались бы как номер пункта
        if ev.is_char and ev.text.isdigit() and not self.typed:
            candidate = (self.number + ev.text)[:3]
            if int(candidate or 0) <= len(self.items):
                self.number = candidate
                index = int(self.number) - 1
                if 0 <= index < len(self.items):
                    self.selected = index
                    self._keep_visible(height)
            return None
        if ev.is_char and self.allow_text:
            self.typed += ev.text
            hit = self._filtered_index(self.typed)
            if hit is not None:
                self.selected = hit
            return None
        if ev.name == "backspace":
            self.number = self.number[:-1]
            if not self.number and self.typed:
                self.typed = self.typed[:-1]
            return None
        if ev.name in ("enter", "ctrl+m"):
            if self.items:
                return self.items[self.selected][1]
            return False
        return super().key(ev, theme, width, height)

    def _keep_visible(self, height: int) -> None:
        avail = max(3, height - 4)
        if len(self.items) <= avail:
            self.scroll = 0
            return
        if self.selected < self.scroll:
            self.scroll = self.selected
        elif self.selected >= self.scroll + avail:
            self.scroll = self.selected - avail + 1


class PromptDialog(Dialog):
    """Однострочный ввод: ключ, путь к папке, имя модели, новое значение лимита."""

    def __init__(self, title: str, hint: str = "", default: str = "",
                 secret: bool = False, note: str = "",
                 validate: Optional[Callable[[str], str]] = None,
                 submit_text: str = "Enter — принять, Esc — отмена"):
        super().__init__(title, submit_text)
        self.value = default
        self.col = len(default)
        self.secret = secret
        self.note = note
        self.hint_text = hint
        self.error = ""
        self.validate = validate or (lambda v: "")
        #: (строка внутри body, колонка внутри строки) — куда ставить каретку терминала
        self.cursor_pos: Optional[Tuple[int, int]] = None

    def body(self, theme: Theme, width: int) -> List[Line]:
        out: List[Line] = []
        if self.hint_text:
            out.extend(wrap_line([(self.hint_text, theme.style("dim"))], width))
        if self.note:
            out.extend(wrap_line([(self.note, theme.style("faint"))], width))
        shown = ("•" * len(self.value)) if self.secret else self.value
        field: Line = [("> ", theme.style("accent", bold=True)),
                       (shown, theme.style("fg"))]
        self.cursor_pos = (len(out), 2 + text_width(shown[:self.col]))
        out.extend(wrap_line(field, width))
        if self.error:
            out.extend(wrap_line([(self.error, theme.style("err"))], width))
        return out

    def cursor_offset(self) -> int:
        return self.col

    def key(self, ev: KeyEvent, theme: Theme, width: int, height: int) -> Any:
        if ev.name == "esc" or ev.name == "ctrl+c":
            return False
        if ev.name in ("enter", "ctrl+m"):
            problem = self.validate(self.value.strip())
            if problem:
                self.error = problem
                return None
            return self.value.strip()
        if ev.name == "backspace":
            if self.col > 0:
                self.value = self.value[:self.col - 1] + self.value[self.col:]
                self.col -= 1
                self.error = ""
            return None
        if ev.name == "delete":
            self.value = self.value[:self.col] + self.value[self.col + 1:]
            return None
        if ev.name == "left":
            self.col = max(0, self.col - 1)
            return None
        if ev.name == "right":
            self.col = min(len(self.value), self.col + 1)
            return None
        if ev.name in ("home", "ctrl+a"):
            self.col = 0
            return None
        if ev.name in ("end", "ctrl+e"):
            self.col = len(self.value)
            return None
        if ev.name == "ctrl+u":
            self.value, self.col = "", 0
            return None
        if ev.name == "ctrl+k":
            self.value, self.col = self.value[:self.col], self.col
            return None
        if ev.name == "paste":
            text = ev.text.replace("\r\n", "\n").replace("\r", "\n").strip()
            self.value = self.value[:self.col] + text + self.value[self.col:]
            self.col += len(text)
            self.error = ""
            return None
        if ev.is_char:
            self.value = self.value[:self.col] + ev.text + self.value[self.col:]
            self.col += len(ev.text)
            self.error = ""
            return None
        return None


class ConfirmDialog(Dialog):
    """Подтверждение правки или команды: показываем, что именно изменится."""

    def __init__(self, tool: str, summary: str, detail: str = "", diff: str = "",
                 command: str = "", theme_role: str = "warn"):
        super().__init__(f"Подтверждение: {tool}",
                         "y — да · a — всегда для этого инструмента · n — нет · s — остановить задачу",
                         max_width=110, role=theme_role)
        self.tool = tool
        self.summary = summary
        self.detail = detail
        self.diff = diff
        self.command = command

    def body(self, theme: Theme, width: int) -> List[Line]:
        out: List[Line] = []
        out.extend(wrap_line([(self.summary, theme.style("warn", bold=True))], width))
        if self.command:
            out.extend(wrap_line([("$ ", theme.style("tool")),
                                  (self.command, theme.style("fg"))], width))
        if self.detail:
            out.extend(wrap_line([(self.detail, theme.style("dim"))], width))
        if self.diff:
            out.extend(render_diff(self.diff, theme, width, indent="", max_lines=200))
        return out

    def key(self, ev: KeyEvent, theme: Theme, width: int, height: int) -> Any:
        if ev.is_char:
            low = ev.text.lower()
            if low in ("y", "д", "a", "ф", "n", "т", "s", "ы", "q"):
                return {"y": "yes", "д": "yes", "a": "always", "ф": "always",
                        "n": "no", "т": "no", "s": "stop", "ы": "stop",
                        "q": "stop"}[low]
        if ev.name == "enter":
            return "yes"
        return super().key(ev, theme, width, height)

    def cancel_value(self) -> Any:
        return "no"
