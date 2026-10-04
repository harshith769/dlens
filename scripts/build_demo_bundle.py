"""Build the public-demo bundle: demo/synthetic_shop/{graph.json, the files the graph cites}.

Usage:  uv run python scripts/build_demo_bundle.py

Loads (or rebuilds with dbt) the synthetic_shop graph, saves it as demo/synthetic_shop/graph.json
and copies only the source/seed files the graph points at. Re-run after any lineage or version
change: LineageGraph.load refuses a graph built by another dlens version.
"""

import shutil
import sys
from pathlib import Path

from dlens.graph import load_or_build
from dlens.ui import demo

CORPUS = demo.ROOT / "corpora" / demo.PROJECT


def main() -> int:
    out = demo.ROOT / "demo" / demo.PROJECT
    graph = load_or_build(CORPUS)
    if out.exists():
        shutil.rmtree(out)
    graph.save(out / demo.GRAPH_FILE)
    files = demo.bundle_files(graph)
    for rel in files:
        src = CORPUS / rel
        if not src.is_file():
            sys.exit(f"missing in the corpus: {rel}")
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, out / rel)
    print(f"wrote {out.relative_to(demo.ROOT)}: graph + {len(files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
