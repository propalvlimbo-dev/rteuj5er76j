# -*- coding: utf-8 -*-
"""Ввод с клавиатуры: сырой режим, разбор ESC-последовательностей, вставка текста.

Один и тот же разбор работает в Windows (msvcrt) и в POSIX (termios + select),
поэтому его можно тестировать, просто скормив байты: ``KeyParser().feed(b"\\x1b[A")``.

Что умеет:
    · обычные символы, Enter, Tab, Backspace, Delete, стрелки, Home/End, PageUp/Down;
    · сочетания Ctrl+A…Ctrl+Z, Alt+Enter (перенос строки), Ctrl+стрелки;
    · bracketed paste — вставка многострочного текста одним событием (иначе терминал
      присылает его посимвольно и Enter внутри вставки отправил бы задачу на середине);
    · одиночный Esc (если после него ничего не пришло за 50 мс).
"""

from __future__ import annotations

import os
import sys
import time
from typing import List, Optional, Tuple

IS_WINDOWS = os.name == "nt"

#: Имена событий-клавиш (символы приходят как name="char")
KEY_NAMES = {
    "A": "up", "B": "down", "C": "right", "D": "left",
    "E": "clear", "F": "end", "H": "home", "P": "f1", "Q": "f2",
    "R": "f3", "S": "f4", "Z": "shift+tab",
}

TILDE_NAMES = {
    "1": "home", "2": "insert", "3": "delete", "4": "end",
    "5": "pageup", "6": "pagedown", "7": "home", "8": "end",
    "11": "f1", "12": "f2", "13": "f3", "14": "f4", "15": "f5",
}

CTRL_NAMES = {
    "\x00": "ctrl+space", "\x01": "ctrl+a", "\x02": "ctrl+b", "\x03": "ctrl+c",
    "\x04": "ctrl+d", "\x05": "ctrl+e", "\x06": "ctrl+f", "\x07": "ctrl+g",
    "\x08": "backspace", "\x09": "tab", "\x0b": "ctrl+k", "\x0c": "ctrl+l",
    "\x0d": "enter", "\x0e": "ctrl+n", "\x0f": "ctrl+o", "\x10": "ctrl+p",
    "\x11": "ctrl+q", "\x12": "ctrl+r", "\x13": "ctrl+s", "\x14": "ctrl+t",
    "\x15": "ctrl+u", "\x16": "ctrl+v", "\x17": "ctrl+w", "\x18": "ctrl+x",
    "\x19": "ctrl+y", "\x1a": "ctrl+z", "\x1b": "esc", "\x7f": "backspace",
    "\x0a": "newline",           # Ctrl+J — перенос строки в поле ввода
}

MODIFIER_PREFIX = {2: "shift+", 3: "alt+", 4: "shift+alt+", 5: "ctrl+",
                   6: "ctrl+shift+", 7: "ctrl+alt+", 8: "alt+"}


class KeyEvent:
    """Одно нажатие. ``name`` — «char» для обычных символов, тогда текст в ``text``."""

    __slots__ = ("name", "text")

    def __init__(self, name: str, text: str = ""):
        self.name = name
        self.text = text

    @property
    def is_char(self) -> bool:
        return self.name == "char"

    def __repr__(self) -> str:  # pragma: no cover - отладка
        return f"KeyEvent({self.name!r}, {self.text!r})"

    def __eq__(self, other: object) -> bool:
        return (isinstance(other, KeyEvent) and other.name == self.name
                and other.text == self.text)


class KeyParser:
    """Инкрементальный разбор потока байтов в события клавиатуры."""

    #: сколько ждём продолжение ESC-последовательности, прежде чем считать её одиночным Esc
    ESC_TIMEOUT = 0.05

    def __init__(self) -> None:
        self.buf = bytearray()
        self._paste: Optional[List[str]] = None
        self._esc_at = 0.0

    # -- публичный интерфейс ------------------------------------------------

    def feed(self, data: bytes) -> List[KeyEvent]:
        """Положить байты и получить список готовых событий."""
        self.buf.extend(data)
        return self._drain(allow_pending_esc=True)

    def flush(self) -> List[KeyEvent]:
        """Доразобрать остаток (например, одиночный Esc, который так и не продолжился)."""
        return self._drain(allow_pending_esc=False)

    # -- внутреннее ---------------------------------------------------------

    def _decode_prefix(self) -> Tuple[str, int]:
        """Декодирует максимально возможный префикс буфера в текст."""
        data = bytes(self.buf)
        try:
            return data.decode("utf-8"), len(data)
        except UnicodeDecodeError:
            # хвост — неполный многобайтовый символ: декодируем то, что удалось
            for cut in range(1, 4):
                try:
                    return data[:-cut].decode("utf-8"), len(data) - cut
                except UnicodeDecodeError:
                    continue
            return "", 0

    def _drain(self, allow_pending_esc: bool) -> List[KeyEvent]:
        out: List[KeyEvent] = []
        while self.buf:
            # режим вставки: копим всё до закрывающей последовательности
            if self._paste is not None:
                text, consumed = self._decode_prefix()
                if not consumed:
                    break
                end = text.find("\x1b[201~")
                if end < 0:
                    self._paste.append(text)
                    del self.buf[:consumed]
                    break
                self._paste.append(text[:end])
                eaten = len(text[:end].encode("utf-8")) + len("\x1b[201~")
                del self.buf[:eaten]
                out.append(KeyEvent("paste", "".join(self._paste)))
                self._paste = None
                continue

            if self.buf[0] == 0x1B:
                if not self._parse_escape(allow_pending_esc, out):
                    break
                continue

            text, consumed = self._decode_prefix()
            if not consumed:
                break                      # ждём остальные байты многобайтового символа
            ch = text[0]
            del self.buf[: len(ch.encode("utf-8"))]
            code = ord(ch)
            if ch in CTRL_NAMES:
                out.append(KeyEvent(CTRL_NAMES[ch]))
            elif code < 0x20:
                continue                   # прочие управляющие — игнорируем
            else:
                out.append(KeyEvent("char", ch))
        return out

    def _parse_escape(self, allow_pending_esc: bool, out: List[KeyEvent]) -> bool:
        """Разбирает последовательность, начинающуюся с ESC. False — нужно ещё байтов."""
        data = bytes(self.buf)
        if len(data) == 1:
            if allow_pending_esc:
                if not self._esc_at:
                    self._esc_at = time.time()
                    return False           # подождём: вдруг это начало стрелки
                if time.time() - self._esc_at < self.ESC_TIMEOUT:
                    return False
            self._esc_at = 0.0
            del self.buf[:1]
            out.append(KeyEvent("esc"))
            return True
        self._esc_at = 0.0

        if data[1:2] == b"[":
            return self._parse_csi(allow_pending_esc, out)
        if data[1:2] == b"O":
            if len(data) < 3:
                return False
            del self.buf[:3]
            out.append(KeyEvent(KEY_NAMES.get(data[2:3].decode("latin-1", "replace"), "unknown")))
            return True

        # Alt+символ (в том числе Alt+Enter — перенос строки)
        rest = data[1:]
        if rest[:1] == b"\x1b":
            del self.buf[:1]
            return True                    # двойной Esc — съедаем один
        ch = rest.decode("utf-8", "replace")[:1]
        del self.buf[: 1 + len(ch.encode("utf-8"))]
        if ch == "\r":
            out.append(KeyEvent("alt+enter"))
        elif ch in CTRL_NAMES:
            out.append(KeyEvent("alt+" + CTRL_NAMES[ch]))
        elif ch:
            out.append(KeyEvent("alt+" + ch, ch))
        return True

    def _parse_csi(self, allow_pending_esc: bool, out: List[KeyEvent]) -> bool:
        """CSI: ESC [ params final. False — последовательность ещё не пришла целиком."""
        data = bytes(self.buf)
        i = 2
        while i < len(data) and (0x30 <= data[i] <= 0x3F):
            i += 1
        if i >= len(data):
            if allow_pending_esc and len(data) < 12:
                return False               # ждём завершающий байт
            self.buf.clear()               # обрывок — выбрасываем, чтобы не зависнуть
            return True
        params = data[2:i].decode("latin-1")
        final = chr(data[i])
        del self.buf[: i + 1]

        if final == "~":
            number, _, modifier = params.partition(";")
            if number == "200":
                self._paste = []
                return True
            if number == "201":
                return True
            name = TILDE_NAMES.get(number, "unknown")
            if modifier.isdigit():
                name = MODIFIER_PREFIX.get(int(modifier), "") + name
            out.append(KeyEvent(name))
            return True

        number, _, modifier = params.partition(";")
        name = KEY_NAMES.get(final, "unknown")
        if modifier.isdigit():
            name = MODIFIER_PREFIX.get(int(modifier), "") + name
        out.append(KeyEvent(name))
        return True


class KeyReader:
    """Читает нажатия из консоли с таймаутом (нужен для анимации спиннера)."""

    def __init__(self) -> None:
        self.parser = KeyParser()
        self._fd: Optional[int] = None
        self._old = None
        self._win_vt = False

    # -- режим терминала ----------------------------------------------------

    def open(self) -> None:
        """Переводит консоль в сырой режим. Безопасно, если stdin не терминал."""
        try:
            if not sys.stdin.isatty():
                return
        except Exception:  # noqa: BLE001
            return
        if IS_WINDOWS:
            self._open_windows()
        else:
            self._open_posix()

    def close(self) -> None:
        if IS_WINDOWS:
            return
        if self._fd is not None and self._old is not None:
            try:
                import termios

                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)
            except Exception:  # noqa: BLE001
                pass
        self._fd, self._old = None, None

    def _open_posix(self) -> None:
        import termios
        import tty

        self._fd = sys.stdin.fileno()
        self._old = termios.tcgetattr(self._fd)
        tty.setraw(self._fd)

    def _open_windows(self) -> None:
        """В Windows сырой режим не нужен: msvcrt отдаёт по символу.

        Дополнительно пробуем включить VT-вход (Windows 10+): тогда консоль сама
        присылает ESC-последовательности и bracketed paste для вставки.
        """
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                ENABLE_WINDOW_INPUT = 0x0008
                ENABLE_VT_INPUT = 0x0200
                new_mode = (mode.value & ~0x0001 & ~0x0004) | ENABLE_WINDOW_INPUT | ENABLE_VT_INPUT
                self._win_vt = bool(kernel32.SetConsoleMode(handle, new_mode))
                if not self._win_vt:
                    kernel32.SetConsoleMode(handle, mode.value)
        except Exception:  # noqa: BLE001
            self._win_vt = False

    # -- чтение -------------------------------------------------------------

    def read(self, timeout: float = 0.05) -> List[KeyEvent]:
        """Ждёт до ``timeout`` секунд и возвращает все готовые события (возможно, пустой список)."""
        if IS_WINDOWS:
            return self._read_windows(timeout)
        return self._read_posix(timeout)

    def _read_posix(self, timeout: float) -> List[KeyEvent]:
        import select

        events: List[KeyEvent] = []
        deadline = time.time() + max(0.0, timeout)
        while True:
            left = deadline - time.time()
            if left <= 0 and events:
                break
            try:
                ready, _, _ = select.select([sys.stdin], [], [], max(0.0, left))
            except (OSError, ValueError):
                break
            if not ready:
                break
            try:
                data = os.read(sys.stdin.fileno(), 4096)
            except OSError:
                break
            if not data:
                break
            events.extend(self.parser.feed(data))
            if left <= 0:
                break
        # пустой проход нужен, чтобы одиночный Esc «дозрел» по таймауту
        events.extend(self.parser.feed(b""))
        return events

    def _read_windows(self, timeout: float) -> List[KeyEvent]:
        import msvcrt

        events: List[KeyEvent] = []
        deadline = time.time() + max(0.0, timeout)
        while True:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\x00", "\xe0"):
                    code = msvcrt.getwch()
                    mapped = {"H": "up", "P": "down", "M": "right", "K": "left",
                              "G": "home", "O": "end", "S": "delete", "I": "pageup",
                              "Q": "pagedown", "R": "insert"}
                    events.append(KeyEvent(mapped.get(code, "unknown")))
                else:
                    events.extend(self.parser.feed(ch.encode("utf-8", "replace")))
                continue
            if events or time.time() >= deadline:
                break
            time.sleep(0.005)
        events.extend(self.parser.feed(b""))
        return events

    def drain(self) -> List[KeyEvent]:
        """Собрать то, что уже накопилось в буфере (одиночный Esc и хвосты вставки)."""
        return self.parser.flush()
