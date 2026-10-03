"""Plain-text trees for ``dlens trace`` and ``dlens impact``. Pure: every function returns a str."""

from dataclasses import dataclass, field

from dlens.graph.graph import LineageGraph
from dlens.graph.models import ImpactResult, PathList
from dlens.lineage import Confidence, Edge

EXPR_WIDTH = 60


@dataclass
class _Node:
    column: str
    edge: Edge | None = None
    children: dict[str, "_Node"] = field(default_factory=dict)


def _expr(text: str) -> str:
    one = " ".join(text.split())
    return one if len(one) <= EXPR_WIDTH else one[: EXPR_WIDTH - 1] + "…"


def _cite(e: Edge) -> str:
    return (
        f"{e.file} (whole model)"
        if e.model_level_citation
        else f"{e.file}:{e.lines[0]}-{e.lines[1]}"
    )


def _hop(g: LineageGraph, node: _Node) -> str:
    e = node.edge
    assert e is not None
    low = " (low confidence)" if e.confidence == Confidence.LOW else ""
    return f"{g.display_name(node.column)}  [{e.kind}]{low}  {_expr(e.expression)}  {_cite(e)}"


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
            node = node.children.setdefault(e.from_column, _Node(e.from_column, e))
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
        nodes[r.via[col].from_column].children[col] = nodes[col]
    lines = [g.display_name(r.root)]
    _draw(g, nodes[r.root], "", lines)
    if not r.columns:
        lines.append("(nothing downstream reads this column)")
    lines.append("")
    lines.append(f"{len(r.columns)} affected column(s), {len(r.models)} model(s)")
    for depth in sorted(r.columns_by_depth):
        lines.append(f"  depth {depth}: {len(r.columns_by_depth[depth])} column(s)")
    if r.models:
        lines.append("models: " + ", ".join(m.split(".", 2)[-1] for m in r.models))
    lines.append("exposures: " + (", ".join(r.exposures) if r.exposures else "none"))
    if r.truncated:
        lines.append(f"warning: stopped at --depth {max_depth}; more columns lie downstream")
    return "\n".join(lines)
