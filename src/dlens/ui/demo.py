"""Public demo mode (``DLENS_DEMO=1``): the app reads a prebuilt bundle instead of a dbt project.

The bundle (``demo/synthetic_shop/``) holds the saved lineage graph and only the project files the
graph points at: the source ``.sql`` and seed files that the Source tab, ``get_model_sql`` and
validator R3 read. No dbt run, no ``target/``. Build it with ``scripts/build_demo_bundle.py``.
No Streamlit import here, so it is unit-tested directly.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from dlens.graph import LineageGraph

ROOT = Path(__file__).resolve().parents[3]
PROJECT = "synthetic_shop"
GRAPH_FILE = "graph.json"  # not under target/: that folder is gitignored


def enabled(env: Mapping[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    return env.get("DLENS_DEMO") == "1"


def bundle_dir(env: Mapping[str, str] | None = None) -> Path:
    """``$DLENS_DEMO_DIR`` if set (tests use a temp copy), else ``demo/`` in the repo."""
    env = os.environ if env is None else env
    return Path(env["DLENS_DEMO_DIR"]) if env.get("DLENS_DEMO_DIR") else ROOT / "demo"


def projects(env: Mapping[str, str] | None = None) -> dict[str, Path]:
    return {PROJECT: bundle_dir(env) / PROJECT}


def load_graph(project_dir: Path) -> LineageGraph:
    return LineageGraph.load(project_dir / GRAPH_FILE)


def bundle_files(graph: LineageGraph) -> list[str]:
    """Every project-relative file the graph cites: model/seed files and edge files."""
    files = {(graph.model_info(m) or {}).get("file", "") for m in graph.model_ids()}
    files |= {e.file for e in graph.edges()}
    return sorted(f for f in files if f)
