"""trace_upstream: every path from a column back to what it is computed from."""

from __future__ import annotations

from typing import Any

from dlens.agent.tools.budget import MAX_RESULT_TOKENS, largest_fit
from dlens.agent.tools.common import ToolOutput, as_bool, as_int, as_str, resolve_column
from dlens.agent.tools.provenance import Provenance


def trace_upstream(prov: Provenance, args: dict[str, Any]) -> ToolOutput:
    text = as_str(args, "column_id")
    assert text is not None
    max_depth = as_int(args, "max_depth", 10, 1, 50)
    include_indirect = as_bool(args, "include_indirect", False)
    g = prov.graph
    col = resolve_column(g, text)
    paths = g.upstream(col, max_depth=max_depth, include_indirect=include_indirect)
    strings = [[prov.edge_string(e) for e in p.edges] for p in paths]
    notes: list[str] = []
    if include_indirect:
        notes.append("indirect edges are not in the graph yet; only direct edges are returned")
    if not paths:
        notes.append("no upstream columns: this column is a source or a leaf")
    if paths.truncated:
        notes.append("more paths exist than were enumerated")

    def render(k: int) -> dict[str, Any]:
        out: dict[str, Any] = {
            "column": g.display_name(col),
            "n_paths": len(paths),
            "paths": strings[:k],
            "depth_limited": paths.depth_limited,
            "truncated": k < len(paths) or paths.truncated,
            "dropped": {"paths": len(paths) - k},
        }
        if notes:
            out["notes"] = notes
        return out

    kept = largest_fit(len(paths), render, MAX_RESULT_TOKENS)
    edges = {}
    for p in list(paths)[:kept]:
        for e in p.edges:
            rec = prov.edge_record(e)
            edges[str(rec["edge_id"])] = rec
    return ToolOutput(render(kept), {"column": col, "edges": edges})
