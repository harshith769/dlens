"""Pydantic models for the parts of manifest.json and catalog.json that DLens uses."""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

NODE_TYPES = {"model", "seed"}


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


class DependsOn(_Base):
    nodes: list[str] = Field(default_factory=list)


class Node(_Base):
    """A model, seed or source."""

    unique_id: str
    resource_type: Literal["model", "seed", "source"]
    name: str
    relation_name: str | None = None
    original_file_path: str | None = None
    compiled_code: str | None = None
    depends_on: DependsOn = Field(default_factory=DependsOn)


class Exposure(_Base):
    unique_id: str
    name: str
    type: str
    depends_on: DependsOn = Field(default_factory=DependsOn)


class Manifest(_Base):
    nodes: dict[str, Node]
    exposures: dict[str, Exposure]

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
    raw = json.loads(path.read_text())
    nodes = {k: v for k, v in raw.get("nodes", {}).items() if v.get("resource_type") in NODE_TYPES}
    nodes.update(raw.get("sources", {}))
    return Manifest.model_validate({"nodes": nodes, "exposures": raw.get("exposures", {})})


def load_catalog(path: Path) -> Catalog:
    """Load every catalog table (nodes and sources), columns sorted by index."""
    raw = json.loads(path.read_text())
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
