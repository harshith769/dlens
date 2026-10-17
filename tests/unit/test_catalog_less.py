"""Catalog-less artifact ingest (ADR 0013, S06): manifest-declared columns plus schema growth
(spec §7 step 2); a star over a table nobody declared is a gap (TABLE_ONLY), never an edge."""

import shutil
from pathlib import Path

import pytest
import yaml

from dlens.ingest import load_target
from dlens.lineage import ParseQuality, compare, extract_lineage, short_id

ROOT = Path(__file__).parents[2]
ARTIFACTS = ROOT / "tests" / "fixtures" / "artifacts"


def _manifest_only(src: Path, tmp_path: Path) -> Path:
    target = tmp_path / "target"
    target.mkdir()
    shutil.copy(src / "manifest.json", target / "manifest.json")
    return target


def test_eph_shop_star_over_undeclared_seed_is_table_only(tmp_path: Path) -> None:
    target = _manifest_only(ARTIFACTS / "eph_shop" / "target", tmp_path)
    ingested, info = load_target(target)
    assert info.catalog_less
    result = extract_lineage(ingested, tmp_path, grow_schema=True)
    co = result.parse_report["model.eph_shop.customer_orders"]
    assert co.quality == ParseQuality.TABLE_ONLY
    # One gap per output column, each named once, however many paths reach it.
    assert co.gaps == [
        f"{c} <- unexpanded * from eph_shop.main.raw_orders"
        for c in ("order_id", "customer_id", "order_date")
    ]
    assert not any("*" in e.from_column for e in result.edges)
    # The column that does not come through the star still has its edge.
    edges = {(short_id(e.from_column), short_id(e.to_column)) for e in result.edges}
    assert ("order_payments.amount_usd", "customer_orders.amount_usd") in edges


def test_schema_growth_lets_downstream_models_resolve(tmp_path: Path) -> None:
    """customer_summary reads customer_orders, which declares no types: growth adds its parsed
    output columns, so the summary's columns resolve with HIGH confidence."""
    target = _manifest_only(ARTIFACTS / "eph_shop" / "target", tmp_path)
    ingested, _ = load_target(target)
    result = extract_lineage(ingested, tmp_path, grow_schema=True)
    summary = [e for e in result.edges if e.to_column.startswith("model.eph_shop.customer_summary")]
    assert summary and all(e.confidence == "high" for e in summary)
    assert ingested.schema["eph_shop"]["main"].get("customer_summary") is None  # copy, not ours


@pytest.mark.parametrize("grow", [False, True])
def test_synthetic_shop_catalog_less(tmp_path: Path, grow: bool) -> None:
    """synthetic_shop declares every seed column in YAML, so with growth catalog-less ingest
    matches the gold as well as the catalog path; without growth it doesn't."""
    target = _manifest_only(ARTIFACTS / "synthetic_shop", tmp_path)
    ingested, _ = load_target(target)
    result = extract_lineage(ingested, tmp_path, grow_schema=grow)
    spec = yaml.safe_load((ROOT / "corpora" / "synthetic_shop" / "lineage_spec.yml").read_text())
    f1 = compare(result.edges, [g for g in spec["edges"] if g["phase"] == "v0.1"]).f1
    full = sum(p.quality == ParseQuality.FULL for p in result.parse_report.values())
    if grow:
        assert (full, f1) == (49, 1.0)
    else:
        assert full < 49 and f1 < 0.9


def test_synthetic_shop_fixture_catalog_matches_gold_inventory() -> None:
    """Guards the fixture itself: every model and seed column of the gold spec is in it."""
    ingested, _ = load_target(ARTIFACTS / "synthetic_shop")
    spec = yaml.safe_load((ROOT / "corpora" / "synthetic_shop" / "lineage_spec.yml").read_text())
    want = {f"{m}.{c}" for m, v in spec["models"].items() for c in v["columns"]}
    want |= {f"{s}.{c}" for s, cols in spec["seeds"].items() for c in cols}
    got = {f"{t.name}.{c.name}".lower() for t in ingested.catalog.tables for c in t.columns}
    assert got == want
