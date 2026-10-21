"""The answer-phase evidence list, rebuilt from the Toolbox log (never from chat history).

Each item is one line. Lines with an ``id`` are citable (``e_`` edges, ``s_`` excerpts, ``r_``
graph-check facts, ``c_`` search_docs chunks) and appear only if the id is in
``toolbox.emitted_ids``. A chunk line is ``c_… | file:a-b | title "<snippet>"``: the snippet is
quoted project text (data, may be stale), plus the graph facts the hit carries. Lines without one
are context: impact models and exposures, resolve_entity candidates, tool errors.

``priority`` is the hop distance from the column the tool was asked about (trace: position in the
path + 1; impact: depth). Excerpts, facts and context lines are 0. ``trim`` drops the most distant
evidence first, so every path keeps a contiguous run of edges starting at the queried column.

Impact evidence (S12a, payload shape B) keeps the tool's grouping: a context header per (depth,
kind) group, then one line per column: a direct column as its edge string (with the expression),
an indirect one as ``model.column e_…``. Every column item carries its group ``<model> (<kind>)``,
and ``trim`` writes one "+K more columns in <model> (<kind>)" line per group it cuts, so nothing is
dropped silently.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from dlens.agent.tools import Toolbox, ToolResult

SNIPPET_CHARS = 400
ID_RE = re.compile(r"\b[esc]_[0-9a-f]{8}\b")


@dataclass
class EvidenceItem:
    id: str | None
    line: str
    priority: int
    order: int
    group: str | None = None  # impact items: "<model> (<kind>)", for trim's "+K more" lines


def _clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _line_no(line: str) -> int:
    head = line.split(":", 1)[0]
    return int(head) if head.isdigit() else -1


def describe_error(r: ToolResult) -> str:
    err = r.llm_payload["error"]
    arg = next(iter(r.args.values()), "")
    line = f"{r.tool}({arg}): {err.get('code')}: {err.get('message')}"
    extra = err.get("suggestions") or err.get("candidates")
    if extra and "did you mean" not in line.lower():
        line += f"; did you mean: {', '.join(map(str, extra))}"
    return line


def describe_candidates(r: ToolResult) -> str:
    p = r.llm_payload
    cands = ", ".join(f"{c['id']} ({c['score']})" for c in p.get("candidates", []))
    tag = " (ambiguous)" if p.get("ambiguous") else ""
    return f'resolve_entity("{p.get("query", "")}"){tag}: {cands or "no candidates"}'


def build_evidence(toolbox: Toolbox) -> list[EvidenceItem]:
    emitted = toolbox.emitted_ids
    by_id: dict[str, EvidenceItem] = {}
    context: list[EvidenceItem] = []
    ambiguous: list[EvidenceItem] = []  # resolve_entity results: kept when ambiguous,
    resolved: list[EvidenceItem] = []  # or when nothing citable was found at all
    order = 0

    def add(item_id: str, line: str, priority: int, group: str | None = None) -> None:
        nonlocal order
        if item_id not in emitted:
            return
        if item_id in by_id:
            by_id[item_id].priority = min(by_id[item_id].priority, priority)
            return
        by_id[item_id] = EvidenceItem(item_id, line, priority, order, group)
        order += 1

    def note(line: str, bucket: list[EvidenceItem]) -> None:
        nonlocal order
        if all(it.line != line for it in bucket):
            bucket.append(EvidenceItem(None, line, 0, order))
            order += 1

    for r in toolbox.log:
        p = r.llm_payload
        if r.is_error:
            continue
        if r.tool == "trace_upstream":
            for path in p.get("paths", []):
                for pos, line in enumerate(path):
                    add(line.split(":", 1)[0], line, pos + 1)
            if not p.get("paths"):
                note(f"trace_upstream({p.get('column')}): no upstream columns", context)
        elif r.tool == "impact_downstream":
            for key, items in p.get("columns_by_depth", {}).items():
                depth, label = int(key.split(" ", 1)[0]), key.split("[", 1)[1].rstrip("]")
                note(f"impact of {p.get('column')}, depth {key}:", context)
                for it in items:
                    name, eid = it.rsplit(" ", 1)
                    if label == "direct":
                        line = toolbox.edge_string(eid) or f"{eid}: -> {name}"
                    else:
                        line = f"{name} {eid}"
                    add(eid, line, depth, f"{name.rsplit('.', 1)[0]} ({label})")
            for line in p.get("more", []):
                note(line, context)
            models = ", ".join(p.get("models", [])) or "none"
            exps = ", ".join(f"{x['name']} ({x['type']})" for x in p.get("exposures", [])) or "none"
            more = " (truncated)" if p.get("truncated") else ""
            note(f"impact of {p.get('column')}: models: {models}; exposures: {exps}{more}", context)
        elif r.tool == "get_model_sql":
            for w in p.get("windows", []):
                a, b = w["range"]
                body = [ln for ln in p.get("excerpt", []) if _line_no(ln) in range(a, b + 1)]
                snippet = _clip(" | ".join(body), SNIPPET_CHARS)
                add(w["excerpt_id"], f'{w["excerpt_id"]}: {p["file"]}:{a}-{b} "{snippet}"', 0)
        elif r.tool == "reachability":
            add(p["fact_id"], f"{p['fact_id']}: {p['fact']}", 0)
            for pos, line in enumerate(p.get("path", [])):
                add(line.split(":", 1)[0], line, pos + 1)
        elif r.tool == "resolve_entity":
            note(describe_candidates(r), ambiguous if p.get("ambiguous") else resolved)
        elif r.tool == "search_docs":
            for h in p.get("hits", []):
                add(h["id"], chunk_line(h), 0)

    citable = sorted(by_id.values(), key=lambda it: it.order)
    extra = ambiguous if citable else [*ambiguous, *resolved]
    return sorted([*citable, *context, *extra], key=lambda it: it.order)


def chunk_line(hit: dict[str, Any]) -> str:
    """``c_… | file:a-b | title "<snippet>"`` (+ the hit's graph facts) for a search_docs hit."""
    a, b = hit["lines"]
    span = f"{hit['file']}:{a}" if a == b else f"{hit['file']}:{a}-{b}"
    body = _clip(str(hit.get("sql") or hit.get("quoted_text") or ""), SNIPPET_CHARS)
    line = f'{hit["id"]} | {span} | {hit.get("title", "")} "{body.replace(chr(34), chr(39))}"'
    if hit.get("level"):
        line += f" [{hit['level']}]"
    if g := hit.get("graph"):
        ins, down = g.get("direct_inputs", 0), g.get("downstream", 0)
        line += f" (graph: {ins} direct inputs, {down} downstream)"
    return line


def tool_errors(toolbox: Toolbox) -> list[str]:
    return [describe_error(r) for r in toolbox.log if r.is_error]


def render_evidence(items: Sequence[EvidenceItem]) -> str:
    return "\n".join(it.line for it in items)


def trim(
    items: list[EvidenceItem], fits: Callable[[list[EvidenceItem]], bool]
) -> tuple[list[EvidenceItem], list[str]]:
    """Drop the most distant citable items first (latest first on ties), then context lines from
    the end, until ``fits`` holds. Every impact group that loses items gets one "+K more columns
    in <model> (<kind>)" line, counted in ``fits``. Returns the kept items (with those lines) and
    the dropped ids."""
    kept = list(items)
    dropped: list[str] = []
    cut: Counter[str] = Counter()
    at: dict[str, int] = {}

    def shown() -> list[EvidenceItem]:
        notes = [EvidenceItem(None, f"+{n} more columns in {g}", 0, at[g]) for g, n in cut.items()]
        return sorted([*kept, *notes], key=lambda it: it.order)

    while kept and not fits(shown()):
        with_id = [it for it in kept if it.id is not None]
        victim = (
            max(with_id, key=lambda it: (it.priority, it.order))
            if with_id
            else max(kept, key=lambda it: it.order)
        )
        kept.remove(victim)
        if victim.id is not None:
            dropped.append(victim.id)
        if victim.group is not None:
            cut[victim.group] += 1
            at.setdefault(victim.group, victim.order)
    return shown(), dropped
