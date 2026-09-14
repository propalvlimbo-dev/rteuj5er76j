#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты запускатора windows/launch.py: проверка связи с роутером, ожидание старта,
строка расхода (вместо веб-панели), выбор модели и папки проекта.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "windows"))

import launch  # noqa: E402


class FakeRouter(BaseHTTPRequestHandler):
    """Мини-роутер: /health и /status.json как у настоящего, но с заданными числами."""

    status = {"providers": [{
        "name": "smartapi", "kind": "anthropic",
        "limits": {"tpd": 400000},
        "keys": [{"index": 0, "tokens_day": 120000, "requests_day": 40}],
        "stats": {"requests": 42, "ok": 42, "fail": 0},
    }]}

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/health"):
            body = b'{"status": "ok"}'
        elif self.path.startswith("/status.json"):
            body = json.dumps(self.status).encode()
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


_server_lock = threading.Lock()
_server = None


def fake_router_port() -> int:
    """Один фейковый роутер на весь файл тестов (классы не переиспользуют порт)."""
    global _server
    with _server_lock:
        if _server is None:
            _server = ThreadingHTTPServer(("127.0.0.1", 0), FakeRouter)
            _server.daemon_threads = True
            threading.Thread(target=_server.serve_forever, daemon=True).start()
    return _server.server_address[1]


class LauncherTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = fake_router_port()

    @classmethod
    def tearDownClass(cls):
        pass


class TestHealthAndWait(LauncherTestBase):
    def test_health_true_when_router_up(self):
        self.assertTrue(launch.health_ok(self.port))

    def test_health_false_when_nothing_listens(self):
        self.assertFalse(launch.health_ok(18499, timeout=1))

    def test_wait_for_router_reports_ticks(self):
        ticks = []
        ok = launch.wait_for_router(self.port, timeout=5, on_tick=lambda s: ticks.append(s))
        self.assertTrue(ok)
        self.assertEqual(ticks, [], "если роутер уже отвечает, ждать не нужно")

    def test_wait_for_router_gives_up(self):
        calls = []
        ok = launch.wait_for_router(18498, timeout=2, on_tick=lambda s: calls.append(s))
        self.assertFalse(ok)
        self.assertTrue(calls, "должен сообщать, сколько ждёт")


class TestSpendLine(LauncherTestBase):
    """Расход показывается строкой в консоли — веб-панель для этого не нужна."""

    def test_spend_summary(self):
        line = launch.spend_summary(self.port)
        self.assertIn("120 000", line)
        self.assertIn("400 000", line)
        self.assertIn("30%", line)
        self.assertIn("запросов: 42", line)

    def test_spend_summary_without_router(self):
        self.assertEqual(launch.spend_summary(18497, timeout=1), "")

    def test_spend_ignores_mock_provider(self):
        old = FakeRouter.status
        try:
            FakeRouter.status = {"providers": [{
                "name": "mock", "kind": "mock", "limits": {"tpd": 100},
                "keys": [{"tokens_day": 50}], "stats": {"requests": 1}}]}
            self.assertEqual(launch.spend_summary(self.port), "")
        finally:
            FakeRouter.status = old


class TestPromptLogic(unittest.TestCase):
    def test_model_by_number(self):
        self.assertEqual(launch.ask_model(ask=lambda _: "2"), "smart")
        self.assertEqual(launch.ask_model(ask=lambda _: "4"), "cheap")
        self.assertEqual(launch.ask_model(ask=lambda _: "3"), "max")

    def test_model_enter_keeps_default(self):
        self.assertEqual(launch.ask_model(ask=lambda _: "", default="auto"), "auto")

    def test_model_accepts_exact_name(self):
        self.assertEqual(launch.ask_model(ask=lambda _: "smartapi/claude-opus-5"),
                         "smartapi/claude-opus-5")

    def test_workspace_uses_last_and_creates(self):
        tmp = tempfile.mkdtemp(prefix="fc-launch-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            # папка по умолчанию — домашняя, если ничего не помним
            self.assertEqual(launch.read_last_workspace(), "")
            missing = os.path.join(tmp, "проект")
            ws = launch.ask_workspace(ask=lambda prompt: missing if "Папка" in prompt else "y")
            self.assertEqual(ws, os.path.abspath(missing))
            self.assertTrue(os.path.isdir(missing))
            # в следующий раз предлагается именно она
            self.assertEqual(launch.read_last_workspace(), os.path.abspath(missing))
            again = launch.ask_workspace(ask=lambda prompt: "" if "Папка" in prompt else "")
            self.assertEqual(again, os.path.abspath(missing))

    def test_workspace_refuses_missing_folder_without_consent(self):
        tmp = tempfile.mkdtemp(prefix="fc-launch2-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        answers = iter([os.path.join(tmp, "нет"), "", tmp])
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            ws = launch.ask_workspace(ask=lambda _: next(answers))
        self.assertEqual(ws, os.path.abspath(tmp))


class TestRouterCommand(unittest.TestCase):
    def test_command_has_config_port_and_log(self):
        cmd = launch.router_command("/repo", "router/providers.smartapi.json", 8788, "/tmp/r.log")
        self.assertIn("--config", cmd)
        self.assertIn("8788", cmd)
        self.assertIn("--log-file", cmd)
        self.assertTrue(any(p.endswith("freecoder_router.py") for p in cmd))

    def test_log_tail_reads_last_lines(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = os.path.join(tmp, "log.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(f"строка {i}" for i in range(30)))
        tail = launch.log_tail(path, lines=3)
        self.assertIn("строка 29", tail)
        self.assertNotIn("строка 26", tail)

    def test_log_tail_missing_file(self):
        self.assertEqual(launch.log_tail("/tmp/нет-такого-файла-лог"), "")


class TestMainDryRun(unittest.TestCase):
    """Полный прогон: роутер уже отвечает (фейк), ключ задан, --no-agent."""

    def setUp(self):
        self.port = fake_router_port()

    def test_main_with_existing_router(self):
        tmp = tempfile.mkdtemp(prefix="fc-main-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with mock.patch.dict(os.environ, {"SMARTAPI_KEY": "sk-test", "LOCALAPPDATA": tmp}):
            code = launch.main(["--port", str(self.port), "--no-agent",
                                "--root", ROOT,
                                "--config", "router/providers.smartapi.json"])
        self.assertEqual(code, 0)

    def test_main_without_key_returns_error(self):
        tmp = tempfile.mkdtemp(prefix="fc-main2-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            os.environ.pop("SMARTAPI_KEY", None)
            code = launch.main(["--port", str(self.port), "--no-agent",
                                "--root", ROOT,
                                "--config", "router/providers.smartapi.json"])
        self.assertEqual(code, 1, "без ключа работать нечем — понятная ошибка, а не зависание")


if __name__ == "__main__":
    unittest.main(verbosity=2)
