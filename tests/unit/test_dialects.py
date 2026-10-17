"""Artifact ingest across dialects (S06, ADR 0013): synthetic_shop's compiled SQL transpiled from
DuckDB to snowflake, bigquery and postgres with sqlglot, ingested as fake artifacts, and scored
against the gold. Direct and indirect F1 must stay within 0.02 of DuckDB.

This tests sqlglot's round trip and our dialect handling, not real-world SQL written for each
warehouse. Identifier case is the only normalisation (column ids are lowercased).
"""

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[2]
_spec = importlib.util.spec_from_file_location(
    "dialect_check", ROOT / "scripts" / "dialect_check.py"
)
assert _spec and _spec.loader
dc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dc)

# Accepted (owner, 17 Oct 2026): sqlglot writes count(x) filter (where c) as
# count(iff(c, x, null)) for Snowflake, so c's CONDITIONAL edge becomes a direct one.
SNOWFLAKE_CONDITIONAL_TO_DIRECT = [
    "fct_orders.previous_order_date -> fct_customer_cohorts.repeat_customers",
    "int_order_item_margins.is_discounted -> fct_product_performance.discounted_units",
    "int_shipments_enriched.is_late_delivery -> int_order_shipping.late_shipment_count",
    "int_web_sessions_clean.channel -> int_customer_sessions.paid_session_count",
]


@pytest.fixture(scope="module")
def report() -> dict[str, Any]:
    result: dict[str, Any] = dc.run()
    return result


@pytest.mark.parametrize("dialect", dc.DIALECTS)
def test_f1_within_two_points_of_duckdb(report: dict[str, Any], dialect: str) -> None:
    row = report["dialects"][dialect]
    assert row["direct_drop"] <= dc.MAX_DROP, row["lost_direct"]
    assert row["indirect_drop"] <= dc.MAX_DROP, row["lost_indirect"]
    assert row["quality"] == {"FULL": 49, "TABLE_ONLY": 0, "FAILED": 0}


def test_every_difference_is_known(report: dict[str, Any]) -> None:
    rows = report["dialects"]
    for dialect in ("bigquery", "postgres"):
        r = rows[dialect]
        assert (
            r["lost_direct"]
            == r["gained_direct"]
            == r["lost_indirect"]
            == r["gained_indirect"]
            == []
        )
    sf = rows["snowflake"]
    assert (sf["lost_direct"], sf["gained_indirect"]) == ([], [])
    assert sf["gained_direct"] == SNOWFLAKE_CONDITIONAL_TO_DIRECT
    assert sf["lost_indirect"] == [f"{e} CONDITIONAL" for e in SNOWFLAKE_CONDITIONAL_TO_DIRECT]


def test_snowflake_fakes_look_like_snowflake(tmp_path: Path) -> None:
    target = dc.fake_artifacts("snowflake", tmp_path)
    manifest = json.loads((target / "manifest.json").read_text())
    catalog = json.loads((target / "catalog.json").read_text())
    node = manifest["nodes"]["model.synthetic_shop.int_product_costs_current"]
    assert manifest["metadata"]["adapter_type"] == "snowflake"
    assert node["relation_name"] == "synthetic_shop.main.int_product_costs_current"
    assert '"synthetic_shop"' not in node["compiled_code"]  # relations rendered unquoted
    seed = catalog["nodes"]["seed.synthetic_shop.raw_orders"]
    assert seed["metadata"]["name"] == "RAW_ORDERS" and "USER_ID" in seed["columns"]


def test_committed_report_is_current(report: dict[str, Any]) -> None:
    committed = json.loads(dc.REPORT.read_text())
    assert committed == json.loads(json.dumps(report)), (
        "run: uv run python scripts/dialect_check.py"
    )
