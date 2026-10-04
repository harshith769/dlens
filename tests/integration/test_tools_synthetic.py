"""Tools on synthetic_shop: provenance contract, gold agreement, locator quality, entity linking."""

import re
import shutil
from collections import Counter
from pathlib import Path

import pytest
import yaml

from dlens.agent.tools import Toolbox
from dlens.graph import LineageGraph, build_graph
from dlens.lineage import short_id

pytestmark = pytest.mark.integration

CORPUS = Path(__file__).parents[2] / "corpora" / "synthetic_shop"


@pytest.fixture(scope="module")
def box(synthetic_graph: LineageGraph, synthetic_project: Path) -> Toolbox:
    return Toolbox(synthetic_graph, synthetic_project)


def gold_kinds() -> dict[tuple[str, str], str]:
    spec = yaml.safe_load((CORPUS / "lineage_spec.yml").read_text())["edges"]
    return {(e["from"].lower(), e["to"].lower()): e["kind"] for e in spec}


GAPS = yaml.safe_load((CORPUS / "engine_gaps.yml").read_text())


def known_engine_kinds() -> dict[tuple[str, str], str]:
    """Known parser gaps where the graph has an edge the gold lacks or kinds differ."""
    return {
        (g["from"], g["to"]): g["engine_kind"]
        for g in GAPS["direct_edges"]
        if g["engine"] in ("extra", "wrong_kind")
    }


MODEL_LEVEL_CITED = {(g["from"], g["to"]) for g in GAPS["model_level_citations"]}


def test_every_edge_returned_by_trace_and_impact_is_in_the_gold_spec(
    box: Toolbox, synthetic_graph: LineageGraph
) -> None:
    gold = gold_kinds()
    gaps = known_engine_kinds()
    seen: set[str] = set()
    seen_gaps: set[tuple[str, str]] = set()
    for col in synthetic_graph.columns():
        box.reset()
        for tool in ("trace_upstream", "impact_downstream"):
            r = box.call(tool, {"column_id": col})
            assert not r.is_error, (tool, col, r.llm_payload)
            for eid, rec in r.side_records["edges"].items():
                key = (short_id(rec["from"]), short_id(rec["to"]))
                if gold.get(key) != rec["kind"]:  # only a listed gap may disagree
                    assert gaps.get(key) == rec["kind"], (key, rec["kind"], gold.get(key))
                    seen_gaps.add(key)
                seen.add(eid)
    assert len(seen) == len(synthetic_graph.edges())  # and together they reach every edge
    assert seen_gaps == set(gaps)  # engine_gaps.yml is exact: no stale entries


def test_edge_ids_are_stable_across_two_builds_and_unique(
    synthetic_graph: LineageGraph, synthetic_project: Path, tmp_path: Path
) -> None:
    other = tmp_path / "again"
    shutil.copytree(synthetic_project, other, ignore=shutil.ignore_patterns("target", "*.duckdb"))
    second = build_graph(other)
    a = Toolbox(synthetic_graph, synthetic_project)
    b = Toolbox(second, other)
    col = "fct_daily_revenue.revenue_finance"
    ra, rb = (
        a.call("trace_upstream", {"column_id": col}),
        b.call("trace_upstream", {"column_id": col}),
    )
    assert ra.llm_payload == rb.llm_payload
    assert set(ra.side_records["edges"]) == set(rb.side_records["edges"])
    ids = [a._prov.edge_by_id(i) for i in ra.side_records["edges"]]
    assert all(ids)


def test_locator_quality_on_every_column(
    box: Toolbox, synthetic_graph: LineageGraph, capsys
) -> None:  # type: ignore[no-untyped-def]
    counts: Counter[str] = Counter()
    model_level: set[str] = set()
    for col in synthetic_graph.columns():
        c = box._prov.column_citation(col)
        name = synthetic_graph.nx_graph.nodes[col]["name"]
        text = (box.project_dir / c.file).read_text()
        counts[c.level] += 1
        if c.level == "model":
            if not col.startswith("seed."):
                model_level.add(synthetic_graph.display_name(col))
            assert (c.line_start, c.line_end) == (1, len(text.splitlines()))
            continue
        chunk = "\n".join(text.splitlines()[c.line_start - 1 : c.line_end])
        if c.level == "line":
            assert re.search(rf"(?<!\w){re.escape(name)}(?!\w)", chunk, re.I), (col, chunk)
        else:
            assert c.level == "star" and "*" in chunk, (col, chunk)
    with capsys.disabled():
        print(f"\nlocator on synthetic_shop columns: {dict(counts)} of {sum(counts.values())}")
    # only seed columns (CSV, no SQL) fall back to model level, plus the listed parser gap
    assert model_level == {to for _, to in MODEL_LEVEL_CITED}


def test_edge_citations_hold_for_every_edge(box: Toolbox, synthetic_graph: LineageGraph) -> None:
    levels: Counter[str] = Counter()
    model_level: set[tuple[str, str]] = set()
    for e in synthetic_graph.edges():
        c = box._prov.edge_citation(e)
        levels[c.level] += 1
        assert (box.project_dir / c.file).is_file() and c.file.startswith("models/")
        if c.level == "model":
            model_level.add((short_id(e.from_column), short_id(e.to_column)))
    assert levels["line"] + levels["star"] + levels["model"] == len(synthetic_graph.edges())
    assert model_level == MODEL_LEVEL_CITED  # engine_gaps.yml; zero once the gap is fixed


# -- resolve_entity -----------------------------------------------------------------------------


def top(box: Toolbox, text: str, k: int = 5) -> list[dict[str, object]]:
    return box.call("resolve_entity", {"text": text, "k": k}).llm_payload["candidates"]  # type: ignore[no-any-return]


def test_top1_on_every_exact_column_id(box: Toolbox, synthetic_graph: LineageGraph) -> None:
    """Every exact column id is top-1, except the known linker gaps in linker_gaps.yml (S08). The
    failures must equal that list: a new failure fails, and a fixed one fails until removed."""
    failures = set()
    for col in synthetic_graph.columns():
        want = synthetic_graph.display_name(col)
        if top(box, want, 1)[0]["id"] != want:
            failures.add(want)
    gaps = yaml.safe_load((CORPUS / "linker_gaps.yml").read_text())["exact_id_top1"]
    assert failures == {g["id"] for g in gaps}


def test_top1_on_exact_bare_names_is_a_column_with_that_name(box: Toolbox) -> None:
    for name in ("order_id", "refund_amt", "lifetime_value", "tax_usd", "event_amount_usd"):
        first = top(box, name, 1)[0]
        assert first["kind"] == "column" and str(first["id"]).endswith("." + name)


# Hand-written from DESIGN.md / traps.yml, not from parser output: (query, expected top-1 id).
ABBREVIATIONS = [
    ("stg_payments.amt", "stg_payments.amount_usd"),  # amt = amount; raw_payments.amt is renamed
    ("raw_payments.amt", "raw_payments.amt"),
    ("amt", "raw_payments.amt"),  # a literal name beats an abbreviation match
    ("tax usd", "raw_orders.tax_usd"),
    ("lifetime value", "dim_customers.lifetime_value"),
    ("OrderDate of fct_daily_revenue", "fct_daily_revenue.order_date"),
    ("revnue_finance", "fct_daily_revenue.revenue_finance"),  # typo
    ("paid at", "stg_payments.paid_at"),
    ("payment method", "stg_payments.payment_method"),
]


@pytest.mark.parametrize(("query", "expected"), ABBREVIATIONS)
def test_abbreviations_and_variants(box: Toolbox, query: str, expected: str) -> None:
    ids = [str(c["id"]) for c in top(box, query, 5)]
    assert ids[0] == expected, ids


def test_equal_candidates_are_all_returned_and_flagged(box: Toolbox) -> None:
    # DESIGN: event_amount_usd exists in both int_payment_events and fct_payment_events (a star)
    ids = [str(c["id"]) for c in top(box, "event amount", 5)]
    assert set(ids[:2]) == {
        "int_payment_events.event_amount_usd",
        "fct_payment_events.event_amount_usd",
    }
    assert box.call("resolve_entity", {"text": "event amount"}).llm_payload["ambiguous"] is True


def test_qty_finds_every_quantity_column(box: Toolbox) -> None:
    # DESIGN_v2 §9 + owner decision (S02b): no order between `quantity` and literal `qty_*`
    # columns is asserted; that ranking is S08 linker design.
    ids = [str(c["id"]) for c in top(box, "qty", 6)]
    assert {
        "raw_order_items.quantity",
        "stg_order_items.quantity",
        "int_order_items_enriched.quantity",
        "int_order_item_margins.quantity",
    } <= set(ids)
    assert box.call("resolve_entity", {"text": "qty"}).llm_payload["ambiguous"] is True


def test_near_duplicate_refund_names_are_not_collapsed(box: Toolbox) -> None:
    lit = top(box, "refund_amt", 8)
    by_id = {str(c["id"]): float(c["score"]) for c in lit}  # type: ignore[arg-type]
    assert lit[0]["id"] == "stg_refunds.refund_amt"  # non-seed first among literal ties
    assert by_id["stg_refunds.refund_amt"] > by_id["int_order_financials.refund_amount"]
    assert by_id["int_order_financials.refund_amount"] > by_id["fct_orders.refunded_amount"]
    assert box.call("resolve_entity", {"text": "refund_amt"}).llm_payload["ambiguous"] is True


def test_models_resolve(box: Toolbox) -> None:
    first = top(box, "fct_orders", 3)[0]
    assert (first["kind"], first["id"]) == ("model", "fct_orders")


def test_get_model_sql_shows_where_lifetime_value_is_computed(box: Toolbox) -> None:
    """Expected lines read by hand from corpora/synthetic_shop/models/marts/dim_customers.sql:
    line 7 computes it inside the order_agg CTE
    (``sum(items_subtotal + sales_tax - refunded_amount) as lifetime_value``);
    line 21 is the final select (``coalesce(order_agg.lifetime_value, 0) as lifetime_value``)."""
    box.reset()
    r = box.call("get_model_sql", {"model_id": "dim_customers", "around_column": "lifetime_value"})
    p = r.llm_payload
    shown = {int(line.split(":", 1)[0]) for line in p["excerpt"] if line != "…"}
    assert {7, 21} <= shown
    assert any(line.startswith("7:") and "sum(items_subtotal" in line for line in p["excerpt"])
    assert all(w["excerpt_id"] in box.emitted_ids for w in p["windows"])
