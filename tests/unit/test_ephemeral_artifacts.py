"""Ephemeral models in real dbt artifacts (eph_shop fixture): lineage attributes columns to the
ephemeral model, never to an anonymous __dbt__cte__ CTE, and the graph has nodes for them."""

from pathlib import Path

import pytest

from dlens.graph import LineageGraph
from dlens.ingest import load_target
from dlens.lineage import ParseQuality, extract_lineage, short_id

TARGET = Path(__file__).parents[1] / "fixtures" / "artifacts" / "eph_shop" / "target"


@pytest.fixture(scope="module")
def graph() -> LineageGraph:
    ingested, info = load_target(TARGET)
    assert info.project_dir is not None
    return LineageGraph.from_results(ingested, extract_lineage(ingested, info.project_dir))


def _direct(g: LineageGraph) -> set[tuple[str, str, str]]:
    return {(short_id(e.from_column), short_id(e.to_column), str(e.kind)) for e in g.edges()}


def test_edges_stop_at_ephemeral_models(graph: LineageGraph) -> None:
    edges = _direct(graph)
    # Written from the fixture SQL: paid_payments -> order_payments -> customer_orders.
    assert ("raw_payments.amount_cents", "paid_payments.amount_cents", "IDENTITY") in edges
    assert ("paid_payments.amount_cents", "order_payments.amount_usd", "AGGREGATION") in edges
    assert ("order_payments.amount_usd", "customer_orders.amount_usd", "IDENTITY") in edges
    assert not any("__dbt__cte__" in f for f, _, _ in edges)
    # customer_orders reads raw_payments only through the ephemeral models.
    assert not any(
        f.startswith("raw_payments.") and t.startswith("customer_orders.") for f, t, _ in edges
    )


def test_ephemeral_join_key_is_an_indirect_edge_from_the_ephemeral(graph: LineageGraph) -> None:
    indirect = {
        (short_id(e.from_column), short_id(e.to_column), str(e.kind))
        for e in graph.indirect_edges()
    }
    assert ("order_payments.order_id", "customer_orders.order_id", "JOIN") in indirect
    # paid_payments' own WHERE belongs to paid_payments, not to its downstream models.
    assert ("raw_payments.amount_cents", "customer_orders.amount_usd", "FILTER") not in indirect
    assert ("raw_payments.amount_cents", "order_payments.amount_usd", "FILTER") not in indirect


def test_ephemeral_columns_are_graph_nodes(graph: LineageGraph) -> None:
    cid = "model.eph_shop.order_payments.amount_usd"
    assert graph.has_column(cid)
    assert graph.nx_graph.nodes[cid]["model"] == "model.eph_shop.order_payments"
    report = graph.parse_report()
    assert report["model.eph_shop.order_payments"] == ParseQuality.FULL
    assert report["model.eph_shop.customer_orders"] == ParseQuality.FULL
