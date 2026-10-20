"""impact_downstream: what reads a column, grouped by depth and hop kind, plus affected models
and exposures.

Direct + indirect by default (spec §7/§8; s12-design A5, ADR 0026); ``include_indirect`` is
accepted but not advertised to the LLM. Payload shape B (owner, 20 Oct 2026): full dotted ids,
one ``via`` edge id each, grouped by (depth, kind)::

    "columns_by_depth": {"1 [direct]": ["fct_x.a e_…", …], "2 [JOIN]": ["fct_y.b e_…", …]}

Labels: a column is ``[direct]`` only if an all-direct path reaches it, at its direct depth.
Otherwise its label is the kind of the FIRST indirect hop on its shortest path, and its depth is
that path's length. A column reachable both ways appears once, under ``[direct]``.

Over the token cap, columns are cut in a fixed order (depth, model, column), kept from the front,
and every cut (depth, kind, model) leaves one visible line in ``more``: "+K more columns in
<model> (<kind>)". If that would take more than ``MAX_MORE_LINES`` lines (a wide project where
each cut model loses one column, so the lines would be as long as the columns they replace), the
lines are per (depth, kind) instead: "+K more columns in N models (<kind>, depth D)".
``side["full"]`` always holds every column with its whole via chain.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from dlens.agent.tools.budget import MAX_RESULT_TOKENS, largest_fit
from dlens.agent.tools.common import (
    ToolOutput,
    as_bool,
    as_int,
    as_str,
    hop,
    resolve_column,
)
from dlens.agent.tools.provenance import Provenance, edge_id
from dlens.graph import Hop, ImpactResult, LineageGraph, hop_label
from dlens.lineage import Edge, IndirectKind

DIRECT = "direct"
MAX_MORE_LINES = 12


@dataclass(frozen=True)
class Reached:
    column: str  # full id
    name: str  # model.column, as shown
    model: str  # model name
    depth: int
    label: str  # "direct", or the kind of the first indirect hop on the path
    chain: tuple[Hop, ...]  # the queried column -> this column

    @property
    def via(self) -> Hop:
        return self.chain[-1]

    @property
    def group(self) -> str:
        return f"{self.depth} [{self.label}]"

    @property
    def item(self) -> str:
        return f"{self.name} {edge_id(self.via)}"


def label_rank(label: str) -> int:
    return 0 if label == DIRECT else 1 + list(IndirectKind).index(IndirectKind(label))


def _chain(r: ImpactResult, root: str, column: str) -> tuple[Hop, ...]:
    out: list[Hop] = []
    while column != root:
        h = hop(r.via[column])
        out.append(h)
        column = h.from_column
    return tuple(reversed(out))


def reached_columns(
    g: LineageGraph, col: str, max_depth: int, include_indirect: bool
) -> tuple[list[Reached], ImpactResult]:
    """Every reached column with its label and chain, in cut order (depth, model, column)."""
    r = g.downstream(col, max_depth=max_depth, include_indirect=include_indirect)
    # A5-IMPACT-DIRECT-LABEL: a direct-only walk decides which columns are [direct]
    d = g.downstream(col, max_depth=max_depth, include_indirect=False) if include_indirect else r
    out: list[Reached] = []
    for c in r.via:
        if c in d.via:
            chain, label = _chain(d, col, c), DIRECT
        else:
            chain = _chain(r, col, c)
            label = next(hop_label(h) for h in chain if not isinstance(h, Edge))
        model = (g.model_info(g.model_of(c)) or {}).get("name", g.model_of(c))
        out.append(Reached(c, g.display_name(c), model, len(chain), label, chain))
    out.sort(key=lambda x: (x.depth, x.model, x.name))
    return out, r


def _groups(items: list[Reached]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for x in sorted(items, key=lambda x: (x.depth, label_rank(x.label), x.model, x.name)):
        groups.setdefault(x.group, []).append(x.item)
    return groups


def more_lines(cut: list[Reached]) -> list[str]:
    """One line per cut (depth, kind, model), in cut order; per (depth, kind) when that would be
    more than ``MAX_MORE_LINES`` lines."""
    counts = Counter((x.depth, x.label, x.model) for x in cut)
    if len(counts) <= MAX_MORE_LINES:
        return [f"+{n} more columns in {m} ({label})" for (_, label, m), n in counts.items()]
    groups: dict[tuple[int, str], tuple[int, set[str]]] = {}
    for x in cut:
        n, models = groups.get((x.depth, x.label), (0, set()))
        groups[(x.depth, x.label)] = (n + 1, models | {x.model})
    return [
        f"+{n} more columns in {len(models)} model{'s' if len(models) > 1 else ''} "
        f"({label}, depth {depth})"
        for (depth, label), (n, models) in groups.items()
    ]


def impact_downstream(prov: Provenance, args: dict[str, Any]) -> ToolOutput:
    text = as_str(args, "column_id")
    assert text is not None
    max_depth = as_int(args, "max_depth", 10, 1, 50)
    include_indirect = as_bool(args, "include_indirect", True)
    g = prov.graph
    col = resolve_column(g, text)
    flat, r = reached_columns(g, col, max_depth, include_indirect)

    models = [(g.model_info(m) or {}).get("name", m) for m in r.models]
    exposures = [
        {"name": (info or {}).get("name", x), "type": (info or {}).get("type", "")}
        for x in r.exposures
        for info in [g.exposure_info(x)]
    ]

    def render(kc: int, km: int) -> dict[str, Any]:
        out: dict[str, Any] = {
            "column": g.display_name(col),
            "mode": "direct + indirect" if include_indirect else "direct",
            "columns_by_depth": _groups(flat[:kc]),
        }
        if kc < len(flat):
            out["more"] = more_lines(flat[kc:])
        return out | {
            "models": models[:km],
            "exposures": exposures,
            "depth_limited": r.truncated,
            "truncated": kc < len(flat) or km < len(models),
            "dropped": {"columns": len(flat) - kc, "models": len(models) - km},
        }

    kc = largest_fit(len(flat), lambda k: render(k, len(models)), MAX_RESULT_TOKENS)
    km = len(models)
    if kc == 0 and flat:
        km = largest_fit(len(models), lambda k: render(0, k), MAX_RESULT_TOKENS)
    edges, columns = {}, {}
    for x in flat[:kc]:
        rec = prov.edge_record(x.via)
        edges[str(rec["edge_id"])] = rec
        columns[x.name] = {
            "id": x.column,
            "citation": prov.column_citation(x.column).model_dump(),
            "depth": x.depth,
            "label": x.label,
        }
    full_edges = {edge_id(h): prov.edge_record(h) for x in flat for h in x.chain}
    full_columns = {
        x.name: {
            "id": x.column,
            "depth": x.depth,
            "label": x.label,
            "via": edge_id(x.via),
            "chain": [edge_id(h) for h in x.chain],
        }
        for x in flat
    }
    side = {
        "column": col,
        "edges": edges,  # shown columns' via edges: what the ledger emits
        "columns": columns,
        "full": {"columns": full_columns, "edges": full_edges},  # for code (G1), never shown
    }
    return ToolOutput(render(kc, km), side)
