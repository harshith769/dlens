"""reachability: a graph check between two columns, run by CODE (never offered to the LLM).

The loop calls it when a yes/no question names exactly two exact columns (docs/explain/agent.md).
It emits one citable fact id, ``r_`` + sha1("from|to|reach")[:8], whose record states whether
``from`` reaches ``to`` (and the reverse), plus the edges of the shortest connecting path, which
are emitted like any trace edge. The validator's R3 re-runs ``check`` for an ``r_`` id, and R9
holds the answer's yes/no verdict to it.

Mode (s12-design A5, ADR 0026, R9 option (a)): the verdict uses direct + indirect hops, because
yes/no is an impact-family question (metrics M4). The fact also states the direct reading
(decision A5-R9-DIRECT-READING: the shortest path over DERIVES edges only), so the model sees
whether the link runs through direct edges or only through join / filter / group keys.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import networkx as nx

from dlens.agent.tools.common import ToolOutput, as_str, resolve_column
from dlens.agent.tools.provenance import Provenance, edge_id
from dlens.graph import Hop, LineageGraph
from dlens.lineage import Edge

MAX_REACH_DEPTH = 100  # longer than any path in a dbt project; the walk stops when it runs out


def fact_id(src: str, dst: str) -> str:
    return "r_" + hashlib.sha1(f"{src}|{dst}|reach".encode()).hexdigest()[:8]


@dataclass(frozen=True)
class Reach:
    src: str  # full column ids, in the direction the question asks
    dst: str
    forward: tuple[Hop, ...] | None  # shortest directed path src -> dst, None if unreachable
    backward: tuple[Hop, ...] | None  # shortest directed path dst -> src
    direct_forward: tuple[Edge, ...] | None = None  # the same over DERIVES edges only
    direct_backward: tuple[Edge, ...] | None = None

    @property
    def reaches(self) -> bool:
        return self.forward is not None

    @property
    def path(self) -> tuple[Hop, ...]:
        """The path to show: forward if it exists, else backward, else none."""
        return self.forward or self.backward or ()


def _shortest_direct(graph: LineageGraph, a: str, b: str) -> tuple[Edge, ...] | None:
    """A5-R9-DIRECT-READING: shortest path over DERIVES edges (``nx_graph`` holds only those)."""
    try:
        nodes = nx.shortest_path(graph.nx_graph, a, b)
    except nx.NetworkXNoPath:
        return None
    return tuple(graph.edge(u, v) for u, v in zip(nodes, nodes[1:], strict=False))


def _shortest(graph: LineageGraph, a: str, b: str) -> tuple[Hop, ...] | None:
    """Shortest path over direct and indirect hops (a direct hop preferred at equal depth)."""
    r = graph.downstream(a, max_depth=MAX_REACH_DEPTH, include_indirect=True)
    if b not in r.via:
        return None
    out: list[Hop] = []
    while b != a:
        h = r.via[b]
        out.append(h)
        b = h.from_column
    return tuple(reversed(out))


def check(graph: LineageGraph, src: str, dst: str) -> Reach:
    return Reach(
        src,
        dst,
        _shortest(graph, src, dst),
        _shortest(graph, dst, src),
        _shortest_direct(graph, src, dst),
        _shortest_direct(graph, dst, src),
    )


def _hops(n: int) -> str:
    return f"{n} hop" if n == 1 else f"{n} hops"


def _direct_part(path: tuple[Hop, ...], direct: tuple[Edge, ...] | None) -> str:
    if direct is None:
        return "with indirect dependencies; not through direct edges"
    if len(direct) == len(path) and all(isinstance(h, Edge) for h in path):
        return "through direct edges"
    return f"with indirect dependencies; through direct edges in {_hops(len(direct))}"


def statement(graph: LineageGraph, r: Reach) -> str:
    """The fact in words, stating both readings, e.g. "a.x reaches b.y in 1 hop (graph check:
    with indirect dependencies; not through direct edges)"."""
    a, b = graph.display_name(r.src), graph.display_name(r.dst)
    if r.forward is not None:
        how = _direct_part(r.forward, r.direct_forward)
        return f"{a} reaches {b} in {_hops(len(r.forward))} (graph check: {how})"
    out = f"{a} does NOT reach {b} (graph check: direct or indirect)"
    if r.backward is not None:
        out += f"; {b} reaches {a} in {_hops(len(r.backward))}"
    return out


def fact_record(graph: LineageGraph, r: Reach) -> dict[str, Any]:
    """The ledger record of an ``r_`` id (no citation: R3 re-runs ``check`` instead)."""
    return {
        "fact_id": fact_id(r.src, r.dst),
        "from": r.src,
        "to": r.dst,
        "reaches": r.reaches,
        "hops": None if r.forward is None else len(r.forward),
        "reverse_hops": None if r.backward is None else len(r.backward),
        "path": [edge_id(e) for e in r.path],
        "direct_reaches": r.direct_forward is not None,
        "direct_hops": None if r.direct_forward is None else len(r.direct_forward),
        "fact": statement(graph, r),
    }


def reachability(prov: Provenance, args: dict[str, Any]) -> ToolOutput:
    g = prov.graph
    src = resolve_column(g, as_str(args, "from_column") or "")
    dst = resolve_column(g, as_str(args, "to_column") or "")
    r = check(g, src, dst)
    rec = fact_record(g, r)
    payload = {
        "from": g.display_name(src),
        "to": g.display_name(dst),
        "fact_id": rec["fact_id"],
        "fact": rec["fact"],
        "reaches": r.reaches,
        "path": [prov.edge_string(e) for e in r.path],
    }
    side = {
        "edges": {edge_id(e): prov.edge_record(e) for e in r.path},
        "facts": {rec["fact_id"]: rec},
        "columns": {g.display_name(c): {"id": c} for c in (src, dst)},
    }
    return ToolOutput(payload, side)
