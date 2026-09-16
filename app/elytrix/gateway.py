# -*- coding: utf-8 -*-
"""Шлюз к SmartAPI: стриминг, prompt caching, failover, учёт расхода и дневной лимит.

Почему напрямую, а не через локальный роутер:
    · минус один сетевой переход на каждый шаг агента (быстрее старт и ответ);
    · один процесс — меньше окон, меньше мест, где что-то может не подняться;
    · Anthropic-формат шлюза (``/v1/messages``) даёт нативные инструменты, потоковый
      вывод и кэш промпта. Если он откажет — тот же запрос уходит в OpenAI-формат
      (``/v1/chat/completions``), перевод форматов живёт здесь же.

Экономия токенов (подробно — docs/02-ЭКОНОМИЯ.md):
    · prompt caching: system, инструменты и префикс диалога помечаются
      ``cache_control``, повторная часть контекста тарифицируется как кэш-чтение;
      если шлюз не поддерживает пометки — они отключаются автоматически;
    · расход считается в зачётных токенах (× коэффициент модели) и сверяется
      с дневным лимитом ДО отправки запроса;
    · один HTTP-keep-alive канал на хост: TLS-рукопожатие не повторяется на каждом шаге.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import ssl
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .config import Catalog, Config, State

VERSION = "3.0.0"

#: Внутреннее представление сообщения — формат Anthropic (он основной).
#: Блоки: {"type":"text","text":..} | {"type":"tool_use",..} | {"type":"tool_result",..}
Message = Dict[str, Any]
Block = Dict[str, Any]


class GatewayError(RuntimeError):
    """Базовая ошибка шлюза: текст уже человекочитаемый, его можно показать как есть."""

    def __init__(self, message: str, code: int = 0, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class AuthError(GatewayError):
    pass


class DailyLimitError(GatewayError):
    pass


class Cancelled(GatewayError):
    pass


@dataclass
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read: int = 0
    cache_write: int = 0
    charged: int = 0            # зачётные токены (×коэффициент модели)
    elapsed: float = 0.0
    ttfb: float = 0.0           # время до первого символа — то, что чувствует пользователь

    @property
    def total(self) -> int:
        return self.tokens_in + self.tokens_out


@dataclass
class ToolCall:
    id: str
    name: str
    args: Dict[str, Any] = field(default_factory=dict)
    raw: str = ""               # сырой JSON аргументов (для журнала)
    error: str = ""             # если аргументы не распознаны


@dataclass
class Turn:
    """Один ответ модели."""

    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    stop_reason: str = ""
    model: str = ""
    endpoint: str = ""          # anthropic | openai — по какому формату реально ушло
    usage: Usage = field(default_factory=Usage)
    cache_enabled: bool = False


def estimate_tokens(text: Any) -> int:
    """Оценка токенов без зависимостей: латиница ~4 символа/токен, кириллица ~2.5."""
    if text is None:
        return 0
    if not isinstance(text, str):
        try:
            text = json.dumps(text, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            text = str(text)
    latin = sum(1 for c in text if ord(c) < 128)
    return max(0, int(latin / 4 + (len(text) - latin) / 2.5))


def messages_tokens(messages: Sequence[Message], system: Any = None,
                    tools: Optional[Sequence[Dict[str, Any]]] = None) -> int:
    """Сколько токенов примерно уедет на входе в следующем запросе."""
    total = estimate_tokens(system)
    for msg in messages:
        total += estimate_tokens(msg.get("content"))
    if tools:
        total += estimate_tokens(tools) + 8 * len(tools)
    return total


# ---------------------------------------------------------------------------
# Перевод форматов
# ---------------------------------------------------------------------------


def to_openai(system: Any, messages: Sequence[Message], tools: Optional[Sequence[Dict[str, Any]]],
              max_tokens: int, temperature: Optional[float]) -> Dict[str, Any]:
    """Внутренний (Anthropic) формат -> OpenAI chat/completions."""
    out: List[Dict[str, Any]] = []
    system_text = system_to_text(system)
    if system_text:
        out.append({"role": "system", "content": system_text})

    for msg in messages:
        role = msg.get("role", "user")
        blocks = msg.get("content")
        if isinstance(blocks, str):
            out.append({"role": role, "content": blocks})
            continue
        text_parts: List[str] = []
        calls: List[Dict[str, Any]] = []
        results: List[Dict[str, Any]] = []
        for block in blocks or []:
            kind = block.get("type")
            if kind == "text":
                text_parts.append(block.get("text") or "")
            elif kind == "tool_use":
                calls.append({
                    "id": block.get("id") or f"call_{len(calls)}",
                    "type": "function",
                    "function": {"name": block.get("name") or "tool",
                                 "arguments": json.dumps(block.get("input") or {},
                                                         ensure_ascii=False)},
                })
            elif kind == "tool_result":
                content = block.get("content")
                if not isinstance(content, str):
                    content = json.dumps(content, ensure_ascii=False)
                results.append({"role": "tool", "tool_call_id": block.get("tool_use_id") or "call_0",
                                "content": content})
        if results:
            if text_parts:
                out.append({"role": role, "content": "\n".join(text_parts)})
            out.extend(results)
            continue
        entry: Dict[str, Any] = {"role": role, "content": "\n".join(text_parts) or None}
        if calls:
            entry["tool_calls"] = calls
            if not entry["content"]:
                entry["content"] = None
        out.append(entry)

    payload: Dict[str, Any] = {"messages": out, "max_tokens": max_tokens}
    if temperature is not None:
        payload["temperature"] = temperature
    if tools:
        payload["tools"] = [{"type": "function",
                             "function": {"name": t.get("name"),
                                          "description": t.get("description", ""),
                                          "parameters": t.get("input_schema")
                                          or {"type": "object", "properties": {}}}}
                            for t in tools]
        payload["tool_choice"] = "auto"
    return payload


def system_to_text(system: Any) -> str:
    """system может быть строкой или списком блоков (для cache_control)."""
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        return "\n\n".join(b.get("text", "") for b in system if isinstance(b, dict))
    return ""


def system_to_blocks(system: Any, cache: bool) -> Any:
    """Строка -> список блоков Anthropic с пометкой кэша на последнем."""
    text = system_to_text(system)
    if not cache:
        return text
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def from_openai_chunk(state: Dict[str, Any], obj: Dict[str, Any]) -> Tuple[str, str]:
    """Достаёт из SSE-чанка OpenAI (текст, имя/аргументы инструмента) — пишется в state."""
    delta_text = ""
    tool_json = ""
    for choice in obj.get("choices") or []:
        delta = choice.get("delta") or {}
        piece = delta.get("content")
        if isinstance(piece, str) and piece:
            delta_text += piece
        for call in delta.get("tool_calls") or []:
            idx = int(call.get("index") or 0)
            slot = state.setdefault("calls", {}).setdefault(idx, {"id": "", "name": "", "args": ""})
            if call.get("id"):
                slot["id"] = call["id"]
            fn = call.get("function") or {}
            if fn.get("name"):
                slot["name"] = fn["name"]
            if fn.get("arguments"):
                slot["args"] += fn["arguments"]
                tool_json += fn["arguments"]
        if choice.get("finish_reason"):
            state["stop_reason"] = choice["finish_reason"]
    usage = obj.get("usage")
    if usage:
        state["usage"] = usage
    return delta_text, tool_json


# ---------------------------------------------------------------------------
# Соединение
# ---------------------------------------------------------------------------


class Connection:
    """Один keep-alive канал до хоста шлюза.

    ``http.client`` вместо ``urllib.request``: соединение не пересоздаётся на каждый
    шаг агента, а значит не повторяется TLS-рукопожатие (−100…300 мс на запрос).
    """

    def __init__(self, url: str, timeout: int = 180):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.host = ""
        self._conn: Optional[http.client.HTTPConnection] = None
        self._lock = threading.Lock()

    def _connect(self) -> http.client.HTTPConnection:
        from urllib.parse import urlparse

        parts = urlparse(self.url)
        self.host = parts.netloc or parts.path
        secure = parts.scheme == "https"
        base = parts.netloc
        ctx = None
        if secure and os.environ.get("ELYTRIX_NO_VERIFY") == "1":
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        if secure:
            return http.client.HTTPSConnection(base, timeout=self.timeout, context=ctx)
        return http.client.HTTPConnection(base, timeout=self.timeout)

    def request(self, method: str, path: str, body: Optional[bytes] = None,
                headers: Optional[Dict[str, str]] = None) -> http.client.HTTPResponse:
        """Отправляет запрос, при обрыве соединения повторяет на новом канале."""
        headers = dict(headers or {})
        headers.setdefault("Connection", "keep-alive")
        if body is not None:
            headers.setdefault("Content-Length", str(len(body)))
        with self._lock:
            last_error: Optional[Exception] = None
            for attempt in range(2):
                try:
                    if self._conn is None:
                        self._conn = self._connect()
                    self._conn.request(method, path, body=body, headers=headers)
                    return self._conn.getresponse()
                except (http.client.BadStatusLine, http.client.CannotSendRequest,
                        http.client.RemoteDisconnected, ConnectionError, OSError) as e:
                    last_error = e
                    self.close()
                    if attempt:
                        break
            raise GatewayError(f"нет соединения с {self.url}: {last_error}", retryable=True)

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._conn = None


# ---------------------------------------------------------------------------
# Гейтвей
# ---------------------------------------------------------------------------


class SmartAPI:
    """Клиент SmartAPI: Anthropic-формат основной, OpenAI-формат запасной."""

    def __init__(self, cfg: Config, catalog: Catalog, state: State, key: str = "",
                 base_url: str = "", openai_base_url: str = ""):
        self.cfg = cfg
        self.catalog = catalog
        self.state = state
        self.key = key
        gw = cfg.get("gateway", {}) or {}
        self.base_url = (base_url or gw.get("base_url") or "https://api.smartapi.shop").rstrip("/")
        self.oai_url = (openai_base_url or gw.get("openai_base_url")
                        or (self.base_url + "/v1")).rstrip("/")
        self.anthropic_version = str(gw.get("anthropic_version") or "2023-06-01")
        self.timeout = int(gw.get("timeout") or 300)
        self.connect_timeout = int(gw.get("connect_timeout") or 15)
        self.daily_limit = int(cfg.get("limits.daily_tokens") or 0)
        self.cache_enabled = bool(cfg.get("economy.cache", True))
        self.cache_supported = True       # отключается, если шлюз отверг cache_control
        self.stream_default = bool(cfg.get("ui.stream", True))
        self._conns: Dict[str, Connection] = {}
        self.lock = threading.Lock()
        # статистика сессии
        self.session = Usage()
        self.session_cache_read = 0
        self.errors: List[str] = []
        self.last_model = ""
        self.last_endpoint = ""
        self.cooldown_until = 0.0
        self.cooldown_reason = ""

    # --- соединения ---

    def conn(self, url: str) -> Connection:
        with self.lock:
            hit = self._conns.get(url)
            if hit is None:
                hit = Connection(url, timeout=min(self.timeout, 240))
                self._conns[url] = hit
            return hit

    def close(self) -> None:
        with self.lock:
            for c in self._conns.values():
                c.close()
            self._conns.clear()

    def headers(self, kind: str) -> Dict[str, str]:
        base = {
            "Content-Type": "application/json",
            "User-Agent": f"ELYTRIX/{VERSION}",
            "X-Title": "ELYTRIX",
        }
        if kind == "anthropic":
            base.update({"x-api-key": self.key, "Authorization": f"Bearer {self.key}",
                         "anthropic-version": self.anthropic_version})
        else:
            base["Authorization"] = f"Bearer {self.key}"
        return base

    # --- лимиты ---

    def check_limit(self) -> None:
        """Проверяет дневной лимит ДО запроса: платить за отказ шлюза не нужно."""
        if self.daily_limit and self.state.tokens_day >= self.daily_limit:
            raise DailyLimitError(
                f"Дневной лимит расхода выбран: {self.state.tokens_day:,} из "
                f"{self.daily_limit:,} зачётных токенов. Лимит сбрасывается в полночь по UTC. "
                f"Поднять прямо сейчас: /limit 800000 (или /limit 0 — без лимита)."
                .replace(",", " ")
            )

    def spend_left(self) -> int:
        if not self.daily_limit:
            return 0
        return max(0, self.daily_limit - self.state.tokens_day)

    # --- кэш промпта ---

    def apply_cache(self, system: Any, tools: Optional[List[Dict[str, Any]]],
                    messages: List[Message]) -> Tuple[Any, Optional[List[Dict[str, Any]]],
                                                      List[Message]]:
        """Ставит пометки кэша: инструменты, system и префикс диалога.

        Кэш Anthropic работает по префиксу: всё, что до пометки, при повторе
        тарифицируется как чтение кэша (заметно дешевле и быстрее). Помечаем три
        точки — инструменты, system и последний блок предпоследнего сообщения,
        чтобы на следующем шаге переиспользовался уже весь диалог.
        """
        if not (self.cache_enabled and self.cache_supported):
            return system, tools, messages
        cached_system = system_to_blocks(system, True)
        cached_tools = None
        if tools:
            cached_tools = [dict(t) for t in tools]
            cached_tools[-1] = {**cached_tools[-1],
                                "cache_control": {"type": "ephemeral"}}
        # префикс диалога: помечаем последний блок сообщения перед свежими,
        # чтобы на следующем шаге переиспользовался уже весь диалог
        sent = list(messages)
        if len(sent) >= 3:
            target = sent[-3]
            blocks = target.get("content")
            if isinstance(blocks, list) and blocks:
                last = dict(blocks[-1])
                if last.get("type") in ("text", "tool_result", "tool_use"):
                    last.pop("cache_control", None)
                    last["cache_control"] = {"type": "ephemeral"}
                    sent[-3] = {**target, "content": list(blocks[:-1]) + [last]}
        return cached_system, cached_tools, sent

    # --- основной вызов ---

    def chat(self, model: str, system: Any, messages: List[Message],
             tools: Optional[List[Dict[str, Any]]] = None,
             max_tokens: Optional[int] = None, temperature: Optional[float] = 0.2,
             stream: Optional[bool] = None,
             on_text: Optional[Callable[[str], None]] = None,
             on_tool: Optional[Callable[[str, Dict[str, Any]], None]] = None,
             cancel: Optional[threading.Event] = None) -> Turn:
        """Отправляет запрос модели и собирает ответ (со стримингом, если включён).

        ``on_text`` вызывается на каждый пришедший кусок текста — так интерфейс
        печатает ответ по мере генерации. ``on_tool`` — когда модель начала вызывать
        инструмент (имя известно сразу, аргументы ещё дописываются).
        """
        self.check_limit()
        if time.time() < self.cooldown_until:
            wait = int(self.cooldown_until - time.time())
            raise GatewayError(f"Шлюз на паузе ещё {wait} с ({self.cooldown_reason}). "
                               f"Можно сменить модель: /model")

        want_stream = self.stream_default if stream is None else bool(stream)
        max_tokens = int(max_tokens or self.cfg.get("limits.max_output_tokens", 8192))
        resolved = self.catalog.resolve(model)
        mult = self.catalog.multiplier(resolved)
        endpoints = ["anthropic", "openai"]

        cached_system, cached_tools, sent_messages = self.apply_cache(system, tools, messages)
        last_error: Optional[GatewayError] = None
        for kind in endpoints:
            if cancel is not None and cancel.is_set():
                raise Cancelled("остановлено пользователем")
            try:
                turn = self._call(kind, resolved, cached_system if kind == "anthropic" else system,
                                  sent_messages, cached_tools if kind == "anthropic" else tools,
                                  max_tokens, temperature, want_stream, on_text, on_tool, cancel)
            except GatewayError as e:
                last_error = e
                self.errors.append(f"{kind}: {e}")
                if isinstance(e, (AuthError, DailyLimitError, Cancelled)):
                    raise
                if e.code == 400 and "cache_control" in str(e):
                    self.cache_supported = False
                    cached_system, cached_tools, sent_messages = system, tools, messages
                    continue                       # повторяем без пометок кэша
                if e.code in (401, 403):
                    raise AuthError(str(e), code=e.code) from e
                if not e.retryable and e.code and e.code < 500 and kind == "openai":
                    raise
                continue
            turn.usage.charged = self._account(resolved, mult, turn.usage)
            turn.cache_enabled = self.cache_enabled and self.cache_supported
            self.last_model = resolved
            self.last_endpoint = kind
            return turn

        raise last_error or GatewayError("шлюз не ответил", retryable=True)

    def _account(self, model: str, mult: float, usage: Usage) -> int:
        """Списывает расход в состояние и в счётчик сессии."""
        charged = self.state.record(model, usage.tokens_in, usage.tokens_out, mult,
                                    usage.cache_read, usage.cache_write)
        with self.lock:
            self.session.tokens_in += usage.tokens_in
            self.session.tokens_out += usage.tokens_out
            self.session.cache_read += usage.cache_read
            self.session.cache_write += usage.cache_write
            self.session.charged += charged
            self.session.elapsed += usage.elapsed
        usage.charged = charged
        self.session_cache_read += usage.cache_read
        return charged

    # --- один запрос к одному формату ---

    def _call(self, kind: str, model: str, system: Any, messages: List[Message],
              tools: Optional[List[Dict[str, Any]]], max_tokens: int,
              temperature: Optional[float], stream: bool,
              on_text: Optional[Callable[[str], None]],
              on_tool: Optional[Callable[[str, Dict[str, Any]], None]],
              cancel: Optional[threading.Event]) -> Turn:
        if kind == "anthropic":
            url = self.base_url + "/v1/messages"
            payload: Dict[str, Any] = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "stream": stream,
            }
            text = system_to_text(system)
            if text:
                payload["system"] = system
            if temperature is not None:
                payload["temperature"] = temperature
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = {"type": "auto"}
        else:
            url = self.oai_url + "/chat/completions"
            payload = to_openai(system, messages, tools, max_tokens, temperature)
            payload["model"] = model
            payload["stream"] = stream
            if stream:
                payload["stream_options"] = {"include_usage": True}

        conn = self.conn(self.base_url if kind == "anthropic" else self.oai_url)
        path = "/v1/messages" if kind == "anthropic" else "/chat/completions"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        t0 = time.time()
        try:
            resp = conn.request("POST", path, body=body, headers=self.headers(kind))
        except socket.timeout as e:
            conn.close()
            raise GatewayError(f"{kind}: таймаут соединения ({self.connect_timeout}с)",
                               code=0, retryable=True) from e

        status = getattr(resp, "status", 200)
        if status >= 400:
            detail = _safe_read(resp, 800)
            conn.close()
            raise self._http_error(kind, status, detail)

        if stream:
            turn = self._read_stream(kind, resp, model, on_text, on_tool, cancel, t0)
        else:
            raw = json.loads(_safe_read(resp, 4_000_000) or "{}")
            turn = self._parse_full(kind, raw, model)
        turn.usage.elapsed = time.time() - t0
        return turn

    def _http_error(self, kind: str, status: int, detail: str) -> GatewayError:
        low = detail.lower()
        hint = ""
        if status in (401, 403):
            hint = ("Ключ не принят. Проверьте SMARTAPI_KEY: кабинет "
                    "https://smartapi.shop/api-keys, затем /key внутри ELYTRIX.")
            return AuthError(hint + (" " + detail[:200] if detail else ""), code=status)
        if status == 404 or "does not exist" in low or "not available" in low or "model_not_found" in low:
            hint = (f"Модели нет в каталоге шлюза ({kind}). Список: /model, "
                    f"обновить каталог: /models reload.")
            return GatewayError(f"HTTP {status}: {hint} {detail[:200]}", code=status, retryable=True)
        if status == 429:
            self.cooldown_until = time.time() + int(self.cfg.get("gateway.cooldown_429", 60))
            self.cooldown_reason = "429 от шлюза"
            return GatewayError(f"HTTP 429: шлюз просит подождать. {detail[:200]}",
                                code=429, retryable=True)
        if "cache_control" in low or "prompt caching" in low or "ephemeral" in low:
            return GatewayError(f"HTTP {status}: шлюз не принял пометки кэша: {detail[:200]}",
                                code=400, retryable=True)
        if "tools" in low or "tool_choice" in low or "tool_use" in low:
            return GatewayError(f"HTTP {status}: шлюз не принял инструменты: {detail[:250]}",
                                code=status, retryable=True)
        if status >= 500:
            return GatewayError(f"HTTP {status} у шлюза ({kind}): {detail[:200]}",
                                code=status, retryable=True)
        return GatewayError(f"HTTP {status} ({kind}): {detail[:300]}", code=status,
                            retryable=status >= 500)

    # --- разбор ответов ---

    def _parse_full(self, kind: str, raw: Dict[str, Any], model: str) -> Turn:
        if kind == "anthropic":
            turn = Turn(model=model, endpoint="anthropic", stop_reason=str(raw.get("stop_reason") or ""))
            for block in raw.get("content") or []:
                btype = block.get("type")
                if btype == "text":
                    turn.text += block.get("text") or ""
                elif btype == "tool_use":
                    turn.tool_calls.append(ToolCall(id=str(block.get("id") or ""),
                                                    name=str(block.get("name") or ""),
                                                    args=block.get("input") or {},
                                                    raw=json.dumps(block.get("input") or {},
                                                                   ensure_ascii=False)))
            usage = raw.get("usage") or {}
            turn.usage = Usage(
                tokens_in=int(usage.get("input_tokens") or 0),
                tokens_out=int(usage.get("output_tokens") or 0),
                cache_read=int(usage.get("cache_read_input_tokens") or 0),
                cache_write=int(usage.get("cache_creation_input_tokens") or 0),
            )
            if turn.usage.cache_read or turn.usage.cache_write:
                turn.usage.tokens_in += turn.usage.cache_read + turn.usage.cache_write
            return turn

        choice = (raw.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        turn = Turn(model=model, endpoint="openai",
                    text=str(msg.get("content") or ""),
                    stop_reason=str(choice.get("finish_reason") or ""))
        for call in msg.get("tool_calls") or []:
            fn = call.get("function") or {}
            raw_args = str(fn.get("arguments") or "{}")
            try:
                args = json.loads(raw_args)
                if not isinstance(args, dict):
                    args = {"value": args}
            except ValueError:
                args, err = {}, "аргументы не JSON"
                turn.tool_calls.append(ToolCall(id=str(call.get("id") or ""),
                                                name=str(fn.get("name") or ""), args=args,
                                                raw=raw_args, error=err))
                continue
            turn.tool_calls.append(ToolCall(id=str(call.get("id") or ""),
                                            name=str(fn.get("name") or ""), args=args, raw=raw_args))
        usage = raw.get("usage") or {}
        turn.usage = Usage(tokens_in=int(usage.get("prompt_tokens") or 0),
                           tokens_out=int(usage.get("completion_tokens") or 0))
        return turn

    def _read_stream(self, kind: str, resp: Any, model: str,
                     on_text: Optional[Callable[[str], None]],
                     on_tool: Optional[Callable[[str, Dict[str, Any]], None]],
                     cancel: Optional[threading.Event], t0: float) -> Turn:
        """Читает SSE-поток построчно и сразу отдаёт куски в интерфейс."""
        state: Dict[str, Any] = {"calls": {}, "blocks": {}, "usage": {}, "stop_reason": "",
                                 "json": {}, "announced": set(), "complete": False}
        turn = Turn(model=model, endpoint=kind)
        first = True
        buffer = b""
        try:
            while True:
                if cancel is not None and cancel.is_set():
                    raise Cancelled("остановлено пользователем")
                chunk = _read1(resp)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    raw_line, buffer = buffer.split(b"\n", 1)
                    line = raw_line.decode("utf-8", "replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        state["complete"] = True
                        break
                    try:
                        obj = json.loads(data)
                    except ValueError:
                        continue
                    if first:
                        turn.usage.ttfb = time.time() - t0
                        first = False
                    if kind == "anthropic":
                        self._anthropic_event(obj, state, turn, on_text, on_tool)
                    else:
                        text_piece, _ = from_openai_chunk(state, obj)
                        if text_piece:
                            turn.text += text_piece
                            if on_text:
                                on_text(text_piece)
            if kind == "openai":
                self._finish_openai_stream(state, turn)
        except (Cancelled, GatewayError):
            _close_quiet(resp)
            raise
        except (http.client.HTTPException, ConnectionError, OSError) as e:
            _close_quiet(resp)
            if not turn.text and not turn.tool_calls:
                raise GatewayError(f"обрыв потока ({kind}): {e}", retryable=True) from e
        else:
            _close_quiet(resp)
        usage = state.get("usage") or {}
        if kind == "anthropic":
            turn.usage.tokens_in = int(usage.get("input_tokens") or turn.usage.tokens_in)
            turn.usage.tokens_out = int(usage.get("output_tokens") or 0)
            turn.usage.cache_read = int(usage.get("cache_read_input_tokens") or 0)
            turn.usage.cache_write = int(usage.get("cache_creation_input_tokens") or 0)
            if turn.usage.cache_read or turn.usage.cache_write:
                turn.usage.tokens_in += turn.usage.cache_read + turn.usage.cache_write
        else:
            turn.usage.tokens_in = int(usage.get("prompt_tokens") or 0)
            turn.usage.tokens_out = int(usage.get("completion_tokens") or 0)
        turn.stop_reason = str(state.get("stop_reason") or turn.stop_reason)
        if not state.get("complete"):
            # поток оборвался: пустой ответ считать успехом нельзя, иначе задача
            # «выполнится» молча, а повторный запрос стоит токенов
            if not turn.text and not turn.tool_calls:
                raise GatewayError(f"поток оборвался до конца ответа ({kind})", retryable=True)
            turn.stop_reason = turn.stop_reason or "incomplete"
        if turn.usage.ttfb == 0.0:
            turn.usage.ttfb = time.time() - t0
        return turn

    def _anthropic_event(self, obj: Dict[str, Any], state: Dict[str, Any], turn: Turn,
                         on_text: Optional[Callable[[str], None]],
                         on_tool: Optional[Callable[[str, Dict[str, Any]], None]]) -> None:
        etype = obj.get("type")
        if etype == "message_start":
            msg = obj.get("message") or {}
            state["usage"] = dict(msg.get("usage") or {})
            turn.stop_reason = str(msg.get("stop_reason") or "")
            return
        if etype == "content_block_start":
            index = obj.get("index", 0)
            block = obj.get("content_block") or {}
            if block.get("type") == "tool_use":
                state["blocks"][index] = {"id": block.get("id") or "", "name": block.get("name") or "",
                                          "json": ""}
                if on_tool:
                    on_tool(block.get("name") or "", {"id": block.get("id") or "", "start": True})
            else:
                state["blocks"][index] = {"type": "text"}
            return
        if etype == "content_block_delta":
            index = obj.get("index", 0)
            delta = obj.get("delta") or {}
            dtype = delta.get("type")
            if dtype == "text_delta":
                piece = delta.get("text") or ""
                if piece:
                    turn.text += piece
                    if on_text:
                        on_text(piece)
            elif dtype == "input_json_delta":
                slot = state["blocks"].setdefault(index, {"id": "", "name": "", "json": ""})
                slot["json"] = slot.get("json", "") + (delta.get("partial_json") or "")
            elif dtype == "thinking_delta":
                pass                       # рассуждения модели не печатаем — экономим экран
            return
        if etype == "content_block_stop":
            index = obj.get("index", 0)
            block = state["blocks"].get(index)
            if isinstance(block, dict) and "name" in block:
                raw_args = block.get("json") or "{}"
                try:
                    args = json.loads(raw_args)
                    if not isinstance(args, dict):
                        args = {"value": args}
                    err = ""
                except ValueError:
                    args, err = {}, "аргументы не JSON"
                call = ToolCall(id=str(block.get("id") or ""), name=str(block.get("name") or ""),
                                args=args, raw=raw_args, error=err)
                turn.tool_calls.append(call)
                if on_tool:
                    on_tool(call.name, {"id": call.id, "args": args, "done": True})
            return
        if etype == "message_stop":
            state["complete"] = True
            return
        if etype == "message_delta":
            delta = obj.get("delta") or {}
            if delta.get("stop_reason"):
                state["stop_reason"] = delta["stop_reason"]
                turn.stop_reason = str(delta["stop_reason"])
            if obj.get("usage"):
                state["usage"].update(obj["usage"])
            return

    def _finish_openai_stream(self, state: Dict[str, Any], turn: Turn) -> None:
        if state.get("stop_reason"):
            state["complete"] = True
        for _, slot in sorted((state.get("calls") or {}).items()):
            raw_args = slot.get("args") or "{}"
            try:
                args = json.loads(raw_args or "{}")
                if not isinstance(args, dict):
                    args = {"value": args}
                err = ""
            except ValueError:
                args, err = {}, "аргументы не JSON"
            turn.tool_calls.append(ToolCall(id=str(slot.get("id") or ""),
                                            name=str(slot.get("name") or ""),
                                            args=args, raw=raw_args, error=err))
        turn.stop_reason = str(state.get("stop_reason") or "")

    # --- каталог моделей и диагностика ---

    def fetch_models(self, timeout: int = 12) -> List[str]:
        """Список моделей шлюза (GET /v1/models). Пустой список — шлюз каталог не отдаёт."""
        for url, kind in ((self.base_url, "anthropic"), (self.oai_url, "openai")):
            for path in ("/v1/models", "/models"):
                try:
                    conn = self.conn(url)
                    resp = conn.request("GET", path, headers=self.headers(kind))
                except GatewayError:
                    continue
                status = getattr(resp, "status", 0)
                body = _safe_read(resp, 400_000)
                if status != 200 or not body:
                    continue
                try:
                    data = json.loads(body)
                except ValueError:
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

    def probe(self, model: str = "", max_tokens: int = 16) -> Tuple[bool, str]:
        """Быстрая проверка ключа и связи: один короткий запрос. Для /doctor."""
        target = self.catalog.resolve(model or self.catalog.default)
        try:
            turn = self.chat(target, "Ты тестовый ассистент. Ответь одним словом: OK",
                             [{"role": "user", "content": [{"type": "text", "text": "ping"}]}],
                             tools=None, max_tokens=max_tokens, stream=False)
            return True, (turn.text or "").strip()[:80] or "ответ получен"
        except GatewayError as e:
            return False, str(e)


def _read1(resp: Any) -> bytes:
    """Читает доступные байты потока, не дожидаясь конца ответа."""
    try:
        if hasattr(resp, "read1"):
            return resp.read1(65536)
    except Exception:  # noqa: BLE001
        pass
    try:
        line = resp.readline()
        return line or b""
    except Exception:  # noqa: BLE001
        return b""


def _safe_read(resp: Any, limit: int) -> str:
    try:
        data = resp.read(limit) if hasattr(resp, "read") else b""
        return (data or b"").decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


def _close_quiet(resp: Any) -> None:
    try:
        resp.close()
    except Exception:  # noqa: BLE001
        pass
