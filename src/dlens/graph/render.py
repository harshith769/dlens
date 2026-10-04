"""Plain-text trees for ``dlens trace`` and ``dlens impact``. Pure: every function returns a str."""

from dataclasses import dataclass, field

from dlens.graph.graph import LineageGraph
from dlens.graph.models import Hop, ImpactResult, PathList, hop_rank
from dlens.graph.report import Report
from dlens.lineage import Confidence, IndirectEdge

EXPR_WIDTH = 60


@dataclass
class _Node:
    column: str
    edge: Hop | None = None
    # keyed by (column, hop_rank): one column can be reached by several indirect types
    children: dict[tuple[str, int], "_Node"] = field(default_factory=dict)


def _expr(text: str) -> str:
    one = " ".join(text.split())
    return one if len(one) <= EXPR_WIDTH else one[: EXPR_WIDTH - 1] + "…"


def _cite(e: Hop) -> str:
    return (
        f"{e.file} (whole model)"
        if e.model_level_citation
        else f"{e.file}:{e.lines[0]}-{e.lines[1]}"
    )


def _hop(g: LineageGraph, node: _Node) -> str:
    e = node.edge
    assert e is not None
    low = " (low confidence)" if e.confidence == Confidence.LOW else ""
    # An indirect hop is marked with its type; its expression is the clause (ADR 0020).
    tag = f"[indirect {e.kind}]" if isinstance(e, IndirectEdge) else f"[{e.kind}]"
    return f"{g.display_name(node.column)}  {tag}{low}  {_expr(e.expression)}  {_cite(e)}"


def _draw(g: LineageGraph, node: _Node, prefix: str, lines: list[str]) -> None:
    kids = [node.children[k] for k in sorted(node.children)]
    for i, kid in enumerate(kids):
        last = i == len(kids) - 1
        lines.append(f"{prefix}{'└─ ' if last else '├─ '}{_hop(g, kid)}")
        _draw(g, kid, prefix + ("   " if last else "│  "), lines)


def render_trace(g: LineageGraph, root: str, paths: PathList, max_depth: int) -> str:
    tree = _Node(root)
    for p in paths:
        node = tree
        for e in p.edges:
            node = node.children.setdefault((e.from_column, hop_rank(e)), _Node(e.from_column, e))
    lines = [g.display_name(root)]
    _draw(g, tree, "", lines)
    if not paths:
        lines.append("(no upstream columns: this column is a source)")
    else:
        ends = {p.end for p in paths}
        deepest = max(p.depth for p in paths)
        lines.append("")
        lines.append(
            f"{len(paths)} path(s), deepest {deepest} hop(s), {len(ends)} origin column(s)"
        )
        indirect = sum(isinstance(h, IndirectEdge) for p in paths for h in p.edges)
        if indirect:
            lines.append(f"{indirect} indirect hop(s) (join/filter/group/sort/window keys)")
    if paths.depth_limited:
        lines.append(f"note: some paths were cut at --depth {max_depth}; raise it to see more")
    if paths.truncated:
        lines.append(f"warning: path limit reached ({len(paths)}); the list is incomplete")
    return "\n".join(lines)


def render_impact(g: LineageGraph, r: ImpactResult, max_depth: int) -> str:
    nodes: dict[str, _Node] = {r.root: _Node(r.root)}
    for col in r.columns:
        nodes[col] = _Node(col, r.via[col])
    for col in r.columns:
        nodes[r.via[col].from_column].children[(col, 0)] = nodes[col]
    lines = [g.display_name(r.root)]
    _draw(g, nodes[r.root], "", lines)
    if not r.columns:
        lines.append("(nothing downstream reads this column)")
    lines.append("")
    lines.append(f"{len(r.columns)} affected column(s), {len(r.models)} model(s)")
    for depth in sorted(r.columns_by_depth):
        lines.append(f"  depth {depth}: {len(r.columns_by_depth[depth])} column(s)")
    indirect = sum(isinstance(h, IndirectEdge) for h in r.via.values())
    if indirect:
        lines.append(f"{indirect} column(s) reached by an indirect hop")
    if r.models:
        lines.append("models: " + ", ".join(m.split(".", 2)[-1] for m in r.models))
    lines.append("exposures: " + (", ".join(r.exposures) if r.exposures else "none"))
    if r.truncated:
        lines.append(f"warning: stopped at --depth {max_depth}; more columns lie downstream")
    return "\n".join(lines)


def render_report(report: Report) -> str:
    """Per-model quality (problems first, with reasons and gaps), then totals."""
    t = report.totals
    order = {"FAILED": 0, "TABLE_ONLY": 1, "FULL": 2}
    models = sorted(report.models, key=lambda m: (order[m.quality], m.model))
    width = max((len(_short_model(m.model)) for m in models), default=0)
    lines = ["Parse quality per model:"]
    for m in models:
        extra = f"  ({len(m.constants)} constant column(s))" if m.constants else ""
        lines.append(f"  {_short_model(m.model):<{width}}  {m.quality}{extra}")
        if m.quality == "FAILED" and m.reason:
            lines.append(f"      reason: {_expr(m.reason)}")
        lines += [f"      gap: {g}" for g in m.gaps]
        lines += [f"      citation gap: {g}" for g in m.citation_gaps]
    q = t.models_by_quality
    lines += [
        "",
        f"Models: {q['FULL']} FULL, {q['TABLE_ONLY']} TABLE_ONLY, {q['FAILED']} FAILED",
        f"Edges: {t.edges}  (" + ", ".join(f"{k} {n}" for k, n in t.edges_by_kind.items()) + ")",
        f"Model-level citations: {t.model_level_citations}",
        f"Indirect edges: {t.indirect_edges}  "
        f"(model-level citations: {t.indirect_model_level_citations})",
        f"Low-confidence edges: {t.low_confidence_edges}",
        f"Deferred indirect (window keys, v0.3): {t.deferred_indirect}",
        f"Constant columns (no edges): {t.constants}",
    ]
    return "\n".join(lines)


def _short_model(unique_id: str) -> str:
    return unique_id.split(".")[-1]
