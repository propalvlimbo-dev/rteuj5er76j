# -*- coding: utf-8 -*-
"""Темы оформления ELYTRIX: палитры, наборы рамок, спиннеры.

Тема — это словарь «роль -> RGB». Роль (accent, ok, err, border …) используется
везде в интерфейсе, поэтому сменить настроение консоли можно одной строкой
в config/elytrix.json или командой /theme, не трогая остальной код.

Если терминал не понимает цвет (канал, NO_COLOR, старая консоль), все роли
превращаются в пустой стиль — интерфейс остаётся читаемым.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from .screen import Palette, Style

RGB = Tuple[int, int, int]

# ---------------------------------------------------------------------------
# Палитры
# ---------------------------------------------------------------------------

_ROSE: Dict[str, Optional[RGB]] = {
    "fg": (255, 244, 248),          # почти белый с розовым подтоном
    "dim": (226, 205, 216),
    "faint": (171, 148, 162),
    "accent": (255, 121, 176),      # розовый — заголовки, активное
    "accent2": (255, 177, 209),     # светлая роза — модель, вторичный акцент
    "ok": (170, 232, 201),
    "warn": (255, 214, 176),
    "err": (255, 146, 165),
    "info": (255, 244, 248),
    "user": (255, 177, 209),
    "assistant": (252, 246, 249),
    "tool": (240, 190, 216),
    "border": (186, 143, 166),
    "border_active": (255, 121, 176),
    "panel": (56, 40, 50),
    "code_fg": (246, 236, 241),
    "keyword": (255, 121, 176),
    "string": (170, 232, 201),
    "comment": (171, 148, 162),
    "number": (255, 214, 176),
    "function": (255, 177, 209),
    "diff_add": (170, 232, 201),
    "diff_del": (255, 146, 165),
    "diff_meta": (226, 205, 216),
    "cursor_bg": (255, 121, 176),
}

_DARK: Dict[str, Optional[RGB]] = {
    "fg": (226, 232, 240),
    "dim": (148, 163, 184),
    "faint": (100, 116, 139),
    "accent": (125, 211, 252),        # голубой — заголовки, активное
    "accent2": (196, 181, 253),       # сиреневый — модель, вторичный акцент
    "ok": (134, 239, 172),
    "warn": (253, 224, 71),
    "err": (252, 165, 165),
    "info": (147, 197, 253),
    "user": (253, 224, 71),
    "assistant": (226, 232, 240),
    "tool": (94, 234, 212),
    "border": (71, 85, 105),
    "border_active": (125, 211, 252),
    "panel": (30, 41, 59),
    "code_fg": (203, 213, 225),
    "keyword": (244, 114, 182),
    "string": (134, 239, 172),
    "comment": (100, 116, 139),
    "number": (253, 224, 71),
    "function": (125, 211, 252),
    "diff_add": (134, 239, 172),
    "diff_del": (252, 165, 165),
    "diff_meta": (148, 163, 184),
    "cursor_bg": (125, 211, 252),
}

_NIGHT: Dict[str, Optional[RGB]] = {
    "fg": (205, 214, 244),
    "dim": (147, 153, 178),
    "faint": (108, 111, 133),
    "accent": (137, 180, 250),
    "accent2": (203, 166, 247),
    "ok": (166, 227, 161),
    "warn": (249, 226, 175),
    "err": (243, 139, 168),
    "info": (148, 226, 213),
    "user": (249, 226, 175),
    "assistant": (205, 214, 244),
    "tool": (148, 226, 213),
    "border": (69, 71, 90),
    "border_active": (137, 180, 250),
    "panel": (24, 24, 37),
    "code_fg": (186, 194, 222),
    "keyword": (203, 166, 247),
    "string": (166, 227, 161),
    "comment": (108, 111, 133),
    "number": (250, 179, 135),
    "function": (137, 180, 250),
    "diff_add": (166, 227, 161),
    "diff_del": (243, 139, 168),
    "diff_meta": (147, 153, 178),
    "cursor_bg": (137, 180, 250),
}

_LIGHT: Dict[str, Optional[RGB]] = {
    "fg": (30, 41, 59),
    "dim": (100, 116, 139),
    "faint": (148, 163, 184),
    "accent": (2, 132, 199),
    "accent2": (124, 58, 237),
    "ok": (22, 163, 74),
    "warn": (202, 138, 4),
    "err": (220, 38, 38),
    "info": (37, 99, 235),
    "user": (180, 83, 9),
    "assistant": (30, 41, 59),
    "tool": (13, 148, 136),
    "border": (148, 163, 184),
    "border_active": (2, 132, 199),
    "panel": (241, 245, 249),
    "code_fg": (51, 65, 85),
    "keyword": (190, 24, 93),
    "string": (22, 163, 74),
    "comment": (148, 163, 184),
    "number": (180, 83, 9),
    "function": (2, 132, 199),
    "diff_add": (22, 163, 74),
    "diff_del": (220, 38, 38),
    "diff_meta": (100, 116, 139),
    "cursor_bg": (2, 132, 199),
}

_MONO: Dict[str, Optional[RGB]] = {
    "fg": (229, 229, 229),
    "dim": (163, 163, 163),
    "faint": (115, 115, 115),
    "accent": (255, 255, 255),
    "accent2": (212, 212, 212),
    "ok": (229, 229, 229),
    "warn": (255, 255, 255),
    "err": (255, 255, 255),
    "info": (212, 212, 212),
    "user": (255, 255, 255),
    "assistant": (229, 229, 229),
    "tool": (212, 212, 212),
    "border": (115, 115, 115),
    "border_active": (255, 255, 255),
    "panel": (23, 23, 23),
    "code_fg": (229, 229, 229),
    "keyword": (255, 255, 255),
    "string": (212, 212, 212),
    "comment": (115, 115, 115),
    "number": (229, 229, 229),
    "function": (255, 255, 255),
    "diff_add": (229, 229, 229),
    "diff_del": (163, 163, 163),
    "diff_meta": (115, 115, 115),
    "cursor_bg": (255, 255, 255),
}

THEMES: Dict[str, Dict[str, Optional[RGB]]] = {
    "rose": _ROSE,
    "dark": _DARK,
    "night": _NIGHT,
    "light": _LIGHT,
    "mono": _MONO,
}

THEME_NAMES = ("rose", "dark", "night", "light", "mono")

# ---------------------------------------------------------------------------
# Наборы символов
# ---------------------------------------------------------------------------


class Charset:
    """Символы рамок и значков: Unicode для современных консолей, ASCII для древних."""

    def __init__(self, unicode_ok: bool = True):
        if unicode_ok:
            self.h, self.v = "─", "│"
            self.tl, self.tr, self.bl, self.br = "╭", "╮", "╰", "╯"
            self.lt, self.rt, self.tt, self.bt = "├", "┤", "┬", "┴"
            self.cross = "┼"
            self.dot = "●"
            self.arrow = "→"
            self.play, self.check, self.cross_mark = "⏵", "✓", "✗"
            self.warn_mark, self.gear = "!", "⚙"
            self.bullet = "•"
            self.ellipsis = "…"
            self.corner = "└"
            self.bar_full, self.bar_empty = "█", "░"
            self.bar_half = "▓"
        else:
            self.h, self.v = "-", "|"
            self.tl, self.tr, self.bl, self.br = "+", "+", "+", "+"
            self.lt, self.rt, self.tt, self.bt = "+", "+", "+", "+"
            self.cross = "+"
            self.dot = "*"
            self.arrow = "->"
            self.play, self.check, self.cross_mark = ">", "v", "x"
            self.warn_mark, self.gear = "!", "#"
            self.bullet = "*"
            self.ellipsis = "..."
            self.corner = "`"
            self.bar_full, self.bar_empty = "#", "."
            self.bar_half = "+"


SPINNER_BRAILLE = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
SPINNER_ASCII = ("|", "/", "-", "\\")
SPINNER_DOTS = ("⠁", "⠂", "⠄", "⡀", "⢀", "⠠", "⠐", "⠈")


class Theme:
    """Доступ к стилям темы по имени роли: ``theme.style("accent", bold=True)``."""

    def __init__(self, name: str = "rose", palette: Optional[Palette] = None,
                 unicode_ok: bool = True):
        name = (name or "rose").lower()
        if name not in THEMES:
            name = "rose"
        self.name = name
        self.colors = dict(THEMES[name])
        self.palette = palette or Palette()
        # Unicode-рамки зависят только от кодировки консоли: NO_COLOR не обязан
        # превращать интерфейс в ascii-таблицы
        self.charset = Charset(unicode_ok)
        self.spinner = SPINNER_BRAILLE if self.charset.ellipsis == "…" else SPINNER_ASCII
        if self.palette.mode == "none":
            self.spinner = SPINNER_ASCII
        self._cache: Dict[Tuple, Style] = {}

    def rgb(self, role: str) -> Optional[RGB]:
        return self.colors.get(role)

    def style(self, role: str = "fg", bold: bool = False, dim: bool = False,
              italic: bool = False, underline: bool = False, reverse: bool = False,
              bg_role: Optional[str] = None) -> Style:
        """Стиль по роли. Кэшируется — в кадре сотни вызовов."""
        key = (role, bold, dim, italic, underline, reverse, bg_role)
        hit = self._cache.get(key)
        if hit is None:
            hit = Style(fg=self.colors.get(role), bg=self.colors.get(bg_role) if bg_role else None,
                        bold=bold, dim=dim, italic=italic, underline=underline, reverse=reverse)
            self._cache[key] = hit
        return hit

    # короткие синонимы, чтобы код интерфейса читался легко
    def __getattr__(self, item: str) -> Style:
        if item.startswith("_") or item in ("name", "colors", "palette", "charset", "spinner"):
            raise AttributeError(item)
        if item in self.colors:
            return self.style(item)
        raise AttributeError(item)

    def spin(self, tick: int) -> str:
        return self.spinner[tick % len(self.spinner)]


def load_theme(name: str = "rose", color_mode: str = "auto",
               unicode_ok: bool = True) -> Theme:
    return Theme(name, Palette(color_mode), unicode_ok)
