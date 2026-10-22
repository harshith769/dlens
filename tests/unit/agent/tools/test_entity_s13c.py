"""Linker changes of S13c (docs/plans/s13c-design.md), on the synthetic_shop graph built from the
committed fixture artifacts. The index is a stub that fails if searched, so a test proves the
hybrid stage was not reached without needing the retrieval extra.

L2: a dotted id whose model names no model, seed or source never goes to the fuzzy or hybrid
stages (dev-93).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import pytest

from dlens.agent.tools.entity import link
from dlens.graph import LineageGraph, build_graph_from_artifacts

ROOT = Path(__file__).resolve().parents[4]
SS_TARGET = ROOT / "tests" / "fixtures" / "artifacts" / "synthetic_shop"


@cache
def graph() -> LineageGraph:
    return build_graph_from_artifacts(SS_TARGET)[0]


class NoSearch:
    """An index stand-in: reaching the hybrid stage is a test failure."""

    def search(self, *_: Any, **__: Any) -> list[Any]:
        raise AssertionError("the hybrid stage was reached")


# -- L2 --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["fct_returns.return_amount", "payroll.employee_salary"])
def test_dotted_unknown_model_has_no_candidate_and_no_hybrid(text: str) -> None:
    cands, info = link(graph(), text, NoSearch())  # type: ignore[arg-type]
    assert cands == []
    assert info["closest"] and all("." not in n for n in info["closest"])  # model names
    assert any("no model, seed or source" in n for n in info["notes"])


def test_dev93_closest_models_are_named() -> None:
    _, info = link(graph(), "fct_returns.return_amount", None)
    assert "fct_orders" in info["closest"] or any(n.startswith("fct_") for n in info["closest"])


def test_dotted_known_model_unknown_column_is_unchanged() -> None:
    cands, info = link(graph(), "stg_orders.ship_date", NoSearch())  # type: ignore[arg-type]
    assert cands == [] and all(c.startswith("stg_orders.") for c in info["closest"])


def test_dotted_exact_id_is_unchanged() -> None:
    cands, _ = link(graph(), "stg_payments.amount_usd", NoSearch())  # type: ignore[arg-type]
    assert [c.row["id"] for c in cands] == ["stg_payments.amount_usd"]


def test_dotted_abbreviation_is_unchanged() -> None:
    cands, info = link(graph(), "stg_payments.amt", NoSearch())  # type: ignore[arg-type]
    assert [c.row["id"] for c in cands] == ["stg_payments.amount_usd"]
    assert info["notes"]  # "interpreted ..."


def test_plain_text_still_reaches_hybrid() -> None:
    """Only a dotted text is kept from stage 3; a description still goes there."""
    with pytest.raises(AssertionError, match="hybrid stage was reached"):
        link(graph(), "gift card balance", NoSearch())  # type: ignore[arg-type]


# -- L1: "<column> in <model>" ---------------------------------------------------------------------


def top(text: str, index: Any = None) -> tuple[list[str], bool, list[str]]:
    from dlens.agent.tools.entity import AMBIGUOUS_GAP

    cands, _ = link(graph(), text, index)
    amb = len(cands) > 1 and cands[0].raw - cands[1].raw < AMBIGUOUS_GAP
    return [c.row["id"] for c in cands], amb, [c.tier for c in cands]


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("line_margin in int_order_item_margins", "int_order_item_margins.line_margin"),  # dev-29
        ("order_id in int_order_profit", "int_order_profit.order_id"),  # dev-40
        ("revenue_marketing in fct_daily_revenue", "fct_daily_revenue.revenue_marketing"),  # dev-56
        ("customer_id in int_customer_sessions", "int_customer_sessions.customer_id"),  # dev-71
        ("customer segment in customer leaderboard", "fct_customer_leaderboard.customer_segment"),
        ("last name in raw customers", "raw_customers.last_name"),  # dev-75: the layer is named
    ],
)
def test_column_in_model_is_a_unique_qualified_top1_and_skips_hybrid(text: str, want: str) -> None:
    ids, amb, tiers = top(text, NoSearch())
    assert ids[0] == want and tiers[0] == "qualified" and not amb


def test_wrong_model_is_not_qualified() -> None:
    ids, _, tiers = top("line_margin in fct_orders")
    assert "qualified" not in tiers


def test_bare_column_is_unchanged() -> None:
    _, _, tiers = top("line_margin")
    assert "qualified" not in tiers


# owner's negative tests (S13c decision 3)


def test_number_of_orders_per_customer_is_not_qualified_and_dev15_links() -> None:
    ids, amb, tiers = top("number of orders per customer")
    assert "qualified" not in tiers
    assert ids[0] == "dim_customers.order_count" and not amb


def test_multi_model_phrase_gives_no_qualified_candidate() -> None:
    with pytest.raises(AssertionError, match="hybrid stage was reached"):
        top("revenue from fct_orders to dim_customers", NoSearch())  # not confident: no qualified
    _, _, tiers = top("revenue from fct_orders to dim_customers")
    assert "qualified" not in tiers


def test_orders_in_the_last_month_gives_no_qualified_candidate() -> None:
    _, _, tiers = top("orders in the last month")
    assert "qualified" not in tiers


def test_unprefixed_model_name_shared_by_several_models_is_not_qualified() -> None:
    # "orders" is the unprefixed name of raw_orders, stg_orders and fct_orders
    _, _, tiers = top("order_id in orders")
    assert "qualified" not in tiers


def test_qualified_drops_other_models_readings() -> None:
    """The text names its model, so another model's stage-2 reading is not a candidate."""
    ids, _, _ = top("last name in raw customers")
    assert "stg_customers.last_name" not in ids


# owner's conditions on the drop rule (S13c, decision 3 correction)


def test_last_name_in_raw_customers_picks_raw_and_drops_stg() -> None:
    ids, amb, tiers = top("last name in raw customers")
    assert ids[0] == "raw_customers.last_name" and tiers[0] == "qualified" and not amb
    assert "stg_customers.last_name" not in ids


def test_unprefixed_non_unique_model_part_drops_nothing() -> None:
    ids, _, tiers = top("order_id in orders")
    assert "qualified" not in tiers
    assert len({i.split(".")[0] for i in ids}) > 1  # other models' readings are kept


def test_wrong_model_drops_nothing() -> None:
    ids, _, tiers = top("line_margin in fct_orders")
    assert "qualified" not in tiers
    assert "int_order_item_margins.line_margin" in ids  # the real column is still a candidate


def test_drop_applies_per_mention_only() -> None:
    """Two mentions in one question are two resolve_entity calls; dropping other models'
    readings for the qualified one leaves the other mention's candidates alone."""
    from dlens.agent.tools import Toolbox

    box = Toolbox(graph(), ROOT / "corpora" / "synthetic_shop")
    first = box.call("resolve_entity", {"text": "last name in raw customers"}).llm_payload
    second = box.call("resolve_entity", {"text": "last name"}).llm_payload
    assert [c["id"] for c in first["candidates"]] == ["raw_customers.last_name"]
    assert {"raw_customers.last_name", "stg_customers.last_name"} <= {
        c["id"] for c in second["candidates"]
    }
