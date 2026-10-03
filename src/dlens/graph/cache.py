"""Cached graph at ``<project>/target/dlens_graph.json``."""

from pathlib import Path

from dlens.graph.graph import LineageGraph, build_graph

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
            return LineageGraph.load(cache)
        except (ValueError, KeyError, OSError):
            pass  # unreadable or old-format cache: rebuild
    graph = build_graph(project_dir, dialect)
    graph.save(cache)
    return graph
