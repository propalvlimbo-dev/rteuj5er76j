#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты шлюза: форматы запросов, потоковый вывод, отказоустойчивость, учёт расхода.

Запуск:  python dev/tests/test_gateway.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mockapi import MockGateway, call, text, tool  # noqa: E402

from elytrix.config import Catalog, Config, State  # noqa: E402
from elytrix.gateway import (AuthError, Cancelled, DailyLimitError, GatewayError,  # noqa: E402
                             SmartAPI, estimate_tokens, messages_tokens, system_to_text,
                             to_openai)

MODEL = "claude-sonnet-4-6"
SYSTEM = "Ты тестовый агент."
USER = [{"role": "user", "content": [{"type": "text", "text": "сделай что-нибудь"}]}]
TOOLS = [{"name": "read", "description": "читать", "input_schema": {"type": "object",
                                                                    "properties": {}}}]


class GatewayCase(unittest.TestCase):
    """Общий стенд: свой временный профиль, конфиг на mock-шлюз, свежий клиент."""

    def setUp(self) -> None:
        self.home = tempfile.mkdtemp(prefix="elytrix-test-")
        os.environ["ELYTRIX_HOME"] = self.home
        os.environ["SMARTAPI_KEY"] = "sk-smart-test-key"
        self.mock = MockGateway().start()
        self.cfg = Config({
            "gateway": {"base_url": self.mock.base_url, "openai_base_url": self.mock.openai_url,
                        "timeout": 10, "connect_timeout": 5},
            "limits": {"daily_tokens": 100000, "max_output_tokens": 1024},
            "economy": {"cache": True},
            "ui": {"stream": True},
        })
        self.catalog = Catalog(dict(self.cfg.get("models")))
        self.state = State()
        self.gw = SmartAPI(self.cfg, self.catalog, self.state, key="sk-smart-test-key")

    def tearDown(self) -> None:
        self.gw.close()
        self.mock.stop()
        shutil.rmtree(self.home, ignore_errors=True)
        os.environ.pop("ELYTRIX_HOME", None)

    def chat(self, **kw):
        params = {"model": MODEL, "system": SYSTEM, "messages": [dict(m) for m in USER],
                  "tools": TOOLS, "stream": False}
        params.update(kw)
        return self.gw.chat(**params)


class TestFormats(GatewayCase):
    def test_anthropic_plain_text(self):
        self.mock.queue(text("готово", tokens_in=500, tokens_out=40))
        turn = self.chat()
        self.assertEqual(turn.text, "готово")
        self.assertEqual(turn.endpoint, "anthropic")
        self.assertEqual(turn.tool_calls, [])
        self.assertEqual(turn.usage.tokens_in, 500)
        self.assertEqual(turn.usage.tokens_out, 40)
        payload = self.mock.last["payload"]
        self.assertEqual(payload["model"], MODEL)
        self.assertEqual(system_to_text(payload["system"]), SYSTEM)
        self.assertEqual(payload["max_tokens"], 1024)

    def test_anthropic_stream_text(self):
        self.mock.queue(text("ответ собирается по кускам", tokens_in=300, tokens_out=25))
        pieces = []
        turn = self.chat(stream=True, on_text=pieces.append)
        self.assertEqual(turn.text, "ответ собирается по кускам")
        self.assertGreater(len(pieces), 1, "поток должен приходить частями")
        self.assertEqual("".join(pieces), turn.text)
        self.assertEqual(turn.usage.tokens_out, 25)
        self.assertGreater(turn.usage.ttfb, 0.0)

    def test_anthropic_stream_tool_calls(self):
        self.mock.queue(tool(call("read", path="main.py"), call("grep", pattern="TODO"),
                             thought="смотрим"))
        announced = []
        turn = self.chat(stream=True, on_tool=lambda name, info: announced.append(name))
        self.assertEqual([c.name for c in turn.tool_calls], ["read", "grep"])
        self.assertEqual(turn.tool_calls[0].args, {"path": "main.py"})
        self.assertEqual(turn.tool_calls[1].args, {"pattern": "TODO"})
        self.assertEqual(turn.stop_reason, "tool_use")
        self.assertIn("read", announced)
        self.assertTrue(all(c.id for c in turn.tool_calls), "у tool_use должен быть id")

    def test_openai_fallback_payload(self):
        """Anthropic-адрес не отвечает — уходим в OpenAI-формат и переводим запрос."""
        self.mock.anthropic_status = 500
        self.mock.queue(text("через запасной формат"))
        turn = self.chat()
        self.assertEqual(turn.text, "через запасной формат")
        self.assertEqual(turn.endpoint, "openai")
        oai = [p for p in self.mock.payloads() if p.get("messages")
               and isinstance(p["messages"][0].get("content"), str)]
        self.assertTrue(oai, "должен быть запрос в формате OpenAI")
        payload = oai[-1]
        self.assertEqual(payload["messages"][0], {"role": "system", "content": SYSTEM})
        self.assertEqual(payload["tools"][0]["type"], "function")
        self.assertEqual(payload["tools"][0]["function"]["name"], "read")

    def test_openai_stream_with_tool_calls(self):
        self.mock.anthropic_status = 503
        self.mock.queue(tool(call("write", path="a.txt", content="привет"), thought="пишу"))
        turn = self.chat(stream=True)
        self.assertEqual(turn.endpoint, "openai")
        self.assertEqual(turn.tool_calls[0].name, "write")
        self.assertEqual(turn.tool_calls[0].args, {"path": "a.txt", "content": "привет"})

    def test_to_openai_conversion(self):
        messages = [
            {"role": "user", "content": [{"type": "text", "text": "задача"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "ок"},
                                              {"type": "tool_use", "id": "c1", "name": "read",
                                               "input": {"path": "a.py"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1",
                                          "content": "содержимое"}]},
        ]
        payload = to_openai("система", messages, TOOLS, 100, 0.1)
        roles = [m["role"] for m in payload["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant", "tool"])
        self.assertEqual(payload["messages"][2]["tool_calls"][0]["id"], "c1")
        self.assertEqual(payload["messages"][3]["tool_call_id"], "c1")


class TestPromptCache(GatewayCase):
    def test_cache_marks_are_sent(self):
        self.mock.queue(text("ок"))
        messages = [dict(USER[0]) for _ in range(4)]
        self.chat(messages=messages)
        payload = self.mock.last["payload"]
        self.assertIsInstance(payload["system"], list, "system должен быть блоками с cache_control")
        self.assertEqual(payload["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(payload["tools"][-1]["cache_control"], {"type": "ephemeral"})
        marked = [b for m in payload["messages"] for b in (m.get("content") or [])
                  if isinstance(b, dict) and b.get("cache_control")]
        self.assertTrue(marked, "префикс диалога тоже должен быть помечен")

    def test_cache_disabled_by_config(self):
        self.gw.cache_enabled = False
        self.mock.queue(text("ок"))
        self.chat()
        payload = self.mock.last["payload"]
        self.assertEqual(payload["system"], SYSTEM)
        self.assertNotIn("cache_control", json.dumps(payload))

    def test_cache_rejected_by_gateway(self):
        """Шлюз не понимает cache_control — отключаем пометки и повторяем без них."""
        self.mock.reject_cache = True
        self.mock.queue(text("дошло без кэша"))
        turn = self.chat()
        self.assertEqual(turn.text, "дошло без кэша")
        self.assertFalse(self.gw.cache_supported)
        self.assertFalse(turn.cache_enabled)
        payload = self.mock.last["payload"]
        self.assertNotIn("cache_control", json.dumps(payload))

    def test_cache_read_tokens_are_counted(self):
        self.mock.queue(text("ок", tokens_in=100, tokens_out=10, cache_read=5000))
        turn = self.chat()
        self.assertEqual(turn.usage.cache_read, 5000)
        self.assertEqual(self.gw.session.cache_read, 5000)
        self.assertEqual(turn.usage.tokens_in, 5100, "кэш-чтение входит в объём входа")


class TestResilience(GatewayCase):
    def test_auth_error(self):
        self.mock.fail_with = (401, "invalid api key")
        with self.assertRaises(AuthError) as ctx:
            self.chat()
        self.assertIn("smartapi.shop/api-keys", str(ctx.exception))

    def test_model_not_found_message(self):
        self.mock.unknown_model = True
        self.mock.catalog = ["other-model"]
        with self.assertRaises(GatewayError) as ctx:
            self.chat(model="gpt-5.6-luna")
        self.assertIn("/model", str(ctx.exception))

    def test_retry_once_on_500(self):
        self.mock.fail_with = (500, "внутренняя ошибка шлюза")
        self.mock.fail_once = True
        self.mock.queue(text("со второй попытки"))
        turn = self.chat()
        self.assertEqual(turn.text, "со второй попытки")
        self.assertEqual(len(self.mock.requests), 2)

    def test_429_sets_cooldown(self):
        self.mock.fail_with = (429, "too many requests")
        self.mock.fail_once = False
        with self.assertRaises(GatewayError):
            self.chat()
        self.assertGreater(self.gw.cooldown_until, 0)
        with self.assertRaises(GatewayError) as ctx:
            self.chat()
        self.assertIn("пауз", str(ctx.exception))

    def test_broken_stream_is_tolerated(self):
        self.mock.cut_stream = True
        with self.assertRaises(GatewayError):
            self.chat(stream=True)

    def test_cancel_stops_request(self):
        self.mock.stall = 0.4
        self.mock.queue(text("не должно дойти"))
        cancel = threading.Event()
        threading.Timer(0.05, cancel.set).start()
        with self.assertRaises(Cancelled):
            self.chat(stream=True, cancel=cancel)


class TestAccounting(GatewayCase):
    def test_daily_spend_with_multiplier(self):
        self.mock.queue(text("ок", tokens_in=1000, tokens_out=200))
        self.chat()
        mult = self.catalog.multiplier(MODEL)
        self.assertEqual(mult, 2.0)
        self.assertEqual(self.state.tokens_day, int(1200 * mult))
        self.assertEqual(self.state.requests_day, 1)
        self.assertEqual(self.gw.session.charged, int(1200 * mult))

    def test_daily_limit_blocks_before_request(self):
        self.state.data["tokens_day"] = 100000
        self.mock.queue(text("не должно дойти"))
        with self.assertRaises(DailyLimitError):
            self.chat()
        self.assertEqual(len(self.mock.requests), 0, "запрос не должен уходить в сеть")

    def test_daily_limit_message_mentions_command(self):
        self.gw.daily_limit = 10
        self.state.data["tokens_day"] = 11
        with self.assertRaises(DailyLimitError) as ctx:
            self.chat()
        self.assertIn("/limit", str(ctx.exception))

    def test_limit_can_be_lifted(self):
        self.gw.daily_limit = 10
        self.state.data["tokens_day"] = 11
        self.gw.daily_limit = 0
        self.mock.queue(text("теперь можно"))
        self.assertEqual(self.chat().text, "теперь можно")

    def test_state_persists_between_clients(self):
        self.mock.queue(text("ок", tokens_in=100, tokens_out=10))
        self.chat()
        again = State()
        self.assertEqual(again.tokens_day, self.state.tokens_day)
        self.assertIn(MODEL, again.by_model())

    def test_day_rollover_resets_spend(self):
        self.mock.queue(text("ок", tokens_in=100, tokens_out=10))
        self.chat()
        self.state.data["day"] = "2000-01-01"
        self.state.save()
        fresh = State()
        self.assertEqual(fresh.tokens_day, 0)
        self.assertTrue(fresh.history(), "вчерашний расход остаётся в истории")


class TestCatalogAndProbe(GatewayCase):
    def test_fetch_models_adds_unknown(self):
        ids = self.gw.fetch_models(timeout=5)
        self.assertIn(MODEL, ids)
        added = self.catalog.add_models(ids)
        self.assertEqual(added, 1, "mock-unknown-model должен добавиться в меню")

    def test_probe_ok(self):
        self.mock.queue(text("OK"))
        ok, detail = self.gw.probe(MODEL, max_tokens=8)
        self.assertTrue(ok)
        self.assertEqual(detail, "OK")

    def test_probe_reports_error(self):
        self.mock.fail_with = (401, "bad key")
        self.mock.fail_once = False
        ok, detail = self.gw.probe(MODEL)
        self.assertFalse(ok)
        self.assertTrue(detail)

    def test_alias_resolution(self):
        self.assertEqual(self.catalog.resolve("auto"), MODEL)
        self.assertEqual(self.catalog.resolve("cheap"), "gpt-5.6-luna")
        self.assertEqual(self.catalog.resolve("gpt-6-astra"), "gpt-6-astra")
        self.assertEqual(self.catalog.multiplier("claude-fable-5"), 10.0)
        self.assertEqual(self.catalog.family("gpt-5.6-luna"), "GPT")


class TestTokenEstimate(unittest.TestCase):
    def test_latin_and_cyrillic(self):
        self.assertLess(estimate_tokens("a" * 400), estimate_tokens("ы" * 400))
        self.assertEqual(estimate_tokens(""), 0)
        self.assertEqual(estimate_tokens(None), 0)

    def test_messages_tokens_grow_with_history(self):
        small = messages_tokens(USER, SYSTEM, TOOLS)
        big = messages_tokens(USER * 5, SYSTEM, TOOLS)
        self.assertGreater(big, small)


if __name__ == "__main__":
    unittest.main(verbosity=2)
