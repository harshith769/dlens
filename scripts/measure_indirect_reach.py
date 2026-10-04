"""Measure what indirect traversal would do to impact results (S04 item 7). Measures only.

    uv run python scripts/measure_indirect_reach.py                      # synthetic_shop
    uv run python scripts/measure_indirect_reach.py corpora/synthetic_shop --column stg_orders.order_id

For each column, side by side with include_indirect False and True:
- the max hop depth reached (traversal run to depth 50) and whether the default depth limit of 10
  truncates the result;
- the token size of the full, uncapped impact payload at depth 10, in the impact_downstream tool's
  shape, against the tool-result cap (MAX_RESULT_TOKENS) and the ~3K input cap (MAX_INPUT_TOKENS).
  Indirect hops get edge ids of the same form and length as direct ones.

Changes no limit and no default: the tools still pass include_indirect=False (S10/S12 decide).
Builds a temporary copy of the corpus, so the repo stays free of target/ and *.duckdb.
"""

import argparse
import hashlib
import shutil
import tempfile
from pathlib import Path
from typing import Any

from dlens.agent.llm.tokens import MAX_INPUT_TOKENS
from dlens.agent.tools.budget import MAX_RESULT_TOKENS, payload_tokens
from dlens.graph import Hop, ImpactResult, LineageGraph, build_graph

DEFAULT_COLUMNS = ["stg_products.product_id", "raw_order_items.unit_price"]
DEFAULT_DEPTH = 10
DEEP = 50


def hop_id(hop: Hop) -> str:
    """Same form as dlens.agent.tools.provenance.edge_id, for direct and indirect hops."""
    key = f"{hop.from_column}|{hop.to_column}|{hop.kind.value}"
    return "e_" + hashlib.sha1(key.encode()).hexdigest()[:8]


def uncapped_payload(g: LineageGraph, col: str, r: ImpactResult) -> dict[str, Any]:
    """impact_downstream's payload with every column and model kept (no budget trimming)."""
    by_depth: dict[str, list[dict[str, str]]] = {}
    for d in sorted(r.columns_by_depth):
        for c in r.columns_by_depth[d]:
            by_depth.setdefault(str(d), []).append(
                {"id": g.display_name(c), "via": hop_id(r.via[c])}
            )
    models = [(g.model_info(m) or {}).get("name", m) for m in r.models]
    exposures = [
        {"name": (g.exposure_info(x) or {}).get("name", x), "type": ""} for x in r.exposures
    ]
    return {
        "column": g.display_name(col),
        "columns_by_depth": by_depth,
        "models": models,
        "exposures": exposures,
        "depth_limited": r.truncated,
        "truncated": False,
        "dropped": {"columns": 0, "models": 0},
        "notes": ["indirect edges (join/filter/group keys) are not in the graph yet"],
    }


def measure(g: LineageGraph, text: str, include_indirect: bool) -> dict[str, Any]:
    col = g.resolve(text)
    deep = g.downstream(col, max_depth=DEEP, include_indirect=include_indirect)
    default = g.downstream(col, max_depth=DEFAULT_DEPTH, include_indirect=include_indirect)
    tokens = payload_tokens(uncapped_payload(g, col, default))
    return {
        "columns": len(deep.columns),
        "max hops": max(deep.columns_by_depth, default=0),
        "columns at depth<=10": len(default.columns),
        "depth 10 truncates": default.truncated,
        "payload tokens (depth 10)": tokens,
        "over tool cap": tokens > MAX_RESULT_TOKENS,
        "over input cap": tokens > MAX_INPUT_TOKENS,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus", type=Path, nargs="?", default=Path("corpora/synthetic_shop"))
    ap.add_argument("--column", action="append", help="column to measure (repeatable)")
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / args.corpus.name
        shutil.copytree(
            args.corpus, project, ignore=shutil.ignore_patterns("target", "*.duckdb", "logs")
        )
        g = build_graph(project)
    print(f"caps: tool result {MAX_RESULT_TOKENS} tokens, input {MAX_INPUT_TOKENS} tokens")
    for text in args.column or DEFAULT_COLUMNS:
        off, on = measure(g, text, False), measure(g, text, True)
        print(f"\n{text}")
        print(f"  {'':28} {'include_indirect=False':>24} {'include_indirect=True':>24}")
        for key in off:
            print(f"  {key:28} {off[key]!s:>24} {on[key]!s:>24}")


if __name__ == "__main__":
    main()
