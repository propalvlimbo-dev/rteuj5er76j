# -*- coding: utf-8 -*-
"""Точка входа ELYTRIX: разбор аргументов, подготовка и запуск нужного режима.

Режимы:
    (без аргументов)      полноэкранная консоль — то, что запускает ELYTRIX.bat
    «текст задачи»        одна задача и выход (удобно из скриптов)
    --router [порт]       только локальный шлюз для редакторов
    --doctor              диагностика: ключ, шлюз, каталог моделей, лимиты
    --models              список моделей с коэффициентами расхода

Всё на стандартной библиотеке: ни pip, ни Node.js, ни Git ставить не нужно.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

from . import __version__
from .agent import Agent
from .config import (Catalog, Config, State, config_path, credentials_path, ensure_home,
                     home_dir, mask_key, project_root, read_key, save_key, sessions_dir)
from .gateway import GatewayError, SmartAPI
from .screen import Palette, enable_vt, force_utf8, is_tty, supports_unicode
from .theme import Theme
from .tools import Toolbox, Workspace


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="elytrix",
        description="ELYTRIX — компактный ИИ-агент для консоли на ключе SmartAPI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Примеры:
  ELYTRIX.bat                                  консоль (полноэкранный интерфейс)
  python -m elytrix                            то же из терминала
  python -m elytrix "в api.py исправь get_user"  одна задача и выход
  python -m elytrix prompt.txt                   задача из файла (большие промты)
  python -m elytrix -w C:\\Projects\\bot -m cheap  папка и дешёвая модель
  python -m elytrix --router 8789              шлюз для Cline / Continue / opencode
  python -m elytrix --doctor                   проверка ключа и связи со шлюзом
""")
    ap.add_argument("task", nargs="*", help="задача словами (пусто — интерактивная консоль)")
    ap.add_argument("-w", "--workspace", default="", help="папка с вашим кодом")
    ap.add_argument("-m", "--model", default="", help="модель или маршрут: auto, cheap, smart, max")
    ap.add_argument("--key", default="", help="ключ SmartAPI (иначе SMARTAPI_KEY или файл)")
    ap.add_argument("--config", default="", help="свой конфиг вместо config/elytrix.json")
    ap.add_argument("--theme", default="", help="тема: dark, night, light, mono")
    ap.add_argument("--color", default="", help="цвет: auto, truecolor, 256, 16, none")
    ap.add_argument("--steps", type=int, default=0, help="лимит шагов на задачу")
    ap.add_argument("--limit", type=int, default=-1, help="дневной лимит зачётных токенов (0 — снять)")
    ap.add_argument("-y", "--yes", action="store_true", help="править без подтверждений")
    ap.add_argument("--ask", action="store_true", help="спрашивать подтверждение на каждую правку")
    ap.add_argument("--readonly", action="store_true", help="только чтение: файлы не менять")
    ap.add_argument("--plain", action="store_true", help="без полноэкранного интерфейса (обычный вывод)")
    ap.add_argument("--no-cache", action="store_true", help="выключить prompt caching")
    ap.add_argument("--no-stream", action="store_true", help="не печатать ответ по мере генерации")
    ap.add_argument("--router", nargs="?", const=-1, default=None, metavar="PORT",
                    help="поднять только шлюз для редакторов")
    ap.add_argument("--host", default="127.0.0.1", help="адрес роутера (по умолчанию 127.0.0.1)")
    ap.add_argument("--doctor", action="store_true", help="диагностика и выход")
    ap.add_argument("--models", action="store_true", help="список моделей и выход")
    ap.add_argument("--version", action="version", version=f"ELYTRIX {__version__}")
    return ap


def resolve_task(args: argparse.Namespace) -> str:
    """Задача из аргументов; если аргумент один и это файл — текст берём из файла.

    Так большой промт не нужно печатать или вставлять в консоль: положили его
    в prompt.txt и запустили ``python -m elytrix prompt.txt``.
    """
    parts = [p for p in (args.task or []) if p.strip()]
    if len(parts) == 1:
        path = os.path.expanduser(parts[0])
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    return f.read(500000).strip()
            except OSError:
                pass
    return " ".join(parts).strip()


def _print(text: str = "") -> None:
    print(text, flush=True)


def resolve_key(args: argparse.Namespace, cfg: Config) -> Tuple[str, str]:
    """Ключ из аргумента, окружения или файла. Пустой результат — спросим в интерфейсе."""
    if args.key:
        save_key(args.key)
        return args.key.strip(), "аргумент"
    key, source = read_key(str(cfg.get("gateway.key_env", "SMARTAPI_KEY")))
    return key, {"env": "переменная окружения", "file": "файл профиля"}.get(source, source)


def resolve_workspace(args: argparse.Namespace, state: State) -> str:
    """Папка проекта: аргумент → последняя использованная → текущая."""
    if args.workspace:
        return os.path.abspath(os.path.expanduser(args.workspace))
    last = str(state.get("last_workspace") or "")
    if last and os.path.isdir(last):
        return last
    return os.getcwd()


def make_agent(args: argparse.Namespace, cfg: Config, catalog: Catalog, state: State,
               key: str, workspace: str) -> Tuple[SmartAPI, Toolbox, Agent]:
    """Собирает агента: шлюз, рабочая папка, инструменты, цикл."""
    gateway = SmartAPI(cfg, catalog, state, key=key)
    if args.no_cache:
        gateway.cache_enabled = False
    if args.no_stream:
        gateway.stream_default = False
    ws = Workspace(workspace, limits=dict(cfg.get("economy", {}) or {}))
    toolbox = Toolbox(ws, dict(cfg.get("economy", {}) or {}))
    agent = Agent(gateway, toolbox, cfg, catalog, state)
    if args.model:
        agent.model = args.model
    elif state.get("model"):
        agent.model = str(state.get("model"))
    if args.steps:
        agent.max_steps = max(1, args.steps)
    if args.limit >= 0:
        gateway.daily_limit = args.limit
        cfg.set("limits.daily_tokens", args.limit)
    if args.yes:
        agent.confirm_mode = "auto"
    elif args.readonly:
        agent.confirm_mode = "readonly"
    elif args.ask:
        agent.confirm_mode = "ask"
    elif state.get("confirm"):
        agent.confirm_mode = str(state.get("confirm"))
    else:
        agent.confirm_mode = str(cfg.get("ui.confirm", "ask"))
    return gateway, toolbox, agent


def make_theme(args: argparse.Namespace, cfg: Config, state: State) -> Theme:
    """Тема оформления: аргумент → сохранённая в профиле → конфиг."""
    name = args.theme or str(state.get("theme") or cfg.get("ui.theme", "dark"))
    color = args.color or str(cfg.get("ui.color", "auto"))
    return Theme(name, Palette(color), supports_unicode())


# ---------------------------------------------------------------------------
# Режимы без интерфейса
# ---------------------------------------------------------------------------


def run_doctor(cfg: Config, catalog: Catalog, state: State, gateway: SmartAPI,
               workspace: str, key_source: str) -> int:
    _print("ELYTRIX — диагностика")
    _print(f"  версия:        {__version__} · python {sys.version.split()[0]} · {sys.platform}")
    _print(f"  терминал:      цвет {gateway.cfg.get('ui.color', 'auto')} · "
           f"VT {'включён' if enable_vt() else 'недоступен'} · tty {'да' if is_tty() else 'нет'}")
    _print(f"  конфиг:        {cfg.path or config_path()}")
    _print(f"  профиль:       {home_dir()}")
    _print(f"  ключ:          {mask_key(gateway.key)} · источник: {key_source or 'не задан'}"
           + ("" if gateway.key else "  ← введите: ELYTRIX.bat спросит сам"))
    _print(f"  шлюз:          {gateway.base_url} (Anthropic) · {gateway.oai_url} (OpenAI)")
    _print(f"  папка:         {workspace}")
    model = catalog.resolve(cfg.get("models.default"))
    _print(f"  модель:        {model} ×{catalog.multiplier(model):g} · "
           f"контекст {catalog.context(model):,}".replace(",", " "))
    _print(f"  дневной лимит: {gateway.daily_limit:,} зачётных токенов".replace(",", " ")
           + ("" if gateway.daily_limit else " (выключен)"))
    _print(f"  расход сегодня:{state.tokens_day:>9,} зачётных, запросов {state.requests_day}".replace(",", " "))
    _print()

    _print("  каталог моделей шлюза…")
    try:
        ids = gateway.fetch_models(timeout=15)
    except Exception as e:  # noqa: BLE001
        ids = []
        _print(f"    не получен: {type(e).__name__}: {e}")
    if ids:
        added = catalog.add_models(ids)
        _print(f"    получен: {len(ids)} моделей" + (f", новых добавлено: {added}" if added else ""))
        _print(f"    первые: {', '.join(ids[:10])}")
        missing = [m for m in catalog.catalog if m not in ids]
        if missing:
            _print(f"    в конфиге, но нет у шлюза: {', '.join(missing[:6])}")
    else:
        _print("    шлюз не отдаёт список — работаем по конфигу (это не ошибка)")

    if gateway.key:
        _print()
        _print(f"  контрольный запрос к {model}…")
        ok, detail = gateway.probe(model, max_tokens=8)
        _print(f"    {'прошёл' if ok else 'НЕ ПРОШЁЛ'}: {detail}")
        _print(f"    кэш промпта: {'поддерживается шлюзом' if gateway.cache_supported else 'шлюз отверг пометки — отключён'}")
    _print()
    _print(f"  журнал сессий: {sessions_dir()}")
    _print(f"  резервные копии правок: {os.path.join(workspace, '.elytrix', 'backups')}")
    return 0 if gateway.key else 1


def run_models(cfg: Config, catalog: Catalog, state: State) -> int:
    _print("Модели SmartAPI (× — во сколько раз дороже обычного токена)")
    _print()
    _print("  Маршруты:")
    for alias, info in catalog.aliases.items():
        model = str(info.get("model") or alias)
        mark = "  ← сейчас" if model == catalog.resolve(cfg.get("models.default")) else ""
        _print(f"    {alias:<7} {model:<22} ×{catalog.multiplier(model):<5g} "
               f"{info.get('note', '')}{mark}")
    _print()
    _print("  Все модели (сначала дешёвые):")
    families: Dict[str, List[str]] = {}
    for model in catalog.all_models():               # уже отсортированы по коэффициенту
        families.setdefault(catalog.family(model), []).append(model)
    spent_by_model = state.by_model()
    for family, models in families.items():          # порядок семейств — по дешевейшей модели
        _print(f"    {family}:")
        for model in models:
            mult = catalog.multiplier(model)
            spent = spent_by_model.get(model, {}).get("tokens", 0)
            tail = f" · сегодня {spent:,}".replace(",", " ") if spent else ""
            _print(f"      {model:<22} ×{mult:<5g} {catalog.price_word(mult)}{tail}")
    _print()
    _print("  Сменить модель в консоли: /model · из командной строки: --model cheap")
    return 0


def run_task(args: argparse.Namespace, cfg: Config, catalog: Catalog, state: State,
             gateway: SmartAPI, toolbox: Toolbox, agent: Agent, task: str) -> int:
    """Одна задача в плоском режиме: ответ потоком, в конце — итог по расходу."""
    from .tui import PlainUI

    theme = make_theme(args, cfg, state)
    ui = PlainUI(agent, theme, stream=gateway.stream_default)
    _print(f"ELYTRIX {__version__} · {toolbox.ws.root} · {catalog.resolve(agent.model)} "
           f"×{catalog.multiplier(catalog.resolve(agent.model)):g}")
    _print(f"  задача: {task}")
    _print()
    report = ui.run_task(task)
    return 0 if not report.error else 1


# ---------------------------------------------------------------------------
# Главный сценарий
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    force_utf8()
    vt_ok = enable_vt()
    ensure_home()

    cfg = Config.load(args.config or None)
    state = State()
    catalog = Catalog(dict(cfg.get("models", {}) or {}))
    key, key_source = resolve_key(args, cfg)

    # рабочая папка: для роутера и диагностики она не обязательна
    workspace = ""
    try:
        workspace = resolve_workspace(args, state)
        if not os.path.isdir(workspace):
            workspace = os.getcwd()
    except OSError:
        workspace = os.getcwd()

    if args.router is not None:
        from .router import DEFAULT_PORT, serve_forever

        port = DEFAULT_PORT if args.router == -1 else int(args.router)
        gateway = SmartAPI(cfg, catalog, state, key=key)
        if not key:
            _print("  [ОШИБКА] ключ SMARTAPI_KEY не задан. Запустите ELYTRIX.bat — он спросит ключ,")
            _print("           либо создайте его в кабинете https://smartapi.shop/api-keys")
            return 1
        return serve_forever(cfg, catalog, state, gateway, host=args.host, port=port)

    if args.models:
        return run_models(cfg, catalog, state)

    gateway, toolbox, agent = make_agent(args, cfg, catalog, state, key, workspace)

    if args.doctor:
        return run_doctor(cfg, catalog, state, gateway, workspace, key_source)

    task = resolve_task(args)
    interactive = is_tty() and not args.plain and not task

    if not interactive:
        if not key:
            _print("  [ОШИБКА] нет ключа SmartAPI. Возьмите его на "
                   "https://smartapi.shop/api-keys и запустите ELYTRIX.bat — он спросит и сохранит.")
            return 1
        if not task:
            _print("  [ОШИБКА] вывод не в консоль, а задача не задана.")
            _print("           Пример: python -m elytrix \"исправь ошибку в api.py\"")
            return 1
        try:
            return run_task(args, cfg, catalog, state, gateway, toolbox, agent, task)
        except KeyboardInterrupt:
            _print("\n  остановлено")
            return 130
        except GatewayError as e:
            _print(f"\n  ОШИБКА: {e}")
            return 1

    # полноэкранная консоль
    from .tui import App

    if not vt_ok and os.name == "nt":
        # старая консоль Windows без VT: полноэкранный режим невозможен, но агент работает
        args.plain = True
    theme = make_theme(args, cfg, state)
    app = App(cfg, catalog, state, gateway, toolbox, agent, theme, key_source=key_source)
    if gateway.key:
        gateway.warm()          # рукопожатия TLS параллельно со стартовым экраном
    app.set_title(f"ELYTRIX · {catalog.resolve(agent.model)} · {os.path.basename(workspace)}")
    try:
        code = app.run()
    except KeyboardInterrupt:
        code = 0
    finally:
        gateway.close()
        state.set("last_model", catalog.resolve(agent.model))
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
