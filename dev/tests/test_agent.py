#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты цикла агента: шаги, инструменты, подтверждения, сжатие контекста, память, отмена.

Запуск:  python dev/tests/test_agent.py
"""

from __future__ import annotations

import os
import shutil
import sys
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mockapi import MockGateway, Stack, call, make_workspace, text, tool  # noqa: E402

from elytrix.agent import parse_text_action  # noqa: E402
from elytrix.gateway import DailyLimitError  # noqa: E402

MODEL = "claude-sonnet-4-6"


class AgentCase(unittest.TestCase):
    def test_step_cap_flattens_history_growth(self):
        self.agent.cfg.set("economy.step_cap", 500)
        for i in range(30):
            self.agent.messages.append(
                {"role": "user", "content": [{"type": "text", "text": f"шаг {i} " + "данные " * 40}]})
            self.agent.messages.append(
                {"role": "assistant", "content": [{"type": "text", "text": f"ответ {i} " + "ещё " * 40}]})
        before = self.agent.prompt_tokens()
        self.agent._auto_compact()
        self.assertLess(self.agent.prompt_tokens(), before)

    def test_quick_task_heuristic(self):
        from elytrix.agent import _is_quick
        self.assertTrue(_is_quick("удали сообщение «Привет» из AirdropManager.java"))
        self.assertTrue(_is_quick("исправь опечатку в readme"))
        self.assertFalse(_is_quick("перепиши плагин аирдропов под новую версию API "
                                    "и добавь поддержку нескольких миров"))
        self.assertFalse(_is_quick(""))

    def test_memory_persists_between_agents(self):
        import json as _json
        from elytrix.agent import Agent
        self.agent.memory = [{"task": "удалил привет", "result": "ok [Airdrop.java]"}]
        self.agent._save_memory()
        path = self.agent._memory_path()
        self.assertTrue(_json.load(open(path, encoding="utf-8")))
        a = self.agent
        fresh = Agent(a.gw, a.tools, a.cfg, a.catalog, a.state)
        self.assertEqual(fresh.memory[0]["task"], "удалил привет")

    def test_cap_result_truncates_huge_output(self):
        from elytrix.agent import RESULT_CAP, _cap_result
        big = "x" * (RESULT_CAP + 5000)
        capped = _cap_result(big)
        self.assertLessEqual(len(capped), RESULT_CAP + 200)
        self.assertIn("урезано", capped)
        self.assertEqual(_cap_result("коротко"), "коротко")

    def test_repeat_detector_and_nudge(self):
        import types
        from elytrix.agent import Turn
        from elytrix.gateway import ToolCall
        turn1 = Turn(model="m", endpoint="anthropic")
        turn1.tool_calls = [ToolCall(id="c1", name="ls", args={"path": ""})]
        self.agent._note_repeat(turn1)
        self.assertEqual(self.agent._repeat, 0)
        turn2 = Turn(model="m", endpoint="anthropic")
        turn2.tool_calls = [ToolCall(id="c2", name="ls", args={"path": ""})]
        self.agent._note_repeat(turn2)
        self.assertEqual(self.agent._repeat, 1)
        self.agent.messages = []
        self.agent._execute_tools(turn2, 1)
        last = self.agent.messages[-1]["content"]
        self.assertTrue(any(b.get("type") == "text" and "ELYTRIX:" in b.get("text", "")
                            for b in last))

    def test_send_accepts_kind_inside_data(self):
        got = []
        self.agent.emit = lambda k, d: got.append((k, d))
        self.agent._send("note", text="шлюз перегружен", kind="warn")
        self.assertEqual(got, [("note", {"text": "шлюз перегружен", "kind": "warn"})])

    def setUp(self) -> None:
        self.mock = MockGateway().start()
        self.root = make_workspace()
        self.stack = Stack(self.mock, self.root)
        self.agent = self.stack.agent
        self._file("main.py", "def get_user(uid):\n    return db[uid]\n")
        self._file("README.md", "# Проект\n")

    def tearDown(self) -> None:
        self.stack.cleanup()
        self.mock.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def _file(self, rel: str, content: str) -> str:
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def _read(self, rel: str) -> str:
        with open(os.path.join(self.root, rel), "r", encoding="utf-8") as f:
            return f.read()


class TestSimpleTask(AgentCase):
    def test_answer_without_tools(self):
        self.mock.queue(text("Всё готово: поправил main.py"))
        report = self.agent.run_task("исправь main.py")
        self.assertEqual(report.answer, "Всё готово: поправил main.py")
        self.assertEqual(report.steps, 1)
        self.assertFalse(report.error)
        self.assertIn("text", self.stack.kinds())

    def test_streamed_text_is_emitted(self):
        self.mock.queue(text("ответ приходит кусками, а не одним блоком"))
        self.agent.run_task("расскажи")
        pieces = [d["text"] for d in self.stack.of("text")]
        self.assertGreater(len(pieces), 1)
        self.assertIn("кусками", "".join(pieces))

    def test_usage_is_reported(self):
        self.mock.queue(text("ок", tokens_in=1000, tokens_out=50))
        report = self.agent.run_task("задача")
        self.assertEqual(report.usage.tokens_in, 1000)
        self.assertEqual(report.usage.tokens_out, 50)
        self.assertEqual(report.usage.charged, int(1050 * 2.0))
        self.assertGreater(report.elapsed, 0.0)

    def test_task_is_stored_in_history(self):
        self.mock.queue(text("готово"))
        self.agent.run_task("первая задача")
        self.assertEqual(len(self.agent.messages), 2)
        self.assertEqual(self.agent.messages[0]["role"], "user")
        self.assertEqual(self.agent.messages[1]["role"], "assistant")

    def test_system_prompt_is_lean(self):
        prompt = self.agent.system_prompt()
        self.assertIn("ELYTRIX", prompt)
        self.assertIn(self.root, prompt)
        self.assertLess(len(prompt), 2200,
                        "системный промпт уезжает в каждый запрос — держим его коротким")
        self.assertNotIn("node_modules", prompt)


class TestToolLoop(AgentCase):
    def test_read_then_answer(self):
        self.mock.queue(tool(call("read", path="main.py"), thought="читаю"),
                        text("Вижу проблему: нужен db.get(uid)"))
        report = self.agent.run_task("посмотри main.py")
        self.assertEqual(report.steps, 2)
        self.assertIn("db.get", report.answer)
        results = self.stack.of("result")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "read")
        self.assertTrue(results[0]["ok"])
        # в истории должен остаться результат инструмента
        tool_results = [b for m in self.agent.messages for b in (m.get("content") or [])
                        if isinstance(b, dict) and b.get("type") == "tool_result"]
        self.assertEqual(len(tool_results), 1)
        self.assertIn("def get_user", tool_results[0]["content"])

    def test_write_creates_file_and_reports_it(self):
        self.mock.queue(tool(call("write", path="index.html", content="<h1>Сайт</h1>")),
                        text("Сделал index.html"))
        report = self.agent.run_task("сделай сайт")
        self.assertEqual(report.files, ["index.html"])
        self.assertEqual(self._read("index.html"), "<h1>Сайт</h1>")

    def test_edit_changes_file(self):
        self.mock.queue(tool(call("edit", path="main.py", old="return db[uid]",
                                  new="return db.get(uid)")),
                        text("Поправил"))
        self.agent.run_task("исправь")
        self.assertIn("db.get(uid)", self._read("main.py"))

    def test_parallel_read_tools(self):
        """Несколько чтений в одном ответе выполняются вместе — меньше кругов и токенов."""
        self.mock.queue(tool(call("read", path="main.py"), call("read", path="README.md")),
                        text("прочитал оба"))
        report = self.agent.run_task("прочитай оба файла")
        names = [d["path"] or d["summary"] for d in self.stack.of("result")]
        self.assertEqual(len(self.stack.of("result")), 2)
        self.assertEqual(report.tool_calls, 2)
        self.assertTrue(names)
        order = [b.get("tool_use_id") for m in self.agent.messages
                 for b in (m.get("content") or [])
                 if isinstance(b, dict) and b.get("type") == "tool_result"]
        self.assertEqual(len(order), 2, "на каждый tool_use должен быть свой tool_result")

    def test_tool_error_is_returned_to_model(self):
        self.mock.queue(tool(call("read", path="нет-такого.py")), text("Файла нет — создал бы"))
        self.agent.run_task("прочитай несуществующее")
        results = self.stack.of("result")
        self.assertFalse(results[0]["ok"])
        tool_results = [b for m in self.agent.messages for b in (m.get("content") or [])
                        if isinstance(b, dict) and b.get("type") == "tool_result"]
        self.assertTrue(tool_results[0]["is_error"])
        self.assertIn("ФАЙЛА НЕТ", tool_results[0]["content"])

    def test_journal_is_collected(self):
        self.mock.queue(tool(call("read", path="main.py"), call("ls")), text("ок"))
        self.agent.run_task("осмотрись")
        self.assertTrue(self.agent.journal)
        self.assertTrue(any("read" in line for line in self.agent.journal))

    def test_step_limit(self):
        self.agent.max_steps = 3
        for _ in range(5):
            self.mock.queue(tool(call("ls")))
        report = self.agent.run_task("бесконечная задача")
        self.assertEqual(report.steps, 3)
        self.assertIn("предел шагов", report.answer)

    def test_set_model_clears_history(self):
        self.mock.queue(text("ок"))
        self.agent.run_task("задача")
        self.assertTrue(self.agent.messages)
        self.agent.set_model("cheap")
        self.assertEqual(self.agent.messages, [])
        self.assertEqual(self.agent.model, "cheap")


class TestConfirmations(AgentCase):
    def test_ask_mode_rejects_on_no(self):
        self.agent.confirm_mode = "ask"
        asked = []
        self.agent.confirm = lambda req: (asked.append(req), "no")[1]
        self.mock.queue(tool(call("write", path="x.txt", content="данные")), text("не вышло"))
        self.agent.run_task("создай файл")
        self.assertFalse(os.path.exists(os.path.join(self.root, "x.txt")),
                         "после отказа файла быть не должно")
        self.assertEqual(len(asked), 1)
        self.assertEqual(asked[0].tool, "write")
        tool_results = [b for m in self.agent.messages for b in (m.get("content") or [])
                        if isinstance(b, dict) and b.get("type") == "tool_result"]
        self.assertIn("отклонил", tool_results[0]["content"])

    def test_ask_mode_applies_on_yes(self):
        self.agent.confirm_mode = "ask"
        self.agent.confirm = lambda req: "yes"
        self.mock.queue(tool(call("write", path="x.txt", content="данные")), text("готово"))
        self.agent.run_task("создай файл")
        self.assertEqual(self._read("x.txt"), "данные")

    def test_always_remembers_choice(self):
        self.agent.confirm_mode = "ask"
        calls = []
        self.agent.confirm = lambda req: (calls.append(req.tool), "always")[1]
        self.mock.queue(tool(call("write", path="a.txt", content="1")),
                        tool(call("write", path="b.txt", content="2")),
                        text("готово"))
        self.agent.run_task("создай два файла")
        self.assertEqual(len(calls), 1, "второй write не должен спрашиваться")
        self.assertEqual(self._read("b.txt"), "2")

    def test_readonly_mode_blocks_writes(self):
        self.agent.confirm_mode = "readonly"
        self.mock.queue(tool(call("write", path="x.txt", content="данные")), text("не могу менять"))
        self.agent.run_task("создай файл")
        self.assertFalse(os.path.exists(os.path.join(self.root, "x.txt")))

    def test_readonly_mode_allows_reads(self):
        self.agent.confirm_mode = "readonly"
        self.mock.queue(tool(call("read", path="main.py")), text("прочитал"))
        report = self.agent.run_task("прочитай")
        self.assertTrue(all(d["ok"] for d in self.stack.of("result")))
        self.assertIn("прочитал", report.answer)

    def test_confirm_dialog_gets_diff(self):
        self.agent.confirm_mode = "ask"
        seen = []

        def confirm(req):
            seen.append(req)
            return "yes"

        self.agent.confirm = confirm
        self.mock.queue(tool(call("edit", path="main.py", old="return db[uid]",
                                  new="return db.get(uid)")), text("готово"))
        self.agent.run_task("правь")
        self.assertIn("-    return db[uid]", seen[0].diff)
        self.assertIn("+    return db.get(uid)", seen[0].diff)
        self.assertIn("main.py", seen[0].detail)

    def test_stop_aborts_task(self):
        self.agent.confirm_mode = "ask"
        self.agent.confirm = lambda req: "stop"
        self.mock.queue(tool(call("write", path="x.txt", content="1")), text("не должно дойти"))
        report = self.agent.run_task("создай файл")
        self.assertTrue(report.cancelled)
        self.assertFalse(os.path.exists(os.path.join(self.root, "x.txt")))


class TestCompaction(AgentCase):
    def _fat_history(self, count: int = 6, size: int = 3000) -> None:
        self._file("big.txt", "\n".join("x" * 60 for _ in range(size // 60)))
        for i in range(count):
            self.agent.messages.append({"role": "assistant", "content": [
                {"type": "text", "text": f"шаг {i}"},
                {"type": "tool_use", "id": f"c{i}", "name": "read",
                 "input": {"path": "big.txt", "content": "ы" * 500}}]})
            self.agent.messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"c{i}", "content": "данные " * 400}]})

    def test_compact_shrinks_history(self):
        self._fat_history()
        before = self.agent.prompt_tokens()
        saved = self.agent.compact()
        after = self.agent.prompt_tokens()
        self.assertGreater(saved, 0)
        self.assertLess(after, before)

    def test_compact_squeezes_old_results(self):
        self._fat_history()
        self.agent.compact()
        contents = [b.get("content") for m in self.agent.messages
                    for b in (m.get("content") or [])
                    if isinstance(b, dict) and b.get("type") == "tool_result"]
        self.assertTrue(any("[сжато" in str(c) for c in contents[:-1]),
                        "старые результаты должны быть заменены пометкой")

    def test_compact_strips_written_files_from_history(self):
        self._fat_history()
        self.agent.compact()
        # последний шаг держим целиком (модели он ещё нужен), остальные — пометками
        old = str(self.agent.messages[:-2])
        self.assertNotIn("ы" * 500, old, "содержимое файлов не должно оставаться в истории")
        self.assertIn("файл уже на диске", old)

    def test_compact_keeps_recent_results(self):
        self._fat_history()
        self.agent.compact()
        last = [b for b in (self.agent.messages[-1].get("content") or [])
                if b.get("type") == "tool_result"]
        self.assertTrue(last)
        self.assertNotIn("[сжато", str(last[-1].get("content"))[:40])

    def test_aggressive_compact_drops_middle(self):
        self._fat_history(count=10, size=6000)
        self.agent.journal = ["+ read big.txt"] * 5
        self.agent.compact(aggressive=True)
        raw = str(self.agent.messages)
        self.assertIn("середина истории сжата", raw)
        self.assertIn("Журнал сделанного", raw)
        self.assertLessEqual(len(self.agent.messages), 8)

    def test_auto_compact_emits_event(self):
        self.stack.catalog.catalog[MODEL]["ctx"] = 3000
        self.agent.compact_threshold = 0.3
        self._fat_history(count=4, size=2000)
        self.mock.queue(text("готово"))
        self.agent.run_task("длинная задача")
        self.assertIn("compact", self.stack.kinds())
        info = self.stack.of("compact")[0]
        self.assertGreater(info["before"], info["after"])

    def test_history_stays_valid_after_compaction(self):
        """На каждый tool_use должен остаться tool_result — иначе шлюз вернёт 400."""
        self._fat_history(count=8, size=4000)
        self.agent.compact(aggressive=True)
        uses = [b.get("id") for m in self.agent.messages for b in (m.get("content") or [])
                if isinstance(b, dict) and b.get("type") == "tool_use"]
        results = [b.get("tool_use_id") for m in self.agent.messages
                   for b in (m.get("content") or [])
                   if isinstance(b, dict) and b.get("type") == "tool_result"]
        for use_id in uses:
            self.assertIn(use_id, results)


class TestMemory(AgentCase):
    def test_memory_keeps_two_lines_per_task(self):
        self.mock.queue(text("сделал первое"), text("сделал второе"))
        self.agent.run_task("первая задача")
        self.agent.run_task("вторая задача")
        self.assertEqual(len(self.agent.memory), 2)
        self.assertEqual(self.agent.memory[0]["task"], "первая задача")
        self.assertIn("сделал первое", self.agent.memory[0]["result"])

    def test_memory_is_included_in_prompt(self):
        self.mock.queue(text("готово"))
        self.agent.run_task("задача про кнопку")
        prompt = self.agent.system_prompt()
        self.assertIn("СЕССИЯ", prompt)
        self.assertIn("задача про кнопку", prompt)

    def test_memory_records_files(self):
        self.mock.queue(tool(call("write", path="new.txt", content="1")), text("создал"))
        self.agent.run_task("создай файл")
        self.assertIn("new.txt", self.agent.memory[0]["result"])

    def test_memory_is_limited(self):
        for i in range(12):
            self.mock.queue(text(f"готово {i}"))
            self.agent.run_task(f"задача {i}")
        self.assertLessEqual(len(self.agent.memory), 6)
        self.assertEqual(self.agent.memory[-1]["task"], "задача 11")

    def test_clear_forgets_everything(self):
        self.mock.queue(text("готово"))
        self.agent.run_task("задача")
        self.agent.clear()
        self.assertEqual(self.agent.messages, [])
        self.assertEqual(self.agent.memory, [])
        self.assertEqual(self.agent.journal, [])

    def test_error_is_remembered(self):
        self.mock.fail_with = (401, "bad key")
        self.mock.fail_once = False
        report = self.agent.run_task("задача")
        self.assertTrue(report.error)
        self.assertIn("ошибка", self.agent.memory[-1]["result"])


class TestFailures(AgentCase):
    def test_gateway_error_is_reported(self):
        self.mock.fail_with = (500, "шлюз лёг")
        self.mock.fail_once = False
        report = self.agent.run_task("задача")
        self.assertTrue(report.error)
        self.assertIn("error", self.stack.kinds())
        self.assertFalse(self.agent.busy)

    def test_daily_limit_is_reported(self):
        self.stack.gw.daily_limit = 5
        self.stack.state.data["tokens_day"] = 10
        report = self.agent.run_task("задача")
        self.assertIn("/limit", report.error)

    def test_cancel_during_request(self):
        self.mock.stall = 0.5
        self.mock.queue(text("не должно дойти"))
        threading.Timer(0.05, self.agent.cancel.set).start()
        report = self.agent.run_task("задача")
        self.assertTrue(report.cancelled)
        self.assertFalse(report.answer)

    def test_busy_flag_is_reset(self):
        self.mock.queue(text("готово"))
        self.agent.run_task("задача")
        self.assertFalse(self.agent.busy)


class TestTextProtocol(AgentCase):
    def test_falls_back_when_tools_rejected(self):
        self.mock.drop_tools = True
        self.mock.queue(
            text('{"thought":"читаю","tool":"read","args":{"path":"main.py"}}'),
            text('{"thought":"итог","done":true,"answer":"прочитал main.py"}'),
        )
        report = self.agent.run_task("прочитай main.py")
        self.assertTrue(self.agent.text_protocol)
        self.assertIn("прочитал", report.answer)
        self.assertTrue(self.stack.of("result"))

    def test_parse_text_action_variants(self):
        self.assertEqual(parse_text_action('{"tool":"ls","args":{}}')["tool"], "ls")
        self.assertEqual(parse_text_action('```json\n{"tool":"ls"}\n```')["tool"], "ls")
        self.assertEqual(parse_text_action('думаю {"tool":"ls","args":{}} и точка')["tool"], "ls")
        self.assertTrue(parse_text_action('{"done":true,"answer":"готово"}')["done"])
        self.assertIsNone(parse_text_action("просто текст"))
        self.assertIsNone(parse_text_action(""))

    def test_protocol_instruction_is_added_to_prompt(self):
        self.agent.text_protocol = True
        prompt = self.agent.system_prompt()
        self.assertIn("РЕЖИМ БЕЗ ИНСТРУМЕНТОВ", prompt)
        self.assertIn('"done"', prompt)


class TestStats(AgentCase):
    def test_stats_report_context_and_spend(self):
        self.mock.queue(text("готово", tokens_in=800, tokens_out=100))
        self.agent.run_task("задача")
        stats = self.agent.stats()
        self.assertEqual(stats["model"], MODEL)
        self.assertEqual(stats["multiplier"], 2.0)
        self.assertGreater(stats["prompt_tokens"], 0)
        self.assertEqual(stats["tokens_in"], 800)
        self.assertEqual(stats["day_tokens"], 1800)
        self.assertGreaterEqual(stats["context"], 1000)
        self.assertTrue(stats["cache_enabled"])

    def test_context_used_percentage(self):
        self.mock.queue(text("готово"))
        self.agent.run_task("задача")
        stats = self.agent.stats()
        self.assertEqual(stats["context_used"],
                         round(stats["prompt_tokens"] * 100 / stats["context"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
