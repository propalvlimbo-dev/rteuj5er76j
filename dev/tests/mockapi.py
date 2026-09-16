#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Фальшивый шлюз SmartAPI для тестов: Anthropic /v1/messages и OpenAI /v1/chat/completions.

Умеет всё, что нужно проверить без настоящего ключа и без интернета:
    · ответы по сценарию (текст, вызовы инструментов, потоковый вывод);
    · отказы, на которых проверяется живучесть: 400 на tools, 400 на cache_control,
      404 на модели, 429, обрыв соединения, «мёртвый» Anthropic-адрес (уход в OpenAI);
    · запись всех полученных запросов — по ним видно, что реально уехало в сеть
      (сжатая история, пометки кэша, состав инструментов).

Запуск внутри теста:
    gw = MockGateway(); gw.start(); gw.script.append(text("привет"))
    ...; gw.stop()
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Конструкторы ответов сценария
# ---------------------------------------------------------------------------


def text(value: str, tokens_in: int = 100, tokens_out: int = 20,
         cache_read: int = 0) -> Dict[str, Any]:
    """Ответ только текстом (задача закончена)."""
    return {"text": value, "tools": [], "usage": {"in": tokens_in, "out": tokens_out,
                                                  "cache_read": cache_read}}


def tool(*calls: Dict[str, Any], thought: str = "", tokens_in: int = 120,
         tokens_out: int = 30, cache_read: int = 0) -> Dict[str, Any]:
    """Ответ с вызовами инструментов: tool({"name": "read", "args": {"path": "a.py"}})."""
    return {"text": thought, "tools": list(calls),
            "usage": {"in": tokens_in, "out": tokens_out, "cache_read": cache_read}}


def call(name: str, **args: Any) -> Dict[str, Any]:
    return {"name": name, "args": args}


# ---------------------------------------------------------------------------
# Сервер
# ---------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "MockSmartAPI/1.0"

    api: "MockGateway" = None  # type: ignore[assignment]

    def log_message(self, *args: Any) -> None:      # тишина в выводе тестов
        pass

    # -- вспомогательное --

    def _read_payload(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            return {}

    def _json(self, obj: Any, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, code: int, message: str) -> None:
        self._json({"error": {"message": message, "type": "mock_error"}}, code)

    # -- маршруты --

    def do_GET(self) -> None:  # noqa: N802
        api = self.api
        api.gets.append(self.path)
        if self.path.endswith("/models"):
            return self._json({"object": "list",
                               "data": [{"id": m} for m in api.catalog]})
        if self.path.endswith("/health"):
            return self._json({"status": "ok"})
        return self._error(404, "not found")

    def do_POST(self) -> None:  # noqa: N802
        api = self.api
        payload = self._read_payload()
        anthropic = self.path.endswith("/messages")
        api.requests.append({"path": self.path, "anthropic": anthropic, "payload": payload,
                             "headers": dict(self.headers), "at": time.time()})

        if anthropic and api.anthropic_status and api.anthropic_status >= 400:
            return self._error(api.anthropic_status, api.anthropic_message or "anthropic disabled")

        if api.fail_with:
            code, message = api.fail_with
            once = api.fail_once
            api.fail_with = None if once else api.fail_with
            return self._error(code, message)

        if api.reject_cache and _has_cache_control(payload):
            return self._error(400, "unexpected field cache_control: prompt caching is not supported")

        if api.drop_tools and payload.get("tools"):
            return self._error(400, "tools are not supported by this model")

        if api.unknown_model and payload.get("model") not in api.catalog:
            return self._error(404, f"The requested model '{payload.get('model')}' does not exist")

        step = api.next_step()
        if step is None:
            step = text("[mock] сценарий пуст")
        if api.stall:
            time.sleep(api.stall)
        if api.cut_stream or api.cut_empty:
            # обрыв потока: кусок мусора (или ничего) и закрытие соединения без [DONE]
            empty = api.cut_empty
            if api.cut_once:
                api.cut_stream = False
                api.cut_empty = False
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                if not empty:
                    self.wfile.write(b"5\r\nhello\r\n")
                self.wfile.flush()
            except Exception:  # noqa: BLE001
                pass
            self.close_connection = True
            return

        if payload.get("stream"):
            return self._stream(step, payload, anthropic)
        return self._full(step, payload, anthropic)

    # -- ответы --

    def _full(self, step: Dict[str, Any], payload: Dict[str, Any], anthropic: bool) -> None:
        usage = step.get("usage") or {}
        model = payload.get("model", "mock")
        if anthropic:
            content: List[Dict[str, Any]] = []
            if step.get("text"):
                content.append({"type": "text", "text": step["text"]})
            for i, tc in enumerate(step.get("tools") or []):
                content.append({"type": "tool_use", "id": tc.get("id") or f"toolu_{i}_{uuid.uuid4().hex[:6]}",
                                "name": tc["name"], "input": tc.get("args") or {}})
            if not content:
                content = [{"type": "text", "text": ""}]
            body = {
                "id": f"msg_{uuid.uuid4().hex[:10]}", "type": "message", "role": "assistant",
                "model": model, "content": content,
                "stop_reason": "tool_use" if step.get("tools") else "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": usage.get("in", 10),
                          "output_tokens": usage.get("out", 5),
                          "cache_read_input_tokens": usage.get("cache_read", 0),
                          "cache_creation_input_tokens": usage.get("cache_write", 0)},
            }
            return self._json(body)

        message: Dict[str, Any] = {"role": "assistant", "content": step.get("text") or None}
        if step.get("tools"):
            message["tool_calls"] = [
                {"id": tc.get("id") or f"call_{i}_{uuid.uuid4().hex[:6]}", "type": "function",
                 "function": {"name": tc["name"],
                              "arguments": json.dumps(tc.get("args") or {}, ensure_ascii=False)}}
                for i, tc in enumerate(step["tools"])]
        body = {
            "id": f"chatcmpl-{uuid.uuid4().hex[:10]}", "object": "chat.completion",
            "created": int(time.time()), "model": model,
            "choices": [{"index": 0, "message": message,
                         "finish_reason": "tool_calls" if step.get("tools") else "stop"}],
            "usage": {"prompt_tokens": usage.get("in", 10),
                      "completion_tokens": usage.get("out", 5),
                      "total_tokens": usage.get("in", 10) + usage.get("out", 5)},
        }
        return self._json(body)

    def _stream(self, step: Dict[str, Any], payload: Dict[str, Any], anthropic: bool) -> None:
        usage = step.get("usage") or {}
        model = payload.get("model", "mock")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def send(data: str) -> None:
            chunk = data.encode("utf-8")
            try:
                self.wfile.write(b"%x\r\n" % len(chunk) + chunk + b"\r\n")
                self.wfile.flush()
            except Exception:  # noqa: BLE001
                pass

        def sse(obj: Any, event: Optional[str] = None) -> None:
            prefix = f"event: {event}\n" if event else ""
            send(prefix + "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n")

        if anthropic:
            sse({"type": "message_start", "message": {
                "id": f"msg_{uuid.uuid4().hex[:8]}", "type": "message", "role": "assistant",
                "model": model, "content": [],
                "usage": {"input_tokens": usage.get("in", 10), "output_tokens": 1,
                          "cache_read_input_tokens": usage.get("cache_read", 0),
                          "cache_creation_input_tokens": usage.get("cache_write", 0)}}},
                "message_start")
            index = 0
            if step.get("text"):
                sse({"type": "content_block_start", "index": index,
                     "content_block": {"type": "text", "text": ""}}, "content_block_start")
                # текст отдаём кусками — так проверяется потоковая печать
                for piece in _chunks(step["text"], 12):
                    sse({"type": "content_block_delta", "index": index,
                         "delta": {"type": "text_delta", "text": piece}}, "content_block_delta")
                sse({"type": "content_block_stop", "index": index}, "content_block_stop")
                index += 1
            for tc in step.get("tools") or []:
                call_id = tc.get("id") or f"toolu_{index}_{uuid.uuid4().hex[:6]}"
                sse({"type": "content_block_start", "index": index,
                     "content_block": {"type": "tool_use", "id": call_id,
                                       "name": tc["name"], "input": {}}}, "content_block_start")
                args_json = json.dumps(tc.get("args") or {}, ensure_ascii=False)
                for piece in _chunks(args_json, 20):
                    sse({"type": "content_block_delta", "index": index,
                         "delta": {"type": "input_json_delta", "partial_json": piece}},
                        "content_block_delta")
                sse({"type": "content_block_stop", "index": index}, "content_block_stop")
                index += 1
            sse({"type": "message_delta",
                 "delta": {"stop_reason": "tool_use" if step.get("tools") else "end_turn"},
                 "usage": {"output_tokens": usage.get("out", 5)}}, "message_delta")
            sse({"type": "message_stop"}, "message_stop")
        else:
            completion = f"chatcmpl-{uuid.uuid4().hex[:8]}"

            def chunk(delta: Dict[str, Any], finish: Optional[str] = None,
                      with_usage: bool = False) -> None:
                obj: Dict[str, Any] = {"id": completion, "object": "chat.completion.chunk",
                                       "created": int(time.time()), "model": model,
                                       "choices": [{"index": 0, "delta": delta,
                                                    "finish_reason": finish}]}
                if with_usage:
                    obj["usage"] = {"prompt_tokens": usage.get("in", 10),
                                    "completion_tokens": usage.get("out", 5),
                                    "total_tokens": usage.get("in", 10) + usage.get("out", 5)}
                sse(obj)

            chunk({"role": "assistant", "content": ""})
            if step.get("text"):
                for piece in _chunks(step["text"], 12):
                    chunk({"content": piece})
            for i, tc in enumerate(step.get("tools") or []):
                chunk({"tool_calls": [{"index": i, "id": tc.get("id") or f"call_{i}",
                                       "type": "function",
                                       "function": {"name": tc["name"], "arguments": ""}}]})
                args_json = json.dumps(tc.get("args") or {}, ensure_ascii=False)
                for piece in _chunks(args_json, 20):
                    chunk({"tool_calls": [{"index": i, "function": {"arguments": piece}}]})
            chunk({}, finish="tool_calls" if step.get("tools") else "stop",
                  with_usage=bool((payload.get("stream_options") or {}).get("include_usage")))
            send("data: [DONE]\n\n")
        try:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except Exception:  # noqa: BLE001
            pass


def _has_cache_control(payload: Dict[str, Any]) -> bool:
    raw = json.dumps(payload, ensure_ascii=False)
    return "cache_control" in raw


def _chunks(text: str, size: int) -> List[str]:
    return [text[i:i + size] for i in range(0, len(text), size)] or [""]


class MockGateway:
    """Поднимается на случайном порту, адрес передаётся агенту через конфиг."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.script: List[Dict[str, Any]] = []
        self.requests: List[Dict[str, Any]] = []
        self.gets: List[str] = []
        self.catalog = ["claude-sonnet-4-6", "claude-opus-4-8", "gpt-5.6-luna",
                        "mock-unknown-model"]
        self.fail_with: Optional[tuple] = None
        self.fail_once = True
        self.reject_cache = False
        self.drop_tools = False
        self.unknown_model = False
        self.anthropic_status: Optional[int] = None
        self.anthropic_message = ""
        self.stall = 0.0
        self.cut_stream = False
        self.cut_empty = False
        self.cut_once = False
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.host = host
        self.port = port
        self.lock = threading.Lock()

    # -- запуск --

    def start(self) -> "MockGateway":
        handler = type("BoundHandler", (_Handler,), {"api": self})
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler)
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def openai_url(self) -> str:
        return f"http://{self.host}:{self.port}/v1"

    # -- сценарий --

    def next_step(self) -> Optional[Dict[str, Any]]:
        with self.lock:
            if self.script:
                return self.script.pop(0)
        return None

    def queue(self, *steps: Dict[str, Any]) -> "MockGateway":
        with self.lock:
            self.script.extend(steps)
        return self

    # -- проверка того, что ушло в сеть --

    @property
    def last(self) -> Dict[str, Any]:
        return self.requests[-1] if self.requests else {}

    def payloads(self, anthropic: Optional[bool] = None) -> List[Dict[str, Any]]:
        out = [r["payload"] for r in self.requests
               if anthropic is None or r["anthropic"] == anthropic]
        return out

    def used_paths(self) -> List[str]:
        return [r["path"] for r in self.requests]

    def wait_for(self, count: int = 1, timeout: float = 5.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if len(self.requests) >= count:
                return True
            time.sleep(0.02)
        return len(self.requests) >= count


# ---------------------------------------------------------------------------
# Общий стенд для тестов агента, интерфейса и роутера
# ---------------------------------------------------------------------------


class Stack:
    """Собранный агент на mock-шлюзе + временные папки (профиль и проект)."""

    def __init__(self, mock: "MockGateway", workspace: str, config: Optional[Dict[str, Any]] = None):
        import tempfile

        from elytrix.agent import Agent
        from elytrix.config import Catalog, Config, State
        from elytrix.gateway import SmartAPI
        from elytrix.tools import Toolbox, Workspace

        self.home = tempfile.mkdtemp(prefix="elytrix-home-")
        os.environ["ELYTRIX_HOME"] = self.home
        os.environ["SMARTAPI_KEY"] = "sk-smart-test-key"
        base: Dict[str, Any] = {
            "gateway": {"base_url": mock.base_url, "openai_base_url": mock.openai_url,
                        "timeout": 10, "connect_timeout": 5},
            "limits": {"daily_tokens": 1000000, "max_steps": 8, "max_output_tokens": 512},
            "economy": {"cache": True, "tool_result_chars": 2000, "read_chars": 4000,
                        "keep_recent": 1, "compact_at": 0.5},
            "ui": {"stream": True, "confirm": "auto"},
        }
        for key, value in (config or {}).items():
            base.setdefault(key, {}).update(value) if isinstance(value, dict) else base.update({key: value})
        self.cfg = Config(base)
        self.catalog = Catalog(dict(self.cfg.get("models")))
        self.state = State()
        self.gw = SmartAPI(self.cfg, self.catalog, self.state, key="sk-smart-test-key")
        self.ws = Workspace(workspace, limits=dict(self.cfg.get("economy")))
        self.toolbox = Toolbox(self.ws, dict(self.cfg.get("economy")))
        self.events: List[Tuple[str, Dict[str, Any]]] = []
        self.agent = Agent(self.gw, self.toolbox, self.cfg, self.catalog, self.state,
                           emit=lambda kind, data: self.events.append((kind, data)),
                           confirm=lambda req: "yes")
        self.agent.confirm_mode = "auto"
        self.agent.model = "auto"

    def kinds(self) -> List[str]:
        return [kind for kind, _ in self.events]

    def of(self, kind: str) -> List[Dict[str, Any]]:
        return [data for k, data in self.events if k == kind]

    def cleanup(self) -> None:
        self.gw.close()
        shutil.rmtree(self.home, ignore_errors=True)
        os.environ.pop("ELYTRIX_HOME", None)


def make_workspace(prefix: str = "elytrix-ws-") -> str:
    """Временная папка «проекта пользователя» для тестов."""
    import tempfile

    return tempfile.mkdtemp(prefix=prefix)
