"""Pydantic models for the parts of manifest.json and catalog.json that DLens uses."""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

NODE_TYPES = {"model", "seed"}


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class DependsOn(_Base):
    nodes: list[str] = Field(default_factory=list)


class ManifestColumn(_Base):
    """A column declared in YAML. ``data_type`` is often missing; only artifact ingest without a
    catalog uses these."""

    name: str
    data_type: str | None = None


class NodeConfig(_Base):
    materialized: str | None = None


class Node(_Base):
    """A model, seed or source."""

    unique_id: str
    resource_type: Literal["model", "seed", "source"]
    name: str
    relation_name: str | None = None
    original_file_path: str | None = None
    compiled_code: str | None = None
    depends_on: DependsOn = Field(default_factory=DependsOn)
    package_name: str | None = None
    database: str | None = None
    schema_name: str | None = Field(default=None, alias="schema")
    alias: str | None = None
    identifier: str | None = None
    """Sources only: the table name in the warehouse (models and seeds use ``alias``)."""
    columns: dict[str, ManifestColumn] = Field(default_factory=dict)
    config: NodeConfig = Field(default_factory=NodeConfig)


class Exposure(_Base):
    unique_id: str
    name: str
    type: str
    depends_on: DependsOn = Field(default_factory=DependsOn)


class ManifestMetadata(_Base):
    dbt_schema_version: str | None = None
    dbt_version: str | None = None
    adapter_type: str | None = None
    project_name: str | None = None


class Manifest(_Base):
    nodes: dict[str, Node]
    exposures: dict[str, Exposure]
    metadata: ManifestMetadata = Field(default_factory=ManifestMetadata)

    @property
    def models(self) -> list[Node]:
        return [n for n in self.nodes.values() if n.resource_type == "model"]

    @property
    def seeds(self) -> list[Node]:
        return [n for n in self.nodes.values() if n.resource_type == "seed"]

    @property
    def sources(self) -> list[Node]:
        return [n for n in self.nodes.values() if n.resource_type == "source"]


class CatalogColumn(_Base):
    name: str
    type: str
    index: int


class CatalogTable(_Base):
    """One relation in the warehouse; columns are in index order."""

    unique_id: str
    database: str | None
    schema_name: str
    name: str
    columns: list[CatalogColumn]


class Catalog(_Base):
    tables: list[CatalogTable]

    @property
    def total_columns(self) -> int:
        return sum(len(t.columns) for t in self.tables)


def load_manifest(path: Path) -> Manifest:
    """Load models, seeds, sources and exposures; tests and other node types are skipped."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    nodes = {k: v for k, v in raw.get("nodes", {}).items() if v.get("resource_type") in NODE_TYPES}
    nodes.update(raw.get("sources", {}))
    return Manifest.model_validate(
        {
            "nodes": nodes,
            "exposures": raw.get("exposures", {}),
            "metadata": raw.get("metadata", {}),
        }
    )


def load_catalog(path: Path) -> Catalog:
    """Load every catalog table (nodes and sources), columns sorted by index."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    tables: list[CatalogTable] = []
    for section in ("nodes", "sources"):
        for key, entry in raw.get(section, {}).items():
            meta = entry.get("metadata", {})
            cols = sorted(
                (CatalogColumn.model_validate(c) for c in entry.get("columns", {}).values()),
                key=lambda c: c.index,
            )
            tables.append(
                CatalogTable(
                    unique_id=key,
                    database=meta.get("database"),
                    schema_name=meta["schema"],
                    name=meta["name"],
                    columns=cols,
                )
            )
    return Catalog(tables=tables)
