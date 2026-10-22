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
