"""Set-E gold export: the DLens graph of the pinned dbt_jira (S15a; spec §11.1 exception).

uv run python scripts/build_external_gold.py            # writes eval/questions/drafts/external_gold_graph_v1.json
uv run python scripts/build_external_gold.py --verify   # rebuilds, compares graph_sha256, writes nothing

Copies corpora/dbt_jira to a temporary directory, builds it offline (dbt-duckdb, as
scripts/s13d_measure.py::jira_build), builds the lineage graph from the artifacts and exports the
parts set-E gold needs: short-id columns (`model.column`; sources by table name; seeds have no
edges and are left out), direct edges with their citation, indirect pairs and model dependencies.
`graph_sha256` is the sha256 of the full graph JSON (LineageGraph.save), which is deterministic.

This IS parser output, used as gold only for set E (spec §11.1), and recorded as such in every
set-E draft (`gold_source: parser`). Freeze rule (s15a-drafts-design.md §2.1): before the freeze the
owner runs --verify with the frozen engine; any mismatch -> STOP, set-E gold is regenerated and
re-reviewed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
JIRA = ROOT / "corpora" / "dbt_jira"
OUT = ROOT / "eval" / "questions" / "drafts" / "external_gold_graph_v1.json"


def corpus_commit() -> str:
    m = re.search(r"pinned commit `([0-9a-f]{40})`", (JIRA / "SOURCE.md").read_text())
    assert m, "SOURCE.md has no pinned commit"
    return m.group(1)


def build_graph_json(work: Path) -> str:
    """Build dbt_jira under `work` and return the full graph JSON text."""
    from dlens.graph import build_graph_from_artifacts
    from dlens.ingest.runner import run_dbt

    project = work / "dbt_jira"
    shutil.copytree(JIRA, project, symlinks=True, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("target", "logs", "*.duckdb"))  # fmt: skip
    target = run_dbt(project / "integration_tests").target_dir
    graph, _ = build_graph_from_artifacts(target)
    graph.save(work / "graph.json")
    return (work / "graph.json").read_text()


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def corpus_file(file: str) -> str:
    """A citation path from the integration_tests project, as a repo path."""
    if file.startswith("dbt_packages/jira/"):
        return "corpora/dbt_jira/" + file.removeprefix("dbt_packages/jira/")
    return "corpora/dbt_jira/integration_tests/" + file


def export(graph_text: str) -> dict[str, Any]:
    raw = json.loads(graph_text)
    names = {m["unique_id"]: m["name"] for m in raw["models"]}
    kinds = {m["unique_id"]: m["resource_type"] for m in raw["models"]}

    def short(column_id: str, model: str | None = None) -> str:
        if model is None:
            model = next(u for u in names if column_id.startswith(u + "."))
        return f"{names[model]}.{column_id.removeprefix(model + '.')}"

    models: dict[str, dict[str, list[str]]] = {}
    sources: dict[str, list[str]] = {}
    nodes = []
    for n in raw["nodes"]:
        kind = kinds[n["model"]]
        if kind == "seed":
            continue  # seeds carry no edge (sources are declared over their tables)
        sid = short(n["id"], n["model"])
        nodes.append(sid)
        if kind == "source":
            sources.setdefault(names[n["model"]], []).append(n["name"])
        else:
            models.setdefault(names[n["model"]], {"columns": [], "depends_on": []})
            models[names[n["model"]]]["columns"].append(n["name"])
    for child, parent in raw["depends_on"]:
        if child in names and parent in names and names[child] in models:
            models[names[child]]["depends_on"].append(names[parent])
    edges = [
        {"from": short(e["from_column"]), "to": short(e["to_column"]), "kind": e["kind"],
         "file": corpus_file(e["file"]), "line": e["lines"][0],
         "model_level_citation": e["model_level_citation"]}
        for e in raw["derives"]
    ]  # fmt: skip
    indirect = sorted(
        {(short(e["from_column"]), short(e["to_column"]), e["kind"]) for e in raw["indirect"]}
    )
    return {
        "meta": {
            "corpus": "dbt_jira",
            "corpus_commit": corpus_commit(),
            "dlens_version": raw["dlens_version"],
            "graph_format_version": raw["version"],
            "sqlglot": version("sqlglot"),
            "dbt_core": version("dbt-core"),
            "dbt_duckdb": version("dbt-duckdb"),
            "graph_sha256": sha256(graph_text),
            "note": "parser output used as set-E gold (spec 11.1); owner audit pending",
        },
        "nodes": sorted(nodes),
        "sources": {k: sorted(v) for k, v in sorted(sources.items())},
        "models": {
            k: {"columns": sorted(v["columns"]), "depends_on": sorted(set(v["depends_on"]))}
            for k, v in sorted(models.items())
        },  # fmt: skip
        "edges": sorted(edges, key=lambda e: (e["from"], e["to"])),
        "indirect": [{"from": f, "to": t, "type": k} for f, t, k in indirect],
        "exposures": {x["name"]: [] for x in raw["exposures"]},
    }


def render(doc: dict[str, Any]) -> str:
    return json.dumps(doc, indent=1, sort_keys=True) + "\n"


def verify(graph_text: str, out: Path) -> tuple[bool, str]:
    """Compare a fresh build's graph_sha256 with the committed export (A3 drift guard)."""
    want = json.loads(out.read_text())["meta"]["graph_sha256"]
    got = sha256(graph_text)
    if got == want:
        return True, f"OK: graph_sha256 {got[:12]}… matches {out.name}"
    return False, (
        f"STOP: graph_sha256 {got[:12]}… != {want[:12]}… in {out.name}. Set-E gold must be "
        "regenerated and re-reviewed before the freeze."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--verify", action="store_true", help="rebuild and compare; write nothing")
    ap.add_argument("--work", type=Path, default=None, help="build dir (default: a temp dir)")
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        graph_text = build_graph_json(args.work or Path(tmp))
    if args.verify:
        ok, msg = verify(graph_text, OUT)
        print(msg)
        return 0 if ok else 1
    doc = export(graph_text)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(doc))
    print(f"wrote {OUT.relative_to(ROOT)}: {len(doc['nodes'])} columns, {len(doc['edges'])} direct "
          f"edges, {len(doc['indirect'])} indirect pairs; graph_sha256 "
          f"{doc['meta']['graph_sha256'][:12]}…")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
