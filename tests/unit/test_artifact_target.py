import json
from pathlib import Path

import pytest

from dlens.ingest.artifacts import ManifestMetadata
from dlens.ingest.target import (
    ADAPTER_DIALECTS,
    ArtifactError,
    check_catalog_version,
    check_manifest_version,
    load_target,
    resolve_dialect,
    schema_version,
)

V12 = "https://schemas.getdbt.com/dbt/manifest/v12.json"


def test_schema_version_parses_url() -> None:
    assert schema_version(V12) == "v12"
    assert schema_version("https://schemas.getdbt.com/dbt/catalog/v1.json") == "v1"
    assert schema_version(None) is None
    assert schema_version("nonsense") is None


def test_v12_is_supported() -> None:
    assert check_manifest_version(ManifestMetadata(dbt_schema_version=V12)) == "v12"


@pytest.mark.parametrize("url", [V12.replace("v12", "v11"), V12.replace("v12", "v13"), None])
def test_unknown_manifest_version_is_a_clear_error(url: str | None) -> None:
    with pytest.raises(ArtifactError, match="not supported; supported: v12"):
        check_manifest_version(ManifestMetadata(dbt_schema_version=url, dbt_version="9.9"))


def test_catalog_version() -> None:
    assert check_catalog_version("https://schemas.getdbt.com/dbt/catalog/v1.json") == "v1"
    with pytest.raises(ArtifactError, match="catalog-less fallback"):
        check_catalog_version("https://schemas.getdbt.com/dbt/catalog/v2.json")


@pytest.mark.parametrize(
    ("adapter", "dialect"),
    [
        ("duckdb", "duckdb"),
        ("snowflake", "snowflake"),
        ("bigquery", "bigquery"),
        ("postgres", "postgres"),
        ("redshift", "redshift"),
        ("databricks", "databricks"),
        ("spark", "spark"),
        ("trino", "trino"),
        ("Snowflake", "snowflake"),
    ],
)
def test_adapter_maps_to_dialect(adapter: str, dialect: str) -> None:
    assert resolve_dialect(ManifestMetadata(adapter_type=adapter)) == dialect


def test_every_mapped_dialect_exists_in_sqlglot() -> None:
    from sqlglot.dialects.dialect import Dialect

    for dialect in ADAPTER_DIALECTS.values():
        Dialect.get_or_raise(dialect)


def test_unknown_adapter_suggests_dialect_flag() -> None:
    with pytest.raises(ArtifactError, match="Pass --dialect"):
        resolve_dialect(ManifestMetadata(adapter_type="sqlserver"))
    with pytest.raises(ArtifactError, match="Pass --dialect"):
        resolve_dialect(ManifestMetadata())


def test_dialect_override_wins_and_is_checked() -> None:
    assert resolve_dialect(ManifestMetadata(adapter_type="sqlserver"), "postgres") == "postgres"
    with pytest.raises(ArtifactError, match="unknown --dialect"):
        resolve_dialect(ManifestMetadata(adapter_type="duckdb"), "tsql")


# -- load_target ------------------------------------------------------------------------------

FIX = Path(__file__).parent / "fixtures"


def _target(tmp_path: Path, *, catalog: bool = True, **meta: str) -> Path:
    """A target/ dir from the unit fixtures, with manifest metadata (v12 duckdb by default)."""
    target = tmp_path / "target"
    target.mkdir(parents=True)
    manifest = json.loads((FIX / "manifest.json").read_text())
    manifest["metadata"] = {"dbt_schema_version": V12, "adapter_type": "duckdb"} | meta
    manifest["nodes"]["model.p.orders"]["package_name"] = "p"
    manifest["nodes"]["model.p.orders"]["columns"] = {
        "id": {"name": "id", "data_type": "integer"},
        "Amount": {"name": "Amount"},
    }
    (target / "manifest.json").write_text(json.dumps(manifest))
    if catalog:
        cat = json.loads((FIX / "catalog.json").read_text())
        cat["metadata"] = {"dbt_schema_version": "https://schemas.getdbt.com/dbt/catalog/v1.json"}
        (target / "catalog.json").write_text(json.dumps(cat))
    return target


def test_load_target_with_catalog(tmp_path: Path) -> None:
    ingested, info = load_target(_target(tmp_path))
    assert (info.manifest_version, info.dialect, info.catalog_less) == ("v12", "duckdb", False)
    assert ingested.schema["db"]["main"]["orders"] == {"id": "INTEGER", "amount": "DOUBLE"}
    assert ingested.relation_map["db.main.orders"] == "model.p.orders"
    assert info.project_dir is None  # no dbt_project.yml next to target/


def test_load_target_catalog_less_uses_declared_columns(tmp_path: Path) -> None:
    ingested, info = load_target(_target(tmp_path, catalog=False))
    assert info.catalog_less
    assert ingested.schema == {"db": {"main": {"orders": {"id": "integer", "amount": "unknown"}}}}
    # Nodes without declared columns stay unknown to sqlglot but keep their relation.
    assert ingested.relation_map["db.main.raw"] == "seed.p.raw"
    [orders] = ingested.catalog.tables
    assert (orders.unique_id, [c.index for c in orders.columns]) == ("model.p.orders", [1, 2])


def test_compiled_sql_falls_back_to_compiled_files(tmp_path: Path) -> None:
    target = _target(tmp_path)
    manifest = json.loads((target / "manifest.json").read_text())
    manifest["nodes"]["model.p.orders"]["compiled_code"] = None
    (target / "manifest.json").write_text(json.dumps(manifest))
    compiled = target / "compiled" / "p" / "models" / "orders.sql"
    compiled.parent.mkdir(parents=True)
    compiled.write_text("select 2 as id")
    ingested, info = load_target(target)
    assert ingested.manifest.nodes["model.p.orders"].compiled_code == "select 2 as id"
    assert info.compiled_from_files == ["model.p.orders"]
    assert info.missing_compiled == ["model.p.eph"]  # no compiled_code and no file


def test_project_dir_is_the_parent_with_dbt_project(tmp_path: Path) -> None:
    target = _target(tmp_path)
    (tmp_path / "dbt_project.yml").write_text("name: p\n")
    assert load_target(target)[1].project_dir == tmp_path


def test_missing_manifest_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(ArtifactError, match="no manifest.json"):
        load_target(tmp_path)


def test_load_target_checks_version_and_adapter(tmp_path: Path) -> None:
    with pytest.raises(ArtifactError, match="not supported"):
        load_target(_target(tmp_path / "a", dbt_schema_version=V12.replace("v12", "v9")))
    with pytest.raises(ArtifactError, match="Pass --dialect"):
        load_target(_target(tmp_path / "b", adapter_type="oracle"))
    _, info = load_target(_target(tmp_path / "c", adapter_type="oracle"), dialect="postgres")
    assert info.dialect == "postgres"


def test_unknown_catalog_version_is_an_error(tmp_path: Path) -> None:
    target = _target(tmp_path)
    (target / "catalog.json").write_text(
        json.dumps({"metadata": {"dbt_schema_version": "x/v9.json"}})
    )
    with pytest.raises(ArtifactError, match="catalog schema version"):
        load_target(target)


def test_load_target_never_writes(tmp_path: Path) -> None:
    target = _target(tmp_path)
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    load_target(target)
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == before


# -- committed fixtures (scripts/make_artifact_fixture.py) ------------------------------------

ARTIFACTS = Path(__file__).parents[1] / "fixtures" / "artifacts"


def test_eph_shop_fixture_loads() -> None:
    ingested, info = load_target(ARTIFACTS / "eph_shop" / "target")
    assert (info.dialect, info.catalog_less, info.project_dir) == (
        "duckdb",
        False,
        ARTIFACTS / "eph_shop",
    )
    ephemeral = {n.name for n in ingested.manifest.models if n.config.materialized == "ephemeral"}
    assert ephemeral == {"paid_payments", "order_payments"}
    assert all(m.compiled_code for m in ingested.manifest.models)


def test_synthetic_shop_fixture_loads() -> None:
    ingested, info = load_target(ARTIFACTS / "synthetic_shop")
    assert (info.manifest_version, info.dialect, info.project_dir) == ("v12", "duckdb", None)
    assert len(ingested.manifest.models) == 49
    assert ingested.unmapped == []
