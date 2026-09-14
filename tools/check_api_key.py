#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_api_key.py — проверка чужого API-ключа/шлюза (лоты вида «Claude Opus 5 за 30 ₽»).

Что делает: прогоняет 12 тестов и говорит, соответствует ли ключ тому, что обещал продавец.
Что ищет:
  · подмену модели (просили Opus 5 — отвечает бесплатная модель);
  · шаренный пул (несколько параллельных запросов → 429/таймауты);
  · вранье в учёте токенов («коэффициенты», завышенный расход);
  · скрытое усечение контекста (агент не увидит ваши файлы целиком);
  · отсутствие поддержки tools — критично для агентов (Cline, opencode, наш агент);
  · посредника-перепродавца по отпечаткам в ответах и в текстах ошибок;
  · экономику: сколько на самом деле стоит то, что вам продали.

Только стандартная библиотека. Ничего не устанавливает, ничего не читает с диска,
кроме своего отчёта.

Использование:
    python tools/check_api_key.py --base-url https://адрес-шлюза/v1 --key ВАШ-КЛЮЧ \
        --model claude-opus-5 --claimed-tokens 8000000 --price-rub 20 --report report.json

ВАЖНО: только для проверки того, что вы уже оплатили. Не направляйте через такие ключи
рабочий код, пароли, .env и персональные данные: владелец шлюза видит все запросы.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

VERSION = "1.1.0"

# Адаптер форматов берём из роутера, чтобы не дублировать логику перевода.
_ROUTER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "router")
if _ROUTER_DIR not in sys.path:
    sys.path.insert(0, _ROUTER_DIR)
try:
    import freecoder_router as _fcr
    _HAS_ADAPTER = True
except Exception:  # noqa: BLE001
    _HAS_ADAPTER = False

# ---------------------------------------------------------------------------
# Отпечатки: по ним видно, чей каталог моделей перепродают
# ---------------------------------------------------------------------------

UPSTREAM_MARKERS = {
    "opencode/zen": ["opencode.ai", "zen/v1", "big-pickle", "gpt-6-astra", "claude-fable-5",
                     "nemotron-3-ultra-free", "deepseek-v4-flash-free", "mimo-v2.5-free",
                     "ling-3.0-flash"],
    "openrouter": ["openrouter.ai", ":free", "nousresearch", "poolside", "laguna"],
    "cloudflare": ["cloudflare", "workers.ai", "@cf/"],
    "nvidia": ["integrate.api.nvidia.com", "nim"],
    "google": ["generativelanguage.googleapis.com", "gemini-"],
}

# Официальные цены $ за 1M токенов (вход, выход) — для калькулятора экономики
OFFICIAL_PRICES = {
    "opus": (5.0, 25.0),
    "fable": (10.0, 50.0),
    "sonnet": (3.0, 15.0),
    "haiku": (1.0, 5.0),
    "gpt-5": (1.25, 10.0),
    "gpt-6": (2.0, 12.0),
    "gemini": (0.6, 3.6),
    "deepseek": (0.14, 0.28),
    "glm": (0.6, 2.2),
    "kimi": (0.6, 2.5),
}

USD_RUB = 80.0  # ориентировочный курс для прикидки; можно поменять

NEEDLE = "МАЯК-7F3A2B-КВАРЦ"
FILLER = ("The quick brown fox jumps over the lazy dog and keeps running through the field. ")


# ---------------------------------------------------------------------------
# Результаты
# ---------------------------------------------------------------------------

OK, WARN, FAIL, INFO = "OK", "WARN", "FAIL", "INFO"
BADGES = {OK: "✓ OK  ", WARN: "! WARN", FAIL: "✗ FAIL", INFO: "· инфо"}


@dataclass
class Result:
    name: str
    status: str
    detail: str
    extra: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Клиент шлюза
# ---------------------------------------------------------------------------


class Gateway:
    def __init__(self, base_url: str, key: str, timeout: int = 120, api_format: str = "openai"):
        self.base_url = base_url.rstrip("/")
        self.key = key
        self.timeout = timeout
        self.api_format = api_format  # openai | anthropic

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.key}",
            "x-api-key": self.key,
            "User-Agent": f"check-api-key/{VERSION}",
        }

    def get(self, path: str) -> Tuple[int, str, Dict[str, str]]:
        req = urllib.request.Request(self.base_url + path, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace"), dict(e.headers or {})
        except Exception as e:  # noqa: BLE001
            return 0, f"{type(e).__name__}: {e}", {}

    def chat(self, payload: Dict[str, Any], stream: bool = False,
             timeout: Optional[int] = None) -> Dict[str, Any]:
        if self.api_format == "anthropic" and _HAS_ADAPTER:
            url = (self.base_url + "/messages" if self.base_url.endswith("/v1")
                   else self.base_url + "/v1/messages")
            converted = _fcr.oai_to_anthropic(payload)
            converted["stream"] = False
            body = json.dumps(converted, ensure_ascii=False).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "x-api-key": self.key,
                "anthropic-version": "2023-06-01",
                "User-Agent": f"check-api-key/{VERSION}",
            }
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            t0 = time.time()
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    raw = json.loads(r.read().decode("utf-8", "replace"))
                oai = _fcr.anthropic_to_oai(raw, payload.get("model"))
                return {"status": 200, "json": oai, "text": json.dumps(oai, ensure_ascii=False),
                        "elapsed": time.time() - t0}
            except urllib.error.HTTPError as e:
                return {"status": e.code, "text": e.read().decode("utf-8", "replace"),
                        "elapsed": time.time() - t0, "error": True}
            except Exception as e:  # noqa: BLE001
                return {"status": 0, "text": f"{type(e).__name__}: {e}",
                        "elapsed": time.time() - t0, "error": True}

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.base_url + "/chat/completions", data=body,
                                     headers=self._headers(), method="POST")
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                if stream:
                    chunks, raw = [], b""
                    started = None
                    while True:
                        line = r.readline()
                        if not line:
                            break
                        if started is None:
                            started = time.time() - t0
                        raw += line
                        chunks.append(line.decode("utf-8", "replace"))
                    return {"status": r.status, "stream_text": "".join(chunks),
                            "first_chunk_s": started or 0.0, "elapsed": time.time() - t0}
                text = r.read().decode("utf-8", "replace")
                return {"status": r.status, "json": json.loads(text), "text": text,
                        "elapsed": time.time() - t0}
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", "replace")
            return {"status": e.code, "text": err, "elapsed": time.time() - t0, "error": True}
        except Exception as e:  # noqa: BLE001
            return {"status": 0, "text": f"{type(e).__name__}: {e}",
                    "elapsed": time.time() - t0, "error": True}

    def message_of(self, resp: Dict[str, Any]) -> str:
        try:
            return (resp["json"]["choices"][0]["message"].get("content") or "")
        except Exception:
            return ""


def est_tokens(text: str) -> int:
    """Оценка токенов: латиница ~4 символа/токен, кириллица ~2.5."""
    lat = sum(1 for c in text if ord(c) < 128)
    cyr = len(text) - lat
    return max(1, round(lat / 4 + cyr / 2.5))


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


def t_reachability(g: Gateway, model: str) -> List[Result]:
    out: List[Result] = []
    st, text, _ = g.get("/models")
    if st == 200:
        try:
            data = json.loads(text)
            ids = [m.get("id") for m in data.get("data", []) if isinstance(m, dict)]
            out.append(Result("Шлюз доступен, список моделей отдаётся", OK,
                              f"получено {len(ids)} моделей", {"models": ids}))
        except Exception:
            out.append(Result("Список моделей", WARN, f"ответ не JSON: {text[:200]}"))
    elif st in (401, 403):
        out.append(Result("Ключ отклонён", FAIL, f"HTTP {st}: {text[:200]}"))
    elif st == 0:
        out.append(Result("Шлюз не отвечает", FAIL, text[:200]))
    else:
        out.append(Result("GET /models", INFO, f"HTTP {st}: {text[:150]}"))
    return out


def t_models_contains(g: Gateway, model: str, models: List[str]) -> Result:
    if not models:
        return Result("Заявленная модель есть в каталоге", INFO, "каталог недоступен — проверить нельзя")
    hit = [m for m in models if model and m.lower() == model.lower()]
    close = [m for m in models if model and model.lower() in m.lower()]
    if hit:
        return Result("Заявленная модель есть в каталоге", OK, f"'{model}' найдена")
    if close:
        return Result("Заявленная модель есть в каталоге", WARN,
                      f"точного '{model}' нет, похожие: {', '.join(close[:5])}")
    return Result("Заявленная модель есть в каталоге", WARN,
                  f"'{model}' в каталоге отсутствует. Есть, например: {', '.join(models[:8])}")


def t_basic(g: Gateway, model: str) -> Tuple[Result, Dict[str, Any]]:
    r = g.chat({"model": model, "messages": [{"role": "user", "content": "Ответь ровно: OK"}],
                "max_tokens": 20})
    if r.get("error") or r["status"] != 200:
        return Result("Базовый запрос", FAIL, f"HTTP {r['status']}: {r['text'][:250]}"), r
    content = g.message_of(r).strip()
    usage = (r["json"].get("usage") or {})
    return Result("Базовый запрос", OK,
                  f"ответ за {r['elapsed']:.1f}с: {content[:60]!r}; usage={usage}"), r


def t_model_substitution(g: Gateway, model: str, basic: Dict[str, Any]) -> List[Result]:
    """Просили одну модель — что реально ответило?"""
    out: List[Result] = []
    answered = ""
    try:
        answered = basic["json"].get("model") or ""
    except Exception:
        pass
    if answered and model and answered.strip().lower() != model.strip().lower():
        out.append(Result("Подмена модели в ответе", FAIL,
                          f"просили '{model}', а ответ помечен как '{answered}' "
                          f"(шлюз перенаправил запрос на другую модель)"))
    elif answered:
        out.append(Result("Поле model в ответе", OK, f"'{answered}' — совпадает с запросом"))
    else:
        out.append(Result("Поле model в ответе", WARN, "шлюз не вернул имя модели"))

    ident = g.chat({"model": model, "messages": [
        {"role": "user", "content": "Ответь кратко, одной строкой: какая ты модель и версия? "
                                    "И кто производитель (OpenAI, Anthropic, Google, другой)?"}],
        "max_tokens": 120})
    said = g.message_of(ident).strip() if not ident.get("error") else ""
    if said:
        low = said.lower()
        claims_wrong = []
        if "opus" in (model or "").lower() and "claude" not in low and "anthropic" not in low:
            claims_wrong.append("заявлена Claude, а модель говорит о себе иначе")
        if "gpt" in (model or "").lower() and "gpt" not in low and "openai" not in low:
            claims_wrong.append("заявлен GPT, а модель говорит о себе иначе")
        if "deepseek" in low or "qwen" in low or "llama" in low or "glm" in low or "kimi" in low:
            claims_wrong.append("модель называет себя другой семьёй (дешёвая подмена)")
        out.append(Result("Самоидентификация модели",
                          WARN if claims_wrong else INFO,
                          f"говорит: {said[:180]}" + ("; ⚠ " + "; ".join(claims_wrong) if claims_wrong else "")))
    else:
        out.append(Result("Самоидентификация модели", INFO, "не удалось спросить"))
    return out


def t_tools(g: Gateway, model: str) -> List[Result]:
    """Критично для агентов: умеет ли шлюз tool calling и протокол role=tool."""
    tools = [{
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Прочитать файл",
            "parameters": {"type": "object",
                           "properties": {"path": {"type": "string"}},
                           "required": ["path"]},
        },
    }]
    r1 = g.chat({"model": model, "messages": [
        {"role": "user", "content": "Прочитай файл main.py — вызови инструмент read_file."}],
        "tools": tools, "tool_choice": "auto", "max_tokens": 200})
    if r1.get("error") or r1["status"] != 200:
        return [Result("Tool calling (нужен агентам)", FAIL,
                       f"запрос с tools отклонён: HTTP {r1['status']} {r1['text'][:200]}")]
    try:
        msg = r1["json"]["choices"][0]["message"]
    except Exception:
        return [Result("Tool calling (нужен агентам)", WARN, "неожиданный формат ответа")]
    calls = msg.get("tool_calls") or []
    out = []
    if not calls:
        out.append(Result("Tool calling (нужен агентам)", WARN,
                          "модель ответила текстом, а не вызовом инструмента — "
                          "агент сможет работать, но менее надёжно"))
        return out
    call = calls[0]
    out.append(Result("Tool calling (нужен агентам)", OK,
                      f"вызвала {call.get('function', {}).get('name')}"))
    # второй шаг: шлюз должен принять результаты инструмента
    r2 = g.chat({"model": model, "messages": [
        {"role": "user", "content": "Прочитай файл main.py."},
        {"role": "assistant", "content": None, "tool_calls": calls},
        {"role": "tool", "tool_call_id": call.get("id", "call_1"), "content": "print('hello')"},
    ], "tools": tools, "max_tokens": 150})
    if r2.get("error") or r2["status"] != 200:
        out.append(Result("Протокол role=tool", FAIL,
                          f"шлюз не принимает результаты инструментов: HTTP {r2['status']} "
                          f"{r2['text'][:200]}"))
    else:
        out.append(Result("Протокол role=tool", OK, "шлюз корректно принимает результаты инструментов"))
    return out


def t_stream(g: Gateway, model: str) -> List[Result]:
    r = g.chat({"model": model, "messages": [{"role": "user", "content": "Считай до пяти"}],
                "stream": True, "max_tokens": 60}, stream=True, timeout=90)
    if r.get("status") != 200:
        return [Result("Стриминг ответа", WARN,
                       f"не поддерживается (HTTP {r.get('status')}); агенту будет тяжелее")]
    text = r.get("stream_text", "")
    if "data:" not in text:
        return [Result("Стриминг ответа", WARN, "ответ не похож на поток SSE")]
    n_chunks = text.count("data:")
    return [Result("Стриминг ответа", OK,
                   f"{n_chunks} чанков, первый через {r.get('first_chunk_s', 0):.1f}с")]


def t_token_accounting(g: Gateway, model: str) -> List[Result]:
    """Врут ли в учёте токенов (главный способ «съесть» баланс)."""
    filler = FILLER * 60           # ~4200 символов латиницы ≈ ~1050 токенов
    r = g.chat({"model": model, "messages": [
        {"role": "user", "content": filler + "\n\nОтветь одним словом: сколько букв в слове 'кот'?"}],
        "max_tokens": 20})
    if r.get("error") or r["status"] != 200:
        return [Result("Честность учёта токенов", WARN, f"тест не прошёл: HTTP {r['status']}")]
    usage = r["json"].get("usage") or {}
    reported = usage.get("prompt_tokens")
    expected = est_tokens(filler) + 12
    if not reported:
        return [Result("Честность учёта токенов", WARN,
                       "шлюз не возвращает usage — проверить расход невозможно")]
    ratio = reported / expected
    if ratio > 2.5:
        return [Result("Честность учёта токенов", FAIL,
                       f"запрос ~{expected} токенов, а списано {reported} (×{ratio:.1f}). "
                       f"Похоже на «коэффициенты» — баланс будет таять в разы быстрее обещанного")]
    if ratio < 0.35:
        return [Result("Честность учёта токенов", WARN,
                       f"заявлено {reported} токенов при ~{expected} фактических — "
                       f"учёт занижен либо шлюз молча режет контекст: "
                       f"цифрам баланса доверять нельзя")]
    return [Result("Честность учёта токенов", OK,
                   f"запрос ~{expected} токенов, списано {reported} (×{ratio:.2f}) — похоже на правду")]


def t_context_needle(g: Gateway, model: str) -> List[Result]:
    """Не режет ли шлюз контекст молча (агент не увидит файлы целиком)."""
    out: List[Result] = []
    for where, body in (("в начале", NEEDLE + "\n" + FILLER * 420),
                        ("в середине", FILLER * 210 + "\n" + NEEDLE + "\n" + FILLER * 210)):
        r = g.chat({"model": model, "messages": [
            {"role": "user", "content": body + "\n\nКакое кодовое слово было в этом тексте? "
                                               "Ответь только этим словом."}],
            "max_tokens": 40}, timeout=180)
        if r.get("error") or r["status"] != 200:
            out.append(Result(f"Контекст ~30k знаков ({where})", WARN,
                              f"запрос не прошёл: HTTP {r['status']} {r['text'][:120]}"))
            continue
        answer = g.message_of(r).upper()
        if "7F3A2B" in answer or "КВАРЦ" in answer:
            out.append(Result(f"Контекст ~30k знаков ({where})", OK, "кодовое слово найдено"))
        else:
            out.append(Result(f"Контекст ~30k знаков ({where})", WARN,
                              f"модель не нашла слово ({answer.strip()[:60]!r}) — "
                              f"возможно усечение контекста или слабая модель; "
                              f"для агента это значит «не видит весь файл»"))
    return out


def t_concurrency(g: Gateway, model: str, parallel: int = 5) -> List[Result]:
    """Общий пул у нескольких покупателей выдаёт себя отказами под нагрузкой."""
    def one(i: int) -> Tuple[int, float]:
        r = g.chat({"model": model, "messages": [
            {"role": "user", "content": f"Ответь одним словом: тест {i}"}], "max_tokens": 10},
            timeout=90)
        return r["status"], r["elapsed"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as ex:
        results = list(ex.map(one, range(parallel)))
    ok_n = sum(1 for s, _ in results if s == 200)
    rate_limited = sum(1 for s, _ in results if s == 429)
    others = [s for s, _ in results if s not in (200, 429)]
    slow = sum(1 for s, e in results if s == 200 and e > 25)
    detail = f"{ok_n}/{parallel} успешно, 429: {rate_limited}" + (f", прочее: {others}" if others else "")
    if rate_limited:
        return [Result("Поведение под нагрузкой", FAIL,
                       detail + " — на 5 параллельных запросов приходит лимит. "
                       "Для агента (сотни запросов за сессию) это значит обрывы в работе")]
    if ok_n < parallel:
        return [Result("Поведение под нагрузкой", FAIL, detail + " — часть запросов не прошла")]
    if slow:
        return [Result("Поведение под нагрузкой", WARN, detail + f", {slow} медленнее 25с")]
    return [Result("Поведение под нагрузкой", OK, detail + " — пул не выглядит перегруженным")]


def t_error_leak(g: Gateway, model: str) -> List[Result]:
    """Тексты ошибок часто выдают посредника и upstream."""
    r = g.chat({"model": model, "messages": [{"role": "user", "content": "тест"}],
                "temperature": 99, "max_tokens": 5})
    text = (r.get("text") or "")[:1500]
    if not text:
        return [Result("Утечки в текстах ошибок", INFO, "ошибку вызвать не удалось")]
    low = text.lower()
    found = []
    for upstream, markers in UPSTREAM_MARKERS.items():
        for m in markers:
            if m.lower() in low:
                found.append(f"{m} → {upstream}")
    suspicious = re.findall(r"(account[\w_]*id|org[\w_-]*|acc_[0-9a-f]+|sk-[a-z0-9\-]{8,})", low)
    if found or suspicious:
        return [Result("Утечки в текстах ошибок", WARN,
                       "в тексте ошибки видны следы upstream-посредника: "
                       + "; ".join(sorted(set(found))[:5] + sorted(set(suspicious))[:3])
                       + f" | фрагмент: {text[:200]!r}")]
    return [Result("Утечки в текстах ошибок", OK, f"чисто: {text[:120]!r}")]


def t_credits(g: Gateway) -> List[Result]:
    out: List[Result] = []
    for path in ("/credits", "/me", "/balance", "/user", "/dashboard/billing/credit_grants"):
        st, text, _ = g.get(path)
        if st == 200 and text.strip():
            out.append(Result(f"Баланс доступен ({path})", INFO, text[:200]))
            return out
    out.append(Result("Баланс через API", INFO,
                      "не найден — расход придётся смотреть в кабинете продавца"))
    return out


# ---------------------------------------------------------------------------
# Экономика: сколько на самом деле стоит то, что продали
# ---------------------------------------------------------------------------


def economics(model: str, claimed_tokens: Optional[int], price_rub: Optional[float]) -> List[Result]:
    out: List[Result] = []
    if not claimed_tokens or not price_rub:
        return out
    low = (model or "").lower()
    price_in, price_out = None, None
    for key, pair in OFFICIAL_PRICES.items():
        if key in low:
            price_in, price_out = pair
            break
    if price_in is None:
        price_in, price_out = 3.0, 15.0  # средний ориентир
    # при работе агента выход примерно в 4 раза меньше входа
    usd = (claimed_tokens / 1_000_000) * (price_in * 0.8 + price_out * 0.2)
    rub_official = usd * USD_RUB
    ratio = rub_official / price_rub if price_rub else 0
    out.append(Result("Экономика лота", FAIL if ratio > 4 else WARN,
                      f"{claimed_tokens:,} токенов по официальным ценам стоят ≈ ${usd:,.0f} "
                      f"(≈ {rub_official:,.0f} ₽), а продано за {price_rub:,.0f} ₽ — "
                      f"в {ratio:,.0f} раз дешевле себестоимости. Так не бывает: "
                      f"значит это чужой/общий аккаунт либо подмена на бесплатную модель"))
    return out


# ---------------------------------------------------------------------------
# Оркестратор
# ---------------------------------------------------------------------------


def run_check(base_url: str, key: str, model: str, claimed_tokens: Optional[int],
              price_rub: Optional[float], parallel: int = 5,
              skip_heavy: bool = False, api_format: str = "openai") -> Dict[str, Any]:
    g = Gateway(base_url, key, api_format=api_format)
    results: List[Result] = []
    models: List[str] = []

    print(f"\n{'=' * 70}\nПроверка ключа: {base_url}\nМодель: {model}\n{'=' * 70}\n")

    r0 = t_reachability(g, model)
    results += r0
    for r in r0:
        if r.extra.get("models"):
            models = r.extra["models"]
    results.append(t_models_contains(g, model, models))

    r1, basic = t_basic(g, model)
    results.append(r1)
    if r1.status == FAIL:
        print_report(results, models)
        return {"base_url": base_url, "model": model, "results": [rr.__dict__ for rr in results],
                "aborted": True}

    results += t_model_substitution(g, model, basic)
    results += t_tools(g, model)
    results += t_stream(g, model)
    results += t_token_accounting(g, model)
    if not skip_heavy:
        results += t_context_needle(g, model)
        results += t_concurrency(g, model, parallel)
    results += t_error_leak(g, model)
    results += t_credits(g)
    results += economics(model, claimed_tokens, price_rub)

    print_report(results, models)
    return {"version": VERSION, "base_url": base_url, "model": model,
            "claimed_tokens": claimed_tokens, "price_rub": price_rub,
            "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "models_available": models,
            "results": [rr.__dict__ for rr in results]}


def print_report(results: List[Result], models: List[str]) -> None:
    fails = [r for r in results if r.status == FAIL]
    warns = [r for r in results if r.status == WARN]
    for r in results:
        print(f"  {BADGES[r.status]}  {r.name}")
        if r.detail:
            for i, line in enumerate(r.detail.split("\n")):
                print(f"            {line}" if i == 0 else f"            {line}")

    print("\n" + "-" * 70)
    print(f"ИТОГО: провалено {len(fails)}, предупреждений {len(warns)}")
    if fails:
        print("\n🚩 Красные флаги:")
        for r in fails:
            print(f"   • {r.name}: {r.detail[:200]}")
    if fails:
        print("""
Что делать: сохраните отчёт (--report report.json) и напишите продавцу требование
возврата, приложив его. Формулировка: «ключ не соответствует описанию: подмена модели /
лимиты под нагрузкой / завышенный расход токенов». Если продавец откажет — у продавца
на FunPay есть система арбитража, отчёт будет доказательством.
Ключ после проверки не используйте для рабочего кода: владелец шлюза видит все запросы.""")
    else:
        print("\nЯвных подмен и лимитов не найдено. Но помните: это чужая инфраструктура — "
              "ваш код и промпты через неё видит владелец. Для рабочего кода — официальные "
              "официальный доступ к модели.")


def list_models(base_url: str, key: str, api_format: str = "openai") -> int:
    """Печатает список моделей шлюза: самые частые причины ошибки 400 — неверный ID модели."""
    g = Gateway(base_url, key, api_format=api_format)
    bases = [base_url.rstrip("/")]
    if base_url.rstrip("/").endswith("/v1"):
        bases.append(base_url.rstrip("/")[:-3].rstrip("/"))
    else:
        bases.append(base_url.rstrip("/") + "/v1")

    last_text = ""
    for base in bases:
        st, text, _ = Gateway(base, key, api_format=api_format).get("/models")
        last_text = text
        ids: List[str] = []
        try:
            data = json.loads(text)
            for item in (data.get("data") or data.get("models") or []):
                if isinstance(item, dict):
                    mid = item.get("id") or item.get("name")
                    if mid:
                        ids.append(str(mid))
                elif isinstance(item, str):
                    ids.append(item)
        except Exception:  # noqa: BLE001
            pass
        if ids:
            print(f"\nШлюз: {base}")
            print(f"Моделей доступно: {len(ids)}\n")
            for mid in ids:
                print(f"  {mid}")
            print("\nСкопируйте нужный ID в поле \"models\" файла router/providers.smartapi.json"
                  "\n(или возьмите имя со страницы «Модели» в кабинете).")
            return 0
    print(f"\nКаталог моделей по адресу {base_url} не отдаётся (HTTP-ответ ниже).")
    print("Это нормально для Anthropic-формата: возьмите ID модели со страницы «Модели»")
    print("в кабинете SmartAPI и впишите его в router/providers.smartapi.json.")
    print(f"\nОтвет шлюза: {last_text[:400]}")
    return 2


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Проверка стороннего API-ключа/шлюза («промокодные» лоты)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Пример:\n"
               "  python tools/check_api_key.py --base-url https://шлюз/v1 --key sk-xxx \\\n"
               "      --model claude-opus-5 --claimed-tokens 8000000 --price-rub 20 \\\n"
               "      --report report.json\n")
    ap.add_argument("--base-url", help="адрес шлюза, обычно .../v1")
    ap.add_argument("--key", help="ключ, полученный от продавца")
    ap.add_argument("--model", help="модель, которую обещали")
    ap.add_argument("--list-models", action="store_true",
                    help="только показать доступные ID моделей шлюза и выйти")
    ap.add_argument("--claimed-tokens", type=int, default=None, help="сколько токенов обещано")
    ap.add_argument("--price-rub", type=float, default=None, help="сколько вы заплатили, ₽")
    ap.add_argument("--parallel", type=int, default=5, help="число параллельных запросов (по умолчанию 5)")
    ap.add_argument("--quick", action="store_true", help="без тяжёлых тестов (контекст и нагрузка)")
    ap.add_argument("--format", choices=["openai", "anthropic"], default="openai",
                    help="формат шлюза: openai (обычный, /v1/chat/completions) "
                         "или anthropic (/v1/messages)")
    ap.add_argument("--report", default=None, help="куда сохранить JSON-отчёт")
    ap.add_argument("--version", action="version", version=f"check_api_key {VERSION}")
    args = ap.parse_args(argv)

    if args.list_models:
        if not args.base_url or not args.key:
            ap.error("--list-models требует --base-url и --key")
        return list_models(args.base_url, args.key, args.format)

    if not args.base_url or not args.key or not args.model:
        ap.error("нужны --base-url, --key и --model (либо --list-models для вывода каталога)")

    report = run_check(args.base_url, args.key, args.model, args.claimed_tokens,
                       args.price_rub, args.parallel, args.quick, args.format)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\nОтчёт сохранён: {args.report}")
    return 1 if any(r["status"] == FAIL for r in report.get("results", [])) else 0


if __name__ == "__main__":
    sys.exit(main())
