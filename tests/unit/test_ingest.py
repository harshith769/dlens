from pathlib import Path

import pytest
from typer.testing import CliRunner

from dlens import cli
from dlens.ingest import DbtArtifacts, DbtError, load_artifacts
from dlens.ingest.artifacts import Manifest, load_catalog, load_manifest
from dlens.ingest.runner import run_dbt
from dlens.ingest.schema import build_relation_map, build_sqlglot_schema, normalize_relation

FIX = Path(__file__).parent / "fixtures"


def test_manifest_skips_tests_and_keeps_needed_fields() -> None:
    m = load_manifest(FIX / "manifest.json")
    assert {n.unique_id for n in m.models} == {"model.p.orders", "model.p.eph"}
    assert [n.unique_id for n in m.seeds] == ["seed.p.raw"]
    assert [n.unique_id for n in m.sources] == ["source.p.ext.events"]
    assert m.nodes["model.p.orders"].depends_on.nodes == ["seed.p.raw"]
    assert m.exposures["exposure.p.dash"].type == "dashboard"


def test_catalog_columns_in_index_order() -> None:
    c = load_catalog(FIX / "catalog.json")
    orders = next(t for t in c.tables if t.name == "orders")
    assert [col.name for col in orders.columns] == ["id", "Amount"]
    assert c.total_columns == 5


def test_sqlglot_schema_shape_and_lowercase() -> None:
    schema = build_sqlglot_schema(load_catalog(FIX / "catalog.json"))
    assert schema["db"]["main"]["orders"] == {"id": "INTEGER", "amount": "DOUBLE"}
    assert list(schema["db"]["main"]["orders"]) == ["id", "amount"]
    assert schema["db"]["ext"]["events"] == {"e": "TIMESTAMP"}


def test_relation_map_normalises_quotes_and_case() -> None:
    rmap = build_relation_map(load_manifest(FIX / "manifest.json"))
    assert rmap["db.main.orders"] == "model.p.orders"
    assert rmap["db.ext.events"] == "source.p.ext.events"
    assert "model.p.eph" not in rmap.values()  # no relation_name


def test_relation_map_collision_raises() -> None:
    m = Manifest.model_validate(
        {
            "nodes": {
                "model.p.a": {
                    "unique_id": "model.p.a",
                    "resource_type": "model",
                    "name": "a",
                    "relation_name": '"d"."s"."T"',
                },
                "model.p.b": {
                    "unique_id": "model.p.b",
                    "resource_type": "model",
                    "name": "b",
                    "relation_name": '"d"."s"."t"',
                },
            },
            "exposures": {},
        }
    )
    with pytest.raises(ValueError, match="maps to both"):
        build_relation_map(m)


def test_normalize_relation() -> None:
    assert normalize_relation('"DB"."main"."T"') == "db.main.t"


def test_unmapped_relations_reported() -> None:
    r = load_artifacts(DbtArtifacts(FIX))  # reads fixtures/manifest.json + catalog.json
    assert r.unmapped == ["db.main.stray"]


def test_run_dbt_rejects_non_project(tmp_path: Path) -> None:
    with pytest.raises(DbtError, match="not a dbt project"):
        run_dbt(tmp_path)


def test_cli_reports_dbt_failure(tmp_path: Path) -> None:
    res = CliRunner().invoke(cli.app, ["ingest", str(tmp_path)])
    assert res.exit_code == 1
    assert "not a dbt project" in res.output


def test_cli_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "run_ingest", lambda _p: load_artifacts(DbtArtifacts(FIX)))
    res = CliRunner().invoke(cli.app, ["ingest", "x"])
    assert res.exit_code == 0
    for line in (
        "models:      2",
        "seeds:       1",
        "sources:     1",
        "exposures:   1",
        "columns:     5",
        "unmapped relations: 1",
        "db.main.stray",
    ):
        assert line in res.output
