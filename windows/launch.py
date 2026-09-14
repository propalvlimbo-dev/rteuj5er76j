#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeCoder: запуск одним действием (вызывается из windows\\START-SMARTAPI.bat).

Что делает:
  1) проверяет ключ SMARTAPI_KEY (спрашивает один раз и сохраняет в переменную окружения);
  2) поднимает роутер на 127.0.0.1:8788 и ждёт, пока он ответит;
  3) предлагает выбрать модель (Enter — auto, то есть Sonnet ×2);
  4) спрашивает папку с вашим кодом и запоминает её;
  5) запускает агента в этой папке.

Почему на Python, а не на batch: в cmd.exe кавычки, отложенное раскрытие переменных и
вложенные скобки ломаются на русских путях и пробелах. Здесь всё это предсказуемо.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

VERSION = "1.0.0"
PORT = 8788
BASE = f"http://127.0.0.1:{PORT}"
ROUTER_CONFIG = os.path.join("router", "providers.smartapi.json")

MODELS = [
    ("auto",  "claude-sonnet-4-6", "x2",    "обычная работа — обычно её и хватает"),
    ("smart", "claude-opus-4-8",   "x4",    "сложные задачи, заметно умнее"),
    ("max",   "claude-opus-5",     "x5",    "максимум качества, для тяжёлого"),
    ("cheap", "gpt-5.6-luna",      "x1,7",  "экономит баланс на простых правках"),
]


# ---------------------------------------------------------------------------
# Мелочи вывода
# ---------------------------------------------------------------------------


def out(text: str = "") -> None:
    print(text, flush=True)


def head(text: str) -> None:
    out()
    out("=" * 60)
    out(f"  {text}")
    out("=" * 60)


def ok(text: str) -> None:
    out(f"  ✓ {text}")


def warn(text: str) -> None:
    out(f"  ! {text}")


def fail(text: str) -> None:
    out(f"  ✗ {text}")


# ---------------------------------------------------------------------------
# Роутер: проверка, запуск, ожидание
# ---------------------------------------------------------------------------


def health_ok(port: int = PORT, timeout: float = 2.0) -> bool:
    """True, если роутер отвечает на /health."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def wait_for_router(port: int = PORT, timeout: int = 40, on_tick=None) -> bool:
    """Ждёт ответа роутера. on_tick(прошло_секунд) вызывается раз в секунду."""
    deadline = time.time() + timeout
    waited = 0
    while time.time() < deadline:
        if health_ok(port):
            return True
        time.sleep(1)
        waited += 1
        if on_tick:
            on_tick(waited)
    return health_ok(port)


def router_command(root: str, config: str, port: int = PORT, log_file: str = "") -> list:
    cmd = [sys.executable, os.path.join("router", "freecoder_router.py"),
           "--config", config, "--port", str(port)]
    if log_file:
        cmd += ["--log-file", log_file]
    return cmd


def start_router(root: str, config: str, port: int = PORT, log_file: str = "",
                 spawn=None) -> object:
    """Запускает роутер. На Windows — в отдельном окне, чтобы его было видно."""
    spawn = spawn or subprocess.Popen
    cmd = router_command(root, config, port, log_file)
    kwargs = {"cwd": root}
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        kwargs["creationflags"] = flags
        kwargs["env"] = dict(os.environ)
    else:
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL
        kwargs["start_new_session"] = True
    return spawn(cmd, **kwargs)


def log_tail(path: str, lines: int = 15) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = f.readlines()
        return "".join(data[-lines:]).rstrip()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Расход: сколько уже съедено сегодня
# ---------------------------------------------------------------------------


def spend_summary(port: int = PORT, timeout: float = 3.0) -> str:
    """Короткая строка про расход за сегодня — вместо веб-панели."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/status.json", timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return ""

    spent = 0
    limit = 0
    requests = 0
    for p in data.get("providers", []):
        if p.get("kind") == "mock" or not p.get("keys"):
            continue
        day = sum(int(k.get("tokens_day") or 0) for k in p.get("keys", []))
        if day == 0 and not p.get("stats", {}).get("requests"):
            continue
        spent += day
        requests += int(p.get("stats", {}).get("requests") or 0)
        limit = max(limit, int((p.get("limits") or {}).get("tpd") or 0))
    if spent == 0 and requests == 0:
        return ""
    txt = f"израсходовано за сегодня: {spent:,} зачётных токенов".replace(",", " ")
    if limit:
        pct = round(spent * 100 / limit) if limit else 0
        txt += f" из {limit:,}".replace(",", " ") + f" ({pct}%)"
    txt += f"; запросов: {requests}"
    return txt


def print_spend(port: int = PORT) -> None:
    line = spend_summary(port)
    if line:
        out(f"  {line}")


# ---------------------------------------------------------------------------
# Ключ и папка
# ---------------------------------------------------------------------------


def state_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".freecoder")
    return os.path.join(base, "FreeCoder")


def last_workspace_path() -> str:
    return os.path.join(state_dir(), "last-workspace.txt")


def read_last_workspace() -> str:
    try:
        with open(last_workspace_path(), "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def write_last_workspace(path: str) -> None:
    try:
        os.makedirs(state_dir(), exist_ok=True)
        with open(last_workspace_path(), "w", encoding="utf-8") as f:
            f.write(path)
    except OSError:
        pass


def save_key_windows(key: str) -> bool:
    """setx — постоянная переменная окружения пользователя. Без shell, чтобы не светить ключ."""
    if os.name != "nt":
        return False
    try:
        res = subprocess.run(["setx", "SMARTAPI_KEY", key],
                             capture_output=True, text=True, timeout=20)
        return res.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def ensure_key(ask=input) -> str:
    key = (os.environ.get("SMARTAPI_KEY") or "").strip()
    if key:
        ok("ключ SMARTAPI_KEY найден в переменных окружения")
        return key
    warn("переменная SMARTAPI_KEY пока не задана")
    out("  Ключ берётся здесь: https://smartapi.shop/api-keys (выглядит как sk-smart-...)")
    out("  Вставьте его и нажмите Enter. В окне он не отобразится как файл, в переписку не попадёт.")
    try:
        key = (ask("  Ключ: ") or "").strip()
    except (EOFError, KeyboardInterrupt):
        return ""
    if not key:
        return ""
    os.environ["SMARTAPI_KEY"] = key
    if save_key_windows(key):
        ok("ключ сохранён в переменную окружения пользователя (в следующий раз спрашивать не буду)")
    else:
        warn("ключ будет действовать только в этом окне")
    return key


def ask_model(ask=input, default: str = "auto") -> str:
    out()
    out("  Какой моделью работать?")
    for i, (alias, model, mult, note) in enumerate(MODELS, 1):
        out(f"    {i}) {alias:<6} {model:<18} x{mult:<4} {note}")
    out("    Enter — оставить текущую. Полный список с ценами: команда /model в агенте.")
    try:
        ans = (ask(f"  Номер [{default}]: ") or "").strip()
    except (EOFError, KeyboardInterrupt):
        return default
    if not ans:
        return default
    if ans.isdigit():
        idx = int(ans)
        if 1 <= idx <= len(MODELS):
            return MODELS[idx - 1][0]
    return ans


def ask_workspace(ask=input, exists=os.path.isdir, makedirs=os.makedirs) -> str:
    last = read_last_workspace()
    default = last if last and exists(last) else os.path.expanduser("~")
    out()
    out("  В какой папке работать? Это папка с вашим кодом: агент читает и правит")
    out("  файлы только внутри неё. Можно вставить путь из проводника.")
    while True:
        ans = (ask(f"  Папка [{default}]: ") or "").strip().strip('"').strip("'")
        path = ans or default
        path = os.path.abspath(os.path.expanduser(path))
        if exists(path):
            write_last_workspace(path)
            return path
        warn(f"папки нет: {path}")
        make = (ask("  Создать её? [y/N]: ") or "").strip().lower()
        if make in ("y", "yes", "д", "да"):
            try:
                makedirs(path, exist_ok=True)
                write_last_workspace(path)
                return path
            except OSError as e:
                fail(f"не удалось создать папку: {e}")
                continue
        out("  Введите другой путь.")


# ---------------------------------------------------------------------------
# Главный сценарий
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Запуск FreeCoder: роутер + агент")
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--config", default=ROUTER_CONFIG)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--workspace", default="", help="папка проекта (иначе спросит)")
    ap.add_argument("--model", default="", help="модель (иначе спросит)")
    ap.add_argument("--no-agent", action="store_true", help="только поднять роутер")
    ap.add_argument("--version", action="version", version=f"FreeCoder launcher {VERSION}")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root)
    config = args.config if os.path.isabs(args.config) else os.path.join(root, args.config)

    head("FreeCoder: агент на вашем балансе SmartAPI")

    if not os.path.isfile(os.path.join(root, "router", "freecoder_router.py")):
        fail("не найден router/freecoder_router.py — файлы проекта распакованы полностью?")
        return 2
    if not os.path.isfile(config):
        fail(f"не найден конфиг {config}")
        return 2

    # --- шаг 1: ключ
    out()
    out("Шаг 1. Ключ")
    if not ensure_key():
        fail("ключ не введён — работать нечем")
        return 1

    # --- шаг 2: роутер
    out()
    out("Шаг 2. Роутер")
    log_file = os.path.join(state_dir(), "router.log")
    try:
        os.makedirs(state_dir(), exist_ok=True)
    except OSError:
        log_file = ""

    if health_ok(args.port):
        ok(f"роутер уже работает на порту {args.port}")
    else:
        out(f"  запускаю роутер (порт {args.port})…")
        try:
            start_router(root, config, args.port, log_file)
        except Exception as e:  # noqa: BLE001
            fail(f"не удалось запустить роутер: {type(e).__name__}: {e}")
            return 2
        out("  жду ответа роутера")
        alive = wait_for_router(args.port, timeout=40, on_tick=lambda s: out(f"    {s} c…"))
        if not alive:
            fail("роутер не ответил за 40 секунд")
            tail = log_tail(log_file) if log_file else ""
            if tail:
                out("  Последние строки из журнала роутера:")
                for line in tail.splitlines()[-12:]:
                    out("    " + line)
            else:
                warn("журнал пуст — окно роутера должно быть открыто, посмотрите в нём ошибку")
            warn("частые причины: порт 8788 занят другой программой; ключ отозван; нет доступа в интернет")
            return 2
        ok("роутер отвечает")

    print_spend(args.port)

    if args.no_agent:
        ok("роутер готов (агент запускать не просили)")
        return 0

    # --- шаг 3: модель
    out()
    out("Шаг 3. Модель")
    model = args.model or ask_model()
    ok(f"модель: {model} (менять в любой момент: /model)")

    # --- шаг 4: папка
    out()
    out("Шаг 4. Папка проекта")
    workspace = args.workspace or ask_workspace()
    if not os.path.isdir(workspace):
        fail(f"папка не найдена: {workspace}")
        return 1
    ok(f"рабочая папка: {workspace}")

    # --- шаг 5: агент
    out()
    out("Шаг 5. Агент. Пишите задачи словами, например:")
    out("  «в api.py падает get_user на пустом ответе — исправь»")
    out("  «сделай в папке demo index.html и style.css — тёмный адаптивный сайт»")
    out("  Правки агент показывает и спрашивает подтверждение (y). Команды: /help, /model, /cd, /exit")
    out()
    try:
        code = subprocess.call(
            [sys.executable, os.path.join(root, "agent", "freecoder_agent.py"),
             "--workspace", workspace, "--model", model],
            cwd=root,
        )
    except KeyboardInterrupt:
        code = 0

    head("Готово")
    print_spend(args.port)
    out(f"  Резервные копии правок: {os.path.join(workspace, '.freecoder')}")
    out("  Следующий раз — просто запустите START-SMARTAPI.bat снова.")
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
