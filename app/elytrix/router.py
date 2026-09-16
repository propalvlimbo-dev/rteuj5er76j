# -*- coding: utf-8 -*-
"""Локальный шлюз для редакторов — запускается только если он вам нужен.

Сам агент работает без роутера (напрямую в SmartAPI). Но Cline, Continue, Kilo Code,
opencode и Cursor умеют говорить только с HTTP-адресом, поэтому ELYTRIX может поднять
совместимый сервер на 127.0.0.1:

    POST /v1/chat/completions   формат OpenAI (стриминг поддержан)
    POST /v1/messages           формат Anthropic (стриминг поддержан)
    GET  /v1/models             список моделей и алиасов с коэффициентами расхода
    GET  /status.json           расход за сутки, лимит, последние запросы
    GET  /health                жив ли сервер

Через него проходит тот же учёт: коэффициенты моделей, дневной лимит, failover между
форматами шлюза. Ключ редактору можно передать любой — настоящий ключ ELYTRIX держит у себя.

Запуск:  /router внутри агента  ·  python -m elytrix --router  ·  ELYTRIX-ROUTER.bat
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import uuid
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlparse

from . import __version__
from .config import Catalog, Config, State
from .gateway import GatewayError, SmartAPI, Turn
from .tools import TOOL_SCHEMAS

DEFAULT_PORT = 8789
STARTED_AT = time.time()


class GatewayPool:
    """Несколько клиентов SmartAPI на один роутер.

    У клиента одно keep-alive соединение, а редакторы (Cline, Continue) умеют слать
    запросы параллельно: без пула они ломали бы друг другу ответы. Пул создаёт clients
    по мере надобности и переиспользует их — соединения остаются тёплыми.
    """

    def __init__(self, factory: Callable[[], SmartAPI], size: int = 4,
                 first: Optional[SmartAPI] = None):
        self.factory = factory
        self.size = max(1, size)
        self.free: "queue.Queue[SmartAPI]" = queue.Queue()
        self.all: List[SmartAPI] = []
        self.lock = threading.Lock()
        if first is not None:
            self.all.append(first)
            self.free.put(first)

    @contextmanager
    def client(self, daily_limit: int = 0) -> Iterator[SmartAPI]:
        gw = self._take()
        if daily_limit is not None:
            gw.daily_limit = daily_limit        # /limit в консоли действует и на роутер
        broken = False
        try:
            yield gw
        except Exception:
            broken = True
            raise
        finally:
            if broken:
                self._discard(gw)
            else:
                self.free.put(gw)

    def _take(self) -> SmartAPI:
        try:
            return self.free.get_nowait()
        except queue.Empty:
            pass
        with self.lock:
            if len(self.all) < self.size:
                gw = self.factory()
                self.all.append(gw)
                return gw
        return self.free.get()                  # все заняты — подождём освободившийся

    def _discard(self, gw: SmartAPI) -> None:
        with self.lock:
            if gw in self.all:
                self.all.remove(gw)
        try:
            gw.close()
        except Exception:  # noqa: BLE001
            pass

    def stats(self) -> Dict[str, Any]:
        """Сводка по всем клиентам: сессия и состояние кэша — общие для /status.json."""
        out = {"tokens_in": 0, "tokens_out": 0, "charged": 0, "cache_read": 0,
               "cache_enabled": True, "cache_supported": True}
        with self.lock:
            clients = list(self.all)
        for gw in clients:
            out["tokens_in"] += gw.session.tokens_in
            out["tokens_out"] += gw.session.tokens_out
            out["charged"] += gw.session.charged
            out["cache_read"] += gw.session_cache_read
            out["cache_enabled"] = out["cache_enabled"] and gw.cache_enabled
            out["cache_supported"] = out["cache_supported"] and gw.cache_supported
        return out

    def close(self) -> None:
        with self.lock:
            clients = list(self.all)
            self.all.clear()
        while True:
            try:
                self.free.get_nowait()
            except queue.Empty:
                break
        for gw in clients:
            try:
                gw.close()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Перевод входящих запросов во внутренний (Anthropic) формат
# ---------------------------------------------------------------------------


def openai_to_internal(messages: List[Dict[str, Any]],
                       tools: Optional[List[Dict[str, Any]]]) -> Tuple[Any, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """OpenAI chat/completions -> (system, messages, tools)."""
    system_parts: List[str] = []
    out: List[Dict[str, Any]] = []
    pending_results: List[Dict[str, Any]] = []

    def flush() -> None:
        if pending_results:
            out.append({"role": "user", "content": list(pending_results)})
            pending_results.clear()

    for msg in messages or []:
        role = msg.get("role")
        content = msg.get("content")
        if role == "system" or role == "developer":
            if isinstance(content, str):
                system_parts.append(content)
            elif isinstance(content, list):
                system_parts.extend(str(p.get("text", "")) for p in content if isinstance(p, dict))
            continue
        if role == "tool":
            text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            pending_results.append({"type": "tool_result",
                                    "tool_use_id": msg.get("tool_call_id") or "call_0",
                                    "content": text})
            continue
        flush()
        blocks: List[Dict[str, Any]] = []
        if isinstance(content, str) and content:
            blocks.append({"type": "text", "text": content})
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    blocks.append({"type": "text", "text": part.get("text", "")})
        for call in msg.get("tool_calls") or []:
            fn = call.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
                if not isinstance(args, dict):
                    args = {"value": args}
            except ValueError:
                args = {}
            blocks.append({"type": "tool_use", "id": call.get("id") or f"call_{len(blocks)}",
                           "name": fn.get("name") or "tool", "input": args})
        if not blocks:
            blocks = [{"type": "text", "text": ""}]
        out.append({"role": "assistant" if role == "assistant" else "user", "content": blocks})
    flush()

    converted_tools: List[Dict[str, Any]] = []
    for tool in tools or []:
        fn = tool.get("function") or tool
        if not fn.get("name"):
            continue
        converted_tools.append({"name": fn["name"], "description": fn.get("description", ""),
                                "input_schema": fn.get("parameters")
                                or {"type": "object", "properties": {}}})
    return ("\n\n".join(system_parts) or None), out, converted_tools


def turn_to_openai(turn: Turn, requested_model: str) -> Dict[str, Any]:
    message: Dict[str, Any] = {"role": "assistant", "content": turn.text or None}
    if turn.tool_calls:
        message["tool_calls"] = [
            {"id": c.id or f"call_{i}", "type": "function",
             "function": {"name": c.name, "arguments": json.dumps(c.args, ensure_ascii=False)}}
            for i, c in enumerate(turn.tool_calls)]
        message["content"] = turn.text or None
    finish = "tool_calls" if turn.tool_calls else "stop"
    if turn.stop_reason == "max_tokens":
        finish = "length"
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": requested_model or turn.model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": turn.usage.tokens_in,
                  "completion_tokens": turn.usage.tokens_out,
                  "total_tokens": turn.usage.total},
        "x_elytrix": {"endpoint": turn.endpoint, "charged": turn.usage.charged,
                      "cache_read": turn.usage.cache_read, "elapsed": round(turn.usage.elapsed, 2)},
    }


def turn_to_anthropic(turn: Turn, requested_model: str) -> Dict[str, Any]:
    content: List[Dict[str, Any]] = []
    if turn.text:
        content.append({"type": "text", "text": turn.text})
    for call in turn.tool_calls:
        content.append({"type": "tool_use", "id": call.id or f"toolu_{uuid.uuid4().hex[:10]}",
                        "name": call.name, "input": call.args})
    if not content:
        content = [{"type": "text", "text": ""}]
    stop = "tool_use" if turn.tool_calls else "end_turn"
    if turn.stop_reason == "max_tokens":
        stop = "max_tokens"
    return {
        "id": f"msg_{uuid.uuid4().hex[:16]}",
        "type": "message",
        "role": "assistant",
        "model": requested_model or turn.model,
        "content": content,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {"input_tokens": turn.usage.tokens_in, "output_tokens": turn.usage.tokens_out},
    }


def anthropic_to_internal(payload: Dict[str, Any]) -> Tuple[Any, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Anthropic /v1/messages -> (system, messages, tools): формат почти родной."""
    system = payload.get("system")
    messages = []
    for msg in payload.get("messages") or []:
        content = msg.get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        blocks = []
        for block in content or []:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text":
                blocks.append({"type": "text", "text": block.get("text", "")})
            elif kind == "tool_use":
                blocks.append({"type": "tool_use", "id": block.get("id"),
                               "name": block.get("name"), "input": block.get("input") or {}})
            elif kind == "tool_result":
                blocks.append({"type": "tool_result",
                               "tool_use_id": block.get("tool_use_id"),
                               "content": block.get("content")
                               if isinstance(block.get("content"), str)
                               else json.dumps(block.get("content"), ensure_ascii=False),
                               "is_error": bool(block.get("is_error"))})
        messages.append({"role": msg.get("role", "user"), "content": blocks or [{"type": "text", "text": ""}]})
    tools = []
    for tool in payload.get("tools") or []:
        tools.append({"name": tool.get("name"), "description": tool.get("description", ""),
                      "input_schema": tool.get("input_schema") or {"type": "object", "properties": {}}})
    return system, messages, tools


# ---------------------------------------------------------------------------
# HTTP-сервер
# ---------------------------------------------------------------------------


class RouterHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"ELYTRIXRouter/{__version__}"

    gateway: SmartAPI = None            # type: ignore[assignment]
    catalog: Catalog = None             # type: ignore[assignment]
    state: State = None                 # type: ignore[assignment]
    pool: GatewayPool = None            # type: ignore[assignment]
    quiet: bool = True

    # -- утилиты --

    def _json(self, obj: Any, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _text(self, text: str, code: int = 200) -> None:
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _sse_start(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

    def _sse(self, obj: Any) -> None:
        data = ("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8")
        self.wfile.write(b"%x\r\n" % len(data) + data + b"\r\n")
        self.wfile.flush()

    def _sse_raw(self, text: str) -> None:
        data = text.encode("utf-8")
        self.wfile.write(b"%x\r\n" % len(data) + data + b"\r\n")
        self.wfile.flush()

    def _sse_end(self) -> None:
        try:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except Exception:  # noqa: BLE001
            pass

    def log_message(self, fmt: str, *args: Any) -> None:
        if not self.quiet:
            super().log_message(fmt, *args)

    # -- маршруты --

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/health", "/healthz"):
            return self._json({"status": "ok", "version": __version__,
                               "model": self.catalog.resolve(None)})
        if path == "/status.json":
            return self._json(self.status_payload())
        if path.endswith("/models"):
            return self._json(self.models_payload())
        if path in ("/", "/status"):
            return self._text(self.status_text())
        return self._json({"error": {"message": "not found", "type": "invalid_request_error"}}, 404)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8", "replace"))
        except ValueError as e:
            return self._json({"error": {"message": f"bad json: {e}"}}, 400)
        if path.endswith("/chat/completions") or path.endswith("/completions"):
            return self.handle_openai(payload)
        if path.endswith("/messages"):
            return self.handle_anthropic(payload)
        return self._json({"error": {"message": f"unsupported path {path}"}}, 404)

    # -- обработчики --

    def handle_openai(self, payload: Dict[str, Any]) -> None:
        model = str(payload.get("model") or self.catalog.default)
        system, messages, tools = openai_to_internal(payload.get("messages") or [],
                                                     payload.get("tools"))
        if not tools and payload.get("tools") is None and _looks_like_agent(payload):
            tools = TOOL_SCHEMAS
        stream = bool(payload.get("stream"))
        max_tokens = int(payload.get("max_tokens") or payload.get("max_completion_tokens")
                         or self.gateway.cfg.get("limits.max_output_tokens", 8192))
        temperature = payload.get("temperature")
        try:
            if stream:
                return self._stream_openai(model, system, messages, tools, max_tokens,
                                           temperature, payload.get("stream_options") or {})
            with self.pool.client(self.gateway.daily_limit) as gw:
                turn = gw.chat(model, system, messages, tools=tools or None,
                               max_tokens=max_tokens, temperature=temperature,
                               stream=False)
        except GatewayError as e:
            return self._json({"error": {"message": str(e), "type": "elytrix_error",
                                         "code": e.code}}, 429 if e.code == 429 else 502)
        self._log(model, turn)
        return self._json(turn_to_openai(turn, model))

    def _stream_openai(self, model: str, system: Any, messages: List[Dict[str, Any]],
                       tools: List[Dict[str, Any]], max_tokens: int,
                       temperature: Optional[float], options: Dict[str, Any]) -> None:
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        self._sse_start()
        self._sse({"id": completion_id, "object": "chat.completion.chunk", "created": int(time.time()),
                   "model": model, "choices": [{"index": 0, "delta": {"role": "assistant"},
                                                "finish_reason": None}]})
        collected: Dict[str, Any] = {"tool_started": False}

        def on_text(piece: str) -> None:
            self._sse({"id": completion_id, "object": "chat.completion.chunk",
                       "created": int(time.time()), "model": model,
                       "choices": [{"index": 0, "delta": {"content": piece},
                                    "finish_reason": None}]})

        def on_tool(name: str, info: Dict[str, Any]) -> None:
            if not info.get("start") or collected["tool_started"]:
                return
            collected["tool_started"] = True
            self._sse({"id": completion_id, "object": "chat.completion.chunk",
                       "created": int(time.time()), "model": model,
                       "choices": [{"index": 0,
                                    "delta": {"tool_calls": [{"index": 0, "id": info.get("id") or "",
                                                              "type": "function",
                                                              "function": {"name": name,
                                                                           "arguments": ""}}]},
                                    "finish_reason": None}]})

        try:
            with self.pool.client(self.gateway.daily_limit) as gw:
                turn = gw.chat(model, system, messages, tools=tools or None,
                               max_tokens=max_tokens, temperature=temperature,
                               stream=True, on_text=on_text, on_tool=on_tool)
        except GatewayError as e:
            self._sse({"error": {"message": str(e), "type": "elytrix_error"}})
            self._sse_raw("data: [DONE]\n\n")     # без [DONE] редактор будет ждать вечно
            self._sse_end()
            return
        self._log(model, turn)
        for i, call in enumerate(turn.tool_calls):
            self._sse({"id": completion_id, "object": "chat.completion.chunk",
                       "created": int(time.time()), "model": model,
                       "choices": [{"index": 0,
                                    "delta": {"tool_calls": [
                                        {"index": i, "id": call.id or f"call_{i}",
                                         "type": "function",
                                         "function": {"name": call.name,
                                                      "arguments": json.dumps(call.args,
                                                                              ensure_ascii=False)}}]},
                                    "finish_reason": None}]})
        finish = "tool_calls" if turn.tool_calls else "stop"
        last: Dict[str, Any] = {"id": completion_id, "object": "chat.completion.chunk",
                                "created": int(time.time()), "model": model,
                                "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}
        if options.get("include_usage"):
            last["usage"] = {"prompt_tokens": turn.usage.tokens_in,
                             "completion_tokens": turn.usage.tokens_out,
                             "total_tokens": turn.usage.total}
        self._sse(last)
        self._sse_raw("data: [DONE]\n\n")
        self._sse_end()

    def handle_anthropic(self, payload: Dict[str, Any]) -> None:
        model = str(payload.get("model") or self.catalog.default)
        system, messages, tools = anthropic_to_internal(payload)
        stream = bool(payload.get("stream"))
        max_tokens = int(payload.get("max_tokens") or 4096)
        temperature = payload.get("temperature")
        try:
            with self.pool.client(self.gateway.daily_limit) as gw:
                turn = gw.chat(model, system, messages, tools=tools or None,
                               max_tokens=max_tokens, temperature=temperature,
                               stream=stream)
        except GatewayError as e:
            return self._json({"type": "error",
                               "error": {"type": "api_error", "message": str(e)}},
                              429 if e.code == 429 else 502)
        self._log(model, turn)
        if not stream:
            return self._json(turn_to_anthropic(turn, model))

        msg_id = f"msg_{uuid.uuid4().hex[:16]}"
        self._sse_start()
        self._sse_raw(f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': {'id': msg_id, 'type': 'message', 'role': 'assistant', 'model': model, 'content': [], 'usage': {'input_tokens': turn.usage.tokens_in, 'output_tokens': 0}}}, ensure_ascii=False)}\n\n")
        if turn.text:
            self._sse_raw(f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}})}\n\n")
            self._sse_raw(f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': turn.text}}, ensure_ascii=False)}\n\n")
            self._sse_raw("event: content_block_stop\ndata: {\"type\": \"content_block_stop\", \"index\": 0}\n\n")
        for i, call in enumerate(turn.tool_calls):
            index = i + (1 if turn.text else 0)
            self._sse_raw(f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': index, 'content_block': {'type': 'tool_use', 'id': call.id or f'toolu_{i}', 'name': call.name, 'input': {}}})}\n\n")
            self._sse_raw(f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': index, 'delta': {'type': 'input_json_delta', 'partial_json': json.dumps(call.args, ensure_ascii=False)}}, ensure_ascii=False)}\n\n")
            self._sse_raw(f"event: content_block_stop\ndata: {{\"type\": \"content_block_stop\", \"index\": {index}}}\n\n")
        stop = "tool_use" if turn.tool_calls else "end_turn"
        self._sse_raw(f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': stop}, 'usage': {'output_tokens': turn.usage.tokens_out}})}\n\n")
        self._sse_raw("event: message_stop\ndata: {\"type\": \"message_stop\"}\n\n")
        self._sse_end()

    # -- служебное --

    def _log(self, model: str, turn: Turn) -> None:
        if self.quiet:
            return
        spent = self.state.tokens_day
        limit = self.gateway.daily_limit
        tail = f" · за сегодня {spent:,}".replace(",", " ")
        if limit:
            tail += f" из {limit:,}".replace(",", " ") + f" ({round(spent * 100 / limit)}%)"
        print(f"[{time.strftime('%H:%M:%S')}] {model} ×{self.catalog.multiplier(self.catalog.resolve(model)):g}"
              f" · вх {turn.usage.tokens_in} вых {turn.usage.tokens_out}"
              f" · кэш {turn.usage.cache_read} · {turn.usage.elapsed:.1f}с{tail}", flush=True)

    def status_payload(self) -> Dict[str, Any]:
        gw = self.gateway
        pool = self.pool.stats() if self.pool is not None else {}
        pool.setdefault("cache_enabled", gw.cache_enabled)
        pool.setdefault("cache_supported", gw.cache_supported)
        pool.setdefault("cache_read", gw.session_cache_read)
        for key, value in (("tokens_in", gw.session.tokens_in), ("tokens_out", gw.session.tokens_out),
                           ("charged", gw.session.charged)):
            pool.setdefault(key, value)
        return {
            "app": "ELYTRIX",
            "version": __version__,
            "uptime_s": int(time.time() - STARTED_AT),
            "model": self.catalog.resolve(None),
            "default_alias": self.catalog.default,
            "day_tokens": self.state.tokens_day,
            "day_limit": gw.daily_limit,
            "day_requests": self.state.requests_day,
            "by_model": self.state.by_model(),
            "cache": {"enabled": pool["cache_enabled"], "supported": pool["cache_supported"],
                      "read_tokens": pool["cache_read"]},
            "session": {"tokens_in": pool["tokens_in"], "tokens_out": pool["tokens_out"],
                        "charged": pool["charged"]},
            "clients": len(self.pool.all),
            "gateway": {"anthropic": gw.base_url, "openai": gw.oai_url},
        }

    def status_text(self) -> str:
        data = self.status_payload()
        lines = [f"ELYTRIX router {__version__} — работает", "",
                 f"адрес для редакторов: http://127.0.0.1:{self.server.server_address[1]}/v1",
                 f"шлюз: {data['gateway']['anthropic']} (Anthropic) / "
                 f"{data['gateway']['openai']} (OpenAI)",
                 f"модель по умолчанию: {data['model']}",
                 f"за сегодня: {data['day_tokens']} зачётных токенов"
                 + (f" из {data['day_limit']}" if data['day_limit'] else " (без лимита)")
                 + f", запросов: {data['day_requests']}",
                 f"кэш промпта: {'работает' if data['cache']['supported'] else 'шлюз не поддержал'}"
                 f", прочитано из кэша: {data['cache']['read_tokens']}",
                 "", "программный доступ: /status.json · /v1/models · /health"]
        return "\n".join(lines)

    def models_payload(self) -> Dict[str, Any]:
        data: List[Dict[str, Any]] = []
        for alias, info in self.catalog.aliases.items():
            model = str(info.get("model") or alias)
            data.append({"id": alias, "object": "model", "owned_by": "elytrix",
                         "model": model, "multiplier": self.catalog.multiplier(model),
                         "alias": True, "description": info.get("note", "")})
        for model in self.catalog.all_models():
            data.append({"id": model, "object": "model",
                         "owned_by": self.catalog.family(model),
                         "multiplier": self.catalog.multiplier(model),
                         "alias": False, "description": self.catalog.note(model)})
        return {"object": "list", "data": data}


def _looks_like_agent(payload: Dict[str, Any]) -> bool:
    """Подсказка: редактор не прислал tools, но по системному промпту похоже на агента."""
    system = payload.get("messages") or [{}]
    text = json.dumps(system[:1], ensure_ascii=False).lower()
    return "tool" in text and "file" in text


def make_server(cfg: Config, catalog: Catalog, state: State, gateway: SmartAPI,
                host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                quiet: bool = True, pool_size: int = 4) -> ThreadingHTTPServer:
    RouterHandler.gateway = gateway
    RouterHandler.catalog = catalog
    RouterHandler.state = state
    RouterHandler.quiet = quiet
    def make_client() -> SmartAPI:
        client = SmartAPI(cfg, catalog, state, key=gateway.key)
        client.daily_limit = gateway.daily_limit
        return client

    RouterHandler.pool = GatewayPool(make_client, size=pool_size, first=gateway)
    httpd = ThreadingHTTPServer((host, port), RouterHandler)
    httpd.daemon_threads = True
    return httpd


def serve_in_thread(cfg: Config, catalog: Catalog, state: State, gateway: SmartAPI,
                    host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                    quiet: bool = True) -> Tuple[ThreadingHTTPServer, threading.Thread, str]:
    """Поднимает роутер в фоновом потоке (команда /router внутри агента).

    У роутера свой экземпляр клиента — свои keep-alive соединения, чтобы стриминг
    редактора и запросы консоли не мешали друг другу. Учёт расхода общий (state).
    """
    own = SmartAPI(cfg, catalog, state, key=gateway.key)
    own.daily_limit = gateway.daily_limit
    httpd = make_server(cfg, catalog, state, own, host=host, port=port, quiet=quiet)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True, name="elytrix-router")
    thread.start()
    bound = int(httpd.server_address[1])       # port=0 → порт выбрала ОС
    return httpd, thread, f"http://{host}:{bound}"


def serve_forever(cfg: Config, catalog: Catalog, state: State, gateway: SmartAPI,
                  host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> int:
    """Отдельный процесс роутера (ELYTRIX-ROUTER.bat)."""
    httpd = make_server(cfg, catalog, state, gateway, host=host, port=port, quiet=False)
    bound = int(httpd.server_address[1])       # port=0 → порт выбрала ОС
    # flush обязателен: окно роутера часто перенаправляют в файл или читают из скрипта
    def say(line: str = "") -> None:
        print(line, flush=True)

    say()
    say(f"  ELYTRIX router {__version__} слушает http://{host}:{bound}")
    say(f"  адрес для редакторов: http://{host}:{bound}/v1")
    say(f"  шлюз: {gateway.base_url} · модель по умолчанию: {catalog.resolve(None)}")
    limit = gateway.daily_limit
    if limit:
        say(f"  дневной лимит: {limit:,} зачётных токенов".replace(",", " "))
    say("  расход печатается здесь после каждого запроса · Ctrl+C — остановить")
    say()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        say("\n  останавливаю роутер…")
    finally:
        try:
            RouterHandler.pool.close()
        except Exception:  # noqa: BLE001
            pass
        httpd.server_close()
        state.save()
    return 0
