# -*- coding: utf-8 -*-
"""Буфер обмена для Ctrl+Shift+C / Ctrl+Shift+V и команд /copy, /paste.

Порядок бэкендов — от системного к запасному:
    · Windows  — WinAPI через ctypes (без внешних программ);
    · macOS    — pbcopy / pbpaste;
    · Linux    — wl-copy/wl-paste, затем xclip, затем xsel;
    · терминал — OSC 52 (копия уходит в буфер самого терминала, работает даже по ssh);
    · процесс  — внутренняя строка: вставка работает всегда, даже если буфера нет.

``copy`` возвращает имя бэкенда, ``paste`` — пару (текст, имя): интерфейс показывает
их в строке активности, чтобы было видно, куда реально легла копия.
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys
from typing import Optional, Tuple

IS_WINDOWS = os.name == "nt"
IS_MAC = sys.platform == "darwin"

#: запасной буфер внутри процесса (последняя скопированная строка)
_internal = ""

_COPY_CMDS = (("wl-copy", ["wl-copy"]),
              ("xclip", ["xclip", "-selection", "clipboard"]),
              ("xsel", ["xsel", "--clipboard", "--input"]))
_PASTE_CMDS = (("wl-paste", ["wl-paste", "--no-primary"]),
               ("xclip", ["xclip", "-selection", "clipboard", "-o"]),
               ("xsel", ["xsel", "--clipboard", "--output"]))


# ---------------------------------------------------------------------------
# Windows: WinAPI через ctypes
# ---------------------------------------------------------------------------


def _win_clipboard(text: Optional[str]) -> Optional[str]:
    """text is None — читать; иначе писать. None — не получилось."""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.OpenClipboard.argtypes = [ctypes.c_void_p]
        user32.GetClipboardData.restype = ctypes.c_void_p
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    except Exception:  # noqa: BLE001
        return None
    CF_UNICODETEXT = 13
    try:
        if not user32.OpenClipboard(None):
            return None
        try:
            if text is None:
                handle = user32.GetClipboardData(CF_UNICODETEXT)
                if not handle:
                    return ""
                ptr = kernel32.GlobalLock(handle)
                if not ptr:
                    return ""
                try:
                    return ctypes.wstring_at(ptr)
                finally:
                    kernel32.GlobalUnlock(handle)
            data = (text + "\0").encode("utf-16-le")
            user32.EmptyClipboard()
            handle = kernel32.GlobalAlloc(0x0042, len(data))   # MOVEABLE|ZEROINIT
            if not handle:
                return None
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return None
            ctypes.memmove(ptr, data, len(data))
            kernel32.GlobalUnlock(handle)
            return "" if user32.SetClipboardData(CF_UNICODETEXT, handle) else None
        finally:
            user32.CloseClipboard()
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# внешние программы (macOS / Linux)
# ---------------------------------------------------------------------------


def _run(cmd: list, stdin: Optional[str] = None) -> Optional[str]:
    try:
        proc = subprocess.run(cmd,
                              input=stdin.encode("utf-8") if stdin is not None else None,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=2, check=False)
    except Exception:  # noqa: BLE001
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", "replace") if stdin is None else ""


def _osc52(text: str) -> bool:
    """Копия в буфер самого терминала: работает в любом современном терминале,
    в том числе через ssh, где системного буфера у процесса нет."""
    payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
    try:
        sys.stdout.write("\x1b]52;c;" + payload + "\x07")
        sys.stdout.flush()
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# публичный интерфейс
# ---------------------------------------------------------------------------


def copy(text: str, system: bool = True, osc: bool = True) -> str:
    """Положить текст в буфер. Возвращает имя бэкенда («windows», «xclip», …)."""
    global _internal
    _internal = text
    if system:
        if IS_WINDOWS:
            if _win_clipboard(text) is not None:
                return "windows"
        elif IS_MAC:
            if _run(["pbcopy"], text) is not None:
                return "macos"
        else:
            for name, cmd in _COPY_CMDS:
                if _run(cmd, text) is not None:
                    return name
    if osc and _osc52(text):
        return "терминал"
    return "внутренний"


def paste(system: bool = True) -> Tuple[str, str]:
    """Достать текст из буфера: (текст, имя бэкенда). Пусто — («», «»)."""
    if system:
        if IS_WINDOWS:
            value = _win_clipboard(None)
            if value is not None:
                return value, "windows"
        elif IS_MAC:
            value = _run(["pbpaste"])
            if value is not None:
                return value, "macos"
        else:
            for name, cmd in _PASTE_CMDS:
                value = _run(cmd)
                if value is not None:
                    return value, name
    if _internal:
        return _internal, "внутренний"
    return "", ""


def reset() -> None:
    """Сброс внутреннего буфера (для тестов)."""
    global _internal
    _internal = ""
