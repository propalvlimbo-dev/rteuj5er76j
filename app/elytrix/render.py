# -*- coding: utf-8 -*-
"""Блоки ленты событий и их отрисовка.

Лента — это список блоков (сообщение пользователя, ответ модели, вызов инструмента,
служебная строка). Блок умеет сам себя нарисовать в строки сегментов и кэширует
результат: кадр перерисовывается 20-30 раз в секунду, а markdown длинного ответа
пересчитывать каждый раз незачем.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from .screen import Line, Style, text_width, truncate, wrap_line, wrap_text
from .theme import Theme
from .widgets import (bar, human_number, render_diff, render_markdown, seconds_text,
                      sep)

KIND_USER = "user"
KIND_ASSISTANT = "assistant"
KIND_TOOL = "tool"
KIND_INFO = "info"
KIND_ERROR = "error"
KIND_SPACER = "spacer"
KIND_CUSTOM = "custom"
KIND_LOGO = "logo"

#: Логотип старта: рисуется по центру ленты розово-белым градиентом.
LOGO_ART = "\n".join([
    "███████╗██╗     ██╗   ██╗████████╗██████╗ ██╗██    ██",
    "██╔════╝██║     ╚██╗ ██╔╝╚══██╔══╝██╔══██╗██║ ██  ██ ",
    "█████╗  ██║      ╚████╔╝    ██║   ██████╔╝██║  ████  ",
    "██╔══╝  ██║       ╚██╔╝     ██║   ██╔══██╗██║  ████  ",
    "███████╗███████╗   ██║      ██║   ██║  ██║██║ ██  ██ ",
    "╚══════╝╚══════╝   ╚═╝      ╚═╝   ╚═╝  ╚═╝██    ██",
])


class Block:
    """Элемент ленты. ``renderer`` переопределяет отрисовку (панели, списки)."""

    __slots__ = ("kind", "text", "meta", "renderer", "created", "_cache", "_cache_key",
                 "closed", "verbose_only")

    def __init__(self, kind: str, text: str = "", meta: Optional[Dict[str, Any]] = None,
                 renderer: Optional[Callable[[Theme, int], List[Line]]] = None,
                 closed: bool = False):
        self.kind = kind
        self.text = text
        self.meta: Dict[str, Any] = dict(meta or {})
        self.renderer = renderer
        self.created = time.time()
        self.closed = closed
        self.verbose_only = False
        self._cache: Optional[List[Line]] = None
        self._cache_key: Optional[Tuple[int, bool]] = None

    def touch(self) -> None:
        """Пометить кэш недействительным (текст или метаданные изменились)."""
        self._cache = None
        self._cache_key = None

    def append_text(self, piece: str) -> None:
        self.text += piece
        self._cache = None
        self._cache_key = None

    def lines(self, theme: Theme, width: int, verbose: bool = False) -> List[Line]:
        # кэш сбрасывается через touch()/append_text(): перерисовка кадра идёт
        # 20-30 раз в секунду, а markdown длинного ответа считать заново дорого
        key = (width, verbose)
        if self._cache is not None and self._cache_key == key:
            return self._cache
        if self.verbose_only and not verbose:
            self._cache, self._cache_key = [], key
            return []
        if self.kind == KIND_CUSTOM and self.renderer:
            rendered = self.renderer(theme, width)
        elif self.kind == KIND_USER:
            rendered = render_user(self.text, theme, width)
        elif self.kind == KIND_ASSISTANT:
            rendered = render_assistant(self.text, theme, width)
        elif self.kind == KIND_TOOL:
            rendered = render_tool(self.meta, theme, width, verbose)
        elif self.kind == KIND_ERROR:
            rendered = render_error(self.text, theme, width)
        elif self.kind == KIND_SPACER:
            rendered = [[]]
        elif self.kind == KIND_LOGO:
            rendered = render_logo(self.text, theme, width)
        else:
            rendered = render_info(self.text, theme, width)
        self._cache, self._cache_key = rendered, key
        return rendered


# ---------------------------------------------------------------------------
# Отрисовка блоков
# ---------------------------------------------------------------------------


def render_user(text: str, theme: Theme, width: int) -> List[Line]:
    """Сообщение пользователя: маркер ❯ и текст, перенесённый по ширине."""
    cs = theme.charset
    marker = f"{cs.arrow if cs.arrow != '->' else '>'} "
    style = theme.style("user", bold=True)
    out: List[Line] = []
    first = True
    for raw in (text or "").split("\n"):
        wrapped = wrap_line([(raw, style)], width - 4 - text_width(marker))
        for wl in wrapped:
            prefix = [("  ", theme.style("fg")), (marker, theme.style("user"))] if first \
                else [("   ", theme.style("fg")), (" " * text_width(marker), theme.style("fg"))]
            out.append(prefix + wl)
            first = False
    return out or [[("", theme.style("fg"))]]


def render_assistant(text: str, theme: Theme, width: int) -> List[Line]:
    """Ответ модели: markdown с отступом в две колонки."""
    if not text.strip():
        return []
    return render_markdown(text.strip(), theme, width, indent="  ")


def render_tool(meta: Dict[str, Any], theme: Theme, width: int, verbose: bool = False) -> List[Line]:
    """Карточка инструмента: значок состояния, имя, цель, результат.

    В обычном режиме — одна строка (лента остаётся читаемой), в подробном —
    под ней ещё и содержимое результата или diff правки.
    """
    cs = theme.charset
    name = str(meta.get("name") or "?")
    state = str(meta.get("state") or "done")       # run | done | error | skipped
    ok = bool(meta.get("ok", True))
    summary = str(meta.get("summary") or "")
    target = str(meta.get("target") or "")

    if state == "run":
        icon, icon_style = cs.play, theme.style("accent", bold=True)
        name_style = theme.style("accent")
        meta_style = theme.style("dim")
    elif state == "skipped":
        icon, icon_style = cs.warn_mark, theme.style("warn")
        name_style = theme.style("warn")
        meta_style = theme.style("dim")
    elif ok:
        icon, icon_style = cs.check, theme.style("ok")
        name_style = theme.style("tool")
        meta_style = theme.style("dim")
    else:
        icon, icon_style = cs.cross_mark, theme.style("err")
        name_style = theme.style("err")
        meta_style = theme.style("dim")

    parts: Line = [("  ", theme.style("fg")), (icon + " ", icon_style),
                   (f"{name:<6}", name_style)]
    if target:
        parts.append((" " + truncate(target, max(8, width - 40)), theme.style("fg")))
    if summary:
        room = max(10, width - visible(parts) - 3)
        parts.append(("  ", theme.style("fg")))
        parts.append((truncate(summary, room), meta_style))
    elapsed = meta.get("elapsed")
    if elapsed:
        parts.append((f" · {seconds_text(float(elapsed))}", theme.style("faint")))

    out = wrap_line(parts, width)
    if not verbose:
        return out

    diff = str(meta.get("diff") or "")
    if diff:
        out.extend(render_diff(diff, theme, width, indent="      ", max_lines=24))
    detail = str(meta.get("detail") or "")
    if detail and not diff:
        for wl in wrap_text(detail[:1200], width - 6, theme.style("dim")):
            out.append([("      ", theme.style("fg"))] + wl)
    body = str(meta.get("text") or "")
    if body and not diff and not detail:
        shown = body.splitlines()[:14]
        for raw in shown:
            for wl in wrap_line([(raw, theme.style("dim"))], width - 6):
                out.append([("      ", theme.style("fg"))] + wl)
        if len(body.splitlines()) > len(shown):
            out.append([("      … полностью — /verbose off или журнал сессии",
                         theme.style("faint"))])
    return out


def visible(parts: Line) -> int:
    return text_width("".join(t for t, _ in parts))


def render_logo(text: str, theme: Theme, width: int) -> List[Line]:
    """Логотип по центру: розово-белый градиент сверху вниз, под ним подпись."""
    rows = [r for r in (text or "").split("\n")]
    out: List[Line] = []
    top = (255, 250, 252)                    # белый
    bottom = (255, 116, 170)                 # розовый
    if rows and max(text_width(r) for r in rows) > width:
        rows = ["E L Y T R I X"]             # узкое окно — одна строка вместо арта
    last = max(1, len(rows) - 1)
    # центрируем по самой широкой строке: иначе колонны букв съедут
    block_w = max([text_width(r) for r in rows] or [0])
    left = max(0, (width - block_w) // 2)
    for i, raw in enumerate(rows):
        if not raw.strip():
            out.append([("", theme.style("fg"))])
            continue
        t = i / last
        rgb = tuple(int(round(top[c] + (bottom[c] - top[c]) * t)) for c in range(3))
        out.append([(" " * left, theme.style("fg")), (raw, Style(fg=rgb, bold=True))])
    return out


def render_info(text: str, theme: Theme, width: int) -> List[Line]:
    cs = theme.charset
    out: List[Line] = []
    for raw in (text or "").split("\n"):
        for wl in wrap_line([(raw, theme.style("dim"))], width - 4):
            out.append([("  " + cs.bullet + " ", theme.style("faint"))] + wl)
    return out


def render_error(text: str, theme: Theme, width: int) -> List[Line]:
    cs = theme.charset
    out: List[Line] = []
    rows = wrap_text((text or "").strip(), width - 8, theme.style("err"))
    out.append([("  ", theme.style("fg")), (cs.tl + cs.h * (width - 4) + cs.tr,
                                            theme.style("err"))])
    for wl in rows:
        out.append([("  ", theme.style("fg")), (cs.v + " ", theme.style("err")),
                    (cs.cross_mark + " ", theme.style("err", bold=True))] + wl
                   + [(" " * max(0, width - 8 - sum(text_width(t) for t, _ in wl)),
                       theme.style("fg")), (" " + cs.v, theme.style("err"))])
    out.append([("  ", theme.style("fg")), (cs.bl + cs.h * (width - 4) + cs.br,
                                            theme.style("err"))])
    return out


# ---------------------------------------------------------------------------
# Служебные строки интерфейса
# ---------------------------------------------------------------------------


def header(theme: Theme, width: int, title: str, version: str,
           right: List[Tuple[str, str]]) -> List[Line]:
    """Шапка: имя программы слева, текущие параметры справа, под ними линия."""
    left: Line = [(" ", theme.style("fg")),
                  (title, theme.style("accent", bold=True)),
                  (f" {version}", theme.style("faint"))]
    right_line: Line = []
    for i, (text, role) in enumerate(right):
        if i:
            right_line.append(("  ", theme.style("faint")))
            right_line.append((theme.charset.v if theme.charset.v != "|" else "|",
                               theme.style("border")))
            right_line.append(("  ", theme.style("faint")))
        right_line.append((text, theme.style(role)))
    gap = width - visible(left) - visible(right_line) - 1
    if gap < 1:
        right_line = [(truncate("".join(t for t, _ in right_line), max(4, width - visible(left) - 2)),
                       theme.style("dim"))]
        gap = max(1, width - visible(left) - visible(right_line) - 1)
    row = left + [(" " * gap, theme.style("fg"))] + right_line + [(" ", theme.style("fg"))]
    return [row, [(theme.charset.h * width, theme.style("border"))]]


def activity(theme: Theme, width: int, busy: bool, spin_index: int, text: str,
             extra: str = "") -> Line:
    """Строка текущей активности над полем ввода."""
    cs = theme.charset
    if busy:
        icon = theme.spin(spin_index)
        style = theme.style("accent", bold=True)
    elif text.startswith("✓") or text.startswith(cs.check):
        icon, style = cs.check, theme.style("ok")
        text = text.lstrip("✓ " + cs.check).strip()
    elif text.startswith("!"):
        icon, style = cs.warn_mark, theme.style("warn")
        text = text.lstrip("! ").strip()
    else:
        icon, style = cs.dot, theme.style("faint")
    line: Line = [(" ", theme.style("fg")), (icon + " ", style), (text, theme.style("dim"))]
    if extra:
        line.append(("  ", theme.style("fg")))
        line.append((truncate(extra, max(4, width - visible(line) - 2)), theme.style("faint")))
    return line


def status_bar(theme: Theme, width: int, parts: List[Tuple[str, str]],
               day_frac: Optional[float] = None, day_text: str = "") -> Line:
    """Нижняя строка: режим, модель, токены, расход за сутки, подсказки."""
    cs = theme.charset
    line: Line = [(" ", theme.style("fg"))]
    for i, (text, role) in enumerate(parts):
        if i:
            line.append((f" {cs.v if cs.v != '|' else '|'} ", theme.style("border")))
        line.append((text, theme.style(role)))
    if day_frac is not None:
        line.append((f" {cs.v if cs.v != '|' else '|'} ", theme.style("border")))
        line.append(("день ", theme.style("dim")))
        line.append((day_text, theme.style("warn" if day_frac > 0.8 else "fg")))
        line.append((" ", theme.style("fg")))
        line.extend(bar(day_frac, 10, theme,
                        "err" if day_frac > 0.9 else ("warn" if day_frac > 0.7 else "ok")))
    if visible(line) < width - 2:
        line.append((" " * (width - visible(line) - 1), theme.style("fg")))
    return line


def tip_line(theme: Theme, width: int, tips: List[str], index: int) -> Line:
    if not tips:
        return [(" " * width, theme.style("fg"))]
    text = tips[index % len(tips)]
    return [("  ", theme.style("fg")),
            (truncate(text, width - 4), theme.style("faint"))]
