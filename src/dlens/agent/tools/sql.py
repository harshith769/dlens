"""get_model_sql: a numbered excerpt of a model's SOURCE .sql.

With ``around_column`` the excerpt is the column's located lines (+/- 3) plus, followed up to
``MAX_ALIAS_DEPTH`` hops, the earlier lines in the same file that define the aliases the
expression reads (``coalesce(order_agg.lifetime_value, 0)`` pulls in the CTE line
``sum(...) as lifetime_value``). The result is a list of ordered line windows, each with its own
excerpt_id; the flat ``excerpt`` shows them with ``…`` between gaps.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Any

from dlens.agent.tools.budget import MAX_RESULT_TOKENS, largest_fit, payload_tokens
from dlens.agent.tools.common import ToolError, ToolOutput, as_str
from dlens.agent.tools.provenance import Provenance, excerpt_id, text_sha1
from dlens.lineage import column_id

CONTEXT_LINES = 3
MAX_LINE_CHARS = 160
MAX_ALIAS_DEPTH = 3
MAX_ITEM_LINES = 10  # how far up a multi-line select item (CASE ... END as x) is followed
GAP = "…"
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_COMMENT = re.compile(r"--.*$")


def _clip(line: str) -> str:
    return line if len(line) <= MAX_LINE_CHARS else line[: MAX_LINE_CHARS - 1] + "…"


def _resolve_model(prov: Provenance, text: str) -> str:
    g = prov.graph
    q = text.strip().lower()
    ids = g.model_ids()
    if q in ids:
        return q
    hits = [
        m
        for m in ids
        if (g.model_info(m) or {}).get("name", "").lower() == q or m.endswith("." + q)
    ]
    if len(hits) == 1:
        return hits[0]
    names = [(g.model_info(m) or {}).get("name", m) for m in ids]
    if hits:
        raise ToolError("ambiguous", f"{text!r} matches several nodes", candidates=hits)
    raise ToolError(
        "unknown_model",
        f"no model matches {text!r}",
        suggestions=difflib.get_close_matches(q, names, n=3, cutoff=0.0),
    )


def get_model_sql(prov: Provenance, args: dict[str, Any]) -> ToolOutput:
    text = as_str(args, "model_id")
    assert text is not None
    around = as_str(args, "around_column", required=False)
    g = prov.graph
    uid = _resolve_model(prov, text)
    info = g.model_info(uid) or {}
    file = info.get("file", "")
    source = prov.source(file)
    if not file.endswith(".sql") or not source:
        raise ToolError(
            "not_sql", f"{info.get('name', uid)} ({info.get('resource_type')}) has no readable .sql"
        )
    lines = source.splitlines()
    total = len(lines)

    column_cite = None
    spans: list[tuple[int, int, int]] = [(1, total, 0)]  # (first line, last line, alias depth)
    if around:
        name = around.rsplit(".", 1)[-1].lower()
        cid = column_id(uid, name)
        if not g.has_column(cid):
            cols = [g.nx_graph.nodes[c]["name"] for c in g.columns() if g.model_of(c) == uid]
            raise ToolError(
                "unknown_column",
                f"{info['name']} has no column {around!r}",
                suggestions=difflib.get_close_matches(name, cols, n=3, cutoff=0.0),
            )
        column_cite = prov.column_citation(cid)
        if column_cite.level != "model":
            a, b = column_cite.line_start, column_cite.line_end
            spans = [(max(1, a - CONTEXT_LINES), min(total, b + CONTEXT_LINES), 0)]
            spans += alias_definitions(lines, (a, b))
    windows = merge(spans)

    def render(active: list[Window], last_k: int | None = None) -> dict[str, Any]:
        shown: list[str] = []
        meta: list[dict[str, Any]] = []
        for i, w in enumerate(active):
            end = w.end
            if last_k is not None and i == len(active) - 1:
                end = w.start + last_k - 1
            if end < w.start:
                continue
            if shown:
                shown.append(GAP)
            shown += [f"{n}: {_clip(lines[n - 1])}" for n in range(w.start, end + 1)]
            meta.append({"excerpt_id": excerpt_id(file, w.start, end), "range": [w.start, end]})
        n_shown = sum(r["range"][1] - r["range"][0] + 1 for r in meta)
        wanted = sum(w.end - w.start + 1 for w in windows)
        return {
            "model": info["name"],
            "file": file,
            "windows": meta,
            "excerpt": shown,
            "total_lines": total,
            "truncated": n_shown < wanted,
            "dropped": {"lines": wanted - n_shown, "windows": len(windows) - len(meta)},
        }

    # Over the cap: drop the deepest alias windows first (farthest from the column on ties),
    # then cut the last remaining window's tail.
    active = list(windows)
    anchor = (
        windows[0].start
        if len(windows) == 1
        else min((w for w in windows if w.depth == 0), key=lambda w: w.start).start
    )
    while len(active) > 1 and payload_tokens(render(active)) > MAX_RESULT_TOKENS:
        victim = max(active, key=lambda w: (w.depth, abs(w.start - anchor)))
        if victim.depth == 0:
            break
        active.remove(victim)
    payload = render(active)
    if payload_tokens(payload) > MAX_RESULT_TOKENS:
        active = active[:1]
        k = largest_fit(
            active[0].end - active[0].start + 1, lambda k: render(active, k), MAX_RESULT_TOKENS
        )
        payload = render(active, k)
    side: dict[str, Any] = {
        "model": uid,
        "excerpts": {
            w["excerpt_id"]: {
                "excerpt_id": w["excerpt_id"],
                "text_sha1": text_sha1(source, w["range"][0], w["range"][1]),
                "citation": {
                    "file": file,
                    "line_start": w["range"][0],
                    "line_end": w["range"][1],
                    "level": "line",
                },
            }
            for w in payload["windows"]
        },
    }
    if column_cite is not None:
        side["column_citation"] = column_cite.model_dump()
    return ToolOutput(payload, side)


@dataclass
class Window:
    start: int
    end: int
    depth: int  # 0: the column's own lines; n: an alias definition n hops away


def merge(spans: list[tuple[int, int, int]]) -> list[Window]:
    """Ordered, non-overlapping windows; adjacent or overlapping spans merge (min depth wins)."""
    out: list[Window] = []
    for a, b, d in sorted(spans):
        if out and a <= out[-1].end + 1:
            out[-1].end = max(out[-1].end, b)
            out[-1].depth = min(out[-1].depth, d)
        else:
            out.append(Window(a, b, d))
    return out


def _item_start(lines: list[str], n: int) -> int:
    """First line of the select item that ends on line ``n`` (1-based)."""
    first = n
    while first > 1 and n - first < MAX_ITEM_LINES:
        here = _COMMENT.sub("", lines[first - 1]).lower()
        if re.search(r"\bselect\b", here):  # the item starts on a select line
            break
        prev = _COMMENT.sub("", lines[first - 2]).strip().lower()
        if not prev or prev.endswith((",", "(", ")")) or prev.split()[-1] in ("select", "distinct"):
            break
        first -= 1
    return first


def alias_definitions(lines: list[str], span: tuple[int, int]) -> list[tuple[int, int, int]]:
    """Spans of earlier lines that define aliases read by ``span`` (recursive, depth <= 3).

    An identifier counts when it is not a qualifier (not followed by ``.``) and an earlier line
    says ``as <identifier>`` (not ``<identifier> as (``, a CTE header). The nearest earlier
    definition wins. Text search, not a parser: it can only add context lines, never ids."""
    found: list[tuple[int, int, int]] = []
    seen: set[tuple[int, int]] = {span}
    frontier = [span]
    for depth in range(1, MAX_ALIAS_DEPTH + 1):
        nxt: list[tuple[int, int]] = []
        for a, b in frontier:
            text = "\n".join(_COMMENT.sub("", ln) for ln in lines[a - 1 : b])
            names = {
                m.group(0).lower()
                for m in _IDENT.finditer(text)
                if not text[m.end() : m.end() + 1] == "."
            }
            for ident in sorted(names):
                pat = re.compile(rf"\bas\s+{re.escape(ident)}\b(?!\s*\()", re.IGNORECASE)
                hits = [n for n in range(1, a) if pat.search(_COMMENT.sub("", lines[n - 1]))]
                if not hits:
                    continue
                end = hits[-1]
                rng = (_item_start(lines, end), end)
                if rng in seen:
                    continue
                seen.add(rng)
                found.append((*rng, depth))
                nxt.append(rng)
        frontier = nxt
        if not frontier:
            break
    return found
