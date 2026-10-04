"""Pure helpers for the UI: no Streamlit import, so they are unit-tested directly.

Everything here only reshapes results the agent already produced (answer, run record, ledger).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dlens.agent.answer import Answer, marker
from dlens.agent.llm.ollama import DEFAULT_MODEL as OLLAMA_MODEL
from dlens.agent.loop import AgentRun
from dlens.agent.tools import Toolbox
from dlens.agent.tools.provenance import Citation, safe_read
from dlens.cli import trace_summary
from dlens.graph import LineageGraph
from dlens.lineage import ParseQuality
from dlens.ui.style import KIND_COLORS

ROOT = Path(__file__).resolve().parents[3]
DEV_QUESTIONS = ROOT / "eval" / "questions" / "dev.jsonl"
DEV_REPORT = ROOT / "eval" / "reports" / "dev_r9.json"
PROJECTS = {
    "synthetic_shop": ROOT / "corpora" / "synthetic_shop",
    "jaffle_shop": ROOT / "corpora" / "jaffle_shop",
}
EXAMPLES_PER_GROUP = 2


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
    file: str
    text: str
    start: int
    end: int
    level: str

    @property
    def cited(self) -> str:
        """The cited lines with their real line numbers (st.code numbers from 1)."""
        lines = self.text.splitlines()
        if self.level == "model":
            return ""
        width = len(str(self.end))
        return "\n".join(
            f"{n:>{width}} | {lines[n - 1]}"
            for n in range(self.start, min(self.end, len(lines)) + 1)
        )

    @property
    def range_label(self) -> str:
        if self.level == "model":
            return "whole file cited (no line claimed)"
        if self.start == self.end:
            return f"line {self.start}"
        return f"lines {self.start}-{self.end}"


def load_source(project: Path, cite: Citation) -> Source | None:
    text = safe_read(project, cite.file)
    if text is None:
        return None
    return Source(cite.file, text, cite.line_start, cite.line_end, cite.level)


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def subgraph_dot(answer: Answer, toolbox: Toolbox, selected: str | None = None) -> str:
    """DOT for the cited edges, edge label = kind; the selected edge is drawn bold. Columns are
    shown as ``model.column`` (graph display names)."""
    g = toolbox.graph
    lines = ["digraph G {", "  rankdir=LR;", '  node [shape=box, fontsize=10, style="rounded"];']
    nodes: dict[str, str] = {}
    for eid in answer.subgraph:
        rec = toolbox.record(eid)
        if rec is None or "from" not in rec:
            continue
        for end in (str(rec["from"]), str(rec["to"])):
            nodes.setdefault(end, f"n{len(nodes)}")
        kind = str(rec["kind"])
        extra = ", penwidth=3" if eid == selected else ""
        lines.append(
            f"  {nodes[str(rec['from'])]} -> {nodes[str(rec['to'])]} "
            f"[label={_q(kind)}, fontsize=9, color={_q(KIND_COLORS.get(kind, 'gray40'))}{extra}];"
        )
    decl = [
        f"  {n} [label={_q(g.display_name(c) if g.has_column(c) else c)}];"
        for c, n in nodes.items()
    ]
    return "\n".join([*lines[:3], *decl, *lines[3:], "}"])


def _tool_label(call: dict[str, Any]) -> str:
    args = ", ".join(f"{k}={v}" for k, v in (call.get("arguments") or {}).items())
    return f"{call.get('name')}({args})"


def _result_tools(step: Any) -> str:
    return ", ".join(r.tool for r in step.results)


def trace_rows(run: AgentRun) -> list[dict[str, Any]]:
    """One row per step of the run record for the trace expander."""
    return [
        {
            "step": s.index,
            "phase": s.phase,
            "tools": ", ".join(map(_tool_label, s.tool_calls)) or _result_tools(s),
            "in_tokens": s.input_tokens or s.est_input_tokens,
            "out_tokens": s.output_tokens,
            "cached": s.cached,
        }
        for s in run.record.steps
    ]


def trace_info(run: AgentRun) -> dict[str, object]:
    return trace_summary(run)
