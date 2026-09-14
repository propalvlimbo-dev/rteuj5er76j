#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты запускатора app/launch.py: проверка связи с роутером, ожидание старта,
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

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "app"))

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
    CONFIG = os.path.join(ROOT, "config", "providers.json")

    def test_model_by_number(self):
        self.assertEqual(launch.ask_model(ask=lambda _: "1"), "auto")
        self.assertEqual(launch.ask_model(ask=lambda _: "2"), "cheap")
        self.assertEqual(launch.ask_model(ask=lambda _: "3"), "smart")
        self.assertEqual(launch.ask_model(ask=lambda _: "4"), "max")

    def test_catalog_reads_all_vendors(self):
        """В меню должны быть не только Claude, но и GPT с Codex — на этом настаивал пользователь."""
        catalog = dict(launch.read_catalog(self.CONFIG))
        self.assertIn("claude-sonnet-4-6", catalog)
        self.assertIn("gpt-5.6-luna", catalog)
        self.assertIn("codex-auto-review", catalog)
        self.assertEqual(catalog["gpt-5.6-luna"], 1.7)
        self.assertEqual(catalog["claude-opus-4-8"], 4.0)

    def test_family_and_price_note(self):
        self.assertEqual(launch.model_family("gpt-5.6-terra"), "GPT")
        self.assertEqual(launch.model_family("claude-opus-5"), "Claude")
        self.assertEqual(launch.model_family("codex-auto-review"), "Codex")
        self.assertEqual(launch.price_note(1.7), "дёшево")
        self.assertEqual(launch.price_note(10), "очень дорого")
        self.assertEqual(launch.fmt_mult(2.0), "2")
        self.assertEqual(launch.fmt_mult(1.7), "1,7")

    def test_number_picks_gpt_model(self):
        catalog = launch.read_catalog(self.CONFIG)
        ids = [m for m, _ in catalog]
        number = len(launch.ROUTES) + ids.index("gpt-5.6-luna") + 1
        picked = launch.ask_model(ask=lambda _: str(number), catalog=catalog)
        self.assertEqual(picked, "gpt-5.6-luna")

    def test_bad_number_keeps_default(self):
        catalog = launch.read_catalog(self.CONFIG)
        self.assertEqual(launch.ask_model(ask=lambda _: "99", catalog=catalog), "auto")

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
        cmd = launch.router_command("/repo", "config/providers.json", 8788, "/tmp/r.log")
        self.assertIn("--config", cmd)
        self.assertIn("8788", cmd)
        self.assertIn("--log-file", cmd)
        self.assertTrue(any(p.endswith("app/router.py") for p in cmd))

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
                                "--config", "config/providers.json"])
        self.assertEqual(code, 0)

    def test_main_without_key_returns_error(self):
        tmp = tempfile.mkdtemp(prefix="fc-main2-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            os.environ.pop("SMARTAPI_KEY", None)
            code = launch.main(["--port", str(self.port), "--no-agent",
                                "--root", ROOT,
                                "--config", "config/providers.json"])
        self.assertEqual(code, 1, "без ключа работать нечем — понятная ошибка, а не зависание")

class TestAgentCommand(unittest.TestCase):
    """По умолчанию правки применяются сразу — подтверждения по желанию."""

    def test_default_applies_edits(self):
        cmd = launch.agent_command(ROOT, "/tmp/проект", "auto")
        self.assertIn("--yes", cmd)
        self.assertIn("--quiet", cmd, "шапку агента печатает запускатор, дублировать не нужно")
        self.assertNotIn("--allow-cmd", cmd)

    def test_api_base_points_to_router_port(self):
        """Если роутер поднят не на 8788, агент всё равно должен попасть в свой роутер."""
        cmd = launch.agent_command(ROOT, "/tmp/проект", "auto", port=8899)
        self.assertIn("--api-base", cmd)
        self.assertIn("http://127.0.0.1:8899/v1", cmd)

    def test_confirm_mode_asks(self):
        cmd = launch.agent_command(ROOT, "/tmp/проект", "smart", confirm=True)
        self.assertNotIn("--yes", cmd)
        self.assertIn("--allow-cmd", cmd)

    def test_paths_and_model_are_passed(self):
        cmd = launch.agent_command(ROOT, "C:/Мои проекты/сайт", "cheap")
        self.assertIn("C:/Мои проекты/сайт", cmd)
        self.assertIn("cheap", cmd)


class TestRouterInProcess(unittest.TestCase):
    """Роутер поднимается в том же процессе — второго окна командной строки нет."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fc-inproc-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.config = os.path.join(self.tmp, "cfg.json")
        with open(self.config, "w", encoding="utf-8") as f:
            json.dump({
                "default_alias": "auto",
                "aliases": {"auto": ["smartapi/claude-sonnet-4-6"]},
                "providers": [{
                    "name": "smartapi", "kind": "mock", "base_url": "http://127.0.0.1:1",
                    "keys": ["k"], "models": ["claude-sonnet-4-6"],
                    "model_multipliers": {"claude-sonnet-4-6": 2}, "limits": {"tpd": 400000},
                }],
            }, f)

    def test_starts_and_answers_health(self):
        import socket
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        httpd = launch.start_router_in_process(ROOT, self.config, port)
        self.assertIsNotNone(httpd, "роутер должен подниматься внутри процесса")
        self.addCleanup(httpd.shutdown)
        self.assertTrue(launch.health_ok(port))
        self.assertTrue(launch.spend_summary(port) == "" or "зачётных" in launch.spend_summary(port))

    def test_quiet_mode_prints_only_important(self):
        import socket
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        log_file = os.path.join(self.tmp, "router.log")
        httpd = launch.start_router_in_process(ROOT, self.config, port, log_file)
        self.addCleanup(httpd.shutdown)
        self.assertTrue(os.path.isfile(log_file), "журнал пишется в файл даже в тихом режиме")
        text = open(log_file, encoding="utf-8").read()
        self.assertIn("роутер запущен", text)

    def test_missing_module_returns_none(self):
        self.assertIsNone(launch.start_router_in_process("/tmp/нет-такого-проекта", self.config, 18495))


if __name__ == "__main__":
    unittest.main(verbosity=2)
