"""Artifact-only ingest (ADR 0013): read an existing dbt ``target/`` directory, never run dbt.

Reads files only: no dbt, no warehouse, no network, no credentials, and nothing is written
here. The sqlglot dialect comes from the manifest's ``adapter_type`` unless the caller
overrides it, and an unknown manifest schema version is an error, never a guess.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from dlens.ingest.artifacts import (
    Catalog,
    CatalogColumn,
    CatalogTable,
    Manifest,
    ManifestMetadata,
    Node,
    load_catalog,
    load_manifest,
)
from dlens.ingest.schema import (
    IngestResult,
    build_relation_map,
    build_sqlglot_schema,
    normalize_relation,
    unmapped_relations,
)


class ArtifactError(ValueError):
    """The target directory can't be ingested; the message says why and what to do."""


# metadata.dbt_schema_version values we have tested against real artifacts. dbt 1.8 to 1.12
# and dbt 2.0 all write manifest v12 (verified: 1.12.5 and 2.0.8; dbt docs list 1.8-1.11, 2.0).
SUPPORTED_MANIFEST_VERSIONS = ("v12",)
SUPPORTED_CATALOG_VERSIONS = ("v1",)

# dbt adapter_type -> sqlglot dialect.
ADAPTER_DIALECTS = {
    "duckdb": "duckdb",
    "snowflake": "snowflake",
    "bigquery": "bigquery",
    "postgres": "postgres",
    "redshift": "redshift",
    "databricks": "databricks",
    "spark": "spark",
    "trino": "trino",
}

_VERSION = re.compile(r"/(v\d+)\.json$")


def schema_version(url: str | None) -> str | None:
    """``https://schemas.getdbt.com/dbt/manifest/v12.json`` -> ``v12``."""
    m = _VERSION.search(url or "")
    return m.group(1) if m else None


def check_manifest_version(meta: ManifestMetadata) -> str:
    version = schema_version(meta.dbt_schema_version)
    if version not in SUPPORTED_MANIFEST_VERSIONS:
        raise ArtifactError(
            f"manifest schema version {meta.dbt_schema_version!r} (dbt {meta.dbt_version}) is "
            f"not supported; supported: {', '.join(SUPPORTED_MANIFEST_VERSIONS)} "
            "(dbt 1.8 to 1.12 and 2.0). Re-run `dbt compile` with a supported dbt version."
        )
    assert version is not None
    return version


def check_catalog_version(url: str | None) -> str:
    version = schema_version(url)
    if version not in SUPPORTED_CATALOG_VERSIONS:
        raise ArtifactError(
            f"catalog schema version {url!r} is not supported; supported: "
            f"{', '.join(SUPPORTED_CATALOG_VERSIONS)}. Delete catalog.json to use the "
            "catalog-less fallback, or regenerate it with `dbt docs generate`."
        )
    assert version is not None
    return version


def resolve_dialect(meta: ManifestMetadata, override: str | None = None) -> str:
    """The sqlglot dialect: ``override`` if given, else mapped from ``adapter_type``."""
    if override:
        if override not in ADAPTER_DIALECTS.values():
            raise ArtifactError(
                f"unknown --dialect {override!r}; choose one of "
                f"{', '.join(sorted(set(ADAPTER_DIALECTS.values())))}."
            )
        return override
    adapter = (meta.adapter_type or "").lower()
    if adapter not in ADAPTER_DIALECTS:
        raise ArtifactError(
            f"adapter_type {meta.adapter_type!r} has no known sqlglot dialect. Pass --dialect "
            f"with one of {', '.join(sorted(set(ADAPTER_DIALECTS.values())))} if its SQL is "
            "close to one of them."
        )
    return ADAPTER_DIALECTS[adapter]


@dataclass(frozen=True)
class TargetInfo:
    """What artifact ingest found, for the CLI summary and the cache."""

    target_dir: Path
    manifest_version: str
    dbt_version: str | None
    adapter_type: str | None
    dialect: str
    catalog_less: bool
    compiled_from_files: list[str] = field(default_factory=list)
    """Models whose SQL came from ``target/compiled`` because ``compiled_code`` was empty."""
    missing_compiled: list[str] = field(default_factory=list)
    """Models with no compiled SQL anywhere (they become FAILED in the parse report)."""

    @property
    def project_dir(self) -> Path | None:
        """The dbt project holding the source files, if the target sits inside one."""
        parent = self.target_dir.parent
        return parent if (parent / "dbt_project.yml").is_file() else None


def _compiled_file(target_dir: Path, node: Node) -> Path | None:
    if not node.package_name or not node.original_file_path:
        return None
    path = target_dir / "compiled" / node.package_name / node.original_file_path
    return path if path.is_file() else None


def _with_compiled_sql(
    target_dir: Path, manifest: Manifest
) -> tuple[Manifest, list[str], list[str]]:
    """Fill empty ``compiled_code`` from ``target/compiled/<package>/<original_file_path>``."""
    nodes = dict(manifest.nodes)
    from_files: list[str] = []
    missing: list[str] = []
    for uid, node in sorted(manifest.nodes.items()):
        if node.resource_type != "model" or node.compiled_code:
            continue
        path = _compiled_file(target_dir, node)
        if path is None:
            missing.append(uid)
            continue
        nodes[uid] = node.model_copy(update={"compiled_code": path.read_text(encoding="utf-8")})
        from_files.append(uid)
    return manifest.model_copy(update={"nodes": nodes}), from_files, missing


def catalog_from_manifest(manifest: Manifest) -> Catalog:
    """Catalog-less fallback: one table per node with a relation, columns as declared in YAML
    (type ``data_type`` or ``unknown``). Nodes that declare no columns are left out, so sqlglot
    treats them as unknown rather than as empty; ephemeral models have no relation. The relation
    parts come from ``relation_name`` so they match the relation map exactly."""
    tables: list[CatalogTable] = []
    for uid, node in sorted(manifest.nodes.items()):
        if not node.relation_name or not node.columns:
            continue
        parts = normalize_relation(node.relation_name).split(".")
        database, schema, name = ([None] * (3 - len(parts)) + parts)[-3:]
        if schema is None or name is None:
            continue
        cols = [
            CatalogColumn(name=c.name, type=c.data_type or "unknown", index=i)
            for i, c in enumerate(node.columns.values(), start=1)
        ]
        tables.append(
            CatalogTable(
                unique_id=uid, database=database, schema_name=schema, name=name, columns=cols
            )
        )
    return Catalog(tables=tables)


def load_target(target_dir: Path, dialect: str | None = None) -> tuple[IngestResult, TargetInfo]:
    """Ingest an existing dbt ``target/`` directory: manifest.json (required), catalog.json
    (optional) and compiled SQL. Raises :class:`ArtifactError` with an actionable message."""
    manifest_path = target_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ArtifactError(
            f"{target_dir} has no manifest.json. Point --artifacts at a dbt target/ directory "
            "after `dbt compile` (or `dbt build`)."
        )
    try:
        manifest = load_manifest(manifest_path)
    except (ValueError, KeyError) as e:
        raise ArtifactError(f"{manifest_path} is not a readable dbt manifest: {e}") from e
    version = check_manifest_version(manifest.metadata)
    sql_dialect = resolve_dialect(manifest.metadata, dialect)
    manifest, from_files, missing = _with_compiled_sql(target_dir, manifest)

    catalog_path = target_dir / "catalog.json"
    if catalog_path.is_file():
        raw_meta = json.loads(catalog_path.read_text(encoding="utf-8")).get("metadata", {})
        check_catalog_version(raw_meta.get("dbt_schema_version"))
        catalog = load_catalog(catalog_path)
    else:
        catalog = catalog_from_manifest(manifest)

    try:
        relation_map = build_relation_map(manifest)
    except ValueError as e:
        raise ArtifactError(f"{e}; two dbt nodes claim the same warehouse table.") from e
    ingested = IngestResult(
        manifest=manifest,
        catalog=catalog,
        schema=build_sqlglot_schema(catalog),
        relation_map=relation_map,
        unmapped=unmapped_relations(catalog, relation_map),
    )
    info = TargetInfo(
        target_dir=target_dir,
        manifest_version=version,
        dbt_version=manifest.metadata.dbt_version,
        adapter_type=manifest.metadata.adapter_type,
        dialect=sql_dialect,
        catalog_less=not catalog_path.is_file(),
        compiled_from_files=from_files,
        missing_compiled=missing,
    )
    return ingested, info
