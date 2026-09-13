#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты проверяльщика ключей: поднимаем фальшивые шлюзы, каждый со своим «грехом»,
и убеждаемся, что tools/check_api_key.py его ловит.

Запуск: python tests/test_checker.py

Фальшивые шлюзы:
  honest   — честный: ничего не подменяет (проверяльщик не должен ругаться)
  swap     — подменяет модель на дешёвую
  inflate  — завышает расход токенов в 6 раз («коэффициенты»)
  pool     — общий пул: 429 на параллельные запросы
  truncate — молча режет контекст
  leak     — отдаёт в ошибках следы upstream-посредника
  notools  — не умеет tool calling (агенту это критично)
"""

import contextlib
import io
import json
import os
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import check_api_key as cak  # noqa: E402

CONFIG: dict = {}          # port -> dict настроек фальшивого шлюза
ACTIVE: dict = {}          # port -> текущее число одновременных запросов
LOCK = threading.Lock()

FILLER = cak.FILLER
NEEDLE = cak.NEEDLE


def conf(port):
    return CONFIG.get(port, {})


class FakeGateway(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    # --- ответы ---

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        port = self.server.server_address[1]
        c = conf(port)
        if self.path.endswith("/models"):
            models = ["claude-opus-5", "gpt-6-astra", "deepseek-v4-flash-free", "another-model"]
            if c.get("swap_to"):
                models = [c["swap_to"], "cheap-model"]
            return self._json(200, {"object": "list",
                                    "data": [{"id": m, "object": "model"} for m in models]})
        if self.path in ("/credits", "/balance"):
            return self._json(200, {"balance": 100000, "currency": "tokens"})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        port = self.server.server_address[1]
        c = conf(port)
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")

        with LOCK:
            ACTIVE[port] = ACTIVE.get(port, 0) + 1
            current = ACTIVE[port]
        try:
            if c.get("delay"):
                time.sleep(c["delay"])
            limit = c.get("concurrency_limit")
            if limit and current > limit:
                return self._json(429, {"error": {"message": "Rate limit exceeded"}})

            if c.get("leak_error") and body.get("temperature") not in (None, 0.2, 1.0):
                return self._json(400, {"error": {
                    "message": "invalid temperature for opencode.ai/zen/v1 account acc_9f83b2",
                    "type": "invalid_request_error"}})

            if c.get("no_tools") and body.get("tools"):
                return self._json(400, {"error": {"message": "tools are not supported"}})

            messages = body.get("messages") or []
            model_requested = body.get("model")
            answers = [m for m in messages if m.get("role") == "assistant"]
            last_user = ""
            for m in reversed(messages):
                if m.get("role") == "user":
                    last_user = m.get("content") or ""
                    break
            if not isinstance(last_user, str):
                last_user = json.dumps(last_user, ensure_ascii=False)

            # усечение контекста
            if c.get("truncate_chars"):
                last_user = last_user[: c["truncate_chars"]]

            # поток
            if body.get("stream"):
                return self._stream(model_requested, c)

            # tools
            if body.get("tools") and not any(m.get("role") == "tool" for m in messages):
                msg = {"role": "assistant", "content": None, "tool_calls": [{
                    "id": "call_1", "type": "function",
                    "function": {"name": "read_file", "arguments": json.dumps({"path": "main.py"})}}]}
                return self._completion(model_requested, c, msg, 40, 15)

            # содержимое ответа
            if NEEDLE in last_user:
                content = "МАЯК-7F3A2B-КВАРЦ"
            elif "какая ты модель" in last_user.lower():
                content = c.get("identity", "Я Claude Opus 5 от Anthropic.")
            elif "кодовое слово" in last_user.lower():
                content = "не знаю"
            else:
                content = "OK"

            msg = {"role": "assistant", "content": content}
            prompt_tokens = cak.est_tokens(last_user) + 12
            if c.get("inflate"):
                prompt_tokens = int(prompt_tokens * c["inflate"])
            return self._completion(model_requested, c, msg, prompt_tokens, 20)

        finally:
            with LOCK:
                ACTIVE[port] = max(0, ACTIVE.get(port, 1) - 1)

    def _completion(self, model_requested, c, message, prompt_tokens, completion_tokens):
        model_field = c.get("swap_to") or model_requested
        return self._json(200, {
            "id": "chatcmpl-fake", "object": "chat.completion", "created": int(time.time()),
            "model": model_field,
            "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                      "total_tokens": prompt_tokens + completion_tokens},
        })

    def _stream(self, model_requested, c):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for piece in ("Считаю", ": один, два"):
            chunk = json.dumps({"choices": [{"delta": {"content": piece}}],
                                "model": c.get("swap_to") or model_requested}).encode()
            data = b"data: " + chunk + b"\n\n"
            self.wfile.write(b"%x\r\n" % len(data) + data + b"\r\n")
            self.wfile.flush()
        usage = json.dumps({"choices": [], "usage": {"prompt_tokens": 9, "completion_tokens": 4}}).encode()
        data = b"data: " + usage + b"\n\n"
        self.wfile.write(b"%x\r\n" % len(data) + data + b"\r\n")
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()


class CheckerTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ThreadingHTTPServer.allow_reuse_address = True
        cls.servers = {}
        cls.ports = {}
        for i, name in enumerate(["honest", "swap", "inflate", "pool", "truncate", "leak", "notools"]):
            port = 18300 + i
            srv = ThreadingHTTPServer(("127.0.0.1", port), FakeGateway)
            srv.daemon_threads = True
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            cls.servers[name] = srv
            cls.ports[name] = port
        CONFIG.update({
            cls.ports["honest"]: {},
            cls.ports["swap"]: {"swap_to": "deepseek-v4-flash-free",
                                "identity": "Я DeepSeek V3, разработана DeepSeek."},
            cls.ports["inflate"]: {"inflate": 6.0},
            cls.ports["pool"]: {"concurrency_limit": 2, "delay": 0.5},
            cls.ports["truncate"]: {"truncate_chars": 400},
            cls.ports["leak"]: {"leak_error": True},
            cls.ports["notools"]: {"no_tools": True},
        })

    @classmethod
    def tearDownClass(cls):
        for srv in cls.servers.values():
            srv.shutdown()
            srv.server_close()

    def check(self, name, model="claude-opus-5", claimed=None, price=None,
              parallel=5, skip_heavy=False):
        port = self.ports[name]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            report = cak.run_check(f"http://127.0.0.1:{port}/v1", "test-key", model,
                                   claimed, price, parallel, skip_heavy)
        return report

    @staticmethod
    def status_of(report, name_part):
        for r in report["results"]:
            if name_part.lower() in r["name"].lower():
                return r["status"], r["detail"]
        return None, ""


class TestHonestGateway(CheckerTestBase):
    def test_no_failures(self):
        report = self.check("honest", claimed=8_000_000, price=None)
        fails = [r for r in report["results"] if r["status"] == "FAIL"]
        self.assertEqual([], [f["name"] for f in fails],
                         f"честный шлюз не должен получать FAIL: {fails}")

    def test_tools_and_stream_pass(self):
        report = self.check("honest")
        self.assertEqual(self.status_of(report, "Tool calling")[0], "OK")
        self.assertEqual(self.status_of(report, "Стриминг")[0], "OK")


class TestModelSwap(CheckerTestBase):
    def test_swap_detected(self):
        report = self.check("swap")
        st, detail = self.status_of(report, "Подмена модели")
        self.assertEqual(st, "FAIL", f"подмена не поймана: {detail}")
        self.assertIn("deepseek-v4-flash-free", detail)

    def test_cheap_identity_flagged(self):
        report = self.check("swap")
        st, detail = self.status_of(report, "Самоидентификация")
        self.assertEqual(st, "WARN")
        self.assertIn("другой семьёй", detail)


class TestTokenInflation(CheckerTestBase):
    def test_inflation_detected(self):
        report = self.check("inflate")
        st, detail = self.status_of(report, "Честность учёта")
        self.assertEqual(st, "FAIL", f"завышение расхода не поймано: {detail}")
        self.assertIn("коэффициент", detail.lower())


class TestSharedPool(CheckerTestBase):
    def test_pool_detected(self):
        """Реалистичный случай: шлюз отвечает с задержкой, пул на 2 запроса."""
        report = self.check("pool", skip_heavy=False)
        st, detail = self.status_of(report, "Поведение под нагрузкой")
        self.assertEqual(st, "FAIL", f"общий пул не пойман: {detail}")

    def test_pool_spot_visible_in_detail(self):
        report = self.check("pool", skip_heavy=False)
        _, detail = self.status_of(report, "Поведение под нагрузкой")
        self.assertIn("429", detail)


class TestTruncation(CheckerTestBase):
    def test_truncation_warned(self):
        report = self.check("truncate")
        results = [r for r in report["results"] if "Контекст" in r["name"]]
        self.assertTrue(results, "тесты контекста не выполнились")
        self.assertTrue(any(r["status"] == "WARN" for r in results),
                        f"усечение контекста не поймано: {results}")


class TestErrorLeak(CheckerTestBase):
    def test_leak_warned(self):
        report = self.check("leak", skip_heavy=True)
        st, detail = self.status_of(report, "Утечки")
        self.assertEqual(st, "WARN", f"следы посредника не найдены: {detail}")
        self.assertIn("opencode", detail.lower())


class TestNoTools(CheckerTestBase):
    def test_missing_tools_flagged(self):
        report = self.check("notools", skip_heavy=True)
        st, detail = self.status_of(report, "Tool calling")
        self.assertEqual(st, "FAIL", f"отсутствие tools не поймано: {detail}")


class TestEconomics(CheckerTestBase):
    def test_impossible_price_flagged(self):
        out = cak.economics("claude-opus-5", 8_000_000, 20.0)
        self.assertEqual(out[0].status, "FAIL")
        self.assertIn("себестоимости", out[0].detail)

    def test_realistic_price_not_flagged_hard(self):
        # $10 за 1M токенов по официальной цене — не повод ругаться (это нормальная цена)
        out = cak.economics("deepseek-chat", 1_000_000, 800.0)
        self.assertIn(out[0].status, ("WARN", "OK"))

    def test_needle_detected_e2e(self):
        """Полный прогон на честном шлюзе: кодовое слово должно находиться."""
        report = self.check("honest")
        results = [r for r in report["results"] if "Контекст" in r["name"]]
        self.assertTrue(all(r["status"] == "OK" for r in results), results)


class FakeAnthropicGateway(BaseHTTPRequestHandler):
    """Шлюз только в формате Anthropic: /v1/messages, блоки content, usage по-своему."""

    protocol_version = "HTTP/1.1"
    calls = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        return self._json(404, {"error": {"message": "no models endpoint"}})

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        FakeAnthropicGateway.calls.append({"path": self.path, "body": body,
                                           "headers": dict(self.headers)})
        if not self.path.endswith("/messages"):
            return self._json(404, {"error": {"message": "use /v1/messages"}})
        text = "".join(b.get("text", "") for m in (body.get("messages") or [])
                       for b in (m.get("content") or []) if isinstance(b, dict))
        content = [{"type": "text", "text": "OK"}]
        if cak.NEEDLE in text:
            content = [{"type": "text", "text": "МАЯК-7F3A2B-КВАРЦ"}]
        if body.get("tools") and not any(m.get("role") == "user" and isinstance(m.get("content"), list)
                                         and m["content"] and m["content"][0].get("type") == "tool_result"
                                         for m in body["messages"]):
            content = [{"type": "tool_use", "id": "toolu_9", "name": "read_file",
                        "input": {"path": "main.py"}}]
            stop = "tool_use"
        else:
            stop = "end_turn"
        return self._json(200, {
            "id": "msg_x", "type": "message", "role": "assistant", "model": body.get("model"),
            "content": content, "stop_reason": stop,
            "usage": {"input_tokens": 100, "output_tokens": 30},
        })


class TestAnthropicFormat(CheckerTestBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ThreadingHTTPServer.allow_reuse_address = True
        cls.anth = ThreadingHTTPServer(("127.0.0.1", 18310), FakeAnthropicGateway)
        cls.anth.daemon_threads = True
        threading.Thread(target=cls.anth.serve_forever, daemon=True).start()
        cls.anth_port = 18310

    @classmethod
    def tearDownClass(cls):
        cls.anth.shutdown()
        cls.anth.server_close()
        super().tearDownClass()

    def test_anthropic_gateway_checked_end_to_end(self):
        FakeAnthropicGateway.calls = []
        report = cak.run_check(f"http://127.0.0.1:{self.anth_port}", "sk-smart-test",
                               "sonnet-4.6", None, None, parallel=2, skip_heavy=True,
                               api_format="anthropic")
        statuses = {r["name"]: r["status"] for r in report["results"]}
        self.assertEqual(statuses.get("Базовый запрос"), "OK", report["results"])
        self.assertEqual(statuses.get("Tool calling (нужен агентам)"), "OK")
        self.assertIn("Протокол role=tool", statuses)
        call = FakeAnthropicGateway.calls[0]
        self.assertTrue(call["path"].endswith("/v1/messages"), call["path"])
        lower = {k.lower(): v for k, v in call["headers"].items()}
        self.assertEqual(lower.get("x-api-key"), "sk-smart-test")

    def test_anthropic_needle_found(self):
        report = cak.run_check(f"http://127.0.0.1:{self.anth_port}", "k", "sonnet-4.6",
                               None, None, parallel=2, skip_heavy=False, api_format="anthropic")
        ctx = [r for r in report["results"] if "Контекст" in r["name"]]
        self.assertTrue(ctx)
        self.assertTrue(all(r["status"] == "OK" for r in ctx), ctx)


if __name__ == "__main__":
    unittest.main(verbosity=2)
