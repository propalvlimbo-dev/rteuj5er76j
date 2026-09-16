# -*- coding: utf-8 -*-
"""Настройки, ключ и учёт расхода.

Три места, где ELYTRIX хранит данные:

    config/elytrix.json        настройки проекта: шлюз, модели и коэффициенты, лимиты,
                               экономия контекста, оформление (можно править блокнотом)
    ~/.elytrix/credentials.json  ключ SMARTAPI_KEY (права 600, в git не попадает)
    ~/.elytrix/state.json        расход за сутки, последняя папка, режим подтверждений

Ключ ищется по порядку: переменная окружения SMARTAPI_KEY → файл credentials.json →
вопрос в интерфейсе при первом запуске.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

APP_NAME = "ELYTRIX"
CONFIG_REL = os.path.join("config", "elytrix.json")

#: Ключ по умолчанию — Anthropic-формат шлюза SmartAPI
DEFAULT_GATEWAY = {
    "base_url": "https://api.smartapi.shop",
    "openai_base_url": "https://api.smartapi.shop/v1",
    "key_env": "SMARTAPI_KEY",
    "anthropic_version": "2023-06-01",
    "reasoning_effort": "low",  # «думание» reasoning-моделей: low дешевле в разы
    "timeout": 300,
    "connect_timeout": 15,
    "retries": 1,
}

#: Каталог моделей SmartAPI с коэффициентами расхода (баланс — «зачётные токены»)
DEFAULT_MODELS: Dict[str, Any] = {
    "default": "auto",
    "aliases": {
        "auto": {"model": "claude-sonnet-4-6", "note": "обычная работа"},
        "cheap": {"model": "gpt-5.6-luna", "note": "самая дешёвая"},
        "smart": {"model": "claude-opus-4-8", "note": "сложные задачи"},
        "max": {"model": "claude-opus-5", "note": "максимум качества"},
    },
    "catalog": {
        "gpt-5.6-luna": {"mult": 1.7, "ctx": 200000, "family": "GPT", "note": "дёшево и быстро"},
        "claude-sonnet-4-6": {"mult": 2.0, "ctx": 200000, "family": "Claude", "note": "рабочая лошадка"},
        "claude-sonnet-5": {"mult": 2.5, "ctx": 200000, "family": "Claude", "note": "свежий Sonnet"},
        "gpt-5.6-terra": {"mult": 3.0, "ctx": 200000, "family": "GPT", "note": "средний GPT"},
        "gpt-5.6-sol": {"mult": 4.0, "ctx": 200000, "family": "GPT", "note": "старший GPT"},
        "codex-auto-review": {"mult": 4.0, "ctx": 200000, "family": "Codex", "note": "ревью кода"},
        "claude-opus-4-6": {"mult": 4.0, "ctx": 200000, "family": "Claude", "note": "Opus 4.6"},
        "claude-opus-4-7": {"mult": 4.0, "ctx": 200000, "family": "Claude", "note": "Opus 4.7"},
        "claude-opus-4-8": {"mult": 4.0, "ctx": 200000, "family": "Claude", "note": "Opus 4.8"},
        "claude-opus-5": {"mult": 5.0, "ctx": 200000, "family": "Claude", "note": "самый сильный"},
        "gpt-6-astra": {"mult": 8.0, "ctx": 200000, "family": "GPT", "note": "дорого"},
        "claude-fable-5": {"mult": 10.0, "ctx": 200000, "family": "Claude", "note": "очень дорого"},
        "claude-fable-5-1": {"mult": 10.0, "ctx": 200000, "family": "Claude", "note": "очень дорого"},
    },
}

DEFAULT_LIMITS = {
    "daily_tokens": 400000,     # зачётных токенов в сутки (предохранитель от «сжёг за вечер»)
    "max_steps": 24,            # потолок шагов агента на одну задачу
    "max_output_tokens": 8192,  # сколько модель может ответить за шаг
}

DEFAULT_ECONOMY = {
    "cache": True,              # prompt caching: повторный контекст стоит заметно дешевле
    "compact_at": 0.55,         # доля контекста модели, после которой история сжимается
    "tool_result_chars": 6000,  # предел одного результата инструмента
    "bash_output_chars": 4000,  # предел вывода команды
    "grep_hits": 40,            # сколько совпадений отдаём модели
    "keep_recent": 2,           # сколько последних результатов не сжимаем
    "step_cap": 32000,          # стоимостной потолок истории внутри задачи
    "read_chars": 12000,        # сколько символов файла читаем за раз
}

DEFAULT_UI = {
    "theme": "rose",
    "color": "auto",            # auto | truecolor | 256 | 16 | none
    "confirm": "ask",           # ask | auto | readonly
    "verbose": False,           # показывать содержимое результатов инструментов
    "stream": True,
    "show_tips": True,
    "language": "ru",
}

DEFAULTS: Dict[str, Any] = {
    "gateway": DEFAULT_GATEWAY,
    "models": DEFAULT_MODELS,
    "limits": DEFAULT_LIMITS,
    "economy": DEFAULT_ECONOMY,
    "ui": DEFAULT_UI,
}


# ---------------------------------------------------------------------------
# Пути
# ---------------------------------------------------------------------------


def project_root() -> str:
    """Корень проекта ELYTRIX (на уровень выше app/)."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def home_dir() -> str:
    """Папка пользовательских данных: %LOCALAPPDATA%\\ELYTRIX или ~/.elytrix."""
    base = os.environ.get("ELYTRIX_HOME")
    if base:
        return os.path.abspath(os.path.expanduser(base))
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        return os.path.join(base, APP_NAME)
    return os.path.join(os.path.expanduser("~"), ".elytrix")


def ensure_home() -> str:
    path = home_dir()
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    return path


def state_path() -> str:
    return os.path.join(ensure_home(), "state.json")


def credentials_path() -> str:
    return os.path.join(ensure_home(), "credentials.json")


def sessions_dir() -> str:
    path = os.path.join(ensure_home(), "sessions")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    return path


def config_path(root: Optional[str] = None) -> str:
    return os.path.join(root or project_root(), CONFIG_REL)


# ---------------------------------------------------------------------------
# Конфиг
# ---------------------------------------------------------------------------


def _deep_merge(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


class Config:
    """Настройки с доступом по точечному пути: ``cfg.get("limits.daily_tokens")``."""

    def __init__(self, data: Optional[Dict[str, Any]] = None, path: str = ""):
        self.data = _deep_merge(DEFAULTS, data or {})
        self.path = path

    @classmethod
    def load(cls, path: Optional[str] = None) -> "Config":
        path = path or config_path()
        data: Dict[str, Any] = {}
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                data = {}
        cfg = cls(data, path)
        ws = cfg.workspace_config()
        if ws:
            cfg.data = _deep_merge(cfg.data, ws)
        return cfg

    def workspace_config(self, workspace: Optional[str] = None) -> Dict[str, Any]:
        """Локальные настройки папки проекта: .elytrix/config.json (перекрывают общие)."""
        if not workspace:
            return {}
        path = os.path.join(workspace, ".elytrix", "config.json")
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def get(self, path: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, path: str, value: Any) -> None:
        parts = path.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                return
        node[parts[-1]] = value

    def save(self, path: Optional[str] = None) -> bool:
        target = path or self.path
        if not target:
            return False
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            tmp = target + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(tmp, target)
            return True
        except OSError:
            return False


# ---------------------------------------------------------------------------
# Модели и коэффициенты
# ---------------------------------------------------------------------------


class Catalog:
    """Каталог моделей: алиасы, коэффициенты расхода, размер контекста."""

    def __init__(self, models_cfg: Dict[str, Any]):
        self.default = str(models_cfg.get("default") or "auto")
        self.aliases: Dict[str, Dict[str, Any]] = dict(models_cfg.get("aliases") or {})
        self.catalog: Dict[str, Dict[str, Any]] = dict(models_cfg.get("catalog") or {})
        self.extra: List[str] = []        # модели, которых нет в каталоге (добавил пользователь)

    def is_alias(self, name: str) -> bool:
        return name in self.aliases

    def resolve(self, name: Optional[str]) -> str:
        """alias | модель -> конкретный ID модели."""
        wanted = (name or self.default or "auto").strip()
        if wanted in self.aliases:
            return str(self.aliases[wanted].get("model") or wanted)
        return wanted

    def multiplier(self, model: str) -> float:
        entry = self.catalog.get(model) or {}
        try:
            return max(1.0, float(entry.get("mult") or 1.0))
        except (TypeError, ValueError):
            return 1.0

    def context(self, model: str) -> int:
        entry = self.catalog.get(model) or {}
        try:
            return int(entry.get("ctx") or 200000)
        except (TypeError, ValueError):
            return 200000

    def note(self, model: str) -> str:
        return str((self.catalog.get(model) or {}).get("note") or "")

    def family(self, model: str) -> str:
        entry = self.catalog.get(model) or {}
        if entry.get("family"):
            return str(entry["family"])
        low = model.lower()
        for name, prefix in (("Claude", "claude"), ("GPT", "gpt"), ("Codex", "codex")):
            if low.startswith(prefix):
                return name
        return "Прочее"

    def all_models(self) -> List[str]:
        """Сначала дешёвые: агент экономит токены, значит и деньги пользователя."""
        known = sorted(self.catalog.items(), key=lambda kv: (float(kv[1].get("mult") or 1), kv[0]))
        return [name for name, _ in known] + [m for m in self.extra if m not in self.catalog]

    def add_models(self, ids: List[str]) -> int:
        """Добавляет модели, которые шлюз отдал в /models, но которых нет в конфиге."""
        added = 0
        for mid in ids:
            mid = str(mid).strip()
            if not mid or mid in self.catalog or mid in self.extra:
                continue
            self.extra.append(mid)
            added += 1
        return added

    def price_word(self, mult: float) -> str:
        if mult <= 2:
            return "дёшево"
        if mult <= 3:
            return "средне"
        if mult <= 4:
            return "дорого"
        if mult <= 6:
            return "очень дорого"
        return "не тратить зря"


# ---------------------------------------------------------------------------
# Ключ
# ---------------------------------------------------------------------------


def read_key(env_name: str = "SMARTAPI_KEY") -> Tuple[str, str]:
    """Возвращает (ключ, источник). Источник — для строки статуса."""
    key = (os.environ.get(env_name) or "").strip()
    if key:
        return key, "env"
    path = credentials_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        key = str(data.get("key") or "").strip()
        if key:
            return key, "file"
    except (OSError, ValueError):
        pass
    return "", ""


def save_key(key: str, persistent: bool = True) -> str:
    """Пишет ключ в ~/.elytrix/credentials.json с правами 600.

    На Windows дополнительно предлагает setx — тогда ключ виден и в новых окнах cmd,
    и в редакторах (Cline, Continue, opencode) без лишних настроек.
    """
    path = credentials_path()
    ensure_home()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"key": key, "saved_at": time.time()}, f, ensure_ascii=False)
        if os.name != "nt":
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        return ""
    os.environ["SMARTAPI_KEY"] = key
    if persistent and os.name == "nt":
        try:
            subprocess.run(["setx", "SMARTAPI_KEY", key], capture_output=True, timeout=20)
        except Exception:  # noqa: BLE001
            pass
    return path


def mask_key(key: str) -> str:
    if not key:
        return "(нет ключа)"
    if len(key) <= 12:
        return key[:3] + "…"
    return f"{key[:11]}…{key[-4:]}"


# ---------------------------------------------------------------------------
# Состояние: расход за сутки и мелкие настройки
# ---------------------------------------------------------------------------


def utc_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class State:
    """Небольшое JSON-состояние: расход за сутки, последняя папка, режимы.

    Суточный расход считается в «зачётных токенах» (токены × коэффициент модели) —
    ровно так же их считает баланс SmartAPI, поэтому цифра в статус-строке совпадает
    с тем, что видно в кабинете.
    """

    def __init__(self, path: Optional[str] = None):
        self.path = path or state_path()
        self.data: Dict[str, Any] = {"day": utc_day(), "tokens_day": 0, "requests_day": 0,
                                     "by_model": {}, "history": []}
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self.data.update(loaded)
        except (OSError, ValueError):
            pass
        self._roll()

    def _roll(self) -> None:
        today = utc_day()
        if self.data.get("day") != today:
            yesterday = {"day": self.data.get("day"), "tokens": self.data.get("tokens_day", 0),
                         "requests": self.data.get("requests_day", 0)}
            history = list(self.data.get("history") or [])[-29:]
            history.append(yesterday)
            self.data.update({"day": today, "tokens_day": 0, "requests_day": 0,
                              "by_model": {}, "history": history})
            self.save()

    def save(self) -> None:
        try:
            ensure_home()
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            pass

    # --- расход ---

    def record(self, model: str, tokens_in: int, tokens_out: int, mult: float,
               cache_read: int = 0, cache_write: int = 0) -> int:
        """Учитывает запрос, возвращает списанные зачётные токены."""
        self._roll()
        charged = int(round((tokens_in + tokens_out) * float(mult or 1)))
        self.data["tokens_day"] = int(self.data.get("tokens_day") or 0) + charged
        self.data["requests_day"] = int(self.data.get("requests_day") or 0) + 1
        by_model = self.data.setdefault("by_model", {})
        entry = by_model.setdefault(model, {"tokens": 0, "requests": 0, "cache_read": 0})
        entry["tokens"] = int(entry.get("tokens") or 0) + charged
        entry["requests"] = int(entry.get("requests") or 0) + 1
        entry["cache_read"] = int(entry.get("cache_read") or 0) + int(cache_read or 0)
        self.save()
        return charged

    @property
    def tokens_day(self) -> int:
        self._roll()
        return int(self.data.get("tokens_day") or 0)

    @property
    def requests_day(self) -> int:
        self._roll()
        return int(self.data.get("requests_day") or 0)

    def by_model(self) -> Dict[str, Dict[str, int]]:
        return dict(self.data.get("by_model") or {})

    def history(self) -> List[Dict[str, Any]]:
        return list(self.data.get("history") or [])

    # --- мелкие настройки ---

    def get(self, key: str, default: Any = None) -> Any:
        value = self.data.get(key, default)
        return default if value is None else value

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.save()
