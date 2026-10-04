"""impact_downstream: what reads a column, by depth, plus affected models and exposures."""

from __future__ import annotations

from typing import Any

from dlens.agent.tools.budget import MAX_RESULT_TOKENS, largest_fit
from dlens.agent.tools.common import (
    ToolOutput,
    as_bool,
    as_int,
    as_str,
    direct,
    resolve_column,
)
from dlens.agent.tools.provenance import Provenance, edge_id


def impact_downstream(prov: Provenance, args: dict[str, Any]) -> ToolOutput:
    text = as_str(args, "column_id")
    assert text is not None
    max_depth = as_int(args, "max_depth", 10, 1, 50)
    as_bool(args, "include_indirect", True)  # accepted and checked, not traversed (S10/S12)
    g = prov.graph
    col = resolve_column(g, text)
    r = g.downstream(col, max_depth=max_depth, include_indirect=False)

    flat = [(d, c) for d in sorted(r.columns_by_depth) for c in r.columns_by_depth[d]]
    models = [(g.model_info(m) or {}).get("name", m) for m in r.models]
    exposures = [
        {"name": (info or {}).get("name", x), "type": (info or {}).get("type", "")}
        for x in r.exposures
        for info in [g.exposure_info(x)]
    ]
    notes = ["indirect edges (join/filter/group keys) are not in the graph yet"]

    def render(kc: int, km: int) -> dict[str, Any]:
        by_depth: dict[str, list[dict[str, str]]] = {}
        for d, c in flat[:kc]:
            by_depth.setdefault(str(d), []).append(
                {"id": g.display_name(c), "via": edge_id(direct(r.via[c]))}
            )
        return {
            "column": g.display_name(col),
            "columns_by_depth": by_depth,
            "models": models[:km],
            "exposures": exposures,
            "depth_limited": r.truncated,
            "truncated": kc < len(flat) or km < len(models),
            "dropped": {"columns": len(flat) - kc, "models": len(models) - km},
            "notes": notes,
        }

    kc = largest_fit(len(flat), lambda k: render(k, len(models)), MAX_RESULT_TOKENS)
    km = len(models)
    if kc == 0 and flat:
        km = largest_fit(len(models), lambda k: render(0, k), MAX_RESULT_TOKENS)
    edges, columns = {}, {}
    for _, c in flat[:kc]:
        rec = prov.edge_record(direct(r.via[c]))
        edges[str(rec["edge_id"])] = rec
        columns[g.display_name(c)] = {
            "id": c,
            "citation": prov.column_citation(c).model_dump(),
        }
    return ToolOutput(render(kc, km), {"column": col, "edges": edges, "columns": columns})
