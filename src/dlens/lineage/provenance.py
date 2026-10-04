"""Locate an output column in the model's SOURCE .sql (what a user opens), not compiled SQL.

Compiled lines drift from source lines whenever Jinja expands to several lines, so citations
use the source file. The source contains Jinja and cannot be parsed by sqlglot, so this is a
small depth-aware scanner: it splits every SELECT list into top-level items and records each
item's line range and output name. Jinja blocks, strings and comments are skipped as opaque.
"""

import re
from dataclasses import dataclass

_ALIAS = re.compile(r"\bas\s+[\"`]?(\w+)[\"`]?\s*$", re.IGNORECASE | re.DOTALL)
_BARE = re.compile(r"^(?:distinct\s+)?(?:[\"`]?\w+[\"`]?\.)*[\"`]?(\w+)[\"`]?$", re.IGNORECASE)
# ``*``, ``t.*``, optionally with DuckDB modifiers: ``* EXCLUDE (a, b)``, ``t.* REPLACE (x AS y)``.
_STAR = re.compile(
    r"^(?:[\"`]?\w+[\"`]?\.)?\*(?:\s*\b(?:exclude|replace)\s*\(.*\))*$", re.IGNORECASE | re.DOTALL
)
_WORD = re.compile(r"[A-Za-z_]\w*")
_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/|\{#.*?#\}", re.DOTALL)


@dataclass(frozen=True)
class SelectItem:
    name: str | None  # output column name, None if it can't be read (e.g. Jinja-built alias)
    is_star: bool
    lines: tuple[int, int]


@dataclass(frozen=True)
class Citation:
    lines: tuple[int, int]
    model_level: bool


def _skip(text: str, i: int) -> int:
    """If an opaque span (string, comment, Jinja) starts at i, return its end; else i."""
    for start, end in (("{{", "}}"), ("{%", "%}"), ("{#", "#}"), ("/*", "*/")):
        if text.startswith(start, i):
            j = text.find(end, i + 2)
            return len(text) if j < 0 else j + len(end)
    if text.startswith("--", i):
        j = text.find("\n", i)
        return len(text) if j < 0 else j
    if text[i] in "'\"`":
        j = text.find(text[i], i + 1)
        return len(text) if j < 0 else j + 1
    return i


def select_items(text: str) -> list[SelectItem]:
    """Every projection item of every SELECT in the file, in source order."""
    items: list[SelectItem] = []
    open_lists: dict[int, int] = {}  # paren depth -> offset where the current item starts
    depth = 0

    def close(depth_: int, end: int) -> None:
        start = open_lists[depth_]
        raw = text[start:end]
        stripped = raw.strip()
        if stripped:
            lead = start + len(raw) - len(raw.lstrip())
            tail = start + len(raw.rstrip())
            lines = (text.count("\n", 0, lead) + 1, text.count("\n", 0, tail - 1) + 1)
            star = bool(_STAR.match(_COMMENT.sub("", stripped).strip()))
            items.append(SelectItem(_item_name(stripped), star, lines))

    i = 0
    while i < len(text):
        j = _skip(text, i)
        if j != i:
            i = j
            continue
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth in open_lists:
                close(depth, i)
                del open_lists[depth]
            depth -= 1
        elif ch == "," and depth in open_lists:
            close(depth, i)
            open_lists[depth] = i + 1
        elif ch.isalpha() or ch == "_":
            word = _WORD.match(text, i)
            assert word is not None
            kw = word.group().lower()
            if kw == "select":
                open_lists[depth] = word.end()
            elif kw in ("from", "union", "except", "intersect") and depth in open_lists:
                close(depth, i)
                del open_lists[depth]
            i = word.end()
            continue
        i += 1
    for d in list(open_lists):
        close(d, len(text))
    return items


def _item_name(item: str) -> str | None:
    item = _COMMENT.sub("", item).strip()
    if "{{" in item or "{%" in item:
        return None
    for pattern in (_ALIAS, _BARE):
        m = pattern.search(item)
        if m:
            return m.group(1).lower()
    return None


def locate(source: str, column: str, branch: int | None = None) -> Citation:
    """Line range of the item that produces `column`.

    The last named match wins, because the final SELECT comes last in dbt style (CTEs that
    compute the same name come first). For the k-th UNION branch, the k-th match is used.
    Columns that only come through ``SELECT *`` cite the last star. If nothing matches, the
    whole file is cited and flagged as a model-level citation.
    """
    items = select_items(source)
    named = [it for it in items if it.name == column.lower()]
    if named:
        if branch is not None and branch < len(named):
            return Citation(named[branch].lines, False)
        return Citation(named[-1].lines, False)
    stars = [it for it in items if it.is_star]
    if stars:
        return Citation(stars[-1].lines, False)
    return Citation((1, max(1, source.count("\n") + (0 if source.endswith("\n") else 1))), True)
