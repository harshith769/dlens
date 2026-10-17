"""Cached graphs: ``<project>/target/dlens_graph.json`` (dbt run by DLens), and
``<target>/dlens/graph.json`` + ``meta.json`` for artifact-only ingest (ADR 0013)."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from dlens import __version__
from dlens.graph.graph import FORMAT_VERSION, LineageGraph, build_graph, build_graph_from_artifacts
from dlens.ingest import TargetInfo, load_target

SOURCE_DIRS = ("models", "seeds", "macros", "snapshots", "tests")


def cache_path(project_dir: Path) -> Path:
    return project_dir / "target" / "dlens_graph.json"


def _source_files(project_dir: Path) -> list[Path]:
    files = [project_dir / "dbt_project.yml"]
    for d in SOURCE_DIRS:
        files += [p for p in (project_dir / d).rglob("*") if p.is_file()]
    return [p for p in files if p.is_file()]


def is_stale(project_dir: Path) -> bool:
    """True if the cache is missing, older than the manifest, or older than any project source.

    The source check matters because the manifest only changes when dbt runs.
    """
    cache = cache_path(project_dir)
    manifest = project_dir / "target" / "manifest.json"
    if not cache.is_file() or not manifest.is_file():
        return True
    built = cache.stat().st_mtime_ns
    return built < manifest.stat().st_mtime_ns or any(
        p.stat().st_mtime_ns > built for p in _source_files(project_dir)
    )


def load_or_build(
    project_dir: Path, dialect: str = "duckdb", rebuild: bool = False
) -> LineageGraph:
    """Return the cached graph, rebuilding (which runs dbt) when it is stale or ``rebuild``."""
    cache = cache_path(project_dir)
    if not rebuild and not is_stale(project_dir):
        try:
            # LineageGraph.load also reads older formats (the demo bundle); a cache is rebuilt
            # instead, so it gains what the newer format carries (v3: indirect edges; v4:
            # citation gaps).
            if json.loads(cache.read_text()).get("version") == FORMAT_VERSION:
                return LineageGraph.load(cache)
        except (ValueError, KeyError, OSError):
            pass  # unreadable or old-format cache: rebuild
    graph = build_graph(project_dir, dialect)
    graph.save(cache)
    return graph


# -- artifact-only ingest (ADR 0013) -----------------------------------------------------------


@dataclass(frozen=True)
class ArtifactGraph:
    graph: LineageGraph
    info: TargetInfo
    cache_dir: Path
    reused: bool


def artifact_cache_dir(target_dir: Path, out: Path | None = None) -> Path:
    """``--out`` if given, else ``<target_dir>/dlens/``. DLens writes nowhere else."""
    return out if out is not None else target_dir / "dlens"


def _sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def artifact_meta(target_dir: Path, dialect: str) -> dict[str, object]:
    """What a cached artifact graph was built from; any difference means rebuild."""
    return {
        "manifest_sha256": _sha256(target_dir / "manifest.json"),
        "catalog_sha256": _sha256(target_dir / "catalog.json"),
        "dialect": dialect,
        "dlens_version": __version__,
        "format_version": FORMAT_VERSION,
    }


def load_or_build_artifacts(
    target_dir: Path, dialect: str | None = None, out: Path | None = None, rebuild: bool = False
) -> ArtifactGraph:
    """The cached artifact graph if the manifest, catalog, dialect and dlens version are unchanged,
    else build it (no dbt) and write ``graph.json`` and ``meta.json`` to the cache directory."""
    cache = artifact_cache_dir(target_dir, out)
    info = load_target(target_dir, dialect)[1]  # validates version and dialect before any reuse
    meta = artifact_meta(target_dir, info.dialect)
    if not rebuild:
        try:
            if json.loads((cache / "meta.json").read_text(encoding="utf-8")) == meta:
                return ArtifactGraph(LineageGraph.load(cache / "graph.json"), info, cache, True)
        except (ValueError, KeyError, OSError):
            pass  # missing, unreadable or stale: rebuild
    graph, info = build_graph_from_artifacts(target_dir, dialect)
    graph.save(cache / "graph.json")
    (cache / "meta.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return ArtifactGraph(graph, info, cache, False)
