# -*- coding: utf-8 -*-
"""Виджеты отрисовки: markdown, подсветка кода, diff, рамки, шкалы.

Всё работает на «сегментах» из screen.py, поэтому любой виджет можно нарисовать
и в полноэкранной TUI, и в плоском режиме (когда вывод перенаправлен в файл).

Осознанно без сторонних библиотек: свой компактный markdown-рендерер даёт ровно тот
вид, который нужен агенту (заголовки, списки, блоки кода, таблицы, diff), и не тянет
за собой зависимости, которые пришлось бы ставить в ELYTRIX.bat.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .screen import Line, Segment, Style, text_width, truncate, wrap_line
from .theme import Theme

# ---------------------------------------------------------------------------
# Подсветка кода
# ---------------------------------------------------------------------------

KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "py": ("def class return if elif else for while in not and or is None True False "
            "import from as with try except finally raise lambda yield pass break continue "
            "global nonlocal assert del async await self print").split(),
    "js": ("const let var function return if else for while of in new class extends import "
            "export from default async await try catch finally throw typeof instanceof "
            "this null undefined true false switch case break continue yield").split(),
    "ts": ("const let var function return if else for while of in new class extends import "
           "export from default async await try catch finally throw typeof instanceof this "
           "null undefined true false interface type enum implements public private readonly "
           "as switch case break continue namespace declare").split(),
    "go": ("func package import return if else for range var const type struct interface "
           "map chan go defer switch case break continue nil true false string int error").split(),
    "rs": ("fn let mut const struct enum impl trait pub use mod match if else for while loop "
           "return self Self Some None Ok Err true false where async await move ref").split(),
    "sh": ("if then else elif fi for while do done case esac function return echo export "
           "local set shift cd rm cp mv mkdir sudo python pip git npm").split(),
    "sql": ("select from where insert into values update set delete create table alter drop "
            "join left right inner outer on group by order having limit as and or not null "
            "distinct count sum avg").split(),
    "html": ("html head body div span script style link meta class id href src type name "
             "value input form button table tr td ul li p a img").split(),
    "json": ("true false null").split(),
}

LANG_ALIASES = {
    "python": "py", "py": "py", "python3": "py",
    "javascript": "js", "js": "js", "jsx": "js", "node": "js", "mjs": "js", "cjs": "js",
    "typescript": "ts", "ts": "ts", "tsx": "ts",
    "golang": "go", "go": "go",
    "rust": "rs", "rs": "rs",
    "bash": "sh", "sh": "sh", "shell": "sh", "zsh": "sh", "console": "sh", "bat": "sh",
    "powershell": "sh", "ps1": "sh",
    "sql": "sql",
    "html": "html", "xml": "html", "vue": "html", "svelte": "html", "css": "html",
    "scss": "html", "json": "json", "yaml": "json", "yml": "json", "toml": "json",
}

_TOKEN_RE = re.compile(
    r"""(?P<comment>\#[^\n]*|//[^\n]*|/\*.*?\*/|--[^\n]*|;[^\n]*)"""
    r"""|(?P<string>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|\"\"\".*?\"\"\"|'''.*?''')"""
    r"""|(?P<number>\b0[xX][0-9a-fA-F]+\b|\b\d+(?:\.\d+)?(?:[eE][-+]?\d+)?\b)"""
    r"""|(?P<decorator>@\w+)"""
    r"""|(?P<name>[A-Za-z_А-Яа-яЁё][\wА-Яа-яЁё.]*)"""
    r"""|(?P<space>\s+)"""
    r"""|(?P<punct>[^\w\s])""",
    re.S,
)


def highlight(code: str, lang: str, theme: Theme, width: int) -> List[Line]:
    """Красит код по-простому: комментарии, строки, числа, ключевые слова, вызовы."""
    lang_key = LANG_ALIASES.get((lang or "").lower().strip(), "")
    keywords = set(KEYWORDS.get(lang_key, ()))
    st_comment = theme.style("comment", italic=True)
    st_string = theme.style("string")
    st_number = theme.style("number")
    st_keyword = theme.style("keyword", bold=True)
    st_name = theme.style("function")
    st_plain = theme.style("code_fg")
    st_punct = theme.style("dim")
    st_dec = theme.style("accent2")

    out: List[Line] = []
    for raw in code.split("\n"):
        line: Line = []
        pos = 0
        for m in _TOKEN_RE.finditer(raw):
            if m.start() > pos:
                line.append((raw[pos:m.start()], st_plain))
            kind = m.lastgroup or ""
            text = m.group()
            if kind == "comment":
                line.append((text, st_comment))
            elif kind == "string":
                line.append((text, st_string))
            elif kind == "number":
                line.append((text, st_number))
            elif kind == "decorator":
                line.append((text, st_dec))
            elif kind == "name":
                after = raw[m.end():m.end() + 1]
                if text in keywords:
                    line.append((text, st_keyword))
                elif after == "(":
                    line.append((text, st_name))
                else:
                    line.append((text, st_plain))
            elif kind == "space":
                line.append((text, st_plain))
            else:
                line.append((text, st_punct))
            pos = m.end()
        if pos < len(raw):
            line.append((raw[pos:], st_plain))
        out.extend(wrap_line(line or [("", st_plain)], width))
    return out


# ---------------------------------------------------------------------------
# Инлайн-markdown
# ---------------------------------------------------------------------------

_INLINE_RE = re.compile(
    r"(`[^`\n]+`)"                       # `код`
    r"|(\*\*[^*\n]+\*\*)"                # **жирный**
    r"|(__[^_\n]+__)"                    # __жирный__
    r"|(\*[^*\n]+\*)"                    # *курсив*
    r"|(~~[^~\n]+~~)"                    # ~~зачёркнутый~~
    r"|(\[[^\]\n]*\]\([^)\n]+\))"        # [ссылка](url)
)

_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")


def inline(text: str, theme: Theme, base: Optional[Style] = None) -> Line:
    """Разбирает inline-markdown в стилизованные сегменты."""
    base = base or theme.style("assistant")
    code_st = theme.style("accent")
    bold_st = base.copy(bold=True)
    italic_st = base.copy(italic=True)
    strike_st = theme.style("dim")
    link_st = theme.style("info", underline=True)
    url_st = theme.style("faint")

    out: Line = []
    pos = 0
    for m in _INLINE_RE.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], base))
        token = m.group()
        if token.startswith("`"):
            out.append((token[1:-1], code_st))
        elif token.startswith(("**", "__")):
            out.append((token[2:-2], bold_st))
        elif token.startswith("~~"):
            out.append((token[2:-2], strike_st))
        elif token.startswith("*"):
            out.append((token[1:-1], italic_st))
        else:
            lm = _LINK_RE.match(token)
            if lm:
                out.append((lm.group(1) or lm.group(2), link_st))
                if lm.group(1) and lm.group(1) != lm.group(2):
                    out.append((" " + lm.group(2), url_st))
            else:
                out.append((token, base))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], base))
    return out or [("", base)]


# ---------------------------------------------------------------------------
# Markdown-блоки
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^\s*(```+|~~~+)\s*([\w+#.-]*)\s*$")
_HEAD_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_LIST_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
_RULE_RE = re.compile(r"^\s*([-*_])\s*(\1\s*){2,}$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")


def _split_table_row(row: str) -> List[str]:
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [c.strip() for c in row.split("|")]


def render_markdown(text: str, theme: Theme, width: int, indent: str = "") -> List[Line]:
    """Рендерит markdown-текст ответа модели в строки сегментов."""
    cs = theme.charset
    lines: List[Line] = []
    src = (text or "").split("\n")
    i = 0
    inner_w = max(10, width - text_width(indent) - 2)

    while i < len(src):
        raw = src[i]

        fence = _FENCE_RE.match(raw)
        if fence:
            marker, lang = fence.group(1)[0], fence.group(2)
            body: List[str] = []
            i += 1
            while i < len(src) and not _FENCE_RE.match(src[i]):
                body.append(src[i])
                i += 1
            i += 1                                   # закрывающая рамка
            bar = theme.style("border")
            label = lang or "код"
            head_len = max(0, inner_w - len(label) - 4)
            lines.append([(f"{indent}{cs.tl if cs.tl != '+' else '+'}", bar),
                          (f" {label} ", theme.style("faint")),
                          (cs.h * head_len, bar),
                          (cs.tr if cs.tr != "+" else "+", bar)])
            code_w = max(10, inner_w - 2)
            for code_line in highlight("\n".join(body), lang, theme, code_w):
                lines.append([(f"{indent}{cs.v} ", bar)] + code_line)
            lines.append([(f"{indent}{cs.bl if cs.bl != '+' else '+'}", bar),
                          (cs.h * max(0, inner_w), bar),
                          (cs.br if cs.br != "+" else "+", bar)])
            continue

        if _RULE_RE.match(raw):
            lines.append([(indent + cs.h * inner_w, theme.style("border"))])
            i += 1
            continue

        head = _HEAD_RE.match(raw)
        if head:
            level = len(head.group(1))
            style = theme.style("accent" if level <= 2 else "accent2", bold=True)
            prefix = "" if level <= 2 else cs.bullet + " "
            for wl in wrap_line([(prefix + head.group(2).strip(), style)], inner_w):
                lines.append([(indent, theme.style("dim"))] + wl)
            i += 1
            continue

        quote = _QUOTE_RE.match(raw)
        if quote:
            for wl in wrap_line(inline(quote.group(1), theme, theme.style("dim", italic=True)),
                                inner_w - 2):
                lines.append([(indent + cs.v + " ", theme.style("border"))] + wl)
            i += 1
            continue

        # таблица
        if raw.strip().startswith("|") and i + 1 < len(src) and _TABLE_SEP_RE.match(src[i + 1]):
            rows = [_split_table_row(raw)]
            i += 2
            while i < len(src) and src[i].strip().startswith("|"):
                rows.append(_split_table_row(src[i]))
                i += 1
            lines.extend(_render_table(rows, theme, indent, inner_w))
            continue

        item = _LIST_RE.match(raw)
        if item:
            spaces, marker, body_text = item.groups()
            depth = min(3, len(spaces.replace("\t", "    ")) // 2)
            bullet = (cs.bullet if marker in "-*+" else marker)
            pad = indent + "  " * depth
            first = [(pad + bullet + " ", theme.style("accent"))]
            wrapped = wrap_line(inline(body_text, theme), inner_w - text_width(pad) - 2)
            lines.append(first + (wrapped[0] if wrapped else []))
            cont = pad + " " * (text_width(bullet) + 1)
            for extra in wrapped[1:]:
                lines.append([(cont, theme.style("dim"))] + extra)
            i += 1
            continue

        if not raw.strip():
            lines.append([("", theme.style("fg"))])
            i += 1
            continue

        wrapped = wrap_line(inline(raw, theme), inner_w)
        for wl in wrapped:
            lines.append([(indent, theme.style("dim"))] + wl)
        i += 1

    return lines


def _render_table(rows: List[List[str]], theme: Theme, indent: str, width: int) -> List[Line]:
    cs = theme.charset
    if not rows:
        return []
    cols = max(len(r) for r in rows)
    rows = [r + [""] * (cols - len(r)) for r in rows]
    widths = [max(text_width(r[c]) for r in rows) for c in range(cols)]
    total = sum(widths) + 2 * cols + 1
    if total > width:                       # сжимаем пропорционально
        scale = max(0.3, (width - 2 * cols - 1) / max(1, sum(widths)))
        widths = [max(3, int(w * scale)) for w in widths]
    head_st = theme.style("accent", bold=True)
    cell_st = theme.style("fg")
    border_st = theme.style("border")

    def hline(left: str, mid: str, right: str) -> Line:
        out: Line = [(indent + left, border_st)]
        for c, w in enumerate(widths):
            # на ячейку приходится w+1 дефисов и разделитель — ровно как «пробел+текст+│» в строке
            out.append((cs.h * (w + 1), border_st))
            out.append((mid if c < cols - 1 else right, border_st))
        return out

    def row_line(cells: Sequence[str], style: Style) -> Line:
        out: Line = [(indent + cs.v, border_st)]
        for c, cell in enumerate(cells):
            out.append((" ", style))
            out.append((truncate(cell, widths[c]), style))
            out.append((" " * max(0, widths[c] - text_width(cell)), style))
            out.append((cs.v, border_st))
        return out

    lines = [hline(cs.tl if cs.tl != "+" else "+", cs.tt if cs.tt != "+" else "+",
                   cs.tr if cs.tr != "+" else "+")]
    lines.append(row_line(rows[0], head_st))
    lines.append(hline(cs.lt if cs.lt != "+" else "+", cs.cross, cs.rt if cs.rt != "+" else "+"))
    for r in rows[1:]:
        lines.append(row_line(r, cell_st))
    lines.append(hline(cs.bl if cs.bl != "+" else "+", cs.bt if cs.bt != "+" else "+",
                       cs.br if cs.br != "+" else "+"))
    return lines


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------


def render_diff(diff_text: str, theme: Theme, width: int, indent: str = "  ",
                max_lines: int = 0) -> List[Line]:
    """Красит unified diff: добавленное зелёным, удалённое красным, контекст тусклым."""
    add = theme.style("diff_add")
    rem = theme.style("diff_del")
    meta = theme.style("diff_meta", bold=True)
    ctx = theme.style("dim")
    out: List[Line] = []
    rows = (diff_text or "").split("\n")
    if max_lines and len(rows) > max_lines:
        rows = rows[:max_lines] + [f"… ещё {len(rows) - max_lines} строк (полностью — /diff)"]
    for raw in rows:
        if raw.startswith(("--- ", "+++ ", "diff ", "index ", "rename ", "new file", "deleted")):
            style = meta
        elif raw.startswith("@@"):
            style = theme.style("accent2")
        elif raw.startswith("+"):
            style = add
        elif raw.startswith("-"):
            style = rem
        elif raw.startswith("…"):
            style = theme.style("faint")
        else:
            style = ctx
        for wl in wrap_line([(raw, style)], width - text_width(indent)):
            out.append([(indent, theme.style("faint"))] + wl)
    return out


# ---------------------------------------------------------------------------
# Мелочи интерфейса
# ---------------------------------------------------------------------------


def bar(frac: float, width: int, theme: Theme, role: str = "accent") -> Line:
    """Шкала расхода: заполненная часть цветом роли, остаток тусклый."""
    cs = theme.charset
    frac = 0.0 if frac != frac else max(0.0, min(1.0, frac))
    filled = int(round(frac * width))
    full = theme.style(role)
    empty = theme.style("faint")
    return [(cs.bar_full * filled, full), (cs.bar_empty * max(0, width - filled), empty)]


def sep(theme: Theme, width: int, title: str = "") -> Line:
    """Тонкая линия-разделитель, можно с подписью."""
    cs = theme.charset
    if not title:
        return [(cs.h * width, theme.style("border"))]
    left = f" {title} "
    rest = max(0, width - text_width(left) - 2)
    return [(cs.h * 2, theme.style("border")),
            (left, theme.style("dim")),
            (cs.h * rest, theme.style("border"))]


def box(lines: Iterable[Line], theme: Theme, width: int, title: str = "",
        role: str = "border", padding: int = 1) -> List[Line]:
    """Рамка вокруг готовых строк (диалоги, панели помощи)."""
    cs = theme.charset
    border = theme.style(role)
    title_st = theme.style("accent", bold=True)
    inner = max(4, width - 2 - padding * 2)
    out: List[Line] = []
    head = cs.tl + cs.h
    if title:
        head += f" {title} "
    head += cs.h * max(0, width - text_width(head) - 1) + cs.tr
    out.append([(head, border)])
    body: List[Line] = []
    for line in lines:
        body.extend(wrap_line(line, inner))
    for line in body:
        out.append([(cs.v, border), (" " * padding, theme.style("fg"))] + line
                   + [(" " * padding, theme.style("fg")), (cs.v, border)])
    if not body:
        out.append([(cs.v, border), (" " * (width - 2), theme.style("fg")), (cs.v, border)])
    out.append([(cs.bl + cs.h * max(0, width - 2) + cs.br, border)])
    return out


def kv_line(pairs: Iterable[Tuple[str, str]], theme: Theme, sep_str: str = "  ") -> Line:
    """Строка вида «ключ значение · ключ значение»."""
    out: Line = []
    for i, (key, value) in enumerate(pairs):
        if i:
            out.append((sep_str, theme.style("faint")))
        out.append((key + " ", theme.style("dim")))
        out.append((value, theme.style("fg")))
    return out


def human_number(n: float) -> str:
    """12 345 -> 12.3K, 1 200 000 -> 1.2M. Без разделителей — компактнее."""
    n = float(n or 0)
    if abs(n) < 1000:
        return f"{n:.0f}"
    for unit in ("K", "M", "G"):
        n /= 1000.0
        if abs(n) < 1000:
            return (f"{n:.0f}{unit}" if abs(n) >= 100 else f"{n:.1f}{unit}").replace(".0", "")
    return f"{n:.1f}T"


def human_money(n: float) -> str:
    return f"{n:,.0f}".replace(",", " ")


def plural(n: int, one: str, few: str, many: str) -> str:
    """«1 шаг / 2 шага / 5 шагов»."""
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not (12 <= n100 <= 14):
        return few
    return many


def seconds_text(sec: float) -> str:
    if sec < 10:
        return f"{sec:.1f}с"
    if sec < 60:
        return f"{sec:.0f}с"
    return f"{int(sec // 60)}м{int(sec % 60):02d}с"
