"""Artifact-only ingest (ADR 0013): read an existing dbt ``target/`` directory, never run dbt.

Reads files only: no dbt, no warehouse, no network, no credentials, and nothing is written
here. The sqlglot dialect comes from the manifest's ``adapter_type`` unless the caller
overrides it, and an unknown manifest schema version is an error, never a guess.
"""

import re

from dlens.ingest.artifacts import ManifestMetadata


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
