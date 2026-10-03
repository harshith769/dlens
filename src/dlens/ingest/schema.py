"""Turn the dbt catalog and manifest into what the lineage engine needs.

Everything is lowercased: DuckDB identifiers are case-insensitive and dbt quotes them
inconsistently across artifacts, so one normal form keeps lookups reliable. The cost is
that two relations differing only in case would collide; ``relation_map`` raises on that.
"""

from dataclasses import dataclass

from dlens.ingest.artifacts import Catalog, CatalogTable, Manifest

SqlglotSchema = dict[str, dict[str, dict[str, dict[str, str]]]]


def normalize_relation(name: str) -> str:
    """Strip quotes/backticks and lowercase, e.g. '"DB"."main"."T"' -> 'db.main.t'."""
    return name.replace('"', "").replace("`", "").lower()


def _table_key(table: CatalogTable) -> str:
    parts = [table.database, table.schema_name, table.name]
    return normalize_relation(".".join(p for p in parts if p))


def build_sqlglot_schema(catalog: Catalog) -> SqlglotSchema:
    """{db: {schema: {table: {column: type}}}}, columns in catalog index order."""
    schema: SqlglotSchema = {}
    for t in catalog.tables:
        db = (t.database or "").lower()
        cols = {c.name.lower(): c.type for c in t.columns}
        schema.setdefault(db, {}).setdefault(t.schema_name.lower(), {})[t.name.lower()] = cols
    return schema


def build_relation_map(manifest: Manifest) -> dict[str, str]:
    """Normalised relation_name -> unique_id. Nodes without a relation (ephemeral) are skipped."""
    mapping: dict[str, str] = {}
    for node in manifest.nodes.values():
        if not node.relation_name:
            continue
        key = normalize_relation(node.relation_name)
        if key in mapping and mapping[key] != node.unique_id:
            raise ValueError(f"relation {key!r} maps to both {mapping[key]} and {node.unique_id}")
        mapping[key] = node.unique_id
    return mapping


def unmapped_relations(catalog: Catalog, relation_map: dict[str, str]) -> list[str]:
    """Catalog relations that no manifest node claims."""
    return sorted(k for k in map(_table_key, catalog.tables) if k not in relation_map)


@dataclass(frozen=True)
class IngestResult:
    manifest: Manifest
    catalog: Catalog
    schema: SqlglotSchema
    relation_map: dict[str, str]
    unmapped: list[str]
