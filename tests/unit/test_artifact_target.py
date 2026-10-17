import pytest

from dlens.ingest.artifacts import ManifestMetadata
from dlens.ingest.target import (
    ADAPTER_DIALECTS,
    ArtifactError,
    check_catalog_version,
    check_manifest_version,
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
