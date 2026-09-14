#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeCoder: запуск одним действием (вызывается из START.bat в корне проекта).

Что делает:
  1) проверяет ключ SMARTAPI_KEY (спрашивает один раз и сохраняет в переменную окружения);
  2) поднимает роутер на 127.0.0.1:8788 и ждёт, пока он ответит;
  3) предлагает выбрать модель — маршруты и все модели шлюза (Claude, GPT, Codex);
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

VERSION = "2.0.0"
PORT = 8788
BASE = f"http://127.0.0.1:{PORT}"
ROUTER_CONFIG = os.path.join("config", "providers.json")

# Рекомендуемые маршруты: пользователь выбирает одну цифру, роутер сам ведёт на нужную модель.
ROUTES = [
    ("auto",  "claude-sonnet-4-6", "2",    "обычная работа — обычно хватает её"),
    ("cheap", "gpt-5.6-luna",      "1,7",  "самая дешёвая: мелкие правки и вопросы"),
    ("smart", "claude-opus-4-8",   "4",    "сложные задачи, заметно умнее"),
    ("max",   "claude-opus-5",     "5",    "максимум качества, для тяжёлого"),
]
FAMILIES = (("Claude", "claude"), ("GPT", "gpt"), ("Codex", "codex"))


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
    cmd = [sys.executable, os.path.join(root, "app", "router.py"),
           "--config", config, "--port", str(port)]
    if log_file:
        cmd += ["--log-file", log_file]
    return cmd


def start_router(root: str, config: str, port: int = PORT, log_file: str = "",
                 spawn=None) -> object:
    """Запускает роутер отдельным процессом (для тех, кто работает в редакторе)."""
    spawn = spawn or subprocess.Popen
    cmd = router_command(root, config, port, log_file)
    kwargs = {"cwd": root}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        kwargs["env"] = dict(os.environ)
    else:
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL
        kwargs["start_new_session"] = True
    return spawn(cmd, **kwargs)


def start_router_in_process(root: str, config: str, port: int = PORT, log_file: str = ""):
    """Поднимает роутер в фоновом потоке этого же процесса.

    Так получается одно окно: статистика агента и роутер живут в одной консоли.
    Возвращает httpd (или None, если роутер недоступен как модуль).
    """
    router_dir = os.path.join(root, "app")
    if not os.path.isfile(os.path.join(router_dir, "router.py")):
        return None
    if router_dir not in sys.path:
        sys.path.insert(0, router_dir)
    try:
        import router as fcr
    except Exception:  # noqa: BLE001
        return None
    state = os.path.join(state_dir(), "router-state.json")
    httpd, _ = fcr.serve_forever_in_thread(config, host="127.0.0.1", port=port,
                                           state_path=state, quiet=True, log_file=log_file)
    return httpd


def agent_command(root: str, workspace: str, model: str, confirm: bool = False,
                  port: int = PORT) -> list:
    """Команда запуска агента: правки применяются сразу, если не просили подтверждать.

    Адрес роутера передаём явно: если стартовать на другом порту (например, для проверки),
    агент всё равно попадёт в свой роутер, а не в чужой на 8788.
    """
    cmd = [sys.executable, os.path.join(root, "app", "agent.py"),
           "--workspace", workspace, "--model", model, "--quiet",
           "--api-base", f"http://127.0.0.1:{port}/v1"]
    cmd += ["--allow-cmd"] if confirm else ["--yes"]
    return cmd


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


def model_family(model_id: str) -> str:
    short = model_id.split("/")[-1].lower()
    for title, prefix in FAMILIES:
        if short.startswith(prefix):
            return title
    return "Прочее"


def fmt_mult(mult: float) -> str:
    """Коэффициент без хвоста: 2, а не 2,0."""
    number = float(mult)
    return str(int(number)) if number == int(number) else str(number).replace(".", ",")


def price_note(mult: float) -> str:
    if mult <= 2:
        return "дёшево"
    if mult <= 3:
        return "средне"
    if mult <= 4:
        return "дорого"
    return "очень дорого"


def read_catalog(config: str) -> list:
    """Модели из конфига роутера: [(id, коэффициент), ...] — Claude, GPT, Codex.

    Список берётся из config/providers.json, поэтому если в кабинете SmartAPI появятся
    новые модели, достаточно дописать их туда — меню подхватит.
    """
    seen = {}
    try:
        with open(config, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:  # noqa: BLE001
        return []
    for provider in data.get("providers") or []:
        mults = provider.get("model_multipliers") or {}
        names = list(mults.keys()) + [m for m in (provider.get("models") or []) if m not in mults]
        for name in names:
            seen.setdefault(str(name), float(mults.get(name) or 1))
    return sorted(seen.items(), key=lambda kv: (model_family(kv[0]), kv[1]))


def ask_model(ask=input, default: str = "auto", catalog=None) -> str:
    """Меню моделей: сначала 4 маршрута, потом все модели шлюза по семействам."""
    out()
    out("  Чем работать? Номер выбирает модель, Enter — оставить как есть.")
    out()
    out("  Рекомендую:")
    numbered = []
    for alias, model, mult, note in ROUTES:
        numbered.append(alias)
        out(f"    {len(numbered):>2}) {alias:<6} {model:<20} ×{mult:<5} {note}")
    catalog = catalog or []
    if catalog:
        out()
        out("  Любая модель шлюза (номер — работать прямо на ней):")
        family = ""
        line = "    "
        for model_id, mult in catalog:
            fam = model_family(model_id)
            if fam != family:
                if line.strip():
                    out(line)
                family = fam
                line = f"    {fam + ':':<8}"
            numbered.append(model_id)
            cell = f"{len(numbered):>2}) {model_id:<20} ×{fmt_mult(mult):<5}"
            if len(line) + len(cell) > 100:
                out(line)
                line = "    " + " " * 8
            line += cell
        if line.strip():
            out(line)
    out()
    out("  × — во сколько раз дороже токен. Дешевле всего gpt-5.6-luna (×1,7).")
    try:
        ans = (ask(f"  Номер [{default}]: ") or "").strip()
    except (EOFError, KeyboardInterrupt):
        return default
    if not ans:
        return default
    if ans.isdigit():
        idx = int(ans)
        if 1 <= idx <= len(numbered):
            return numbered[idx - 1]
        warn("нет такого номера — оставляю как было")
        return default
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
    # app/launch.py лежит внутри app/, поэтому корень проекта — на уровень выше
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--config", default=ROUTER_CONFIG)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--workspace", default="", help="папка проекта (иначе спросит)")
    ap.add_argument("--model", default="", help="модель (иначе спросит)")
    ap.add_argument("--no-agent", action="store_true", help="только поднять роутер")
    ap.add_argument("--confirm", action="store_true",
                    help="спрашивать подтверждение на каждую правку (по умолчанию правки сразу)")
    ap.add_argument("--version", action="version", version=f"FreeCoder launcher {VERSION}")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root)
    config = args.config if os.path.isabs(args.config) else os.path.join(root, args.config)

    head("FreeCoder: агент на вашем балансе SmartAPI")

    if not os.path.isfile(os.path.join(root, "app", "router.py")):
        fail("не найден app/router.py — файлы проекта распакованы полностью?")
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
            if start_router_in_process(root, config, args.port, log_file) is None:
                start_router(root, config, args.port, log_file)   # запасной путь
        except OSError as e:
            if "Address already in use" in str(e):
                ok("роутер уже слушает этот порт (запущен ранее)")
            else:
                fail(f"не удалось запустить роутер: {type(e).__name__}: {e}")
                return 2
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
    model = args.model or ask_model(catalog=read_catalog(config))
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
    out("  Правки применяются сразу, откат — /undo. Подтверждения: /confirm on")
    out("  Следить за расходом: /tokens. Дешевле: одна задача за запуск и /clear между задачами.")
    out()
    agent_cmd = agent_command(root, workspace, model, confirm=args.confirm, port=args.port)
    try:
        code = subprocess.call(agent_cmd, cwd=root)
    except KeyboardInterrupt:
        code = 0

    head("Готово")
    print_spend(args.port)
    out(f"  Резервные копии правок: {os.path.join(workspace, '.freecoder')}")
    out("  Следующий раз — просто запустите START.bat снова.")
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
