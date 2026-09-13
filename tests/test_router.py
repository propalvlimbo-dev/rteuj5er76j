#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты FreeCoder Router: failover, ротация ключей, учёт квот, стриминг, алиасы.

Запуск:  python tests/test_router.py       (или python -m unittest discover tests)
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "router"))

import freecoder_router as fcr  # noqa: E402


# --------------------------------------------------------------------------
# Фальшивый апстрим: управляется словарём control
# --------------------------------------------------------------------------


class FakeUpstream(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    control = {
        "hits": [],            # список полученных (key, model)
        "status_by_key": {},   # "Bearer key" -> http код
        "default_status": 200,
        "delay": 0.0,
        "stream": False,
    }

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        auth = self.headers.get("Authorization", "")
        FakeUpstream.control["hits"].append((auth, body.get("model"), bool(body.get("stream"))))
        if FakeUpstream.control["delay"]:
            time.sleep(FakeUpstream.control["delay"])

        code = FakeUpstream.control["status_by_key"].get(auth, FakeUpstream.control["default_status"])
        if code != 200:
            payload = json.dumps({"error": {"message": f"fake {code}"}}).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            if code == 429:
                self.send_header("retry-after", "2")
            self.end_headers()
            self.wfile.write(payload)
            return

        if FakeUpstream.control["stream"]:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for piece in ("Привет", ", мир"):
                chunk = json.dumps({"choices": [{"delta": {"content": piece}}], "model": "up"}).encode()
                data = b"data: " + chunk + b"\n\n"
                self.wfile.write(b"%x\r\n" % len(data) + data + b"\r\n")
                self.wfile.flush()
            usage = json.dumps({"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 3}}).encode()
            data = b"data: " + usage + b"\n\n"
            self.wfile.write(b"%x\r\n" % len(data) + data + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            return

        payload = json.dumps({
            "id": "x", "object": "chat.completion", "created": 0, "model": body.get("model"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def start_fake(port):
    srv = ThreadingHTTPServer(("127.0.0.1", port), FakeUpstream)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class RouterTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="fcr-test-")
        FakeUpstream.control.update({
            "hits": [], "status_by_key": {}, "default_status": 200, "delay": 0.0, "stream": False,
        })
        cls.up_a = start_fake(18101)
        cls.up_b = start_fake(18102)

    @classmethod
    def tearDownClass(cls):
        for srv in (cls.up_a, cls.up_b):
            srv.shutdown()
            srv.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def make_router(self, providers, aliases=None, **extra):
        cfg = {"providers": providers, "aliases": aliases or {}, "default_alias": "auto"}
        cfg.update(extra)
        cfg.setdefault("log_requests", False)
        r = fcr.Router(cfg, os.path.join(self.tmp, f"state-{time.time_ns()}.json"))
        server = ThreadingHTTPServer(("127.0.0.1", 0), fcr.Handler)
        server.daemon_threads = True
        fcr.Handler.router = r
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return r, server.server_address[1]

    def post(self, port, payload, raw=False):
        import urllib.request

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode()
                return resp.status, (body if raw else json.loads(body))
        except urllib.error.HTTPError as e:  # noqa: F821
            body = e.read().decode()
            return e.code, (body if raw else json.loads(body))


class TestFailover(RouterTestBase):
    def test_first_provider_ok(self):
        FakeUpstream.control["default_status"] = 200
        r, port = self.make_router([{
            "name": "a", "base_url": "http://127.0.0.1:18101/v1", "keys": ["k1"],
            "models": ["m1"], "priority": 1, "limits": {"rpm": 10, "rpd": 10},
        }])
        code, out = self.post(port, {"model": "auto", "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(code, 200)
        self.assertEqual(out["x_freecoder_provider"], "a")
        self.assertEqual(r.stats["a"]["ok"], 1)

    def test_failover_on_429(self):
        FakeUpstream.control["status_by_key"] = {"Bearer bad": 429}
        r, port = self.make_router([
            {"name": "a", "base_url": "http://127.0.0.1:18101/v1", "keys": ["bad"],
             "models": ["m1"], "priority": 1, "limits": {"rpd": 100}},
            {"name": "b", "base_url": "http://127.0.0.1:18102/v1", "keys": ["good"],
             "models": ["m2"], "priority": 2, "limits": {"rpd": 100}},
        ])
        code, out = self.post(port, {"model": "auto", "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(code, 200, out)
        self.assertEqual(out["x_freecoder_provider"], "b")
        self.assertGreater(r.states["a|0"].blocked_until, time.time())
        self.assertEqual(r.states["a|0"].last_error, "429 (квота/лимит)")

    def test_failover_on_500(self):
        FakeUpstream.control["status_by_key"] = {"Bearer boom": 500}
        _, port = self.make_router([
            {"name": "a", "base_url": "http://127.0.0.1:18101/v1", "keys": ["boom"],
             "models": ["m1"], "priority": 1},
            {"name": "b", "base_url": "http://127.0.0.1:18102/v1", "keys": ["good"],
             "models": ["m2"], "priority": 2},
        ])
        code, out = self.post(port, {"model": "auto", "messages": [{"role": "user", "content": "x"}]})
        self.assertEqual(code, 200, out)
        self.assertEqual(out["x_freecoder_provider"], "b")

    def test_all_failed_returns_429_with_hint(self):
        FakeUpstream.control["status_by_key"] = {"Bearer bad": 429, "Bearer bad2": 429}
        _, port = self.make_router([
            {"name": "a", "base_url": "http://127.0.0.1:18101/v1", "keys": ["bad"], "models": ["m1"]},
            {"name": "b", "base_url": "http://127.0.0.1:18102/v1", "keys": ["bad2"], "models": ["m2"]},
        ])
        code, out = self.post(port, {"model": "auto", "messages": [{"role": "user", "content": "x"}]})
        self.assertEqual(code, 429)
        self.assertIn("квоты", out["error"]["message"])

    def test_key_rotation_within_provider(self):
        """Первый ключ исчерпан — второй должен подхватить в том же запросе."""
        FakeUpstream.control["status_by_key"] = {"Bearer k1": 429, "Bearer k2": 200}
        r, port = self.make_router([{
            "name": "a", "base_url": "http://127.0.0.1:18101/v1", "keys": ["k1", "k2"],
            "models": ["m1"], "priority": 1, "limits": {"rpd": 100},
        }])
        code, out = self.post(port, {"model": "auto", "messages": [{"role": "user", "content": "x"}]})
        self.assertEqual(code, 200, out)
        self.assertGreater(r.states["a|0"].blocked_until, time.time())
        self.assertEqual(r.states["a|1"].blocked_until, 0)
        self.assertEqual(r.stats["a"]["ok"], 1)

    def test_quota_exhausted_skips_provider(self):
        FakeUpstream.control["status_by_key"] = {}
        r, port = self.make_router([
            {"name": "a", "base_url": "http://127.0.0.1:18101/v1", "keys": ["k1"],
             "models": ["m1"], "priority": 1, "limits": {"rpd": 2}},
            {"name": "b", "base_url": "http://127.0.0.1:18102/v1", "keys": ["k2"],
             "models": ["m2"], "priority": 2, "limits": {"rpd": 100}},
        ])
        hits_before = len(FakeUpstream.control["hits"])
        for _ in range(3):
            code, _ = self.post(port, {"model": "auto", "messages": [{"role": "user", "content": "x"}]})
            self.assertEqual(code, 200)
        new_hits = FakeUpstream.control["hits"][hits_before:]
        # 2 запроса ушли в "a", третий обязан уйти в "b" без обращения к "a"
        self.assertEqual(sum(1 for h in new_hits if h[0] == "Bearer k1"), 2)
        self.assertEqual(r.states["a|0"].requests_day, 2)

    def test_local_fallback_when_everything_exhausted(self):
        r, port = self.make_router([
            {"name": "a", "base_url": "http://127.0.0.1:18101/v1", "keys": ["k1"],
             "models": ["m1"], "priority": 1, "limits": {"rpd": 1}},
            {"name": "local", "base_url": "http://127.0.0.1:18102/v1", "keys": ["l"],
             "models": ["qwen"], "priority": 900, "kind": "ollama"},
        ])
        self.post(port, {"model": "auto", "messages": [{"role": "user", "content": "x"}]})
        attempts = r.pick_attempts("auto")
        self.assertTrue(any(p.name == "local" for p, _, _ in attempts),
                        "после исчерпания квоты должен остаться локальный резерв")


class TestProtocol(RouterTestBase):
    def test_models_endpoint(self):
        _, port = self.make_router([{
            "name": "a", "base_url": "http://127.0.0.1:18101/v1", "keys": ["k"],
            "models": ["m1", "m2"], "priority": 1,
        }], aliases={"smart": ["a/m1"], "fast": ["a/m2"]})
        import urllib.request

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=10) as resp:
            data = json.loads(resp.read())
        ids = {m["id"] for m in data["data"]}
        self.assertIn("smart", ids)
        self.assertIn("fast", ids)
        self.assertIn("a/m1", ids)

    def test_streaming_passthrough(self):
        FakeUpstream.control["stream"] = True
        try:
            r, port = self.make_router([{
                "name": "a", "base_url": "http://127.0.0.1:18101/v1", "keys": ["k"],
                "models": ["m1"], "priority": 1, "limits": {"rpd": 100},
            }])
            code, body = self.post(port, {"model": "auto", "stream": True,
                                          "messages": [{"role": "user", "content": "hi"}]}, raw=True)
            self.assertEqual(code, 200)
            self.assertIn("data:", body)
            self.assertIn("Привет", body)
            time.sleep(0.2)
            self.assertEqual(r.states["a|0"].tokens_day, 10)
        finally:
            FakeUpstream.control["stream"] = False

    def test_unknown_model_falls_back_to_auto(self):
        _, port = self.make_router([{
            "name": "a", "base_url": "http://127.0.0.1:18101/v1", "keys": ["k"],
            "models": ["m1"], "priority": 1,
        }])
        code, out = self.post(port, {"model": "не-существует-такая", "messages": [{"role": "user", "content": "x"}]})
        self.assertEqual(code, 200)
        self.assertEqual(out["model"], "не-существует-такая")

    def test_400_tools_are_stripped_and_retried(self):
        """Часть бесплатных тарифов не умеет tools — запрос должен пройти без них."""
        class ToolsRejecting(FakeUpstream):
            control = dict(FakeUpstream.control)

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                ToolsRejecting.control["hits"].append((self.headers.get("Authorization"), body.get("model"), bool(body.get("tools"))))
                if "tools" in body:
                    payload = json.dumps({"error": {"message": "tools are not supported"}}).encode()
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                payload = json.dumps({"choices": [{"message": {"role": "assistant", "content": "ok"}}],
                                      "usage": {}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        srv = ThreadingHTTPServer(("127.0.0.1", 18103), ToolsRejecting)
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)

        _, port = self.make_router([{
            "name": "a", "base_url": "http://127.0.0.1:18103/v1", "keys": ["k"],
            "models": ["m1"], "priority": 1,
        }])
        code, out = self.post(port, {
            "model": "auto", "messages": [{"role": "user", "content": "x"}],
            "tools": [{"type": "function", "function": {"name": "f", "parameters": {}}}],
        })
        self.assertEqual(code, 200, out)
        self.assertEqual(out["choices"][0]["message"]["content"], "ok")

    def test_state_survives_restart(self):
        state = os.path.join(self.tmp, f"persist-{time.time_ns()}.json")
        cfg = {"providers": [{"name": "a", "base_url": "http://127.0.0.1:18101/v1",
                              "keys": ["k"], "models": ["m1"], "limits": {"rpd": 5}}],
               "log_requests": False}
        r1 = fcr.Router(cfg, state)
        r1.account_request(r1.providers[0], 0, 10, 5, ok=True)
        r1.save_state()
        r2 = fcr.Router(cfg, state)
        self.assertEqual(r2.states["a|0"].requests_day, 1)
        self.assertEqual(r2.states["a|0"].tokens_day, 15)


if __name__ == "__main__":
    unittest.main(verbosity=2)
