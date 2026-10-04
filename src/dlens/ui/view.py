"""Pure helpers for the UI: no Streamlit import, so they are unit-tested directly.

Everything here only reshapes results the agent already produced (answer, run record, ledger).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

from dlens.agent.answer import Answer, marker
from dlens.agent.llm.ollama import DEFAULT_MODEL as OLLAMA_MODEL
from dlens.agent.loop import AgentRun
from dlens.agent.tools import Toolbox
from dlens.agent.tools.provenance import Citation, Provenance, edge_id, safe_read
from dlens.cli import trace_summary
from dlens.graph import LineageGraph
from dlens.lineage import Edge, ParseQuality
from dlens.ui.style import BORDER, KIND_COLORS, MUTED, PRIMARY, Tone

ROOT = Path(__file__).resolve().parents[3]
DEV_QUESTIONS = ROOT / "eval" / "questions" / "dev.jsonl"
DEV_REPORT = ROOT / "eval" / "reports" / "dev_r9.json"
PROJECTS = {
    "synthetic_shop": ROOT / "corpora" / "synthetic_shop",
    "jaffle_shop": ROOT / "corpora" / "jaffle_shop",
}
EXAMPLES_PER_GROUP = 2
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


@dataclass(frozen=True)
class ExampleGroup:
    label: str
    hint: str
    questions: tuple[str, ...]


# Dev-set subtypes grouped by what the question asks; order = order shown in the UI.
_GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "Where a column comes from",
        "Traces the column back to its sources.",
        ("upstream", "paraphrase", "abbreviation", "ambiguous_chain", "trap"),
    ),
    (
        "What a column affects",
        "Follows the column downstream; yes/no questions get a graph check.",
        ("downstream", "reachability"),
    ),
    ("How a column is computed", "Shows the expression with its file and line.", ("computed",)),
    (
        "A wrong premise",
        "The question assumes a link the code does not have.",
        ("false_premise",),
    ),
    (
        "Should refuse",
        "The column does not exist, so the agent refuses.",
        ("nonexistent_column",),
    ),
)


def examples(
    project: str, questions: Path = DEV_QUESTIONS, report: Path = DEV_REPORT
) -> list[ExampleGroup]:
    """Dev questions for ``project`` that passed in the last dev report, grouped by kind."""
    if not questions.is_file() or not report.is_file():
        return []
    passed = {r["id"] for r in json.loads(report.read_text())["rows"] if r.get("pass")}
    rows = [
        q
        for q in map(json.loads, questions.read_text().splitlines())
        if q["corpus"] == project and q["id"] in passed
    ]
    out = []
    for label, hint, subtypes in _GROUPS:
        qs = [q["question"] for sub in subtypes for q in rows if q["subtype"] == sub]
        if qs:
            out.append(ExampleGroup(label, hint, tuple(qs[:EXAMPLES_PER_GROUP])))
    return out


# -- header and error states --------------------------------------------------------------------


@dataclass(frozen=True)
class Stats:
    models: int
    columns: int
    edges: int
    parsed: int  # models parsed FULL
    reported: int  # models in the parse report

    @property
    def line(self) -> str:
        cov = f"{round(100 * self.parsed / self.reported)}%" if self.reported else "n/a"
        return (
            f"{self.models} models · {self.columns} columns · {self.edges} edges · "
            f"parse coverage {cov}"
        )


def project_stats(graph: LineageGraph) -> Stats:
    report = graph.parse_report()
    models = sum(
        (graph.model_info(m) or {}).get("resource_type") == "model" for m in graph.model_ids()
    )
    return Stats(
        models=models,
        columns=len(graph.columns()),
        edges=len(graph.edges()),
        parsed=sum(q == ParseQuality.FULL for q in report.values()),
        reported=len(report),
    )


@dataclass(frozen=True)
class Hint:
    """An error state: what went wrong, what to do, and the exact commands to run."""

    title: str
    body: str
    commands: tuple[str, ...] = ()


_DOWN = ("failed to connect", "connection refused", "connecterror", "connection error")


def error_hint(reason: str | None, model: str = OLLAMA_MODEL) -> Hint | None:
    """A fix for a provider failure (the agent turns those into refusals), else None."""
    if not reason:
        return None
    low = reason.lower()
    if "no module named" in low and "ollama" in low:
        return Hint(
            "The Ollama client is not installed",
            "Install the agent and UI extras, then restart the app.",
            ("uv sync --extra agent --extra ui", "make ui"),
        )
    if "ollama" not in low and not low.startswith("providererror"):
        return None
    if "not found" in low and "model" in low:
        return Hint(
            "The local model is not installed",
            f"Pull {model} once, then ask again.",
            (f"ollama pull {model}",),
        )
    if any(k in low for k in _DOWN):
        return Hint(
            "The local model is not reachable",
            "Start Ollama in another terminal, then ask again.",
            ("ollama serve", f"ollama pull {model}"),
        )
    return Hint(
        "The local model call failed",
        "Check that Ollama is running and the model is pulled, then ask again.",
        ("ollama serve", f"ollama pull {model}"),
    )


def project_problem(name: str) -> Hint | None:
    """Why ``name`` cannot be opened (unknown, or its folder is missing), else None."""
    if name not in PROJECTS:
        known = ", ".join(PROJECTS)
        return Hint(f"Unknown project: {name}", f"Pick one of: {known}.")
    if not PROJECTS[name].is_dir():
        return Hint(
            f"Project folder missing: corpora/{name}",
            "Restore the corpus, then build its lineage graph.",
            (f"make ingest CORPUS={name}",),
        )
    return None


def build_failed(name: str, exc: BaseException) -> Hint:
    return Hint(
        f"Could not build the lineage graph for {name}",
        f"{type(exc).__name__}: {exc}",
        (f"make ingest CORPUS={name}",),
    )


# -- answer area -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Badge:
    label: str
    tone: Tone


def verdict(run: AgentRun) -> Badge:
    """From real fields only: refused, clarification, chain mode (ambiguity policy), answered."""
    a = run.answer
    if a.refused:
        return Badge("Refused", "warning")
    if a.clarification is not None:
        return Badge("Clarification", "neutral")
    if (run.record.ambiguity or {}).get("mode") == "chain":
        return Badge("Chain mode", "primary")
    return Badge("Answered", "primary")


def verification(run: AgentRun) -> Badge:
    v = run.record.validation
    if not v or v.get("skipped"):
        return Badge("Not checked", "neutral")
    if v.get("warning"):
        if run.answer.refused:
            return Badge("Nothing verifiable", "warning")
        return Badge("Partially removed", "warning")
    parts = []
    if n := len(v.get("repairs") or []):
        parts.append(f"Repaired {n}")
    if n := len(v.get("completions") or []):
        parts.append(f"Completed {n}")
    if v.get("regenerated"):
        parts.append("Regenerated")
    return Badge(" · ".join(parts) or "Verified", "verified")


@dataclass(frozen=True)
class ClaimRow:
    text: str
    status: str  # "verified" | "repaired" | "completed"
    chips: tuple[tuple[str, str], ...]  # (id, label); r_ ids are "[graph check]"


def _kept_indices(run: AgentRun) -> list[int]:
    """Index of each final claim in the validated draft (salvage drops claims, keeping order)."""
    v = run.record.validation or {}
    dropped = set(v.get("dropped_claims") or [])
    n = len(run.answer.claims) + len(dropped)
    return [i for i in range(n) if i not in dropped]


def claim_rows(run: AgentRun) -> list[ClaimRow]:
    v = run.record.validation or {}
    repaired = {r.get("claim_index") for r in v.get("repairs") or []}
    completed = {c.get("claim_index") for c in v.get("completions") or []}
    rows = []
    for claim, k in zip(run.answer.claims, _kept_indices(run), strict=False):
        status = "repaired" if k in repaired else "completed" if k in completed else "verified"
        chips = tuple(
            (i, chip_label(i, run.answer.citations.get(i)))
            for i in dict.fromkeys(claim.ids)
            if i in run.answer.citations or i.startswith("r_")
        )
        rows.append(ClaimRow(claim.text.strip(), status, chips))
    return rows


@dataclass(frozen=True)
class RemovedClaim:
    text: str | None
    rules: tuple[str, ...]


def _draft_claims(raw: str | None) -> list[dict[str, Any]]:
    try:
        body = json.loads(_FENCE.sub("", (raw or "").strip()) or "{}")
    except ValueError:
        return []
    claims = body.get("claims") if isinstance(body, dict) else None
    return claims if isinstance(claims, list) else []


def removed_claims(run: AgentRun) -> list[RemovedClaim]:
    """Claims the validator dropped, with the rules they failed (same round choice as the loop:
    the one that keeps more claims, ties to the regenerated draft)."""
    v = run.record.validation or {}
    dropped = v.get("dropped_claims") or []
    if not dropped:
        return []
    rounds = [
        (r, raw)
        for r, raw in (
            (v.get("second"), run.record.regenerate_draft_raw),
            (v.get("first"), run.record.draft_raw),
        )
        if r
    ]
    best, raw = max(
        rounds, key=lambda rr: rr[0].get("claims", 0) - len(rr[0].get("dropped_claims") or [])
    )
    texts = _draft_claims(raw)
    out = []
    for k in dropped:
        rules = tuple(
            dict.fromkeys(
                str(f.get("rule", "?")).split(".")[0]
                for f in best.get("failures") or []
                if f.get("claim_index") == k
            )
        )
        text = texts[k].get("text") if k < len(texts) and isinstance(texts[k], dict) else None
        out.append(RemovedClaim(str(text).strip() if text else None, rules))
    return out


def fact_statement(toolbox: Toolbox, item_id: str) -> str | None:
    """The words of an ``r_`` graph-check fact, or None."""
    rec = toolbox.record(item_id)
    return str(rec["fact"]) if rec and "fact" in rec else None


def chip_label(item_id: str, cite: Citation | None) -> str:
    return marker(item_id, cite)


def citation_chips(answer: Answer) -> list[tuple[str, str]]:
    """``(id, label)`` for every distinct cited item with a file; ``r_`` facts have no file."""
    seen: dict[str, str] = {}
    for claim in answer.claims:
        for i in claim.ids:
            cite = answer.citations.get(i)
            if cite is not None and i not in seen:
                seen[i] = chip_label(i, cite)
    return list(seen.items())


@dataclass(frozen=True)
class Source:
    file: str  # relative to the project root, as cited
    text: str
    start: int
    end: int
    level: str

    @property
    def range_label(self) -> str:
        if self.level == "model":
            return "whole file cited (no line claimed)"
        span = f"line {self.start}" if self.start == self.end else f"lines {self.start}-{self.end}"
        return f"{span} (the select * that produced it)" if self.level == "star" else span

    @property
    def highlighted(self) -> range:
        return range(0) if self.level == "model" else range(self.start, self.end + 1)


def highlight_sql(text: str, lines: range = range(0), sql: bool = True) -> str:
    """Escaped HTML of ``text`` with line numbers and the ``lines`` (1-based) highlighted.
    Pygments colors SQL when it is installed; otherwise the text is shown plain."""
    body = text.expandtabs(4).rstrip("\n")
    try:
        from pygments import highlight
        from pygments.formatters import HtmlFormatter
        from pygments.lexers import SqlLexer, TextLexer
    except ImportError:  # pragma: no cover - pygments ships with pytest and rich
        rendered = [escape(line) for line in body.split("\n")]
    else:
        fmt = HtmlFormatter(nowrap=True, noclasses=True, style="friendly")
        # HtmlFormatter closes its spans at every line end, so the output splits on newlines.
        rendered = highlight(body, SqlLexer() if sql else TextLexer(), fmt).rstrip("\n").split("\n")
    width = len(str(len(rendered)))
    out = []
    for n, line in enumerate(rendered, start=1):
        num = f'<span class="ln" style="width:{width + 1}ch">{n}</span>'
        out.append(f'<span class="hl">{num}{line}</span>' if n in lines else num + line)
    return '<div class="dl-src"><pre>' + "\n".join(out) + "</pre></div>"


def load_source(project: Path, cite: Citation) -> Source | None:
    text = safe_read(project, cite.file)
    if text is None:
        return None
    return Source(cite.file, text, cite.line_start, cite.line_end, cite.level)


# -- lineage diagram ---------------------------------------------------------------------------

LAYERS = ("Sources", "Seeds", "Staging", "Intermediate", "Marts", "Models")
DIAGRAM_EDGE_CAP = 40
LABEL_CHARS = 30
KIND_NAMES = {k: k.capitalize() for k in KIND_COLORS}
_PREFIXES = (
    ("stg_", "Staging"),
    ("int_", "Intermediate"),
    ("fct_", "Marts"),
    ("dim_", "Marts"),
    ("mart_", "Marts"),
    ("raw_", "Sources"),
    ("src_", "Sources"),
)
_FOLDERS = (
    ("staging", "Staging"),
    ("intermediate", "Intermediate"),
    ("marts", "Marts"),
    ("mart", "Marts"),
)


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _model_name(graph: LineageGraph, uid: str) -> str:
    return (graph.model_info(uid) or {}).get("name") or uid.rsplit(".", 1)[-1]


def layer_of(graph: LineageGraph, uid: str) -> str:
    """Source/seed by resource type, else staging/intermediate/marts by folder, else by name
    prefix (``stg_``, ``int_``, ``fct_``/``dim_``), else "Models"."""
    info = graph.model_info(uid) or {}
    kind = info.get("resource_type") or uid.split(".", 1)[0]
    if kind == "source":
        return "Sources"
    if kind == "seed":
        return "Seeds"
    folders = [p.lower() for p in Path(info.get("file", "")).parts[:-1]]
    for folder, layer in _FOLDERS:
        if folder in folders:
            return layer
    name = _model_name(graph, uid).lower()
    return next((layer for prefix, layer in _PREFIXES if name.startswith(prefix)), "Models")


def short_expression(expr: str, n: int = LABEL_CHARS) -> str:
    one = " ".join(expr.split())
    return one if len(one) <= n else one[: n - 1] + "…"


def edges_by_id(graph: LineageGraph, ids: list[str]) -> list[Edge]:
    """Graph edges for ``e_`` ids, in the given order; other ids are skipped."""
    index = {edge_id(e): e for e in graph.edges()}
    return [index[i] for i in dict.fromkeys(ids) if i in index]


def neighborhood(graph: LineageGraph, column: str, direction: str, depth: int) -> list[Edge]:
    """Every edge within ``depth`` hops of ``column`` (``upstream``, ``downstream`` or ``both``),
    nearest first, so a cap keeps the closest edges."""
    g = graph.nx_graph
    ranked: dict[tuple[str, str], tuple[int, Edge]] = {}
    for up in {"upstream": (True,), "downstream": (False,)}.get(direction, (True, False)):
        seen, frontier = {column}, [column]
        for hop in range(1, depth + 1):
            nxt: list[str] = []
            for col in frontier:
                for other in sorted(g.predecessors(col) if up else g.successors(col)):
                    e = graph.edge(other, col) if up else graph.edge(col, other)
                    ranked.setdefault((e.from_column, e.to_column), (hop, e))
                    if other not in seen:
                        seen.add(other)
                        nxt.append(other)
            frontier = nxt
    return [e for _, e in sorted(ranked.values(), key=lambda he: he[0])]


def focus_column(run: AgentRun, graph: LineageGraph) -> tuple[str | None, str]:
    """The column the question is about and the direction its tools walked: the first
    ``trace_upstream`` / ``impact_downstream`` / ``reachability`` argument that resolves."""
    for step in run.record.steps:
        for r in step.results:
            col = r.args.get("column_id") or r.args.get("from_column")
            if not isinstance(col, str):
                continue
            try:
                resolved = graph.resolve(col)
            except Exception:  # unknown or ambiguous: try the next call
                continue
            if r.tool == "impact_downstream":
                return resolved, "downstream"
            if r.tool in ("trace_upstream", "reachability"):
                return resolved, "upstream" if r.tool == "trace_upstream" else "both"
    return None, "upstream"


@dataclass(frozen=True)
class LineageDot:
    dot: str
    shown: int  # edges drawn
    total: int  # edges given

    @property
    def note(self) -> str | None:
        if self.shown == self.total:
            return None
        return f"Showing the {self.shown} nearest of {self.total} edges."


def _port_table(
    graph: LineageGraph, uid: str, cols: list[str], ports: dict[str, str], focus: str | None
) -> str:
    rows = [
        f'<TR><TD BGCOLOR="#EEF2F6" ALIGN="LEFT"><B>{escape(_model_name(graph, uid))}</B></TD></TR>'
    ]
    for c in cols:
        name = escape(str(graph.nx_graph.nodes[c].get("name", c.rsplit(".", 1)[-1])))
        if c == focus:
            rows.append(
                f'<TR><TD PORT="{ports[c]}" ALIGN="LEFT" BORDER="2" COLOR="{PRIMARY}">'
                f"<B>{name}</B></TD></TR>"
            )
        else:
            rows.append(f'<TR><TD PORT="{ports[c]}" ALIGN="LEFT">{name}</TD></TR>')
    return (
        f'<<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0" CELLPADDING="4" COLOR="{BORDER}" '
        f'BGCOLOR="#FFFFFF">{"".join(rows)}</TABLE>>'
    )


def _legend() -> str:
    rows = "".join(
        f'<TR><TD ALIGN="LEFT"><FONT COLOR="{KIND_COLORS[k]}">━━ {KIND_NAMES[k]}</FONT></TD></TR>'
        for k in KIND_COLORS
    )
    return (
        "  subgraph cluster_legend {\n"
        f'    label="Edge kinds"; color={_q(BORDER)}; fontcolor={_q(MUTED)}; fontsize=9;\n'
        f'    legend [label=<<TABLE BORDER="0" CELLSPACING="0" CELLPADDING="1">{rows}</TABLE>>];\n'
        "  }"
    )


def build_lineage_dot(
    graph: LineageGraph,
    edges: list[Edge],
    focus: str | None = None,
    highlight: frozenset[str] = frozenset(),
    cap: int = DIAGRAM_EDGE_CAP,
) -> LineageDot:
    """Graphviz DOT: one cluster per layer, one table node per model listing its relevant columns
    as ports, column-to-column edges colored by kind and labeled with a short expression
    (identity edges are unlabeled), ``focus`` drawn with a bold border, edges whose id is in
    ``highlight`` drawn thick, and a legend of the kinds. At most ``cap`` edges, in the given
    order."""
    shown = list(dict.fromkeys(edges))[:cap]
    cols: set[str] = {c for e in shown for c in (e.from_column, e.to_column)}
    if focus is not None and graph.has_column(focus):
        cols.add(focus)
    by_model: dict[str, list[str]] = {}
    for c in sorted(cols):
        by_model.setdefault(graph.model_of(c), []).append(c)
    node = {uid: f"m{i}" for i, uid in enumerate(sorted(by_model))}
    ports = {c: f"c{i}" for i, c in enumerate(sorted(cols))}

    out = [
        "digraph lineage {",
        "  rankdir=LR; nodesep=0.3; ranksep=1.1; bgcolor=transparent;",
        f'  graph [fontname="IBM Plex Sans", fontsize=11, fontcolor={_q(MUTED)}];',
        '  node [shape=plaintext, fontname="IBM Plex Sans", fontsize=10];',
        '  edge [fontname="IBM Plex Sans", fontsize=9, arrowsize=0.6];',
    ]
    layers: dict[str, list[str]] = {}
    for uid in sorted(by_model):
        layers.setdefault(layer_of(graph, uid), []).append(uid)
    for n, layer in enumerate(sorted(layers, key=LAYERS.index)):
        out.append(f"  subgraph cluster_{n} {{")
        out.append(f"    label={_q(layer)}; labeljust=l; style=rounded; color={_q(BORDER)};")
        for uid in layers[layer]:
            label = _port_table(graph, uid, by_model[uid], ports, focus)
            out.append(f"    {node[uid]} [label={label}];")
        out.append("  }")
    for e in shown:
        color = KIND_COLORS.get(e.kind.value, MUTED)
        attrs = [f"color={_q(color)}", f"fontcolor={_q(color)}"]
        if e.kind.value != "IDENTITY":
            attrs.append(f"label={_q(short_expression(e.expression))}")
        if edge_id(e) in highlight:
            attrs.append("penwidth=2.6")
        src = f"{node[graph.model_of(e.from_column)]}:{ports[e.from_column]}:e"
        dst = f"{node[graph.model_of(e.to_column)]}:{ports[e.to_column]}:w"
        out.append(f"  {src} -> {dst} [{', '.join(attrs)}];")
    out.append(_legend())
    out.append("}")
    return LineageDot("\n".join(out), len(shown), len(dict.fromkeys(edges)))


# -- explore (no LLM) ---------------------------------------------------------------------------

DIRECTIONS = {"Upstream": "upstream", "Downstream": "downstream", "Both": "both"}


def column_options(graph: LineageGraph) -> dict[str, str]:
    """Display name (``model.column``) -> full column id, sorted by display name."""
    return dict(sorted((graph.display_name(c), c) for c in graph.columns()))


def explore_rows(graph: LineageGraph, project: Path, edges: list[Edge]) -> list[dict[str, str]]:
    """One row per edge, with the checked citation (project-relative ``file:lines``)."""
    prov = Provenance(graph, project)
    rows = []
    for e in edges:
        cite = prov.edge_citation(e)
        where = cite.file if cite.level == "model" else f"{cite.file}:{cite.line_start}"
        if cite.level != "model" and cite.line_end != cite.line_start:
            where += f"-{cite.line_end}"
        rows.append(
            {
                "From": graph.display_name(e.from_column),
                "To": graph.display_name(e.to_column),
                "Kind": KIND_NAMES.get(e.kind.value, e.kind.value),
                "Expression": " ".join(e.expression.split()),
                "Where": where,
            }
        )
    return rows


def edge_models(graph: LineageGraph, edges: list[Edge], focus: str | None = None) -> list[str]:
    """Models touched by ``edges`` (and the focus column), in first-seen order."""
    cols = [*([focus] if focus else []), *(c for e in edges for c in (e.to_column, e.from_column))]
    return list(dict.fromkeys(graph.model_of(c) for c in cols))


def model_source(graph: LineageGraph, project: Path, uid: str) -> Source | None:
    """The model's file, read through ``safe_read`` (never outside the project)."""
    file = (graph.model_info(uid) or {}).get("file", "")
    text = safe_read(project, file)
    return None if text is None else Source(file, text, 1, 1, "model")


# -- steps and checks --------------------------------------------------------------------------

# (rule, plain-English meaning). R2r and R8c are code steps reported with their rule.
RULES: tuple[tuple[str, str], ...] = (
    ("R1", "Every claim cites at least one id."),
    ("R2", "Every cited id was returned by a tool for this question."),
    ("R2r", "A miscopied id is fixed only when exactly one returned id fits."),
    ("R3", "Each citation still holds on disk: the file lines contain the evidence."),
    ("R4", "Every model or column named in the text exists and came from this question's tools."),
    ("R5", "Kind words (renamed, aggregated, computed) match the kinds of the cited edges."),
    ("R6", "File paths and line numbers in the text match a citation."),
    ("R7", "Each claim's citations touch what the claim names."),
    ("R8", "A claim linking two columns is connected by its cited edges, with no skipped hop."),
    ("R8c", "A missing connecting edge that the tools did return is added by code."),
    ("R9", "A yes/no answer agrees with the graph's reachability check."),
)
NINE_RULES = tuple((r, m) for r, m in RULES if r not in ("R2r", "R8c"))
_PHASES = {
    "tool": "Tool call",
    "code": "Code step",
    "answer": "Answer draft",
    "repair": "Repair",
    "regenerate": "Regenerate",
}


def _tool_label(call: dict[str, Any]) -> str:
    args = ", ".join(f"{k}={v}" for k, v in (call.get("arguments") or {}).items())
    return f"{call.get('name')}({args})"


def _result_label(r: Any) -> str:
    args = ", ".join(f"{k}={v}" for k, v in (r.args or {}).items())
    return f"{r.tool}({args})" + (" (duplicate, skipped)" if r.deduped else "")


@dataclass(frozen=True)
class TimelineItem:
    title: str
    detail: str
    meta: str
    kind: str  # css class: "" (LLM), "code", "check", "warn"


def timeline(run: AgentRun) -> list[TimelineItem]:
    """One item per recorded step, then the validation outcome."""
    items = []
    for s in run.record.steps:
        if s.phase == "code":
            detail = ", ".join(map(_result_label, s.results))
            meta = "by code, no LLM call"
        else:
            detail = ", ".join(map(_tool_label, s.tool_calls)) or ", ".join(
                map(_result_label, s.results)
            )
            tokens = s.input_tokens or s.est_input_tokens
            meta = f"{tokens:,} in / {s.output_tokens:,} out tokens · {s.latency_ms:,.0f} ms"
            if s.cached:
                meta += " · cached"
        if s.error:
            detail = f"{detail} — error: {s.error}".lstrip(" —")
        kind = "warn" if s.error else ("code" if s.phase == "code" else "")
        items.append(TimelineItem(_PHASES.get(s.phase, s.phase), detail, meta, kind))
    badge = verification(run)
    items.append(
        TimelineItem(
            "Validation",
            badge.label,
            f"{len(run.answer.claims)} claims kept",
            "warn" if badge.tone == "warning" else "check",
        )
    )
    return items


@dataclass(frozen=True)
class CheckRow:
    rule: str
    meaning: str
    outcome: str
    failures: str  # "" | "2" | "2 → 0" (first draft → regenerated draft)


def _by_rule(summary: dict[str, Any] | None) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in (summary or {}).get("failures") or []:
        rule = str(f.get("rule", "?")).split(".")[0]
        out[rule] = out.get(rule, 0) + 1
    return out


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def checks_table(run: AgentRun) -> list[CheckRow]:
    """R1-R9 plus R2r/R8c for this answer: what each checks and how it went."""
    v = run.record.validation
    if not v or v.get("skipped"):
        why = "Not checked (refusal or clarification)" if v else "Not checked"
        return [CheckRow(r, m, why, "") for r, m in RULES]
    first, second = _by_rule(v.get("first")), _by_rule(v.get("second"))
    has_second = v.get("second") is not None
    yes_no = any(r.tool == "reachability" for s in run.record.steps for r in s.results)
    rows = []
    for rule, meaning in RULES:
        if rule == "R2r":
            n = len(v.get("repairs") or [])
            rows.append(
                CheckRow(rule, meaning, f"Repaired {_plural(n, 'id')}" if n else "Not needed", "")
            )
            continue
        if rule == "R8c":
            n = len(v.get("completions") or [])
            outcome = f"Completed {_plural(n, 'claim')}" if n else "Not needed"
            rows.append(CheckRow(rule, meaning, outcome, ""))
            continue
        if rule == "R9" and not yes_no:
            rows.append(CheckRow(rule, meaning, "Not a yes/no question", ""))
            continue
        a, b = first.get(rule, 0), second.get(rule, 0)
        if not a and not b:
            rows.append(CheckRow(rule, meaning, "Passed", ""))
            continue
        if has_second:
            count = f"{a} → {b}"
            outcome = "Fixed by regenerating" if not b else "Still failing; claims removed"
        else:
            count = str(a)
            outcome = "Failed; claims removed"
        rows.append(CheckRow(rule, meaning, outcome, count))
    return rows


def trace_info(run: AgentRun) -> dict[str, object]:
    return trace_summary(run)
