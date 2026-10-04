"""DLens command-line entry point."""

import json
from pathlib import Path
from typing import Annotated

import typer

from dlens import __version__
from dlens.agent.answer import render as render_answer
from dlens.agent.llm import make_client
from dlens.agent.loop import AgentRun
from dlens.agent.loop import ask as run_agent
from dlens.agent.runlog import RunLogger, runs_dir
from dlens.agent.tools import Toolbox
from dlens.graph import AmbiguousColumn, ColumnNotFound, LineageGraph, load_or_build
from dlens.graph.render import render_impact, render_report, render_trace
from dlens.graph.report import build_report
from dlens.ingest import DbtError
from dlens.ingest import ingest as run_ingest

app = typer.Typer(help="DLens: column-level lineage and grounded Q&A for dbt projects.")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Show version."
    ),
) -> None:
    """DLens: column-level lineage and grounded Q&A for dbt projects."""


@app.command()
def ingest(project_dir: Annotated[Path, typer.Argument(help="Path to a dbt project.")]) -> None:
    """Run dbt on PROJECT_DIR and summarise what DLens will see."""
    try:
        r = run_ingest(project_dir)
    except DbtError as e:
        typer.echo(f"ingest failed: {e}", err=True)
        raise typer.Exit(1) from e
    typer.echo(f"models:      {len(r.manifest.models)}")
    typer.echo(f"seeds:       {len(r.manifest.seeds)}")
    typer.echo(f"sources:     {len(r.manifest.sources)}")
    typer.echo(f"exposures:   {len(r.manifest.exposures)}")
    typer.echo(f"columns:     {r.catalog.total_columns}")
    typer.echo(f"unmapped relations: {len(r.unmapped)}")
    for rel in r.unmapped:
        typer.echo(f"  - {rel}")


ProjectOpt = Annotated[Path, typer.Option("--project", "-p", help="dbt project directory.")]
DepthOpt = Annotated[int, typer.Option("--depth", "-d", min=1, help="Maximum number of hops.")]
RebuildOpt = Annotated[bool, typer.Option("--rebuild", help="Ignore the cached graph.")]


def _open_graph(project: Path, column: str, rebuild: bool) -> tuple[LineageGraph, str]:
    """Load (or build) the graph and resolve COLUMN; exit 1 on a dbt failure, 2 on a bad column."""
    try:
        graph = load_or_build(project, rebuild=rebuild)
    except DbtError as e:
        typer.echo(f"graph build failed: {e}", err=True)
        raise typer.Exit(1) from e
    try:
        return graph, graph.resolve(column)
    except (ColumnNotFound, AmbiguousColumn) as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from e


@app.command()
def trace(
    column: Annotated[str, typer.Argument(help="Column id, e.g. fct_orders.revenue_finance.")],
    project: ProjectOpt = Path("."),
    depth: DepthOpt = 10,
    rebuild: RebuildOpt = False,
) -> None:
    """Show where COLUMN comes from: every upstream path, with expression and file:lines."""
    graph, col = _open_graph(project, column, rebuild)
    typer.echo(
        render_trace(
            graph, col, graph.upstream(col, max_depth=depth, include_indirect=False), depth
        )
    )


@app.command()
def impact(
    column: Annotated[str, typer.Argument(help="Column id, e.g. raw_orders.tax_usd.")],
    project: ProjectOpt = Path("."),
    depth: DepthOpt = 10,
    rebuild: RebuildOpt = False,
) -> None:
    """Show what COLUMN feeds: downstream columns, models and exposures."""
    graph, col = _open_graph(project, column, rebuild)
    typer.echo(
        render_impact(graph, graph.downstream(col, max_depth=depth, include_indirect=False), depth)
    )


@app.command()
def report(
    project: ProjectOpt = Path("."),
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
    rebuild: RebuildOpt = False,
) -> None:
    """Parse quality per model (FULL / TABLE_ONLY / FAILED) with gaps, and edge totals."""
    try:
        graph = load_or_build(project, rebuild=rebuild)
    except DbtError as e:
        typer.echo(f"graph build failed: {e}", err=True)
        raise typer.Exit(1) from e
    r = build_report(graph)
    typer.echo(r.model_dump_json(indent=2) if as_json else render_report(r))


def trace_summary(run: AgentRun) -> dict[str, object]:
    rec = run.record
    results = [r for s in rec.steps if s.phase != "code" for r in s.results]
    return {
        "llm_calls": rec.llm_calls,
        "tool_calls": sum(not r.deduped for r in results),
        "deduped": sum(r.deduped for r in results),
        "code_calls": sum(s.phase == "code" for s in rec.steps),
        "max_input_tokens_est": rec.tokens.get("max_est_input", 0),
        "cached_calls": rec.tokens.get("cached_calls", 0),
        "compactions": len(rec.compactions),
        "partial_evidence": run.answer.partial_evidence,
        "ambiguity": (rec.ambiguity or {}).get("mode"),
        "stop_reason": rec.stop_reason,
        "validator": _validator_label(rec.validation),
        "log": str(run.log_path) if run.log_path else None,
    }


def _validator_label(v: dict[str, object] | None) -> str:
    if not v or v.get("skipped"):
        return "skipped"
    parts = ["pass" if v.get("passed") else ("warning" if v.get("warning") else "fail")]
    repairs = v.get("repairs") or []
    if isinstance(repairs, list) and repairs:
        parts.append(f"repaired {len(repairs)}")
    completions = v.get("completions") or []
    if isinstance(completions, list) and completions:
        parts.append(f"completed {len(completions)}")
    if v.get("regenerated"):
        parts.append("regenerated")
    return ", ".join(parts)


def render_trace_line(t: dict[str, object]) -> str:
    tools = f"{t['tool_calls']} tools, {t['deduped']} deduped"
    if t["code_calls"]:
        tools += f", {t['code_calls']} by code"
    parts = [
        f"steps {t['llm_calls']} ({tools})",
        f"max input ~{t['max_input_tokens_est']:,} tok",
        f"cached {t['cached_calls']}/{t['llm_calls']}",
        f"compactions {t['compactions']}",
        f"partial {'yes' if t['partial_evidence'] else 'no'}",
    ]
    if t["ambiguity"]:
        parts.append(f"ambiguity {t['ambiguity']}")
    parts += [f"validator: {t['validator']}", f"log: {t['log']}"]
    return " · ".join(parts)


@app.command("ask")
def ask_cmd(
    question: Annotated[str, typer.Argument(help="A lineage question in plain English.")],
    project: ProjectOpt = Path("."),
    provider: Annotated[
        str | None,
        typer.Option("--provider", help="LLM provider (default: $DLENS_PROVIDER or ollama)."),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
    rebuild: RebuildOpt = False,
) -> None:
    """Answer QUESTION with cited lineage evidence (agent loop; logs one JSONL draft record)."""
    try:
        graph = load_or_build(project, rebuild=rebuild)
    except DbtError as e:
        typer.echo(f"graph build failed: {e}", err=True)
        raise typer.Exit(1) from e
    try:
        client = make_client(provider)
    except ValueError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from e
    run = run_agent(
        question, client, Toolbox(graph, project), RunLogger(runs_dir()), project=str(project)
    )
    trace = trace_summary(run)
    if as_json:
        typer.echo(
            json.dumps({"answer": run.answer.model_dump(mode="json"), "trace": trace}, indent=2)
        )
        return
    typer.echo(render_answer(run.answer))
    typer.echo("")
    typer.echo(render_trace_line(trace))
