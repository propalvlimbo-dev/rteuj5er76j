#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeCoder Router — OpenAI-совместимый шлюз к SmartAPI: дневной лимит расхода,
перевод форматов (OpenAI <-> Anthropic), failover между адресами шлюза.

Зачем он нужен:
    Баланс SmartAPI измеряется зачётными токенами, и без прослойки его легко
    сжечь за один вечер. Роутер стоит между агентом и шлюзом и:
      1) считает расход по коэффициенту каждой модели (×1,7 ... ×10),
      2) держит дневной лимит tpd: выбран — платный канал до конца суток не используется,
      3) при 429 / 5xx / таймауте мгновенно пробует второй адрес шлюза,
      4) переводит формат: клиент говорит по-OpenAI, шлюз отвечает по-Anthropic,
      5) при старте сверяет имена моделей с каталогом шлюза и подставляет верные.

    Агенту (opencode, Cline, Kilo Code, aider или встроенному agent/freecoder_agent.py)
    достаточно указать base_url = http://127.0.0.1:8788/v1 и любой ключ-заглушку.

Запуск:
    python freecoder_router.py                 # порт 8788, host 127.0.0.1
    python freecoder_router.py --host 0.0.0.0 --port 8788
    python freecoder_router.py --mock          # демо-провайдер без ключей (проверка)

Зависимостей нет — только стандартная библиотека Python 3.8+.

Лицензия: MIT. Файл можно свободно менять.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Iterable, List, Optional, Tuple

VERSION = "1.0.0"
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(HERE, "providers.json")
SMARTAPI_CONFIG = os.path.join(HERE, "providers.smartapi.json")
DEFAULT_STATE = os.path.join(HERE, "state.json")

# ----------------------------------------------------------------------------
# Вспомогательное
# ----------------------------------------------------------------------------


def now_ts() -> float:
    return time.time()


def utc_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def est_tokens(text: Any) -> int:
    """Грубая оценка токенов (без зависимостей). Для русского ~2.5 символа/токен."""
    if not text:
        return 0
    if not isinstance(text, str):
        try:
            text = json.dumps(text, ensure_ascii=False)
        except Exception:
            text = str(text)
    return max(1, int(len(text) / 2.8))


LOG_FILE: List[str] = [""]          # путь к журналу задаётся ключом --log-file


def log(*parts: Any) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    line = " ".join(str(p) for p in parts)
    print(f"[{stamp}]", line, flush=True)
    path = LOG_FILE[0]
    if path:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"[{stamp}] {line}\n")
        except OSError:
            pass


# ----------------------------------------------------------------------------
# Модель данных
# ----------------------------------------------------------------------------


@dataclass
class Provider:
    """Один провайдер = один OpenAI-совместимый base_url + список ключей."""

    name: str
    base_url: str
    models: List[str] = field(default_factory=list)
    keys: List[str] = field(default_factory=list)
    key_env: Optional[str] = None           # имя переменной окружения со списком ключей
    priority: int = 100                     # меньше = предпочтительнее
    enabled: bool = True
    headers: Dict[str, str] = field(default_factory=dict)
    limits: Dict[str, int] = field(default_factory=dict)  # rpm, rpd, tpm, tpd, max_ctx
    cost_multiplier: float = 1.0            # множитель расхода (коэффициент модели у шлюзов)
    model_multipliers: Dict[str, float] = field(default_factory=dict)  # свой коэффициент каждой модели
    cooldown_on_error: int = 60             # сек. блокировки провайдера после 5xx/сети
    cooldown_on_429: int = 900              # сек. блокировки ключа при исчерпании квоты
    timeout: int = 180                      # сек. на чтение ответа (стриминг длинный!)
    notes: str = ""
    kind: str = "openai"                    # openai | ollama | mock
    model_map: Dict[str, str] = field(default_factory=dict)  # имя в конфиге -> имя в каталоге шлюза

    def all_keys(self) -> List[str]:
        keys = [k.strip() for k in (self.keys or []) if k and k.strip()]
        if self.key_env:
            raw = os.environ.get(self.key_env, "")
            for chunk in re.split(r"[,\n;]", raw):
                chunk = chunk.strip()
                if chunk:
                    keys.append(chunk)
        # Ключи-заглушки для локальных/анонимных провайдеров
        if not keys and self.kind in ("ollama", "mock"):
            keys = ["local"]
        # Дедупликация с сохранением порядка
        seen, out = set(), []
        for k in keys:
            if k not in seen:
                seen.add(k)
                out.append(k)
        return out

    def multiplier(self, model: str = "") -> float:
        """Коэффициент расхода для модели: свой, иначе общий по провайдеру."""
        name = (model or "").split("/")[-1]
        for candidate in (name, self.model_map.get(name, "")):
            if candidate and candidate in self.model_multipliers:
                return max(1.0, float(self.model_multipliers[candidate]))
        return max(1.0, float(self.cost_multiplier or 1.0))

    def url(self, path: str) -> str:
        return self.base_url.rstrip("/") + path


@dataclass
class KeyState:
    """Состояние одного ключа: израсходованная квота и блокировки."""

    requests_min: List[float] = field(default_factory=list)  # timestamps запросов за минуту
    requests_day: int = 0
    tokens_day: int = 0
    day: str = field(default_factory=utc_day)
    blocked_until: float = 0.0
    last_error: str = ""
    last_used: float = 0.0

    def roll(self) -> None:
        today = utc_day()
        if self.day != today:
            self.day = today
            self.requests_day = 0
            self.tokens_day = 0
        cutoff = now_ts() - 60
        if self.requests_min and self.requests_min[0] < cutoff:
            self.requests_min = [t for t in self.requests_min if t >= cutoff]


# ----------------------------------------------------------------------------
# Роутер
# ----------------------------------------------------------------------------


class Router:
    def __init__(self, config: Dict[str, Any], state_path: str, mock: bool = False):
        self.lock = threading.RLock()
        self.config = config
        self.state_path = state_path
        self.mock = mock
        self.aliases: Dict[str, List[str]] = config.get("aliases", {}) or {}
        self.default_alias: str = config.get("default_alias", "auto")
        self.prefer_local_when_quota_out: bool = bool(
            config.get("prefer_local_when_quota_out", True)
        )
        self.log_requests: bool = bool(config.get("log_requests", True))
        self.providers: List[Provider] = []
        self.states: Dict[str, KeyState] = {}     # "provider|key_index" -> KeyState
        self.stats: Dict[str, Dict[str, Any]] = {}
        self.events: List[Dict[str, Any]] = []
        self._load_providers(config)
        self._load_state()

    # ---- конфигурация ------------------------------------------------------

    def _load_providers(self, config: Dict[str, Any]) -> None:
        for raw in config.get("providers", []):
            if not raw.get("enabled", True):
                continue
            p = Provider(
                name=raw["name"],
                base_url=raw.get("base_url", ""),
                models=list(raw.get("models", [])),
                keys=list(raw.get("keys", [])),
                key_env=raw.get("key_env"),
                priority=int(raw.get("priority", 100)),
                enabled=True,
                headers=dict(raw.get("headers", {})),
                limits=dict(raw.get("limits", {})),
                cost_multiplier=float(raw.get("cost_multiplier", 1.0)),
                model_multipliers={str(k): float(v)
                                   for k, v in (raw.get("model_multipliers") or {}).items()},
                cooldown_on_error=int(raw.get("cooldown_on_error", 60)),
                cooldown_on_429=int(raw.get("cooldown_on_429", 900)),
                timeout=int(raw.get("timeout", 180)),
                notes=raw.get("notes", ""),
                kind=raw.get("kind", "openai"),
            )
            if p.kind != "mock" and not p.all_keys():
                log(f"⚠  Провайдер '{p.name}' пропущен: нет ключей (поле keys или {p.key_env}).")
                continue
            self.providers.append(p)
            for i in range(len(p.all_keys())):
                self.states.setdefault(f"{p.name}|{i}", KeyState())
            self.stats.setdefault(
                p.name, {"ok": 0, "fail": 0, "tokens_in": 0, "tokens_out": 0, "requests": 0}
            )

        if self.mock:
            self.providers.insert(
                0,
                Provider(
                    name="mock",
                    base_url="mock://",
                    models=["mock-smart", "mock-fast"],
                    keys=["mock"],
                    priority=0,
                    limits={"rpm": 1000, "rpd": 100000},
                    kind="mock",
                    notes="Демо-провайдер: отвечает без внешней сети. Для проверки настройки.",
                ),
            )
            self.states["mock|0"] = KeyState()
            self.stats["mock"] = {"ok": 0, "fail": 0, "tokens_in": 0, "tokens_out": 0, "requests": 0}
            # в демо-режиме mock должен быть первым в маршрутах, иначе запрос уйдёт в сеть
            for alias in ("auto", "smart", "fast", "local"):
                self.aliases[alias] = ["mock/mock-smart"] + list(self.aliases.get(alias, []))
            log("ℹ  Демо-режим: запросы обслуживает mock-провайдер (без интернета).")

        self.providers.sort(key=lambda p: p.priority)
        if not self.providers:
            log("⚠  Ни одного активного провайдера. Запустите с --mock или добавьте ключи.")
        else:
            log(f"✓ Провайдеров активно: {len(self.providers)} — {', '.join(p.name for p in self.providers)}")

    def _load_state(self) -> None:
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in (data.get("states") or {}).items():
                if k in self.states:
                    st = KeyState(**{**asdict(self.states[k]), **v})
                    st.roll()
                    self.states[k] = st
        except FileNotFoundError:
            pass
        except Exception as e:
            log(f"⚠  Не удалось прочитать state.json: {e}")

    def save_state(self) -> None:
        try:
            with self.lock:
                payload = {
                    "version": VERSION,
                    "saved_at": now_ts(),
                    "states": {k: asdict(v) for k, v in self.states.items()},
                    "stats": self.stats,
                }
            tmp = self.state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.state_path)
        except Exception as e:
            log(f"⚠  state.json не сохранён: {e}")

    # ---- квоты -------------------------------------------------------------

    def _quota_left(self, p: Provider, key_idx: int) -> Dict[str, Any]:
        st = self.states.setdefault(f"{p.name}|{key_idx}", KeyState())
        st.roll()
        lim = p.limits or {}
        out: Dict[str, Any] = {"blocked": st.blocked_until > now_ts(),
                               "blocked_for": max(0, int(st.blocked_until - now_ts()))}
        if lim.get("rpm"):
            out["rpm_left"] = max(0, int(lim["rpm"] - len(st.requests_min)))
        if lim.get("rpd"):
            out["rpd_left"] = max(0, int(lim["rpd"] - st.requests_day))
        if lim.get("tpd"):
            out["tpd_left"] = max(0, int(lim["tpd"] - st.tokens_day))
        return out

    def _available(self, p: Provider, key_idx: int) -> bool:
        q = self._quota_left(p, key_idx)
        if q["blocked"]:
            return False
        for k in ("rpm_left", "rpd_left", "tpd_left"):
            if k in q and q[k] <= 0:
                return False
        return True

    # ---- выбор маршрута ----------------------------------------------------

    def resolve_models(self, requested: Optional[str]) -> List[Tuple[Provider, str]]:
        """
        Возвращает упорядоченный список (провайдер, модель) — в каком порядке пробовать.
        requested: "auto" | alias | "provider/model" | "model-id" | None
        """
        requested = (requested or self.default_alias or "auto").strip()
        candidates: List[Tuple[Provider, str]] = []

        def by_name(name: str) -> Tuple[Optional[Provider], Optional[str]]:
            if "/" in name:
                pname, _, model = name.partition("/")
                for p in self.providers:
                    if p.name == pname:
                        return p, (model or (p.models[0] if p.models else "default"))
            for p in self.providers:
                if name in p.models:
                    return p, name
            return None, None

        names: List[str] = []
        if requested in self.aliases:
            names = list(self.aliases[requested])
        elif requested in ("auto", "", None):
            names = [f"{p.name}/{p.models[0]}" if p.models else p.name for p in self.providers]
        else:
            names = [requested]

        for name in names:
            p, model = by_name(name)
            if p is not None and model:
                candidates.append((p, model))

        if not candidates and requested not in ("auto", ""):
            # запрошена неизвестная модель — не падаем, а отдаём auto
            log(f"↺ Неизвестная модель '{requested}', использую auto.")
            return self.resolve_models("auto")
        return candidates

    def pick_attempts(self, requested: Optional[str], max_attempts: int = 8) -> List[Tuple[Provider, int, str]]:
        """Плоский список попыток: провайдер, индекс ключа, модель."""
        attempts: List[Tuple[Provider, int, str]] = []
        for p, model in self.resolve_models(requested):
            keys = p.all_keys()
            idxs = list(range(len(keys)))
            # ключи с наибольшим остатком квоты — первыми
            idxs.sort(key=lambda i: -(self._quota_left(p, i).get("rpd_left", 10 ** 9)))
            for i in idxs:
                if self._available(p, i):
                    attempts.append((p, i, model))

        # Локальный резерв: если всё исчерпано, но есть Ollama — используем её
        if not attempts and self.prefer_local_when_quota_out:
            for p in self.providers:
                if p.kind == "ollama":
                    st = self.states.setdefault(f"{p.name}|0", KeyState())
                    st.blocked_until = 0
                    attempts.append((p, 0, p.models[0] if p.models else "qwen2.5-coder:7b"))
                    log("⚠  Дневной лимит расхода выбран — до конца суток платный канал не используется.")
                    break
        return attempts[:max_attempts]

    # ---- учёт --------------------------------------------------------------

    def account_request(self, p: Provider, key_idx: int, tokens_in: int = 0, tokens_out: int = 0,
                        ok: bool = True, error: str = "", model: str = "") -> None:
        key = f"{p.name}|{key_idx}"
        with self.lock:
            st = self.states.setdefault(key, KeyState())
            st.roll()
            st.requests_min.append(now_ts())
            st.requests_day += 1
            # у шлюзов с коэффициентами списывается не 1:1, а с множителем:
            # считаем расход в тех же единицах, что и баланс провайдера
            mult = p.multiplier(model)
            st.tokens_day += int((tokens_in + tokens_out) * mult)
            st.last_used = now_ts()
            st.last_error = error
            s = self.stats.setdefault(p.name, {"ok": 0, "fail": 0, "tokens_in": 0, "tokens_out": 0, "requests": 0})
            s["requests"] += 1
            s["ok" if ok else "fail"] += 1
            s["tokens_in"] += tokens_in
            s["tokens_out"] += tokens_out
            self.events.append(
                {"t": now_ts(), "provider": p.name, "ok": ok, "error": error[:160],
                 "tokens": tokens_in + tokens_out}
            )
            self.events = self.events[-200:]
        if self.log_requests:
            mark = "✓" if ok else "✗"
            extra = f" · {error[:70]}" if error else ""
            mult = p.multiplier(model)
            name = (model or "").split("/")[-1] or "?"
            spent_now = self._day_spend(p)
            limit = int((p.limits or {}).get("tpd") or 0)
            progress = ""
            if limit:
                progress = f" · за сегодня {spent_now:,} из {limit:,} ({round(spent_now * 100 / limit)}%)"
            else:
                progress = f" · за сегодня {spent_now:,}"
            log(f"{mark} {p.name} · {name} x{mult:g} · токенов {tokens_in + tokens_out}"
                f"{progress}{extra}".replace(",", " "))

    def _day_spend(self, p: Provider) -> int:
        """Сколько зачётных токенов уже израсходовано у провайдера за текущие сутки."""
        total = 0
        for i in range(len(p.all_keys()) or 1):
            st = self.states.get(f"{p.name}|{i}")
            if st:
                total += int(st.tokens_day or 0)
        return total

    def block_key(self, p: Provider, key_idx: int, seconds: int, reason: str) -> None:
        with self.lock:
            st = self.states.setdefault(f"{p.name}|{key_idx}", KeyState())
            st.blocked_until = now_ts() + seconds
            st.last_error = reason
            log(f"⏸  {p.name}[{key_idx}] остывает {seconds}s: {reason[:90]}")
        self.save_state()

    def block_provider(self, p: Provider, seconds: int, reason: str) -> None:
        for i in range(len(p.all_keys())):
            self.block_key(p, i, seconds, reason)

    # ---- вызовы провайдеров ------------------------------------------------

    def _headers_for(self, p: Provider, key: str) -> Dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "HTTP-Referer": "http://127.0.0.1:8788",
            "X-Title": "FreeCoder Router",
            "User-Agent": f"FreeCoderRouter/{VERSION}",
        }
        h.update(p.headers or {})
        return h

    def call_provider_once(
        self, p: Provider, key_idx: int, key: str, model: str,
        payload: Dict[str, Any], stream: bool,
    ):
        """Возвращает (response, response_headers) либо бросает urllib.error.HTTPError."""
        if p.kind == "mock":
            return MockResponse(payload), {}

        # Если каталог шлюза назвал модель иначе (sonnet-4.6 -> claude-sonnet-4-6),
        # подставляем найденное имя. Заполняется при старте в probe_model_catalog().
        model = p.model_map.get(model, model)

        if p.kind == "anthropic":
            body = oai_to_anthropic({**payload, "model": model})
            headers = {
                "Content-Type": "application/json",
                "x-api-key": key,
                "anthropic-version": os.environ.get("ANTHROPIC_VERSION", "2023-06-01"),
                "User-Agent": f"FreeCoderRouter/{VERSION}",
            }
            headers.update(p.headers or {})
            if p.base_url.rstrip("/").endswith("/v1"):
                url = p.base_url.rstrip("/") + "/messages"
            else:
                url = p.base_url.rstrip("/") + "/v1/messages"
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            ctx = None
            if url.startswith("https://") and os.environ.get("FREECODER_NO_VERIFY") == "1":
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            return urllib.request.urlopen(req, timeout=p.timeout, context=ctx), {}

        body = dict(payload)
        body["model"] = model
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            p.url("/chat/completions"), data=data, headers=self._headers_for(p, key), method="POST"
        )
        ctx = None
        if p.base_url.startswith("https://") and os.environ.get("FREECODER_NO_VERIFY") == "1":
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return urllib.request.urlopen(req, timeout=p.timeout, context=ctx), {}



# ----------------------------------------------------------------------------
# Сверка моделей с каталогом шлюза.
#
# Шлюзы называют модели по-своему: в конфиге "sonnet-4.6", а в каталоге
# "claude-sonnet-4-6". При старте роутер спрашивает /models и, если имя отличается
# только разделителями или приставкой вендора, подставляет настоящее — молча и точно.
# Если совпадения нет, печатает список доступных моделей: это самая частая причина
# ошибки 400 «model does not exist».
# ----------------------------------------------------------------------------


def _norm_model(name: str) -> str:
    """claude-sonnet-4.6 / sonnet-4-6 / Claude Sonnet 4.6 -> sonnet46"""
    n = re.sub(r"[^a-z0-9]+", "", (name or "").lower())
    for prefix in ("anthropic", "claude", "openai", "google", "gpt"):
        if n.startswith(prefix) and len(n) > len(prefix) + 2:
            n = n[len(prefix):]
    return n


def _fetch_catalog(p: Provider, key: str, timeout: int = 8) -> List[str]:
    """Список id моделей шлюза. Пустой список = шлюз каталог не отдаёт."""
    base = (p.base_url or "").rstrip("/")
    candidates = [base + "/models"]
    if base.endswith("/v1"):
        candidates.append(base[:-3].rstrip("/") + "/models")
    else:
        candidates.append(base + "/v1/models")
    for url in candidates:
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {key}",
                    "x-api-key": key,
                    "anthropic-version": os.environ.get("ANTHROPIC_VERSION", "2023-06-01"),
                    "User-Agent": f"FreeCoderRouter/{VERSION}",
                },
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            continue
        ids: List[str] = []
        for item in (data.get("data") or data.get("models") or []):
            if isinstance(item, dict):
                mid = item.get("id") or item.get("name")
                if mid:
                    ids.append(str(mid))
            elif isinstance(item, str):
                ids.append(item)
        if ids:
            return ids
    return []


def probe_model_catalog(providers: List[Provider]) -> None:
    """Сверяет модели из конфига с каталогом шлюза. Никогда не мешает запуску."""
    if os.environ.get("FREECODER_PROBE", "1") == "0":
        return
    for p in providers:
        keys = p.all_keys()
        if not keys or p.kind in ("mock", "ollama"):
            continue
        is_local = re.search(r"(127\.0\.0\.1|localhost|0\.0\.0\.0)", p.base_url or "")
        if is_local and os.environ.get("FREECODER_PROBE_LOCAL") != "1":
            continue   # локальные адреса (Ollama, тестовые шлюзы) не опрашиваем
        log(f"↻  {p.name}: сверяю модели с каталогом шлюза…")
        ids = _fetch_catalog(p, keys[0])
        if not ids:
            log(f"   {p.name}: каталог моделей шлюз не отдаёт (это нормально) — "
                f"имена моделей берутся из конфига как есть.")
            continue
        by_norm: Dict[str, str] = {}
        for mid in ids:
            by_norm.setdefault(_norm_model(mid), mid)

        substituted: List[str] = []
        missing: List[str] = []
        for m in (p.models or []):
            if m in ids:
                continue
            twin = by_norm.get(_norm_model(m))
            if twin and twin != m:
                p.model_map[m] = twin
                substituted.append(f"{m} → {twin}")
            elif not twin:
                missing.append(m)

        if substituted:
            log(f"   {p.name}: шлюз называет иначе, подставил: " + "; ".join(substituted))
        if missing:
            log(f"   ⚠ {p.name}: в каталоге шлюза нет " + ", ".join(repr(x) for x in missing))
            keywords = {_norm_model(m)[:6] for m in missing}
            similar = [i for i in ids if any(k and k in _norm_model(i) for k in keywords)]
            shown = (similar or ids)[:25]
            log(f"     доступные модели ({len(ids)}): " + ", ".join(shown))
            if len(ids) > len(shown):
                log("     … полный список: python tools/check_api_key.py --list-models "
                    "--base-url <адрес шлюза> --key <ключ>")
        if not substituted and not missing:
            log(f"   {p.name}: все модели из конфига есть в каталоге шлюза ✓")

# ----------------------------------------------------------------------------
# Слой совместимости: клиенты говорят на языке OpenAI, а шлюз может требовать
# формат Anthropic (/v1/messages). Здесь мы переводим запросы и ответы.
# ----------------------------------------------------------------------------


def oai_to_anthropic(payload: Dict[str, Any]) -> Dict[str, Any]:
    """OpenAI chat/completions -> Anthropic messages."""
    messages = payload.get("messages") or []
    system_parts: List[str] = []
    out_messages: List[Dict[str, Any]] = []

    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if role == "system":
            if isinstance(content, str) and content.strip():
                system_parts.append(content)
            continue
        if role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": m.get("tool_call_id") or "call_0",
                "content": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
            }
            if out_messages and out_messages[-1]["role"] == "user" and isinstance(out_messages[-1]["content"], list):
                out_messages[-1]["content"].append(block)
            else:
                out_messages.append({"role": "user", "content": [block]})
            continue

        blocks: List[Dict[str, Any]] = []
        if isinstance(content, str) and content:
            blocks.append({"type": "text", "text": content})
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    blocks.append({"type": "text", "text": part.get("text", "")})
        for call in (m.get("tool_calls") or []):
            fn = call.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}
            blocks.append({"type": "tool_use", "id": call.get("id") or "call_0",
                           "name": fn.get("name") or "tool", "input": args})
        if not blocks:
            blocks = [{"type": "text", "text": ""}]
        out_messages.append({"role": "assistant" if role == "assistant" else "user",
                             "content": blocks})

    body: Dict[str, Any] = {
        "model": payload.get("model"),
        "messages": out_messages,
        "max_tokens": int(payload.get("max_tokens") or payload.get("max_completion_tokens") or 8192),
    }
    if system_parts:
        body["system"] = "\n\n".join(system_parts)
    if payload.get("temperature") is not None:
        body["temperature"] = payload["temperature"]
    if payload.get("stop") is not None:
        stop = payload["stop"]
        body["stop_sequences"] = [stop] if isinstance(stop, str) else list(stop)

    tools = payload.get("tools")
    if tools:
        converted = []
        for t in tools:
            fn = t.get("function") or t
            params = fn.get("parameters") or {"type": "object", "properties": {}}
            converted.append({"name": fn.get("name"), "description": fn.get("description", ""),
                              "input_schema": params})
        body["tools"] = converted
        choice = payload.get("tool_choice")
        if choice in (None, "auto"):
            body["tool_choice"] = {"type": "auto"}
        elif choice == "required":
            body["tool_choice"] = {"type": "any"}
        elif isinstance(choice, dict) and choice.get("function", {}).get("name"):
            body["tool_choice"] = {"type": "tool", "name": choice["function"]["name"]}
    return body


def anthropic_to_oai(data: Dict[str, Any], model: Optional[str]) -> Dict[str, Any]:
    """Anthropic messages -> OpenAI chat/completions."""
    text_parts: List[str] = []
    tool_calls: List[Dict[str, Any]] = []
    for block in (data.get("content") or []):
        btype = block.get("type")
        if btype == "text":
            text_parts.append(block.get("text") or "")
        elif btype == "tool_use":
            tool_calls.append({
                "id": block.get("id") or "call_0",
                "type": "function",
                "function": {"name": block.get("name") or "tool",
                             "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False)},
            })
    stop = data.get("stop_reason")
    finish = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length",
              "tool_use": "tool_calls"}.get(stop, "stop")
    message: Dict[str, Any] = {"role": "assistant", "content": "".join(text_parts) or None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    usage = data.get("usage") or {}
    return {
        "id": data.get("id") or "chatcmpl-anthropic",
        "object": "chat.completion",
        "created": int(now_ts()),
        "model": model or data.get("model") or "unknown",
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {
            "prompt_tokens": int(usage.get("input_tokens") or 0),
            "completion_tokens": int(usage.get("output_tokens") or 0),
            "total_tokens": int((usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)),
        },
    }


def oai_sse_from_message(obj: Dict[str, Any]) -> bytes:
    """Собирает корректный SSE-поток из готового ответа (для клиентов, ждущих stream)."""
    choice = (obj.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    chunks = []
    if msg.get("content"):
        chunks.append({"choices": [{"index": 0, "delta": {"role": "assistant",
                                                          "content": msg["content"]}}]})
    for call in (msg.get("tool_calls") or []):
        chunks.append({"choices": [{"index": 0, "delta": {"tool_calls": [call]}}]})
    chunks.append({"choices": [{"index": 0, "delta": {}, "finish_reason": choice.get("finish_reason", "stop")}],
                   "usage": obj.get("usage")})
    out = b""
    for c in chunks:
        c["model"] = obj.get("model")
        data = json.dumps(c, ensure_ascii=False)
        out += ("data: " + data + "\n\n").encode("utf-8")
    out += b"data: [DONE]\n\n"
    return out


class MockResponse:
    """Демо-провайдер: отвечает без сети, чтобы проверить всю обвязку."""

    def __init__(self, payload: Dict[str, Any]):
        self.payload = payload

    def read(self) -> bytes:
        msgs = self.payload.get("messages") or []
        last = ""
        for m in reversed(msgs):
            if m.get("role") == "user":
                last = m.get("content") if isinstance(m.get("content"), str) else json.dumps(m.get("content"))
                break
        tools = self.payload.get("tools")
        saw_tool_result = any(
            m.get("role") == "tool" or "РЕЗУЛЬТАТ" in str(m.get("content") or "")
            for m in msgs
        )
        if tools and not saw_tool_result:
            content = None
            tool_calls = [{
                "id": "call_" + uuid.uuid4().hex[:8],
                "type": "function",
                "function": {"name": "list_files", "arguments": json.dumps({"pattern": "*"})},
            }]
        elif tools and saw_tool_result:
            content = None
            tool_calls = [{
                "id": "call_" + uuid.uuid4().hex[:8],
                "type": "function",
                "function": {"name": "final",
                             "arguments": json.dumps({"summary": "демо-прогон выполнен (mock)"})},
            }]
        else:
            content = f"[mock] Получил: {str(last)[:200]}"
            tool_calls = None
        msg: Dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        out = {
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "created": int(now_ts()),
            "model": self.payload.get("model", "mock"),
            "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        }
        return json.dumps(out, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# ----------------------------------------------------------------------------
# HTTP-сервер
# ----------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"FreeCoderRouter/{VERSION}"

    router: Router  # заполняется при создании сервера

    # ---------- утилиты ответа ----------

    def _send_json(self, obj: Any, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, code: int = 200, ctype: str = "text/html; charset=utf-8") -> None:
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:  # тише в консоли
        if os.environ.get("FREECODER_VERBOSE") == "1":
            super().log_message(fmt, *args)

    # ---------- HTTP ----------

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/status", "/dashboard"):
            summary = status_payload(self.router)
            port = self.server.server_address[1]
            lines = ["FreeCoder Router работает. Расход печатается в окне роутера после каждого запроса.",
                     f"Порт: {port}", ""]
            for p in summary.get("providers", []):
                spent = sum(int(k.get("tokens_day") or 0) for k in p.get("keys", []))
                limit = int((p.get("limits") or {}).get("tpd") or 0)
                reqs = int((p.get("stats") or {}).get("requests") or 0)
                line = f"{p['name']}: {spent} зачётных токенов"
                if limit:
                    line += f" из {limit} ({round(spent * 100 / limit)}%)"
                lines.append(line + f", запросов: {reqs}")
            lines += ["", "Программный доступ: /status.json", "Список моделей: /v1/models"]
            return self._send_text("\n".join(lines))
        if path == "/status.json":
            return self._send_json(status_payload(self.router))
        if path == "/v1/models":
            return self._send_json(models_payload(self.router))
        if path in ("/health", "/healthz"):
            return self._send_json({"status": "ok", "version": VERSION,
                                    "providers": len(self.router.providers)})
        return self._send_json({"error": {"message": "not found", "type": "invalid_request_error"}}, 404)

    def do_POST(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as e:
            return self._send_json({"error": {"message": f"bad json: {e}"}}, 400)

        if path.endswith("/chat/completions"):
            return self.handle_chat(payload)
        if path.endswith("/completions"):
            return self.handle_chat(payload, force_stream=False)
        return self._send_json({"error": {"message": f"unsupported path {path}"}}, 404)

    # ---------- основной обработчик ----------

    def handle_chat(self, payload: Dict[str, Any], force_stream: Optional[bool] = None) -> None:
        r = self.router
        requested_model = payload.get("model")
        stream = bool(payload.get("stream")) if force_stream is None else bool(force_stream)
        payload = dict(payload)
        if "max_tokens" not in payload and "max_completion_tokens" not in payload:
            payload["max_tokens"] = int(r.config.get("default_max_tokens", 8192))

        attempts = r.pick_attempts(requested_model)
        if not attempts:
            r.events.append({"t": now_ts(), "provider": "-", "ok": False,
                             "error": "нет доступных провайдеров", "tokens": 0})
            return self._send_json(
                {
                    "error": {
                        "message": (
                            "Запрос некуда отправить: ключ SMARTAPI_KEY не задан, либо выбран "
                            "дневной лимит расхода, либо шлюз на паузе после ошибок. "
                            "Проверьте http://127.0.0.1:8788/ — там видно, кто остывает и на сколько. "
                            "Варианты: дождаться сброса лимита (полночь по UTC) или поднять tpd "
                            "в router/providers.smartapi.json."
                        ),
                        "type": "insufficient_quota",
                    }
                },
                429,
            )

        prompt_tokens = est_tokens(json.dumps(payload.get("messages", []), ensure_ascii=False))
        last_err = "нет попыток"
        tried: List[str] = []
        saw_quota = False

        for p, key_idx, model in attempts:
            key = p.all_keys()[key_idx]
            tried.append(f"{p.name}/{model}")
            try:
                resp, _ = r.call_provider_once(p, key_idx, key, model, payload, stream)

                if p.kind == "anthropic":
                    raw = json.loads(resp.read().decode("utf-8", "replace"))
                    if raw.get("error"):
                        raise urllib.error.HTTPError(
                            p.url("/messages"), 400, "anthropic error", {}, None)
                    out = anthropic_to_oai(raw, requested_model)
                    usage = out.get("usage") or {}
                    r.account_request(p, key_idx,
                                      tokens_in=int(usage.get("prompt_tokens") or prompt_tokens),
                                      tokens_out=int(usage.get("completion_tokens") or 0),
                                      ok=True, model=model)
                    out["x_freecoder_provider"] = p.name
                    if stream:
                        body = oai_sse_from_message(out)
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                        return
                    return self._send_json(out)

                if p.kind == "mock" or not stream:
                    data = resp.read()
                    out = json.loads(data.decode("utf-8"))
                    usage = out.get("usage") or {}
                    r.account_request(
                        p, key_idx,
                        tokens_in=int(usage.get("prompt_tokens") or prompt_tokens),
                        tokens_out=int(usage.get("completion_tokens") or 0),
                        ok=True, model=model,
                    )
                    out["model"] = requested_model or out.get("model")
                    out.setdefault("x_freecoder_provider", p.name)
                    return self._send_json(out)
                else:
                    return self._stream_through(p, key_idx, resp, requested_model)
            except urllib.error.HTTPError as e:
                code = e.code
                try:
                    err_body = e.read().decode("utf-8", "replace")
                except Exception:
                    err_body = ""
                last_err = f"HTTP {code}: {err_body[:300]}"
                if code == 429:
                    saw_quota = True
                    retry_after = 0
                    try:
                        retry_after = int(e.headers.get("retry-after") or 0)
                    except Exception:
                        retry_after = 0
                    r.block_key(p, key_idx, retry_after or p.cooldown_on_429, "429 (квота/лимит)")
                elif code in (401, 403):
                    r.block_key(p, key_idx, 3600, f"{code} (плохой ключ?) {err_body[:120]}")
                elif code >= 500:
                    r.block_provider(p, p.cooldown_on_error, f"{code} у провайдера")
                elif code == 400:
                    # часто причина — неподдерживаемое поле (tools / response_format)
                    fixed = self._sanitize_payload(payload, err_body)
                    if fixed is not None:
                        try:
                            resp2, _ = r.call_provider_once(p, key_idx, key, model, fixed, stream)
                            data = resp2.read()
                            out = json.loads(data.decode("utf-8"))
                            r.account_request(p, key_idx, prompt_tokens, 0, ok=True, model=model)
                            out["model"] = requested_model or out.get("model")
                            out.setdefault("x_freecoder_provider", p.name)
                            return self._send_json(out)
                        except Exception as e2:  # noqa: BLE001
                            last_err = f"400 после очистки: {e2}"
                    r.account_request(p, key_idx, prompt_tokens, 0, ok=False, error=last_err,
                                      model=model)
                else:
                    r.account_request(p, key_idx, prompt_tokens, 0, ok=False, error=last_err,
                                      model=model)
            except Exception as e:  # сеть, таймаут, SSL
                last_err = f"{type(e).__name__}: {e}"
                r.account_request(p, key_idx, prompt_tokens, 0, ok=False, error=last_err,
                                  model=model)
                r.block_provider(p, p.cooldown_on_error, last_err)

        r.save_state()
        status = 429 if saw_quota else 502
        hint = ("Дневной лимит расхода на сегодня выбран (tpd в конфиге). "
                if saw_quota else "Ни один адрес шлюза не ответил. ")
        return self._send_json(
            {"error": {
                "message": (f"{hint}Пробовал: {tried}. Последняя ошибка: {last_err}. "
                            f"Статус: http://127.0.0.1:{self.server.server_address[1]}/ — "
                            f"там видно, кто остывает и сколько ждать. "
                            f"Дневной лимит сбрасывается в полночь по UTC, "
                            f"либо поднимите tpd в router/providers.smartapi.json."),
                "type": "daily_limit_reached" if saw_quota else "upstream_error"}},
            status,
        )

    def _sanitize_payload(self, payload: Dict[str, Any], err: str) -> Optional[Dict[str, Any]]:
        """Убирает поля, на которые провайдер ругается (бесплатные тарифы капризны)."""
        low = (err or "").lower()
        drop: List[str] = []
        for field_name in ("tools", "tool_choice", "response_format", "parallel_tool_calls",
                           "reasoning_effort", "temperature", "max_tokens", "top_p"):
            if field_name in payload and field_name.lower() in low:
                drop.append(field_name)
        if not drop:
            if "tools" in payload:
                drop = ["tools", "tool_choice"]
            elif "response_format" in payload:
                drop = ["response_format"]
            else:
                return None
        sanitized = {k: v for k, v in payload.items() if k not in drop}
        log(f"↺ Провайдер ругается на {drop} — повторяю без них.")
        return sanitized

    def _stream_through(self, p: Provider, key_idx: int, resp, requested_model: Optional[str]) -> None:
        """Прозрачно пробрасывает SSE-поток, считая токены по usage-чанкам."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        tokens_out = 0
        tokens_in = 0
        try:
            while True:
                line = resp.readline()
                if not line:
                    break
                text = line.decode("utf-8", "replace")
                if text.startswith("data:") and '"usage"' in text:
                    try:
                        obj = json.loads(text[5:].strip())
                        usage = obj.get("usage") or {}
                        tokens_in = int(usage.get("prompt_tokens") or tokens_in)
                        tokens_out = int(usage.get("completion_tokens") or tokens_out)
                    except Exception:
                        pass
                if requested_model and text.startswith("data:") and '"model"' in text:
                    try:
                        obj = json.loads(text[5:].strip())
                        obj["model"] = requested_model
                        text = "data: " + json.dumps(obj, ensure_ascii=False) + "\n"
                    except Exception:
                        pass
                chunk = text.encode("utf-8")
                self.wfile.write(b"%x\r\n" % len(chunk) + chunk + b"\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            self.router.account_request(p, key_idx, tokens_in, tokens_out, ok=True,
                                        model=requested_model or "")


# ----------------------------------------------------------------------------
# Страницы статуса
# ----------------------------------------------------------------------------


SERVER_START = now_ts()


def status_payload(r: Router) -> Dict[str, Any]:
    providers = []
    for p in r.providers:
        keys = []
        for i in range(len(p.all_keys())):
            st = r.states.setdefault(f"{p.name}|{i}", KeyState())
            st.roll()
            keys.append({
                "index": i,
                "requests_day": st.requests_day,
                "tokens_day": st.tokens_day,
                "blocked_for": max(0, int(st.blocked_until - now_ts())),
                "last_error": st.last_error,
                **(r._quota_left(p, i)),
            })
        providers.append({
            "name": p.name,
            "kind": p.kind,
            "priority": p.priority,
            "models": p.models,
            "limits": p.limits,
            "cost_multiplier": p.cost_multiplier,
            "notes": p.notes,
            "keys": keys,
            "stats": r.stats.get(p.name, {}),
        })
    return {
        "version": VERSION,
        "uptime_s": int(now_ts() - SERVER_START),
        "aliases": r.aliases,
        "default_alias": r.default_alias,
        "providers": providers,
        "recent_events": list(reversed(r.events[-25:])),
    }


def models_payload(r: Router) -> Dict[str, Any]:
    """Список моделей для клиентов и для выбора модели в агенте.

    Сначала алиасы (auto/smart/... — то, что видит пользователь), затем все модели
    шлюзов с коэффициентом расхода: по нему агент показывает цену выбора.
    """
    data = []
    seen_aliases: List[str] = []
    for alias in list(r.aliases.keys()) + [r.default_alias]:
        if alias in seen_aliases:
            continue
        seen_aliases.append(alias)
        chain = r.aliases.get(alias, [])
        first = chain[0] if chain else ""
        mult = 1.0
        if first and "/" in first:
            pname, mname = first.split("/", 1)
            for p in r.providers:
                if p.name == pname:
                    mult = p.multiplier(mname)
        data.append({
            "id": alias,
            "object": "model",
            "owned_by": "freecoder-router",
            "description": " -> ".join(chain),
            "multiplier": mult,
            "alias": True,
        })
    seen_models: set = set()
    for p in r.providers:
        for m in p.models:
            if m in seen_models:
                continue   # та же модель через второй адрес шлюза — не дублируем в списке
            seen_models.add(m)
            data.append({
                "id": f"{p.name}/{m}",
                "object": "model",
                "owned_by": p.name,
                "multiplier": p.multiplier(m),
                "alias": False,
            })
    return {"object": "list", "data": data}


# ----------------------------------------------------------------------------
# Точка входа
# ----------------------------------------------------------------------------


def load_config(path: str, mock: bool) -> Dict[str, Any]:
    if not os.path.exists(path):
        fallback = SMARTAPI_CONFIG if os.path.exists(SMARTAPI_CONFIG) else SMARTAPI_CONFIG
        if os.path.exists(fallback) and os.path.abspath(path) == os.path.abspath(DEFAULT_CONFIG):
            log(f"ℹ  {os.path.basename(path)} не найден — беру {os.path.basename(fallback)}.")
            path = fallback
        else:
            log(f"⚠  Конфиг {path} не найден — работаю с пустым списком провайдеров.")
            log("   Рабочий конфиг: router/providers.smartapi.json")
            return {"providers": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="FreeCoder Router — шлюз к SmartAPI с дневным лимитом")
    ap.add_argument("--config", default=os.environ.get("FREECODER_CONFIG", DEFAULT_CONFIG))
    ap.add_argument("--state", default=os.environ.get("FREECODER_STATE", DEFAULT_STATE))
    ap.add_argument("--host", default=os.environ.get("FREECODER_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("FREECODER_PORT", "8788")))
    ap.add_argument("--mock", action="store_true", help="добавить демо-провайдера (проверка без ключей)")
    ap.add_argument("--log-file", default=os.environ.get("FREECODER_LOG", ""),
                    help="дублировать журнал в файл (для разбора сбоев)")
    ap.add_argument("--no-probe", action="store_true",
                    help="не сверять модели с каталогом шлюза при старте")
    args = ap.parse_args(argv)

    if args.log_file:
        LOG_FILE[0] = args.log_file
        try:
            os.makedirs(os.path.dirname(os.path.abspath(args.log_file)), exist_ok=True)
        except OSError:
            pass

    cfg = load_config(args.config, args.mock)
    router = Router(cfg, args.state, mock=args.mock)
    Handler.router = router

    if not args.mock and not args.no_probe:
        try:
            probe_model_catalog(router.providers)
        except Exception as e:  # noqa: BLE001
            log(f"⚠  Сверка моделей не удалась ({type(e).__name__}: {e}) — работаю как есть.")

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.daemon_threads = True

    print()
    log(f"FreeCoder Router v{VERSION} слушает http://{args.host}:{args.port}")
    log(f"  журнал:  расход по каждому запросу печатается здесь же")
    log(f"  API:     http://127.0.0.1:{args.port}/v1   (OpenAI-совместимо)")
    for p in router.providers:
        limit = int((p.limits or {}).get("tpd") or 0)
        if limit:
            log(f"  Лимит {p.name}: {limit:,} зачётных токенов в сутки — "
                f"расход виден здесь после каждого запроса".replace(",", " "))
    log("  Ctrl+C — остановить")
    print()

    def shutdown(*_: Any) -> None:
        log("Сохраняю состояние и выключаюсь…")
        router.save_state()
        os._exit(0)

    try:
        import signal

        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)
    except Exception:
        pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        shutdown()
    finally:
        router.save_state()
    return 0


if __name__ == "__main__":
    sys.exit(main())
