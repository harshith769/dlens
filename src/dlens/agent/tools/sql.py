"""get_model_sql: a numbered excerpt of a model's SOURCE .sql."""

from __future__ import annotations

import difflib
from typing import Any

from dlens.agent.tools.budget import MAX_RESULT_TOKENS, largest_fit
from dlens.agent.tools.common import ToolError, ToolOutput, as_str
from dlens.agent.tools.provenance import Provenance, excerpt_id
from dlens.lineage import column_id

CONTEXT_LINES = 3
MAX_LINE_CHARS = 160


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

    start, column_cite = 1, None
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
            start = max(1, column_cite.line_start - CONTEXT_LINES)
    wanted_end = total
    if column_cite is not None and column_cite.level != "model":
        wanted_end = min(total, column_cite.line_end + CONTEXT_LINES)
    shown = [f"{n}: {_clip(lines[n - 1])}" for n in range(start, wanted_end + 1)]

    def render(k: int) -> dict[str, Any]:
        end = start + k - 1
        return {
            "model": info["name"],
            "file": file,
            "excerpt_id": excerpt_id(file, start, end),
            "excerpt_range": [start, end],
            "excerpt": shown[:k],
            "total_lines": total,
            "truncated": k < len(shown),
            "dropped": {"lines": len(shown) - k},
        }

    k = largest_fit(len(shown), render, MAX_RESULT_TOKENS)
    payload = render(k)
    end = start + k - 1
    side: dict[str, Any] = {
        "model": uid,
        "excerpts": {
            payload["excerpt_id"]: {
                "excerpt_id": payload["excerpt_id"],
                "citation": {"file": file, "line_start": start, "line_end": end, "level": "line"},
            }
        },
    }
    if column_cite is not None:
        side["column_citation"] = column_cite.model_dump()
    return ToolOutput(payload, side)
