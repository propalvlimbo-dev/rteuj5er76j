#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Прогон всех тестов ELYTRIX.

Каждый ``dev/tests/test_*.py`` — самостоятельный (unittest, только стандартная
библиотека), поэтому запускаем их отдельными процессами: так падение одного
набора не мешает остальным, а в конце видна общая картина.

    python dev/tests/run_all.py            всё
    python dev/tests/run_all.py -v         подробно (вывод каждого теста)
    python dev/tests/run_all.py agent tui  только наборы, в имени которых есть «agent»/«tui»
    python dev/tests/run_all.py --list     просто список наборов
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

GREEN = "\x1b[32m"
RED = "\x1b[31m"
YELLOW = "\x1b[33m"
DIM = "\x1b[2m"
BOLD = "\x1b[1m"
RESET = "\x1b[0m"

RAN_RE = re.compile(r"Ran (\d+) tests? in ([\d.]+)s")
OK_RE = re.compile(r"^OK(?: \(.*\))?$", re.MULTILINE)
FAILED_RE = re.compile(r"^FAILED \((.*)\)$", re.MULTILINE)


def color(text: str, code: str, enabled: bool) -> str:
    return f"{code}{text}{RESET}" if enabled else text


def suites() -> list:
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(HERE, "test_*.py")))


def run_one(name: str, verbose: bool) -> dict:
    started = time.time()
    proc = subprocess.run([sys.executable, os.path.join(HERE, name)],
                          capture_output=not verbose, text=True, cwd=ROOT,
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = "" if verbose else (proc.stdout or "") + (proc.stderr or "")
    ran = RAN_RE.search(out)
    failed = FAILED_RE.search(out)
    return {
        "name": name,
        "ok": proc.returncode == 0 and not failed,
        "tests": int(ran.group(1)) if ran else 0,
        "seconds": float(ran.group(2)) if ran else round(time.time() - started, 2),
        "wall": time.time() - started,
        "detail": (failed.group(1) if failed else ""),
        "output": out,
    }


def failures_of(result: dict, limit: int = 12) -> list:
    """Короткий список того, что сломалось: имя теста + последняя строка ошибки."""
    lines = []
    blocks = re.split(r"^=+\n", result["output"], flags=re.MULTILINE)
    for block in blocks:
        head = block.splitlines()[:1]
        if not head or not re.match(r"^(FAIL|ERROR): ", head[0]):
            continue
        tail = [ln for ln in block.splitlines() if ln.strip()]
        message = tail[-1] if len(tail) > 1 else ""
        lines.append((head[0].rstrip(), message[:220]))
    return lines[:limit]


def main() -> int:
    ap = argparse.ArgumentParser(description="прогон тестов ELYTRIX")
    ap.add_argument("filters", nargs="*", help="кусочки имён наборов (например: agent tui)")
    ap.add_argument("-v", "--verbose", action="store_true", help="показывать вывод каждого теста")
    ap.add_argument("--list", action="store_true", help="только список наборов")
    args = ap.parse_args()

    names = suites()
    if args.filters:
        wanted = [f.lower() for f in args.filters]
        names = [n for n in names if any(w in n.lower() for w in wanted)]
    if args.list:
        for name in names:
            print(name)
        return 0
    if not names:
        print("нет наборов для запуска")
        return 1

    use_color = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
    width = max(len(n) for n in names) + 2
    print(color(f"ELYTRIX: {len(names)} наборов тестов", BOLD, use_color))
    print(color("─" * (width + 46), DIM, use_color))

    results = []
    started = time.time()
    for name in names:
        if not args.verbose:
            print(f"  {name:<{width}}", end="", flush=True)
        result = run_one(name, args.verbose)
        results.append(result)
        mark = color("✓", GREEN, use_color) if result["ok"] else color("✗", RED, use_color)
        summary = f"{result['tests']:>3} тестов · {result['seconds']:>5.1f}с"
        if args.verbose:
            print(f"  {mark} {name}: {summary}")
        else:
            print(f"{mark} {summary}" + (color(f" · {result['detail']}", RED, use_color)
                                        if result["detail"] else ""))

    print(color("─" * (width + 46), DIM, use_color))
    total = sum(r["tests"] for r in results)
    broken = [r for r in results if not r["ok"]]
    wall = time.time() - started
    if broken:
        print(color(f"✗ провалено наборов: {len(broken)} из {len(results)} "
                    f"({total} тестов, {wall:.1f}с)", RED + BOLD, use_color))
        for result in broken:
            print(color(f"\n  {result['name']}", RED + BOLD, use_color))
            for head, message in failures_of(result):
                print(color(f"    {head}", RED, use_color))
                if message:
                    print(color(f"      {message}", DIM, use_color))
            if not failures_of(result):
                tail = [ln for ln in result["output"].splitlines() if ln.strip()][-6:]
                for line in tail:
                    print(color(f"      {line}", DIM, use_color))
        return 1
    print(color(f"✓ все тесты прошли: {total} в {len(results)} наборах за {wall:.1f}с",
                GREEN + BOLD, use_color))
    return 0


if __name__ == "__main__":
    sys.exit(main())
