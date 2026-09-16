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

VK_NAMES = {
    0x26: "up", 0x28: "down", 0x27: "right", 0x25: "left",
    0x24: "home", 0x23: "end", 0x21: "pageup", 0x22: "pagedown",
    0x2D: "insert", 0x2E: "delete",
}

#: маски dwControlKeyState
_WIN_CTRL = 0x000C     # LEFT_CTRL | RIGHT_CTRL
_WIN_SHIFT = 0x0010
_WIN_ALT = 0x0003

_INPUT_RECORD_CLS = None


def _input_record_cls():
    """INPUT_RECORD из WinAPI: лениво, чтобы не трогать ctypes вне Windows."""
    global _INPUT_RECORD_CLS
    if _INPUT_RECORD_CLS is None:
        import ctypes

        class _KeyEvent(ctypes.Structure):
            _fields_ = [("bKeyDown", ctypes.c_int32),
                        ("wRepeatCount", ctypes.c_uint16),
                        ("wVirtualKeyCode", ctypes.c_uint16),
                        ("wVirtualScanCode", ctypes.c_uint16),
                        ("uChar", ctypes.c_wchar),
                        ("dwControlKeyState", ctypes.c_uint32)]

        class _InputRecord(ctypes.Structure):
            _fields_ = [("EventType", ctypes.c_uint16), ("Event", _KeyEvent)]

        _INPUT_RECORD_CLS = _InputRecord
    return _INPUT_RECORD_CLS


def win_key_events(items) -> List["KeyEvent"]:
    """События клавиш Windows в события ELYTRIX.

    ``items`` — последовательность (символ, vk, ctrl, shift, alt). Обычные
    символы копятся пакетом: многострочная вставка из меню консоли приходит
    одним событием ``paste`` и не отправляет задачу переводом строки внутри.
    """
    events: List[KeyEvent] = []
    run: List[str] = []

    def flush() -> None:
        if run:
            events.extend(KeyReader.feed_raw(run[:]))
            run.clear()

    for ch, vk, ctrl, shift, alt in items:
        if not ch or ch == "\x00":
            flush()
            name = VK_NAMES.get(vk, "unknown")
            if name != "unknown":
                name = ("ctrl+" if ctrl else "") + ("shift+" if shift else "") \
                    + ("alt+" if alt else "") + name
            events.append(KeyEvent(name))
            continue
        if ctrl and ch in CTRL_NAMES:
            flush()
            if shift and ch in ("\x03", "\x16"):
                events.append(KeyEvent("ctrl+shift+c" if ch == "\x03"
                                         else "ctrl+shift+v"))
            else:
                events.append(KeyEvent(CTRL_NAMES[ch]))
            continue
        if alt:
            flush()
            if ch == "\r":
                events.append(KeyEvent("alt+enter"))
            else:
                events.append(KeyEvent("alt+" + ch, ch))
            continue
        run.append(ch)
    flush()
    return events


_SHARED_PARSER: Optional[KeyParser] = None

WIN_SPECIAL = {
    "H": "up", "P": "down", "M": "right", "K": "left",
    "G": "home", "O": "end", "S": "delete", "I": "pageup",
    "Q": "pagedown", "R": "insert",
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
            parts = params.split(";")
            number = parts[0]
            if number == "200":
                self._paste = []
                return True
            if number == "201":
                return True
            if number == "27" and len(parts) >= 3:
                # modifyOtherKeys: CSI 27;модификаторы;код~ — так приходят
                # Ctrl+Shift+C / Ctrl+Shift+V, неотличимые иначе от Ctrl+C / Ctrl+V
                out.append(KeyEvent(self._modified_name(parts)))
                return True
            name = TILDE_NAMES.get(number, "unknown")
            if len(parts) > 1 and parts[1].isdigit():
                name = MODIFIER_PREFIX.get(int(parts[1]), "") + name
            out.append(KeyEvent(name))
            return True

        if final == "u":
            # kitty-протокол: CSI код-символа;модификаторы u
            out.append(KeyEvent(self._modified_name(params.split(";"), unicode=True)))
            return True

        number, _, modifier = params.partition(";")
        name = KEY_NAMES.get(final, "unknown")
        if modifier.isdigit():
            name = MODIFIER_PREFIX.get(int(modifier), "") + name
        out.append(KeyEvent(name))
        return True

    @staticmethod
    def _modified_name(parts: List[str], unicode: bool = False) -> str:
        """Имя клавиши из «27;мод;код» (modifyOtherKeys) или «код;мод» (kitty)."""
        try:
            if unicode:
                code = int(parts[0])
                mod = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
            else:
                mod = int(parts[1])
                code = int(parts[2])
        except (ValueError, IndexError):
            return "unknown"
        if not 32 <= code < 127:
            return "unknown"
        return MODIFIER_PREFIX.get(mod, "") + chr(code).lower()


class KeyReader:
    """Читает нажатия из консоли с таймаутом (нужен для анимации спиннера)."""

    def __init__(self) -> None:
        self.parser = KeyParser()
        self._fd: Optional[int] = None
        self._old = None
        self._win_vt = False
        self._win_old = None
        self._win_ki = None
        self._mod_keys = False

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
        # modifyOtherKeys: просим терминал присылать Ctrl+Shift+буква отдельной
        # последовательностью — иначе её не отличить от Ctrl+буква.
        # В Windows не просим: сочетания ловим по состоянию Shift, а conhost
        # от незнакомых последовательностей иногда ведёт себя странно.
        if not IS_WINDOWS:
            try:
                sys.stdout.write("\x1b[>4;2m")
                sys.stdout.flush()
                self._mod_keys = True
            except Exception:  # noqa: BLE001
                pass

    def close(self) -> None:
        if self._mod_keys:
            try:
                sys.stdout.write("\x1b[>4;0m")   # выключаем modifyOtherKeys
                sys.stdout.flush()
            except Exception:  # noqa: BLE001
                pass
            self._mod_keys = False
        if IS_WINDOWS:
            if self._win_old is not None:
                try:
                    import ctypes

                    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
                    kernel32.SetConsoleMode(kernel32.GetStdHandle(-10), self._win_old)
                except Exception:  # noqa: BLE001
                    pass
                self._win_old = None
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

        QuickEdit и мышиный ввод на время работы выключаем: случайный клик по
        окну в классической консоли включает выделение и замораживает ввод
        и вывод программы — «буквы пропадают», пока не нажмёшь Esc/Enter.
        """
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                ENABLE_WINDOW_INPUT = 0x0008
                ENABLE_VT_INPUT = 0x0200
                ENABLE_EXTENDED = 0x0080      # нужен, чтобы менять QuickEdit
                MOUSE_INPUT = 0x0010
                QUICK_EDIT = 0x0040
                self._win_old = mode.value
                # QuickEdit/мышь выключаем ОТДЕЛЬНЫм вызовом: даже если VT-вход
                # не поддержан, заморозка выделения не должна оставаться
                no_quick = (mode.value & ~MOUSE_INPUT & ~QUICK_EDIT) | ENABLE_EXTENDED
                kernel32.SetConsoleMode(handle, no_quick)
                # VT-вход legacy-консоли (conhost) ненадёжен в паре с msvcrt —
                # включаем только по явному запросу ELYTRIX_VT=1
                vt_wanted = os.environ.get("ELYTRIX_VT", "").lower() in ("1", "yes", "true", "on")
                new_mode = (no_quick & ~0x0001 & ~0x0004) | ENABLE_WINDOW_INPUT \
                    | (ENABLE_VT_INPUT if vt_wanted else 0)
                self._win_vt = bool(vt_wanted) and bool(kernel32.SetConsoleMode(handle, new_mode))
                if vt_wanted and not self._win_vt:
                    kernel32.SetConsoleMode(handle, no_quick)
        except Exception:  # noqa: BLE001
            self._win_vt = False
        self._win_ki = self._win_prepare()

    def _win_prepare(self):
        """Рекорды и хендл для неблокирующего чтения событий консоли."""
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.GetStdHandle(-10)
            if not handle or handle == -1:
                return None
            recs = (_input_record_cls() * 128)()
            probe = ctypes.c_uint32(0)
            if not kernel32.PeekConsoleInputW(handle, recs, 1, ctypes.byref(probe)):
                return None
            return (kernel32, handle, recs)
        except Exception:  # noqa: BLE001
            return None

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
        """Читает нажатия событиями консоли, без блокировок.

        msvcrt.getwch() умеет встать на служебном событии окна (focus/resize),
        из-за чего символы копятся и вываливаются пачкой — «залагивает».
        PeekConsoleInputW не блокируется никогда: посмотрели, есть ли события,
        и только тогда забираем их ReadConsoleInputW.
        """
        if self._win_ki is None:
            return self._read_windows_msvcrt(timeout)
        events: List[KeyEvent] = []
        deadline = time.time() + max(0.0, timeout)
        while True:
            items = self._win_poll()
            if items:
                events.extend(win_key_events(items))
                continue
            if events or time.time() >= deadline:
                break
            time.sleep(0.005)
        return events

    def _win_poll(self, limit: int = 128):
        import ctypes

        kernel32, handle, recs = self._win_ki
        peeked = ctypes.c_uint32(0)
        if not kernel32.PeekConsoleInputW(handle, recs, limit, ctypes.byref(peeked)):
            return []
        if not peeked.value:
            return []
        got = ctypes.c_uint32(0)
        if not kernel32.ReadConsoleInputW(handle, recs, peeked.value, ctypes.byref(got)):
            return []
        items = []
        for i in range(got.value):
            record = recs[i]
            if record.EventType != 1 or not record.Event.bKeyDown:
                continue          # focus/resize/отжатие — не клавиша
            state = record.Event.dwControlKeyState
            for _ in range(max(1, record.Event.wRepeatCount)):
                items.append((record.Event.uChar, record.Event.wVirtualKeyCode,
                              bool(state & _WIN_CTRL), bool(state & _WIN_SHIFT),
                              bool(state & _WIN_ALT)))
        return items

    def _read_windows_msvcrt(self, timeout: float) -> List[KeyEvent]:
        """Запасной путь, если события консоли недоступны: по символу за раз."""
        import msvcrt

        events: List[KeyEvent] = []
        deadline = time.time() + max(0.0, timeout)
        while True:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\x00", "\xe0"):
                    if not msvcrt.kbhit():
                        events.append(KeyEvent("unknown"))
                        continue
                    events.append(KeyEvent(WIN_SPECIAL.get(msvcrt.getwch(), "unknown")))
                elif ch in ("\x03", "\x16") and self._shift_held():
                    events.append(KeyEvent("ctrl+shift+c" if ch == "\x03"
                                             else "ctrl+shift+v"))
                else:
                    events.extend(self.parser.feed(ch.encode("utf-8", "replace")))
                continue
            if events or time.time() >= deadline:
                break
            time.sleep(0.005)
        events.extend(self.parser.feed(b""))
        return events

    @staticmethod
    def feed_raw(raw: List[str]) -> List[KeyEvent]:
        """Пакет символов из консоли: обычная печать или многострочная вставка."""
        text = "".join(raw)
        body = text[:-1] if text and text[-1] in "\r\n" else text
        if "\r" in body or "\n" in body:
            return [KeyEvent("paste", text.replace("\r\n", "\n").replace("\r", "\n"))]
        return KeyReader._parser_static().feed(text.encode("utf-8", "replace"))

    @staticmethod
    def _parser_static() -> KeyParser:
        """Общий разборчик для пакетов символов (вне экземпляра читалки)."""
        global _SHARED_PARSER
        if _SHARED_PARSER is None:
            _SHARED_PARSER = KeyParser()
        return _SHARED_PARSER

    def drain(self) -> List[KeyEvent]:
        """Собрать то, что уже накопилось в буфере (одиночный Esc и хвосты вставки)."""
        return self.parser.flush()

    @staticmethod
    def _shift_held() -> bool:
        """Зажат ли Shift прямо сейчас (Windows): чтобы отличить Ctrl+Shift+C."""
        try:
            import ctypes

            return bool(ctypes.windll.user32.GetAsyncKeyState(0x10) & 0x8000)
        except Exception:  # noqa: BLE001
            return False
