"""Locate an output column in the model's SOURCE .sql (what a user opens), not compiled SQL.

Compiled lines drift from source lines whenever Jinja expands to several lines, so citations
use the source file. The source contains Jinja and cannot be parsed by sqlglot, so this is a
small depth-aware scanner: it splits every SELECT list into top-level items and records each
item's line range and output name. Jinja blocks, strings and comments are skipped as opaque.

Indirect edges cite a clause (S04): the engine finds the clause in the compiled SQL, and
``line_map`` carries its lines back to the source file (``locate_clause``).
"""

import difflib
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


# -- clause citations for indirect edges (S04) ---------------------------------------------------


def line_map(source: str, compiled: str) -> list[tuple[int, int] | None]:
    """For each compiled line (0-based), the source line range it comes from (1-based), or None.

    dbt renders Jinja in place, so compiled and source lines align except where Jinja expands.
    Lines are aligned with ``difflib`` on their stripped text. Equal runs, and changed runs of
    the same length (``{{ ref() }}`` rendered on its line), map line to line. A changed run of a
    different length (a ``{% for %}`` loop) maps every compiled line to the whole source run.
    Compiled lines with no source run at all map to None.
    """
    src = [line.strip() for line in source.splitlines()]
    out: list[tuple[int, int] | None] = [None] * len(compiled.splitlines())
    cmp = [line.strip() for line in compiled.splitlines()]
    matcher = difflib.SequenceMatcher(None, src, cmp, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1):
            for k in range(j2 - j1):
                out[j1 + k] = (i1 + k + 1, i1 + k + 1)
        elif tag == "replace":
            for k in range(j1, j2):
                out[k] = (i1 + 1, i2)
    return out


def key_token(key: str) -> str:
    """What the cited source lines must hold for a clause key: the column name (last segment of
    the qualified key), a position (``1``) or ``ALL``."""
    return key.replace('"', "").split(".")[-1]


def locate_clause(
    source: str,
    compiled: str,
    span: tuple[int, int] | None,
    key: str,
    lines_of: list[tuple[int, int] | None] | None = None,
) -> Citation | str:
    """Source line range of a clause found at `span` in the compiled SQL, or why there is none.

    The range is checked: the cited source lines must contain the key as written. A clause that
    a macro writes (``{{ my_filter() }}``) maps to that line but fails the check, so the edge
    falls back to a model-level citation with the reason recorded."""
    if span is None:
        return "clause not found in the compiled SQL"
    lines_of = lines_of if lines_of is not None else line_map(source, compiled)
    first = compiled.count("\n", 0, span[0])
    last = compiled.count("\n", 0, max(span[0], span[1] - 1))
    if last >= len(lines_of) or lines_of[first] is None or lines_of[last] is None:
        return "clause lines have no source counterpart"
    a, b = lines_of[first], lines_of[last]
    assert a is not None and b is not None
    lines = (min(a[0], b[0]), max(a[1], b[1]))
    chunk = "\n".join(source.splitlines()[lines[0] - 1 : lines[1]])
    token = key_token(key)
    if not re.search(rf"(?<!\w){re.escape(token)}(?!\w)", chunk, re.IGNORECASE):
        return f"key {token!r} not in source lines {lines[0]}-{lines[1]}"
    return Citation(lines, False)
