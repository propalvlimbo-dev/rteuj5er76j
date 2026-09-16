#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты роутера — локального HTTP-шлюза для Cline, Continue, opencode и Cursor.

Проверяются и чистые переводы форматов (OpenAI ↔ Anthropic ↔ внутренний), и живой
сервер на случайном порту: обычные и потоковые ответы, инструменты, учёт расхода,
ошибки и служебные маршруты.

Запуск:  python dev/tests/test_router.py
"""

from __future__ import annotations

import http.client
import json
import os
import shutil
import sys
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mockapi import MockGateway, Stack, call, make_workspace, text, tool  # noqa: E402

from elytrix.gateway import ToolCall, Turn, Usage  # noqa: E402
from elytrix.router import (_looks_like_agent, anthropic_to_internal,  # noqa: E402
                            openai_to_internal, serve_in_thread, turn_to_anthropic,
                            turn_to_openai)
from elytrix.tools import TOOL_SCHEMAS  # noqa: E402


def sse_events(body: bytes):
    """Разбирает ответ text/event-stream в список (событие, данные)."""
    out = []
    event = ""
    for raw in body.decode("utf-8", "replace").split("\n"):
        line = raw.rstrip("\r")
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            payload = line[5:].strip()
            if payload == "[DONE]":
                out.append((event or "message", "[DONE]"))
                event = ""
                continue
            try:
                out.append((event, json.loads(payload)))
            except ValueError:
                out.append((event, payload))
            event = ""
    return out


# ---------------------------------------------------------------------------
# Перевод форматов (без сети)
# ---------------------------------------------------------------------------


class TestConversions(unittest.TestCase):
    def test_openai_system_messages_are_joined(self):
        system, messages, tools = openai_to_internal([
            {"role": "system", "content": "ты агент"},
            {"role": "developer", "content": "работай в папке"},
            {"role": "user", "content": "привет"},
        ], None)
        self.assertEqual(system, "ты агент\n\nработай в папке")
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[0]["content"][0]["text"], "привет")
        self.assertEqual(tools, [])

    def test_openai_system_as_blocks(self):
        system, _m, _t = openai_to_internal(
            [{"role": "system", "content": [{"type": "text", "text": "правила"}]},
             {"role": "user", "content": "делай"}], None)
        self.assertEqual(system, "правила")

    def test_openai_no_system_is_none(self):
        system, _m, _t = openai_to_internal([{"role": "user", "content": "делай"}], None)
        self.assertIsNone(system)

    def test_openai_tool_calls_become_tool_use(self):
        _system, messages, _tools = openai_to_internal([
            {"role": "user", "content": "прочитай файл"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_1", "type": "function",
                 "function": {"name": "read", "arguments": '{"path": "a.py"}'}}]},
            {"role": "tool", "tool_call_id": "call_1", "content": "print(1)"},
        ], None)
        self.assertEqual(messages[1]["content"][0]["type"], "tool_use")
        self.assertEqual(messages[1]["content"][0]["input"], {"path": "a.py"})
        self.assertEqual(messages[2]["role"], "user")
        self.assertEqual(messages[2]["content"][0]["type"], "tool_result")
        self.assertEqual(messages[2]["content"][0]["tool_use_id"], "call_1")

    def test_openai_parallel_tool_results_are_grouped(self):
        """Два результата подряд — одно сообщение: иначе шлюз вернёт 400."""
        _system, messages, _tools = openai_to_internal([
            {"role": "assistant", "tool_calls": [
                {"id": "a", "function": {"name": "read", "arguments": "{}"}},
                {"id": "b", "function": {"name": "ls", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "a", "content": "первый"},
            {"role": "tool", "tool_call_id": "b", "content": "второй"},
        ], None)
        results = [m for m in messages if m["role"] == "user"]
        self.assertEqual(len(results), 1)
        self.assertEqual(len(results[0]["content"]), 2)

    def test_openai_broken_arguments_do_not_crash(self):
        _system, messages, _tools = openai_to_internal([
            {"role": "assistant", "tool_calls": [
                {"id": "x", "function": {"name": "write", "arguments": "{не json"}}]},
        ], None)
        self.assertEqual(messages[0]["content"][0]["input"], {})

    def test_openai_tools_are_converted(self):
        _s, _m, tools = openai_to_internal([], [
            {"type": "function", "function": {"name": "read", "description": "читает",
                                              "parameters": {"type": "object"}}},
            {"type": "function", "function": {"description": "без имени"}},
        ])
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "read")
        self.assertEqual(tools[0]["input_schema"], {"type": "object"})

    def test_openai_empty_message_keeps_block(self):
        _s, messages, _t = openai_to_internal([{"role": "user", "content": ""}], None)
        self.assertEqual(messages[0]["content"], [{"type": "text", "text": ""}])

    def test_anthropic_is_pass_through(self):
        payload = {
            "system": "ты агент",
            "messages": [{"role": "user", "content": "привет"},
                         {"role": "assistant", "content": [
                             {"type": "text", "text": "думаю"},
                             {"type": "tool_use", "id": "t1", "name": "read",
                              "input": {"path": "a.py"}}]},
                         {"role": "user", "content": [
                             {"type": "tool_result", "tool_use_id": "t1",
                              "content": [{"type": "text", "text": "код"}],
                              "is_error": False}]}],
            "tools": [{"name": "read", "description": "читает",
                       "input_schema": {"type": "object"}}],
        }
        system, messages, tools = anthropic_to_internal(payload)
        self.assertEqual(system, "ты агент")
        self.assertEqual(messages[0]["content"][0]["text"], "привет")
        self.assertEqual(messages[1]["content"][1]["name"], "read")
        result = messages[2]["content"][0]
        self.assertEqual(result["type"], "tool_result")
        self.assertIn("код", result["content"], "список блоков становится текстом")
        self.assertFalse(result["is_error"])
        self.assertEqual(tools[0]["name"], "read")

    def test_anthropic_unknown_blocks_are_dropped(self):
        _s, messages, _t = anthropic_to_internal({"messages": [
            {"role": "user", "content": [{"type": "image", "source": {}},
                                         {"type": "text", "text": "что тут"}]}]})
        self.assertEqual(len(messages[0]["content"]), 1)

    def test_turn_to_openai_text(self):
        turn = Turn(text="готово", stop_reason="end_turn", model="claude-sonnet-4-6",
                    endpoint="anthropic", usage=Usage(100, 20, charged=240))
        out = turn_to_openai(turn, "auto")
        self.assertEqual(out["object"], "chat.completion")
        self.assertEqual(out["model"], "auto")
        self.assertEqual(out["choices"][0]["message"]["content"], "готово")
        self.assertEqual(out["choices"][0]["finish_reason"], "stop")
        self.assertEqual(out["usage"], {"prompt_tokens": 100, "completion_tokens": 20,
                                        "total_tokens": 120})
        self.assertEqual(out["x_elytrix"]["charged"], 240)

    def test_turn_to_openai_tools(self):
        turn = Turn(tool_calls=[ToolCall(id="c1", name="read", args={"path": "a.py"})],
                    stop_reason="tool_use", usage=Usage(10, 5))
        out = turn_to_openai(turn, "gpt-5.6-luna")
        message = out["choices"][0]["message"]
        self.assertEqual(out["choices"][0]["finish_reason"], "tool_calls")
        self.assertEqual(message["tool_calls"][0]["function"]["name"], "read")
        self.assertEqual(json.loads(message["tool_calls"][0]["function"]["arguments"]),
                         {"path": "a.py"})

    def test_turn_to_openai_length_stop(self):
        turn = Turn(text="оборвано", stop_reason="max_tokens", usage=Usage(1, 2))
        self.assertEqual(turn_to_openai(turn, "m")["choices"][0]["finish_reason"], "length")

    def test_turn_to_anthropic(self):
        turn = Turn(text="привет", tool_calls=[ToolCall(id="c1", name="ls", args={})],
                    stop_reason="tool_use", usage=Usage(50, 10))
        out = turn_to_anthropic(turn, "claude-sonnet-4-6")
        self.assertEqual(out["type"], "message")
        self.assertEqual(out["stop_reason"], "tool_use")
        self.assertEqual(out["content"][0], {"type": "text", "text": "привет"})
        self.assertEqual(out["content"][1]["name"], "ls")
        self.assertEqual(out["usage"], {"input_tokens": 50, "output_tokens": 10})

    def test_turn_to_anthropic_empty(self):
        out = turn_to_anthropic(Turn(stop_reason="end_turn"), "m")
        self.assertEqual(out["content"], [{"type": "text", "text": ""}])
        self.assertEqual(out["stop_reason"], "end_turn")

    def test_turn_to_anthropic_max_tokens(self):
        out = turn_to_anthropic(Turn(text="x", stop_reason="max_tokens"), "m")
        self.assertEqual(out["stop_reason"], "max_tokens")

    def test_looks_like_agent(self):
        self.assertTrue(_looks_like_agent({"messages": [
            {"role": "system", "content": "You are an agent. Use tools to read files."}]}))
        self.assertFalse(_looks_like_agent({"messages": [
            {"role": "system", "content": "ты переводчик"}]}))
        self.assertFalse(_looks_like_agent({}))


# ---------------------------------------------------------------------------
# Живой сервер
# ---------------------------------------------------------------------------


class RouterCase(unittest.TestCase):
    def setUp(self):
        self.mock = MockGateway()
        self.mock.start()
        self.ws = make_workspace("elytrix-router-")
        self.stack = Stack(self.mock, self.ws)
        self.httpd, self.thread, self.url = serve_in_thread(
            self.stack.cfg, self.stack.catalog, self.stack.state, self.stack.gw, port=0)
        self.port = int(self.url.rsplit(":", 1)[1])
        self.router_gateway = self.httpd.RequestHandlerClass.gateway

    def tearDown(self):
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:  # noqa: BLE001
            pass
        self.router_gateway.close()
        self.mock.stop()
        self.stack.cleanup()
        shutil.rmtree(self.ws, ignore_errors=True)

    # -- помощники --

    def request(self, method, path, payload=None, headers=None, timeout=25):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8") \
                if payload is not None else None
            # роутеру всё равно, какой ключ прислал редактор: настоящий ключ он держит у себя
            sent = {"Content-Type": "application/json",
                    "Authorization": "Bearer sk-editor-key"}
            sent.update(headers or {})
            conn.request(method, path, body=body, headers=sent)
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, {k.lower(): v for k, v in resp.getheaders()}, data
        finally:
            conn.close()

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, payload, **kw):
        return self.request("POST", path, payload, **kw)

    def json_post(self, path, payload, **kw):
        status, _headers, data = self.post(path, payload, **kw)
        return status, json.loads(data.decode("utf-8"))


class TestServiceRoutes(RouterCase):
    def test_health(self):
        status, headers, data = self.get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(headers["access-control-allow-origin"], "*")
        body = json.loads(data)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["model"], "claude-sonnet-4-6")

    def test_healthz_alias(self):
        self.assertEqual(self.get("/healthz")[0], 200)

    def test_status_json(self):
        self.stack.state.record("gpt-5.6-luna", 1000, 100, 1.7)
        status, _headers, data = self.get("/status.json")
        body = json.loads(data)
        self.assertEqual(status, 200)
        self.assertEqual(body["app"], "ELYTRIX")
        self.assertEqual(body["day_tokens"], 1870)
        self.assertEqual(body["day_limit"], 1000000)
        self.assertEqual(body["day_requests"], 1)
        self.assertIn("gpt-5.6-luna", body["by_model"])
        self.assertEqual(body["gateway"]["anthropic"], self.mock.base_url)
        self.assertIn("cache", body)

    def test_status_text(self):
        status, headers, data = self.get("/")
        body = data.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("text/plain", headers["content-type"])
        self.assertIn("ELYTRIX router", body)
        self.assertIn(f"127.0.0.1:{self.port}/v1", body, "адрес должен содержать настоящий порт")
        self.assertIn("за сегодня", body)

    def test_models_list(self):
        status, _headers, data = self.get("/v1/models")
        body = json.loads(data)
        self.assertEqual(status, 200)
        self.assertEqual(body["object"], "list")
        ids = {item["id"]: item for item in body["data"]}
        self.assertIn("auto", ids)
        self.assertTrue(ids["auto"]["alias"])
        self.assertEqual(ids["auto"]["model"], "claude-sonnet-4-6")
        self.assertEqual(ids["gpt-5.6-luna"]["multiplier"], 1.7)
        self.assertFalse(ids["gpt-5.6-luna"]["alias"])
        self.assertEqual(ids["claude-fable-5"]["multiplier"], 10.0)

    def test_models_sorted_cheap_first(self):
        _s, _h, data = self.get("/v1/models")
        models = [item["id"] for item in json.loads(data)["data"] if not item["alias"]]
        self.assertEqual(models[0], "gpt-5.6-luna")

    def test_unknown_get_is_404(self):
        status, _headers, data = self.get("/v1/unknown")
        self.assertEqual(status, 404)
        self.assertIn("error", json.loads(data))

    def test_options_preflight(self):
        status, headers, data = self.request("OPTIONS", "/v1/chat/completions")
        self.assertEqual(status, 204)
        self.assertEqual(headers["access-control-allow-methods"], "GET, POST, OPTIONS")
        self.assertEqual(data, b"")

    def test_bad_json_is_400(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        conn.request("POST", "/v1/chat/completions", body="{не json".encode("utf-8"),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        body = json.loads(resp.read())
        conn.close()
        self.assertEqual(resp.status, 400)
        self.assertIn("bad json", body["error"]["message"])

    def test_unknown_post_is_404(self):
        status, _headers, _data = self.post("/v1/embeddings", {"model": "x"})
        self.assertEqual(status, 404)


class TestOpenAIEndpoint(RouterCase):
    def test_chat_completion(self):
        self.mock.queue(text("всё готово"))
        status, body = self.json_post("/v1/chat/completions", {
            "model": "gpt-5.6-luna",
            "messages": [{"role": "system", "content": "ты помощник"},
                         {"role": "user", "content": "почини тест"}],
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["object"], "chat.completion")
        self.assertEqual(body["model"], "gpt-5.6-luna")
        self.assertEqual(body["choices"][0]["message"]["content"], "всё готово")
        self.assertEqual(body["choices"][0]["finish_reason"], "stop")
        self.assertGreater(body["usage"]["total_tokens"], 0)

    def test_request_reaches_gateway_in_right_shape(self):
        self.mock.queue(text("ок"))
        self.json_post("/v1/chat/completions", {
            "model": "auto",
            "messages": [{"role": "user", "content": "привет"}],
            "max_tokens": 77,
            "temperature": 0.3,
        })
        payload = self.mock.payloads()[-1]
        self.assertEqual(payload["max_tokens"], 77)
        self.assertEqual(payload["temperature"], 0.3)
        self.assertEqual(payload["messages"][-1]["content"][0]["text"], "привет")

    def test_tools_round_trip(self):
        self.mock.queue(tool(call("read", path="a.py")), text("прочитал"))
        status, body = self.json_post("/v1/chat/completions", {
            "model": "auto",
            "messages": [{"role": "user", "content": "прочитай a.py"}],
            "tools": [{"type": "function", "function": {
                "name": "read", "description": "читает файл",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}}],
        })
        self.assertEqual(status, 200)
        calls = body["choices"][0]["message"]["tool_calls"]
        self.assertEqual(calls[0]["function"]["name"], "read")
        self.assertEqual(json.loads(calls[0]["function"]["arguments"]), {"path": "a.py"})
        self.assertEqual(body["choices"][0]["finish_reason"], "tool_calls")
        sent = self.mock.payloads()[-1]
        self.assertEqual(sent["tools"][0]["name"], "read")

    def test_agent_without_tools_gets_elytrix_toolbox(self):
        """Редактор не прислал tools, но по промпту это агент — даём ему свой набор."""
        self.mock.queue(text("ок"))
        self.json_post("/v1/chat/completions", {
            "model": "auto",
            "messages": [{"role": "system",
                          "content": "You are a coding agent. Use tools to read and write files."},
                         {"role": "user", "content": "почини"}],
        })
        sent = self.mock.payloads()[-1]
        names = {t["name"] for t in sent.get("tools") or []}
        self.assertEqual(names, {spec["name"] for spec in TOOL_SCHEMAS})

    def test_plain_chat_gets_no_tools(self):
        self.mock.queue(text("ок"))
        self.json_post("/v1/chat/completions", {
            "model": "auto",
            "messages": [{"role": "system", "content": "ты переводчик"},
                         {"role": "user", "content": "переведи"}],
        })
        sent = self.mock.payloads()[-1]
        self.assertFalse(sent.get("tools"), "обычному чату инструменты не нужны — это токены")

    def test_max_tokens_defaults_from_config(self):
        self.mock.queue(text("ок"))
        self.json_post("/v1/chat/completions", {
            "model": "auto", "messages": [{"role": "user", "content": "привет"}]})
        self.assertEqual(self.mock.payloads()[-1]["max_tokens"], 512)

    def test_alias_is_resolved_by_gateway(self):
        self.mock.queue(text("ок"))
        self.json_post("/v1/chat/completions", {
            "model": "max", "messages": [{"role": "user", "content": "привет"}]})
        self.assertEqual(self.mock.payloads()[-1]["model"], "claude-opus-5")

    def test_stream(self):
        self.mock.queue(text("поточный ответ модели"))
        status, headers, data = self.post("/v1/chat/completions", {
            "model": "auto", "messages": [{"role": "user", "content": "расскажи"}],
            "stream": True,
        })
        self.assertEqual(status, 200)
        self.assertIn("text/event-stream", headers["content-type"])
        events = sse_events(data)
        payloads = [e for _name, e in events if isinstance(e, dict)]
        self.assertEqual(payloads[0]["choices"][0]["delta"]["role"], "assistant")
        joined = "".join(p["choices"][0]["delta"].get("content") or "" for p in payloads)
        self.assertEqual(joined, "поточный ответ модели")
        self.assertEqual(payloads[-1]["choices"][0]["finish_reason"], "stop")
        self.assertEqual(events[-1][1], "[DONE]")

    def test_stream_with_usage_option(self):
        self.mock.queue(text("ответ"))
        _s, _h, data = self.post("/v1/chat/completions", {
            "model": "auto", "messages": [{"role": "user", "content": "расскажи"}],
            "stream": True, "stream_options": {"include_usage": True}})
        events = sse_events(data)
        with_usage = [e for _n, e in events if isinstance(e, dict) and e.get("usage")]
        self.assertTrue(with_usage)
        self.assertGreater(with_usage[0]["usage"]["total_tokens"], 0)

    def test_stream_with_tool_calls(self):
        self.mock.queue(tool(call("write", path="a.txt", content="данные")), text("готово"))
        _s, _h, data = self.post("/v1/chat/completions", {
            "model": "auto", "messages": [{"role": "user", "content": "создай"}],
            "stream": True, "tools": [{"type": "function", "function": {
                "name": "write", "parameters": {"type": "object"}}}]})
        events = sse_events(data)
        calls = [e for _n, e in events
                 if isinstance(e, dict) and e["choices"][0]["delta"].get("tool_calls")]
        self.assertTrue(calls)
        self.assertEqual(calls[-1]["choices"][0]["delta"]["tool_calls"][0]["function"]["name"],
                         "write")
        finishes = [e["choices"][0]["finish_reason"] for _n, e in events
                    if isinstance(e, dict) and e.get("choices")]
        self.assertIn("tool_calls", finishes)

    def test_cyrillic_round_trip(self):
        self.mock.queue(text("ответ на русском — всё хорошо"))
        _s, body = self.json_post("/v1/chat/completions", {
            "model": "auto",
            "messages": [{"role": "user", "content": "напиши по-русски"}]})
        self.assertIn("всё хорошо", body["choices"][0]["message"]["content"])


class TestAnthropicEndpoint(RouterCase):
    def test_messages(self):
        self.mock.queue(text("сделано"))
        status, body = self.json_post("/v1/messages", {
            "model": "claude-sonnet-4-6",
            "system": "ты агент",
            "messages": [{"role": "user", "content": "почини"}],
            "max_tokens": 300,
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["type"], "message")
        self.assertEqual(body["role"], "assistant")
        self.assertEqual(body["content"][0]["text"], "сделано")
        self.assertEqual(body["stop_reason"], "end_turn")
        self.assertIn("input_tokens", body["usage"])

    def test_messages_with_tools(self):
        self.mock.queue(tool(call("grep", pattern="TODO")), text("нашёл"))
        _s, body = self.json_post("/v1/messages", {
            "model": "auto",
            "messages": [{"role": "user", "content": "найди TODO"}],
            "max_tokens": 300,
            "tools": [{"name": "grep", "description": "поиск",
                       "input_schema": {"type": "object"}}],
        })
        block = [b for b in body["content"] if b["type"] == "tool_use"][0]
        self.assertEqual(block["name"], "grep")
        self.assertEqual(block["input"], {"pattern": "TODO"})
        self.assertEqual(body["stop_reason"], "tool_use")

    def test_messages_tool_result_history(self):
        self.mock.queue(text("продолжаем"))
        _s, body = self.json_post("/v1/messages", {
            "model": "auto",
            "messages": [
                {"role": "user", "content": "прочитай a.py"},
                {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "t1", "name": "read", "input": {"path": "a.py"}}]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": "print(1)"}]},
            ],
            "max_tokens": 200,
        })
        self.assertEqual(body["content"][0]["text"], "продолжаем")
        sent = self.mock.payloads()[-1]
        self.assertEqual(sent["messages"][1]["content"][0]["type"], "tool_use")
        self.assertEqual(sent["messages"][2]["content"][0]["type"], "tool_result")

    def test_messages_stream(self):
        self.mock.queue(text("поток антропик"))
        status, headers, data = self.post("/v1/messages", {
            "model": "auto", "messages": [{"role": "user", "content": "расскажи"}],
            "max_tokens": 200, "stream": True})
        self.assertEqual(status, 200)
        self.assertIn("text/event-stream", headers["content-type"])
        events = sse_events(data)
        names = [name for name, _data in events if name]
        self.assertEqual(names[0], "message_start")
        self.assertIn("content_block_delta", names)
        self.assertEqual(names[-1], "message_stop")
        text_pieces = [d["delta"]["text"] for _n, d in events
                       if isinstance(d, dict) and d.get("type") == "content_block_delta"]
        self.assertEqual("".join(text_pieces), "поток антропик")
        deltas = [d for _n, d in events
                  if isinstance(d, dict) and d.get("type") == "message_delta"]
        self.assertEqual(deltas[0]["delta"]["stop_reason"], "end_turn")

    def test_messages_stream_with_tools(self):
        self.mock.queue(tool(call("ls", path=".")), text("готово"))
        _s, _h, data = self.post("/v1/messages", {
            "model": "auto", "messages": [{"role": "user", "content": "покажи файлы"}],
            "max_tokens": 200, "stream": True,
            "tools": [{"name": "ls", "input_schema": {"type": "object"}}]})
        events = sse_events(data)
        starts = [d for _n, d in events
                  if isinstance(d, dict) and d.get("type") == "content_block_start"]
        kinds = [s["content_block"]["type"] for s in starts]
        self.assertIn("tool_use", kinds)
        tool_block = [s["content_block"] for s in starts if s["content_block"]["type"] == "tool_use"][0]
        self.assertEqual(tool_block["name"], "ls")
        json_deltas = [d["delta"]["partial_json"] for _n, d in events
                       if isinstance(d, dict) and d.get("type") == "content_block_delta"
                       and d["delta"].get("type") == "input_json_delta"]
        self.assertEqual(json.loads("".join(json_deltas)), {"path": "."})
        stops = [d for _n, d in events
                 if isinstance(d, dict) and d.get("type") == "message_delta"]
        self.assertEqual(stops[0]["delta"]["stop_reason"], "tool_use")


class TestAccountingAndErrors(RouterCase):
    def test_spend_is_recorded_with_multiplier(self):
        self.mock.queue(text("ответ"))
        self.json_post("/v1/chat/completions", {
            "model": "gpt-5.6-luna",
            "messages": [{"role": "user", "content": "привет"}]})
        self.assertEqual(self.stack.state.tokens_day,
                         self.stack.state.by_model()["gpt-5.6-luna"]["tokens"])
        self.assertGreater(self.stack.state.tokens_day, 0)
        self.assertEqual(self.stack.state.requests_day, 1)

    def test_router_and_console_share_state(self):
        self.mock.queue(text("через роутер"), text("через консоль"))
        self.json_post("/v1/chat/completions", {
            "model": "auto", "messages": [{"role": "user", "content": "раз"}]})
        after_router = self.stack.state.tokens_day
        self.stack.agent.run_task("два")
        self.assertGreater(self.stack.state.tokens_day, after_router)

    def test_gateway_error_is_502(self):
        self.mock.fail_with = (500, "шлюз лёг")
        self.mock.fail_once = False
        self.mock.queue(text("не дойдёт"))
        status, body = self.json_post("/v1/chat/completions", {
            "model": "auto", "messages": [{"role": "user", "content": "привет"}]})
        self.assertEqual(status, 502)
        self.assertIn("error", body)
        self.assertTrue(body["error"]["message"])

    def test_rate_limit_is_429(self):
        self.mock.fail_with = (429, "too many requests")
        self.mock.fail_once = False
        status, body = self.json_post("/v1/chat/completions", {
            "model": "auto", "messages": [{"role": "user", "content": "привет"}]})
        self.assertEqual(status, 429)
        self.assertEqual(body["error"]["code"], 429)

    def test_anthropic_error_shape(self):
        self.mock.fail_with = (500, "шлюз лёг")
        self.mock.fail_once = False
        status, body = self.json_post("/v1/messages", {
            "model": "auto", "messages": [{"role": "user", "content": "привет"}],
            "max_tokens": 100})
        self.assertEqual(status, 502)
        self.assertEqual(body["type"], "error")
        self.assertEqual(body["error"]["type"], "api_error")

    def test_daily_limit_blocks_request(self):
        self.stack.gw.daily_limit = 10
        self.router_gateway.daily_limit = 10
        self.stack.state.record("claude-sonnet-4-6", 100, 100, 2.0)
        status, body = self.json_post("/v1/chat/completions", {
            "model": "auto", "messages": [{"role": "user", "content": "привет"}]})
        self.assertEqual(status, 502)
        self.assertIn("лимит", body["error"]["message"].lower())

    def test_stream_error_is_reported_inside_stream(self):
        self.mock.fail_with = (500, "шлюз лёг")
        self.mock.fail_once = False
        _s, _h, data = self.post("/v1/chat/completions", {
            "model": "auto", "messages": [{"role": "user", "content": "привет"}],
            "stream": True})
        events = sse_events(data)
        errors = [e for _n, e in events if isinstance(e, dict) and e.get("error")]
        self.assertTrue(errors, f"события: {events}")
        self.assertEqual(events[-1][1], "[DONE]")

    def test_unknown_model_falls_back(self):
        """Редактор прислал имя, которого нет в каталоге, — расход считаем как ×1."""
        self.mock.queue(text("ответ"))
        self.json_post("/v1/chat/completions", {
            "model": "какая-то-модель",
            "messages": [{"role": "user", "content": "привет"}]})
        self.assertEqual(self.mock.payloads()[-1]["model"], "какая-то-модель")
        status, _h, data = self.get("/status.json")
        self.assertEqual(status, 200)
        self.assertIn("какая-то-модель", json.loads(data)["by_model"])


class TestServerLifecycle(RouterCase):
    def test_serve_in_thread_reports_bound_port(self):
        self.assertRegex(self.url, r"^http://127\.0\.0\.1:[1-9]\d*$")
        self.assertTrue(self.thread.is_alive())
        self.assertEqual(self.get("/health")[0], 200)

    def test_router_has_own_gateway_client(self):
        """Стриминг редактора не должен мешать запросам консоли."""
        self.assertIsNot(self.router_gateway, self.stack.gw)
        self.assertEqual(self.router_gateway.key, self.stack.gw.key)

    def test_parallel_requests(self):
        for _ in range(4):
            self.mock.queue(text("ответ"))
        results = []
        errors = []

        def worker():
            try:
                status, body = self.json_post("/v1/chat/completions", {
                    "model": "auto",
                    "messages": [{"role": "user", "content": "привет"}]})
                results.append((status, body["choices"][0]["message"]["content"]))
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 4)
        self.assertTrue(all(status == 200 for status, _ in results))
        self.assertEqual(self.stack.state.requests_day, 4)

    def test_keep_alive_connection(self):
        """Одно соединение — несколько запросов: редакторы держат его открытым."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        try:
            for _ in range(3):
                conn.request("GET", "/health")
                resp = conn.getresponse()
                self.assertEqual(resp.status, 200)
                resp.read()
        finally:
            conn.close()

    def test_shutdown_stops_server(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.assertFalse(self.thread.is_alive())
        with self.assertRaises(OSError):
            self.get("/health", timeout=2)
        # tearDown повторит shutdown — он должен быть безопасным
        self.httpd = type("Stub", (), {"shutdown": lambda self: None,
                                       "server_close": lambda self: None})()


if __name__ == "__main__":
    unittest.main(verbosity=2)
