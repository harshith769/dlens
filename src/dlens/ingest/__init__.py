"""Ingest: run dbt, load its artifacts, build the schema and relation map."""

from pathlib import Path

from dlens.ingest.artifacts import load_catalog, load_manifest
from dlens.ingest.runner import DbtArtifacts, DbtError, run_dbt
from dlens.ingest.schema import (
    IngestResult,
    build_relation_map,
    build_sqlglot_schema,
    unmapped_relations,
)

__all__ = ["DbtArtifacts", "DbtError", "IngestResult", "ingest", "load_artifacts"]


def load_artifacts(artifacts: DbtArtifacts) -> IngestResult:
    manifest = load_manifest(artifacts.manifest)
    catalog = load_catalog(artifacts.catalog)
    relation_map = build_relation_map(manifest)
    return IngestResult(
        manifest=manifest,
        catalog=catalog,
        schema=build_sqlglot_schema(catalog),
        relation_map=relation_map,
        unmapped=unmapped_relations(catalog, relation_map),
    )


def ingest(project_dir: Path) -> IngestResult:
    return load_artifacts(run_dbt(project_dir))
