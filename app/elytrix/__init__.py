# -*- coding: utf-8 -*-
"""ELYTRIX — компактный ИИ-агент для консоли на ключе SmartAPI.

Один процесс, никаких зависимостей кроме стандартной библиотеки Python 3.9+:
агент говорит с https://api.smartapi.shop напрямую (формат Anthropic, при отказе —
формат OpenAI), сам считает расход и держит дневной лимит.

Точка входа: ``python -m elytrix`` (из Windows — ELYTRIX.bat).
"""

__version__ = "3.3.1"
__all__ = ["__version__"]
