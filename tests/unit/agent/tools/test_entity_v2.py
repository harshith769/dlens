"""Linker v2 (S08): stages, scorer, thresholds, dotted ids, hybrid stage, install path.

The graph is hand-built with synthetic_shop-style names (no dbt). Expected numbers are the
design's hand calculations (docs/plans/linker-design.md §3.2, amendments A-E), never v2 output.
"""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dlens.agent.tools import Toolbox
from dlens.agent.tools.entity import (
    AMBIGUOUS_GAP,
    NO_MATCH,
    RRF_MAX,
    _soft_dice,
    dotted_column,
    forms,
)
from dlens.graph import LineageGraph

P = "model.s"
COLUMNS = {
    "dim_customers": ["customer_id", "order_count", "lifetime_value"],
    "fct_daily_revenue": ["order_date", "order_count"],
    "fct_customer_leaderboard": ["customer_id", "lifetime_value_usd"],
    "dim_customer_segments": ["customer_id", "customer_segment"],
    "fct_segment_monthly": ["customer_segment", "segment_order_count"],
    "stg_payments": ["payment_id", "payment_method", "amount_usd"],
    "stg_shipments": ["shipment_id", "shipping_cost_usd"],
    "fct_shipping_performance": ["carrier", "shipping_costs_usd"],
    "int_order_items_enriched": ["order_id", "product_category"],
    "stg_products": ["product_id", "category"],
    "fct_orders": ["order_id", "previous_order_date", "sales_tax"],
    "int_customer_order_history": ["order_id", "previous_order_date", "sales_tax"],
}
SEEDS = {"raw_payments": ["id", "method", "amt"]}


def uid(model: str) -> str:
    return f"seed.s.{model}" if model in SEEDS else f"{P}.{model}"


def make_graph() -> LineageGraph:
    columns: dict[str, dict[str, str]] = {}
    models: dict[str, dict[str, str]] = {}
    for m, cols in {**COLUMNS, **SEEDS}.items():
        rtype = "seed" if m in SEEDS else "model"
        models[uid(m)] = {"resource_type": rtype, "name": m, "file": f"models/{m}.sql"}
        for c in cols:
            columns[f"{uid(m)}.{c}"] = {"model": uid(m), "name": c}
    return LineageGraph(columns, [], [], [], models, {}, {})


@pytest.fixture(scope="module")
def box(tmp_path_factory: pytest.TempPathFactory) -> Toolbox:
    return Toolbox(make_graph(), tmp_path_factory.mktemp("p"))


def resolve(box: Toolbox, text: str, **kw: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    r = box.call("resolve_entity", {"text": text, **kw})
    assert not r.is_error, r.llm_payload
    return r.llm_payload, r.side_records


def top(box: Toolbox, text: str) -> list[tuple[str, float]]:
    return [(c["id"], c["score"]) for c in resolve(box, text)[0]["candidates"]]


# -- stage 1 -----------------------------------------------------------------------------------


def test_exact_id_is_always_first_and_alone_for_a_dotted_id(box: Toolbox) -> None:
    """linker_gaps.yml G1: the model name used to outrank the exact id."""
    p, _ = resolve(box, "dim_customer_segments.customer_segment")
    assert [c["id"] for c in p["candidates"]] == ["dim_customer_segments.customer_segment"]
    assert p["candidates"][0] == {
        "id": "dim_customer_segments.customer_segment",
        "kind": "column",
        "match": "exact",
        "score": 1.0,
    }
    assert p["ambiguous"] is False


def test_exact_bare_name_ties_across_models(box: Toolbox) -> None:
    p, _ = resolve(box, "customer_segment")
    assert {c["id"] for c in p["candidates"][:2]} == {
        "dim_customer_segments.customer_segment",
        "fct_segment_monthly.customer_segment",
    }
    assert p["candidates"][0]["score"] == 0.97 and p["ambiguous"] is True


def test_soft_dice_is_bounded_with_repeated_tokens() -> None:
    """The v1 >1.0 bug: each query token may use each name token once."""
    q = ["dim", "customer", "segment", "customer", "segment"]
    assert _soft_dice(q, ["dim", "customer", "segment"]) <= 1.0


# -- stage 2 and the scorer (design §3.2 worked examples) ------------------------------------


def test_dev15_phrase_rule_plus_model_bonus(box: Toolbox) -> None:
    p, side = resolve(box, "number of orders per customer")
    first = p["candidates"][0]
    assert (first["id"], first["match"], first["score"]) == (
        "dim_customers.order_count",
        "normalised",
        0.94,
    )
    parts = side["parts"]["dim_customers.order_count"]
    assert parts["tier"] == "rewritten" and "P1" in parts["rules"] and parts["model_bonus"] == 0.06
    assert p["ambiguous"] is False


def test_exact_tokens_beat_a_weak_extra_token(box: Toolbox) -> None:
    """linker_gaps.yml fragile: lifetime_value 0.93+0.01 vs lifetime_value_usd 0.87+0.01."""
    assert top(box, "lifetime value")[:2] == [
        ("dim_customers.lifetime_value", 0.94),
        ("fct_customer_leaderboard.lifetime_value_usd", 0.88),
    ]
    assert resolve(box, "lifetime value")[0]["ambiguous"] is False


def test_same_tier_same_evidence_stays_ambiguous(box: Toolbox) -> None:
    """dev-16: the layer prior orders the pair but must not resolve it (spread < delta)."""
    p, _ = resolve(box, "previous order date")
    assert [c["id"] for c in p["candidates"][:2]] == [
        "fct_orders.previous_order_date",
        "int_customer_order_history.previous_order_date",
    ]
    assert p["ambiguous"] is True


def test_partial_model_bonus_orders_but_full_bonus_decides(box: Toolbox) -> None:
    p, side = resolve(box, "prod category on order items")
    assert p["candidates"][0]["id"] == "int_order_items_enriched.product_category"
    assert side["parts"]["int_order_items_enriched.product_category"]["model_bonus"] == 0.04


def test_plural_is_a_rewrite_not_surface(box: Toolbox) -> None:
    """Amendment A: shipping_costs_usd is 0.06 below shipping_cost_usd for 'shipping cost usd'."""
    _, side = resolve(box, "shipping cost usd")
    assert side["parts"]["stg_shipments.shipping_cost_usd"]["tier"] == "surface"
    assert side["parts"]["fct_shipping_performance.shipping_costs_usd"]["tier"] == "rewritten"
    assert top(box, "shipping cost usd")[0][0] == "stg_shipments.shipping_cost_usd"


def test_model_bonus_dropped_when_the_text_is_a_column_name(box: Toolbox) -> None:
    """Amendment D: 'payment method' is a column's name, so raw_payments.method gets no bonus."""
    p, side = resolve(box, "payment method")
    assert p["candidates"][0]["id"] == "stg_payments.payment_method"
    assert side["parts"]["raw_payments.method"]["model_bonus"] == 0.0
    assert p["ambiguous"] is True  # two honest readings, 0.93 vs 0.925


def test_cap_is_on_the_printed_score_only(box: Toolbox) -> None:
    """Amendment E: both print 0.96; the ranking still uses the raw sums."""
    p, side = resolve(box, "sales tax in fct_orders")
    assert p["candidates"][0]["id"] == "fct_orders.sales_tax"
    assert p["candidates"][0]["score"] == 0.96
    assert (
        side["parts"]["fct_orders.sales_tax"]["raw"]
        > side["parts"]["int_customer_order_history.sales_tax"]["raw"]
    )


def test_phrase_rules_add_forms_and_keep_the_original() -> None:
    texts = {f.rule: " ".join(f.surface) for f in forms("number of orders per customer")}
    assert texts == {None: "number of orders per customer", "P1": "orders count per customer"}
    assert {f.rule for f in forms("how many sessions")} == {None, "P2"}
    assert {f.rule for f in forms("count of visitors")} == {None, "P3"}
    assert " ".join(forms("total shipping cost")[1].surface) == "shipping cost total"


# -- no-match and ambiguity margin ------------------------------------------------------------


def test_one_shared_word_of_two_is_no_match_and_closest_stays_out_of_the_payload(
    box: Toolbox,
) -> None:
    p, side = resolve(box, "ship date")
    assert p["candidates"] == [] and p["notes"]
    assert "closest" not in p and side["closest"]  # display-only (Q3, design point 6)


def test_thresholds_are_the_design_values() -> None:
    assert (NO_MATCH, AMBIGUOUS_GAP) == (0.60, 0.05)


# -- dotted ids (amendment C) -------------------------------------------------------------------


def test_dotted_abbreviation_maps_to_exactly_one_column(box: Toolbox) -> None:
    p, side = resolve(box, "stg_payments.amt")  # amt -> amount, usd weak
    assert [c["id"] for c in p["candidates"]] == ["stg_payments.amount_usd"]
    assert p["candidates"][0]["match"] == "normalised" and p["ambiguous"] is False
    assert p["notes"] == ["interpreted stg_payments.amt as stg_payments.amount_usd"]


def test_dotted_ids_get_no_plural_typo_or_fuzzy_rescue(box: Toolbox) -> None:
    for text in (
        "fct_shipping_performance.shipping_cost_usd",
        "fct_orders.sales_taxx",
        "fct_orders.ship_date",
    ):
        p, side = resolve(box, text)
        assert p["candidates"] == [], text
        assert "closest" in side


def test_dotted_column_reports_unknown_models_as_none() -> None:
    assert dotted_column(make_graph(), "no_such_model", "x") is None


# -- stage 3 (hybrid) -----------------------------------------------------------------------------


class FakeIndex:
    """Duck-typed SearchIndex: returns fixed hits."""

    def __init__(self, hits: list[tuple[str, float, float]]) -> None:
        self.hits = hits  # (column id, rrf score, cosine)
        self.queries: list[str] = []

    def search(
        self, query: str, k: int = 8, kinds: list[str] | None = None, mode: str = "hybrid"
    ) -> list[Any]:
        self.queries.append(query)
        assert kinds == ["column"]
        return [
            SimpleNamespace(
                chunk=SimpleNamespace(column=cid), score=s, bm25_rank=i, dense_rank=i, cosine=cos
            )
            for i, (cid, s, cos) in enumerate(self.hits, 1)
        ]


def test_hybrid_runs_only_when_stage2_is_not_confident(tmp_path: Path) -> None:
    idx = FakeIndex([(f"{P}.dim_customers.lifetime_value", RRF_MAX, 0.9)])
    box = Toolbox(make_graph(), tmp_path, index=idx)  # type: ignore[arg-type]
    p, _ = resolve(box, "lifetime value")  # a surface match: no stage 3
    assert idx.queries == [] and "hybrid" not in p


def test_strong_hybrid_beats_a_below_bar_stage2_candidate(tmp_path: Path) -> None:
    """Owner amendment: below-bar S2 (fuzzy) and S3 candidates are ranked together on score."""
    hit = f"{P}.fct_customer_leaderboard.customer_id"
    idx = FakeIndex([(hit, 0.93 * RRF_MAX, 0.88)])  # 0.50 + 0.30 x 0.93 = 0.779
    box = Toolbox(make_graph(), tmp_path, index=idx)  # type: ignore[arg-type]
    p, side = resolve(box, "segment order cnt")  # fuzzy ~0.6-0.7 for segment_order_count
    fuzzy = side["parts"].get("fct_segment_monthly.segment_order_count")
    assert fuzzy is not None and fuzzy["tier"] == "fuzzy" and fuzzy["raw"] < 0.779
    assert p["candidates"][0]["id"] == "fct_customer_leaderboard.customer_id"
    assert p["candidates"][0]["match"] == "hybrid" and p["hybrid"] == "used"


def test_hybrid_needs_the_cosine_floor(tmp_path: Path) -> None:
    idx = FakeIndex([(f"{P}.fct_orders.sales_tax", RRF_MAX, 0.79)])
    box = Toolbox(make_graph(), tmp_path, index=idx)  # type: ignore[arg-type]
    p, _ = resolve(box, "warehouse temperature")
    assert p["candidates"] == [] and p["hybrid"] == "used"


def test_without_an_index_hybrid_is_unavailable(box: Toolbox) -> None:
    assert resolve(box, "lifetime value")[0]["hybrid"] == "unavailable"


def test_core_install_never_imports_retrieval() -> None:
    code = (
        "import sys; from pathlib import Path\n"
        "from dlens.agent.tools import Toolbox\n"
        "from dlens.graph import LineageGraph\n"
        "g = LineageGraph({'model.s.m.a': {'model': 'model.s.m', 'name': 'a'}}, [], [], [],"
        " {'model.s.m': {'resource_type': 'model', 'name': 'm', 'file': 'm.sql'}}, {}, {})\n"
        "Toolbox(g, Path('.')).call('resolve_entity', {'text': 'a'})\n"
        "bad = [m for m in sys.modules if m.startswith('dlens.retrieval')]\n"
        "assert not bad, bad\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_layer_comes_from_the_folder_then_the_name_prefix() -> None:
    """Owner, 18 Oct 2026: folder (fqn path) first, nearest folder wins; name prefix fallback."""
    from dlens.agent.tools.entity import layer

    assert layer("customers", "model", "models/marts/core/customers.sql") == "marts"
    assert (
        layer("int_x", "model", "dbt_packages/jira/models/intermediate/f/int_x.sql")
        == "intermediate"
    )
    assert layer("orders", "model", "models/staging/shop/orders.sql") == "staging"
    assert layer("fct_x", "model", "models/fct_x.sql") == "marts"  # no layer folder: prefix
    assert layer("jira__issue", "model", "models/jira__issue.sql") is None  # neither
    assert layer("anything", "seed", "seeds/anything.csv") == "raw"
    assert layer("stg_x", "model", "models/marts/stg_x.sql") == "marts"  # the folder wins
