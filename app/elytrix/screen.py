# -*- coding: utf-8 -*-
"""Низкоуровневый вывод в консоль: цвет, ширина символов, перенос строк, полноэкранный режим.

Здесь нет ни одной сторонней зависимости — только стандартная библиотека, потому что
ELYTRIX.bat должен работать сразу после установки Python, без pip и интернета.

Что даёт модуль:
    · автоопределение возможностей терминала (truecolor / 256 / 16 / без цвета);
    · включение VT-обработки в консоли Windows (без этого ESC-коды печатаются текстом);
    · «сегменты» — куски текста со стилем, из которых собираются строки интерфейса;
    · перенос по ширине терминала с сохранением стилей (в т.ч. для CJK и emoji);
    · переход в альтернативный экран и обратно (полноэкранная TUI как в opencode).
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import unicodedata
from typing import Iterable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Возможности терминала
# ---------------------------------------------------------------------------

IS_WINDOWS = os.name == "nt"

#: ANSI-последовательности, которые надо уметь вырезать при подсчёте ширины
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[\]P^_].*?(\x07|\x1b\\)")


def is_tty(stream=None) -> bool:
    """True, если вывод идёт в настоящую консоль (а не в файл или канал)."""
    stream = stream or sys.stdout
    try:
        return bool(stream.isatty())
    except Exception:  # noqa: BLE001
        return False


def detect_color_mode() -> str:
    """Определяет, какой цвет понимает терминал: truecolor | 256 | 16 | none."""
    if os.environ.get("NO_COLOR") or os.environ.get("ELYTRIX_NO_COLOR"):
        return "none"
    if not is_tty():
        return "none"
    forced = (os.environ.get("ELYTRIX_COLOR") or "").lower()
    if forced in ("truecolor", "24bit", "256", "16", "none"):
        return "24bit" if forced == "truecolor" else forced
    colorterm = (os.environ.get("COLORTERM") or "").lower()
    term = (os.environ.get("TERM") or "").lower()
    if "truecolor" in colorterm or "24bit" in colorterm:
        return "truecolor"
    # Windows Terminal, VS Code, iTerm, современные терминалы Linux
    if os.environ.get("WT_SESSION") or os.environ.get("TERM_PROGRAM") or "xterm" in term:
        return "truecolor"
    if "256" in term:
        return "256"
    if IS_WINDOWS:
        # Windows 10+ после включения VT понимает 256 цветов, truecolor — только в WT
        return "256"
    if term in ("dumb", ""):
        return "16"
    return "256"


def enable_vt() -> bool:
    """Включает обработку ESC-последовательностей в консоли Windows.

    На Windows 10+ это делается флагом ENABLE_VIRTUAL_TERMINAL_PROCESSING у
    SetConsoleMode; без него консоль печатает ``\\x1b[1m`` как обычный текст.
    Возвращает True, если VT включён (или мы не в Windows).
    """
    if not IS_WINDOWS:
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        if handle == -1:
            return False
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        ENABLE_VT = 0x0004
        if mode.value & ENABLE_VT:
            return True
        return bool(kernel32.SetConsoleMode(handle, mode.value | ENABLE_VT))
    except Exception:  # noqa: BLE001
        return False


def force_utf8() -> None:
    """Переключает stdout/stderr в UTF-8: в консоли Windows по умолчанию cp866/cp1251."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Цвет: RGB -> escape-код под возможности терминала
# ---------------------------------------------------------------------------

#: Базовая палитра ANSI (16 цветов) в RGB — для деградации на старых консолях
_ANSI16 = [
    (0, 0, 0), (170, 0, 0), (0, 170, 0), (170, 85, 0),
    (0, 0, 170), (170, 0, 170), (0, 170, 170), (170, 170, 170),
    (85, 85, 85), (255, 85, 85), (85, 255, 85), (255, 255, 85),
    (85, 85, 255), (255, 85, 255), (85, 255, 255), (255, 255, 255),
]

#: Углы цветового куба xterm-256 (6x6x6) — индексы 16..231
_CUBE_STEPS = (0, 95, 135, 175, 215, 255)


def _nearest_ansi16(rgb: Tuple[int, int, int]) -> int:
    best, best_d = 0, 10 ** 9
    for i, c in enumerate(_ANSI16):
        d = sum((a - b) ** 2 for a, b in zip(rgb, c))
        if d < best_d:
            best, best_d = i, d
    return best


def _nearest_256(rgb: Tuple[int, int, int]) -> int:
    r, g, b = rgb
    # Серые оттенки xterm (232..255) часто точнее куба
    if abs(r - g) < 12 and abs(g - b) < 12:
        if r < 8:
            return 16
        if r > 248:
            return 231
        return 232 + min(23, (r - 8) * 24 // 240)
    idx = 16

    def pick(v: int) -> int:
        return min(range(6), key=lambda i: abs(_CUBE_STEPS[i] - v))

    return idx + 36 * pick(r) + 6 * pick(g) + pick(b)


class Palette:
    """Превращает RGB в escape-код нужной глубины и кэширует результат."""

    def __init__(self, mode: str = "auto"):
        self.mode = detect_color_mode() if mode in ("auto", "") else mode
        self._cache: dict = {}

    @property
    def supports_color(self) -> bool:
        return self.mode != "none"

    def fg(self, rgb: Optional[Tuple[int, int, int]]) -> str:
        return self._code(rgb, 38, 30)

    def bg(self, rgb: Optional[Tuple[int, int, int]]) -> str:
        return self._code(rgb, 48, 40)

    def _code(self, rgb: Optional[Tuple[int, int, int]], base24: int, base16: int) -> str:
        if rgb is None or self.mode == "none":
            return ""
        key = (rgb, base24)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        if self.mode == "truecolor":
            code = f"\x1b[{base24};2;{rgb[0]};{rgb[1]};{rgb[2]}m"
        elif self.mode == "256":
            code = f"\x1b[{base24};5;{_nearest_256(rgb)}m"
        else:
            n = _nearest_ansi16(rgb)
            code = f"\x1b[{base16 + (n if n < 8 else n - 8 + 60)}m"
        self._cache[key] = code
        return code


# ---------------------------------------------------------------------------
# Стили и сегменты
# ---------------------------------------------------------------------------

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
ITALIC = "\x1b[3m"
UNDERLINE = "\x1b[4m"
REVERSE = "\x1b[7m"


class Style:
    """Набор атрибутов текста, который превращается в префикс ANSI."""

    __slots__ = ("fg", "bg", "bold", "dim", "italic", "underline", "reverse")

    def __init__(self, fg: Optional[Tuple[int, int, int]] = None,
                 bg: Optional[Tuple[int, int, int]] = None,
                 bold: bool = False, dim: bool = False, italic: bool = False,
                 underline: bool = False, reverse: bool = False):
        self.fg = fg
        self.bg = bg
        self.bold = bold
        self.dim = dim
        self.italic = italic
        self.underline = underline
        self.reverse = reverse

    def prefix(self, palette: Palette) -> str:
        if palette.mode == "none":
            return ""                      # вывод в файл или канал: никаких ESC-кодов
        parts = []
        if self.bold:
            parts.append(BOLD)
        if self.dim:
            parts.append(DIM)
        if self.italic:
            parts.append(ITALIC)
        if self.underline:
            parts.append(UNDERLINE)
        if self.reverse:
            parts.append(REVERSE)
        fg = palette.fg(self.fg)
        bg = palette.bg(self.bg)
        if fg:
            parts.append(fg)
        if bg:
            parts.append(bg)
        return "".join(parts)

    def copy(self, **kw) -> "Style":
        values = {name: getattr(self, name) for name in self.__slots__}
        values.update(kw)
        return Style(**values)

    def _key(self):
        return (self.fg, self.bg, self.bold, self.dim, self.italic, self.underline, self.reverse)

    def __eq__(self, other: object) -> bool:
        """Стили сравниваются по содержимому: иначе кэши строк и тесты расходятся."""
        return isinstance(other, Style) and self._key() == other._key()

    def __hash__(self) -> int:
        return hash(self._key())


#: Сегмент = (текст, стиль). Строка интерфейса = список сегментов.
Segment = Tuple[str, Style]
Line = List[Segment]


def seg(text: str, style: Optional[Style] = None) -> Segment:
    return (text, style or Style())


def plain(text: str) -> Line:
    """Строка без оформления."""
    return [(text, Style())]


def styled(text: str, style: Style) -> Line:
    return [(text, style)]


def join_lines(*lines: Iterable[Segment]) -> Line:
    out: Line = []
    for line in lines:
        out.extend(line)
    return out


# ---------------------------------------------------------------------------
# Ширина символов и перенос
# ---------------------------------------------------------------------------

_ZERO_WIDTH = {0x200B, 0x200C, 0x200D, 0xFEFF, 0x00AD}
_SPINNER_CHARS = set("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")


def char_width(ch: str) -> int:
    """Экранныая ширина символа: 0 для комбинируемых, 2 для CJK и части emoji."""
    code = ord(ch)
    if code in _ZERO_WIDTH:
        return 0
    if code < 0x20 or code == 0x7F:
        return 0
    if 0x1F300 <= code <= 0x1FAFF or 0x2600 <= code <= 0x27BF:
        return 2
    if code in (0x2192, 0x2190, 0x2500, 0x2502):       # стрелки и линии — узкие
        return 1
    if code in _SPINNER_CHARS:
        return 1
    category = unicodedata.combining(ch)
    if category:
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def text_width(text: str) -> int:
    """Ширина строки без ANSI-кодов в экранных колонках."""
    if "\x1b" in text:
        text = _ANSI_RE.sub("", text)
    return sum(char_width(c) for c in text)


def visible_width(line: Sequence[Segment]) -> int:
    return sum(text_width(t) for t, _ in line)


def pad(line: Sequence[Segment], width: int, palette: Palette,
        fill_style: Optional[Style] = None) -> str:
    """Собирает строку в текст ровно нужной ширины (добивает пробелами)."""
    out: List[str] = []
    used = 0
    for text, style in line:
        prefix = style.prefix(palette)
        if prefix:
            out.append(prefix)
        out.append(text)
        if prefix:
            out.append(RESET)
        used += text_width(text)
    if used < width:
        filler = (fill_style or Style()).prefix(palette)
        out.append(filler + " " * (width - used) + (RESET if filler else ""))
    return "".join(out)


def truncate(text: str, width: int, ellipsis: str = "…") -> str:
    """Обрезает строку до ширины, ставя многоточие."""
    if width <= 0:
        return ""
    if text_width(text) <= width:
        return text
    out: List[str] = []
    used = 0
    limit = width - text_width(ellipsis)
    for ch in text:
        w = char_width(ch)
        if used + w > limit:
            break
        out.append(ch)
        used += w
    return "".join(out) + ellipsis


def _split_hard(text: str, width: int) -> List[str]:
    """Режет длинное слово на куски ровно по ширине."""
    out: List[str] = []
    cur: List[str] = []
    used = 0
    for ch in text:
        w = char_width(ch)
        if used + w > width and cur:
            out.append("".join(cur))
            cur, used = [], 0
        cur.append(ch)
        used += w
    if cur:
        out.append("".join(cur))
    return out or [""]


def wrap_line(line: Sequence[Segment], width: int, indent: str = "") -> List[Line]:
    """Переносит стилизованную строку по ширине, сохраняя стили каждого куска.

    Правила простые и предсказуемые: перенос по пробелам, длинное слово режется,
    явные ``\\n`` в тексте начинают новую строку, продолжение получает отступ ``indent``.
    """
    if width <= 1:
        width = 2
    rows: List[Line] = []
    current: Line = []
    used = 0
    indent_w = text_width(indent)

    def flush() -> None:
        nonlocal current, used
        rows.append(current)
        current = [(indent, Style(dim=True))] if indent else []
        used = indent_w

    for text, style in line:
        pieces = text.split("\n")
        for pi, piece in enumerate(pieces):
            if pi:
                flush()
            tokens = re.split(r"(\s+)", piece)
            for token in tokens:
                if not token:
                    continue
                tw = text_width(token)
                if tw > width - indent_w:
                    for chunk in _split_hard(token, max(1, width - used)):
                        cw = text_width(chunk)
                        if used + cw > width and current and used > indent_w:
                            flush()
                        current.append((chunk, style))
                        used += cw
                    continue
                if used + tw > width and used > indent_w:
                    # убираем хвостовые пробелы перед переносом
                    while current and current[-1][0].strip() == "":
                        used -= text_width(current.pop()[0])
                    flush()
                current.append((token, style))
                used += tw
    rows.append(current)
    return rows or [[]]


def wrap_text(text: str, width: int, style: Optional[Style] = None) -> List[Line]:
    style = style or Style()
    out: List[Line] = []
    for raw in text.split("\n"):
        out.extend(wrap_line([(raw, style)], width))
    return out


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def terminal_size(fallback: Tuple[int, int] = (100, 30)) -> Tuple[int, int]:
    """(колонки, строки) консоли. Работает и в Windows, и в POSIX."""
    try:
        size = shutil.get_terminal_size(fallback)
        cols = max(20, int(size.columns or fallback[0]))
        rows = max(8, int(size.lines or fallback[1]))
        return cols, rows
    except Exception:  # noqa: BLE001
        return fallback


# ---------------------------------------------------------------------------
# Управляющие последовательности полноэкранного режима
# ---------------------------------------------------------------------------

ALT_ON = "\x1b[?1049h"
ALT_OFF = "\x1b[?1049l"
HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"
CLEAR = "\x1b[2J\x1b[H"
HOME = "\x1b[H"
ERASE_LINE = "\x1b[2K"
ERASE_DOWN = "\x1b[J"
BRACKETED_ON = "\x1b[?2004h"
BRACKETED_OFF = "\x1b[?2004l"


def move(row: int, col: int) -> str:
    return f"\x1b[{row};{col}H"


def supports_unicode(stream=None) -> bool:
    """Хватит ли кодировки консоли на рамки и спиннер (иначе — ASCII-набор)."""
    enc = (getattr(stream or sys.stdout, "encoding", "") or "").lower()
    if "utf" in enc:
        return True
    try:
        "─│╭●⏵".encode(enc)
        return True
    except Exception:  # noqa: BLE001
        return False
