"""R4 and SQL alias tokens (S13b F2, post-pilot-fixes.md, option (a)): ``alias.column`` where the
alias is a ref / source alias, a CTE or a derived table of a model in this question's evidence
is "not a node name", neither hallucinated nor supported, as metrics M3 / M7 (iv-k+) read it. An
alias that is also a real model name is checked as the model; an unknown ``foo.bar`` still fails.
Dev cases replay the committed pilot records without a model."""

from __future__ import annotations

from pathlib import Path

import pytest

from dlens.agent.answer import Answer, Claim, attach
from dlens.agent.loop import _parse_draft
from dlens.agent.tools import Toolbox
from dlens.agent.tools.provenance import alias_names
from dlens.agent.validator import validate

from .. import pilot_records as P

# -- the alias regex (owner's list) ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("sql", "alias"),
    [
        ("from {{ ref('fct_orders') }} as orders", "orders"),
        ('from {{ref("fct_orders")}} as orders', "orders"),
        ("from {{ ref('pkg', 'fct_orders') }} as orders", "orders"),
        ("from {{ source('raw', 'orders') }} as o", "o"),
        ("from {{ ref('fct_orders') }} orders", "orders"),  # implicit alias, no AS
        ("from {{ ref('fct_orders') }}\n    AS Orders", "orders"),
    ],
)
def test_ref_and_source_aliases(sql: str, alias: str) -> None:
    assert alias in alias_names(sql)


@pytest.mark.parametrize(
    "word",
    ["left join", "inner join", "join", "where", "on", "group", "order", "limit", "union",
     "qualify", "having", "window", "LEFT JOIN", "Where"],
)  # fmt: skip
def test_keywords_after_the_call_are_never_aliases(word: str) -> None:
    sql = f"select * from {{{{ ref('x') }}}} {word} y.id = 1"
    assert alias_names(sql) == set()


def test_cte_and_derived_names_still_count() -> None:
    sql = "with rfm_scores as (select 1 as a) select m.a from (select 1 as a) as m, rfm_scores"
    assert {"rfm_scores", "m"} <= alias_names(sql)


# -- dev cases (committed records) -----------------------------------------------------------------


def rounds(qid: str, model: str = "qwen"):
    rec = P.record(qid, model)
    led = P.ledger(rec)
    out = {"first": validate(P.first_answer(rec, led), led, rec["question"])}
    if rec["validation"].get("second"):
        regen = attach(_parse_draft(P.regenerate_text(rec)), led)
        out["second"] = validate(regen, led, rec["question"])
    return out


def r4(result, k):
    return [f.item_id for f in result.failures if f.claim_index == k and f.rule.startswith("R4")]


def test_dev46_alias_orders_no_longer_refuses() -> None:
    """`orders` is a ref alias in three of dev-46's files (fct_orders, int_orders_enriched,
    stg_orders): skipping it is safe where rewriting it would not be."""
    for name, res in rounds("dev-46").items():
        assert res.passed, name
    assert rounds("dev-46", "gemini")["first"].passed


def test_dev30_alias_tokens_pass_r4() -> None:
    res = rounds("dev-30")
    assert r4(res["first"], 0) == [] and r4(res["first"], None) == []
    assert res["first"].counts == {"R5": 2}  # its other claims still fail R5, unchanged
    assert res["second"].passed


def test_dev44_claim1_cte_alias_passes_under_a() -> None:
    """Gold-inconsistent in the prep audit only because of the CTE token `rfm_scores.*` itself
    (M3 ignores it); its real nodes dim_customer_rfm.rfm_score and dim_customers.lifetime_value
    are in the gold set. Under (a) the claim passes."""
    res = rounds("dev-44")["first"]
    assert 1 not in res.dropped_claims and res.passed


def test_dev45_claim0_derived_alias_passes_under_a() -> None:
    """Gold-inconsistent only because of the derived-table token `margins_monthly.*` itself; its
    real node fct_monthly_finance.contribution_margin is in the gold set. It passes under (a)."""
    assert rounds("dev-45")["first"].passed


def test_dev45_second_round_non_alias_token_still_fails() -> None:
    res = rounds("dev-45")["second"]
    assert ("R4.hallucinated", "int_order_margins.contribution_margin") in [
        (f.rule, f.item_id) for f in res.failures
    ]


def test_dev54_unknown_column_of_a_real_model_still_fails() -> None:
    assert "fct_orders.net_paid_us" in r4(rounds("dev-54")["first"], 1)


def test_unknown_foo_bar_still_hallucinated() -> None:
    rec = P.record("dev-46")
    led = P.ledger(rec)
    a = P.first_answer(rec, led)
    bad = a.model_copy(
        update={"claims": [*a.claims, Claim(text="foo_x.bar_y is derived here.", edge_ids=[])]}
    )
    res = validate(bad, led, rec["question"])
    assert ("R4.hallucinated", "foo_x.bar_y") in [(f.rule, f.item_id) for f in res.failures]


# -- an alias that is also a real model name is checked as the model -------------------------------


def test_alias_that_is_a_model_name_is_checked_as_the_model(box: Toolbox, shop_root: Path) -> None:
    (shop_root / "models/other.sql").write_text(
        "select\n    stg.total, o2.total as t2\nfrom {{ ref('fct') }} as stg\n"
        "join {{ ref('fct') }} as o2 on 1 = 1\n"
    )
    box.call("get_model_sql", {"model_id": "other"})
    ans = Answer(
        answer_text="ok",
        claims=[
            Claim(text="stg.nope_col is used in other.", edge_ids=[]),
            Claim(text="o2.total is used in other.", edge_ids=[]),
        ],
        confidence="high",
    )
    res = validate(ans, box)
    assert ("R4.hallucinated", "stg.nope_col") in [(f.rule, f.item_id) for f in res.failures]
    assert r4(res, 1) == []  # o2 is an alias of other's SQL and not a model: not a node name
