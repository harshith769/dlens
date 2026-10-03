from pathlib import Path

import pytest
from typer.testing import CliRunner

from dlens.cli import app
from dlens.graph import ColumnNotFound, LineageGraph
from dlens.graph.cache import cache_path
from dlens.lineage import ParseQuality

pytestmark = pytest.mark.integration

REVENUE = "fct_daily_revenue.revenue_finance"
UNIT_PRICE = "raw_order_items.unit_price"


def test_trace_reaches_raw_unit_price_at_depth_7(synthetic_graph: LineageGraph) -> None:
    paths = synthetic_graph.upstream(synthetic_graph.resolve(REVENUE))
    target = synthetic_graph.resolve(UNIT_PRICE)
    depths = {p.depth for p in paths if p.end == target}
    assert depths == {7}
    assert not paths.truncated and not paths.depth_limited


def test_trace_depth_limit_does_not_reach_it(synthetic_graph: LineageGraph) -> None:
    paths = synthetic_graph.upstream(synthetic_graph.resolve(REVENUE), max_depth=6)
    assert synthetic_graph.resolve(UNIT_PRICE) not in {p.end for p in paths}
    assert paths.depth_limited


def test_impact_of_tax_usd_reaches_financials_and_marts(synthetic_graph: LineageGraph) -> None:
    r = synthetic_graph.downstream(synthetic_graph.resolve("raw_orders.tax_usd"))
    reached = {synthetic_graph.display_name(c) for c in r.columns}
    assert "int_order_financials.sales_tax" in reached
    short_models = {m.split(".")[-1] for m in r.models}
    assert {
        "int_order_financials",
        "fct_orders",
        "dim_customers",
        "fct_daily_revenue",
    } <= short_models
    assert not r.truncated


def test_save_load_round_trip(synthetic_graph: LineageGraph, tmp_path: Path) -> None:
    p = tmp_path / "g.json"
    synthetic_graph.save(p)
    assert LineageGraph.load(p) == synthetic_graph


def test_parse_report_covers_every_model(synthetic_graph: LineageGraph) -> None:
    report = synthetic_graph.parse_report()
    assert len([u for u in report if u.startswith("model.")]) == 15
    assert set(report.values()) <= set(ParseQuality)


def test_unknown_column_on_real_graph(synthetic_graph: LineageGraph) -> None:
    with pytest.raises(ColumnNotFound) as e:
        synthetic_graph.resolve("fct_orders.revenue_financ")
    assert "fct_orders.revenue_finance" in e.value.suggestions
    with pytest.raises(ColumnNotFound):
        synthetic_graph.resolve("stg_orders")  # a bare model name is not a column id


def test_cli_trace_and_impact_on_real_project(synthetic_project: Path) -> None:
    assert cache_path(synthetic_project).is_file()
    runner = CliRunner()
    t = runner.invoke(app, ["trace", REVENUE, "-p", str(synthetic_project)])
    assert t.exit_code == 0, t.output
    assert "raw_order_items.unit_price" in t.stdout and "models/" in t.stdout
    i = runner.invoke(app, ["impact", "raw_orders.tax_usd", "-p", str(synthetic_project)])
    assert i.exit_code == 0, i.output
    assert "int_order_financials.sales_tax" in i.stdout and "fct_daily_revenue" in i.stdout
