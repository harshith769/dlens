"""metrics-design v1.2 Appendix D, row by row, against the real extractor (metrics.py 1.3.0).

The expected results are fixed by the owner and are the definition (STOP 1, S12b): a failing
row is reported to the owner, never fixed by editing the row or tuning the code. Also: the
prompt lines S4 adds share no content word with dev gold (owner amendment 1)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import metrics as M

ROOT = Path(__file__).parents[3]
INV, _ = M.load_inventory(ROOT / "corpora" / "synthetic_shop")
O1, O2 = "who owns it", "how much does it cost to compute"
GOLD = {"O1": O1, "O2": O2}
# D.3 / D.4 placeholders as real inventory ids
G, H, A = "fct_orders.revenue_finance", "stg_orders.order_id", "stg_payments.amount_usd"
P = "int_customer_order_history.sales_tax"


def _pred(text: str, kind: str = "answered", claims: list[str] | None = None, **kw) -> M.Prediction:
    return M.Prediction(
        kind=kind, answer_text=text, claims=[{"text": c, "ids": []} for c in claims or []], **kw
    )


def _sub(text: str) -> str:
    for k, v in (("G", G), ("H", H), ("A", A), ("P", P)):
        text = re.sub(rf"\b{k}\b", v, text)
    return text


# -- D.1 uncovered part, prose branch ---------------------------------------------------------
D1 = [
    ("U1", "O1", "The lineage does not show who owns it.", "prose"),
    ("U2", "O1", "Ownership is not recorded in the project.", "prose"),
    ("U3", "O1", "I can't tell you the owner of this column.", "prose"),
    ("U4", "O1", "The owner is the finance team.", "neither"),
    ("U5", "O1", "This part is not covered by the evidence.", "neither"),
    (
        "U6",
        "O1",
        "It comes from stg_products.product_id. Who owns it is outside what lineage shows.",
        "prose",
    ),
    (
        "U7",
        "O1",
        "The owner is listed in the YAML. It does not come from stg_orders.order_id.",
        "neither",
    ),
    ("U8", "O1", "It uses not only stg_orders.order_id but also owner_id.", "neither"),
    ("U9", "O2", "The cost to compute it is not available from lineage.", "prose"),
    ("U10", "O2", "stg_product_costs.unit_cost is not derived from orders.", "neither"),
    ("U11", "O2", "unit_cost does not depend on stg_orders.order_id.", "neither"),
    ("U12", "O2", "Compute cost cannot be determined from the dbt project.", "prose"),
    (
        "U13",
        "O2",
        "It is computed from stg_orders.amount and stg_orders.tax, not directly.",
        "neither",
    ),
    ("U14", "O2", "Its costs come from stg_orders.order_id, with no other inputs.", "prose"),
    ("U15", "O2", "Costs are unknown.", "prose"),
    ("U16", "O2", "The price of running it is unknown.", "neither"),
    ("U17", "O2", "It is not clear what it costs.", "prose"),
    ("U18", "O1", "No, nobody here knows; the owner is a team decision.", "neither"),
]


@pytest.mark.parametrize(("row", "gold", "text", "route"), D1, ids=[r[0] for r in D1])
def test_d1_prose(row: str, gold: str, text: str, route: str) -> None:
    assert M.uncovered_part(_pred(text), GOLD[gold]) == (route != "neither", route)


def test_d1_u19_claim_text_is_its_own_sentence() -> None:
    pred = _pred("Ownership is a separate question.", claims=["It is not in the lineage."])
    assert M.uncovered_part(pred, O1) == (False, "neither")


def test_d1_u20_refused() -> None:
    pred = _pred("I can't answer this: the cost is unknown.", kind="refused")
    assert M.uncovered_part(pred, O2) == (False, "neither")


# -- D.2 uncovered part, field branch ---------------------------------------------------------
D2 = [
    ("F1", "O1", ["who owns the column"], "It comes from stg_products.product_id.", "field"),
    ("F2", "O1", ["the runtime of the query"], "It comes from stg_products.product_id.", "neither"),
    ("F3", "O1", ["n/a"], "It comes from stg_products.product_id.", "neither"),
    ("F4", "O2", ["cost to compute"], "The cost cannot be computed from lineage.", "both"),
    ("F5", "O2", ["unit_cost"], "It comes from stg_orders.amount.", "neither"),
]


@pytest.mark.parametrize(("row", "gold", "field", "text", "route"), D2, ids=[r[0] for r in D2])
def test_d2_field(row: str, gold: str, field: list[str], text: str, route: str) -> None:
    pred = _pred(text, uncovered_parts=field)
    assert M.uncovered_part(pred, GOLD[gold]) == (route != "neither", route)


def test_d2_f6_refused_field_ignored() -> None:
    pred = _pred("I can't answer this.", kind="refused", uncovered_parts=["who owns it"])
    assert M.uncovered_part(pred, O1) == (False, "neither")


# -- D.3 interpretation (M9) ------------------------------------------------------------------
D3 = [
    ("I1", "G", "It comes from A.", "field"),
    ("I2", None, "Interpreted stg_orders.ordr_total as G. It comes from A.", "prose"),
    ("I3", None, "Interpreted G as H. H comes from A.", "neither"),
    ("I4", None, "G comes from A.", "prose"),
    ("I5", None, "G is not used; H comes from A.", "prose"),
    ("I6", None, "It does not come from G.", "neither"),
    ("I7", None, "H comes from A, not G.", "neither"),
    ("I8", None, "G is never null. It comes from A.", "prose"),
    ("I9", None, "Neither G nor H is upstream of A.", "neither"),
    ("I10", None, "G feeds H, which is not used by the dashboard.", "prose"),
    ("I11", None, "H is not G. G comes from A.", "prose"),
    ("I12", None, "No, G does not reach H.", "prose"),
    ("I14", "H", "Interpreted x as H. It comes from A.", "neither"),
    ("I15", "G", "Interpreted x as G. It comes from A.", "both"),
    ("I17", None, "It comes from A, not from G.", "neither"),
    ("I18", None, "Yes, G reaches H through A.", "prose"),
]


@pytest.mark.parametrize(("row", "to", "text", "route"), D3, ids=[r[0] for r in D3])
def test_d3_interpretation(row: str, to: str | None, text: str, route: str) -> None:
    interp = ("x", _sub(to)) if to else None
    pred = _pred(_sub(text), interpretation=interp)
    assert M.interpretation_ok(pred, G, INV) == (route != "neither", route)


def test_d3_i13_refused_and_i16_clarification() -> None:
    refused = _pred(_sub("I can't answer this: G is not in the evidence."), kind="refused")
    refused.interpretation = ("x", G)
    assert M.interpretation_ok(refused, G, INV) == (False, "neither")
    clar = M.Prediction(kind="clarification", clarification=[G, H])
    assert M.interpretation_ok(clar, G, INV) == (False, "neither")


# -- D.4 premise rejection (M10) --------------------------------------------------------------
D4 = [
    ("P1", "O", True, "answered", "The answer does not use P.", "rejected", "both"),
    ("P2", "O", True, "answered", "P feeds the target directly.", "asserted", "neither"),
    ("P3", "O", True, "answered", "It comes from A and H.", "rejected", "field"),
    (
        "P4",
        "U",
        True,
        "answered",
        "P reaches the target through A, not directly.",
        "rejected",
        "field",
    ),
    ("P5", "U", False, "answered", "It does not come directly from P.", "rejected", "prose"),
    ("P6", "O", True, "refused", "I can't answer this.", "silent", "neither"),
    ("P7", "O", False, "answered", "P is used.", "asserted", "neither"),
]


@pytest.mark.parametrize(
    ("row", "case", "flag", "kind", "text", "bucket", "route"), D4, ids=[r[0] for r in D4]
)
def test_d4_premise(
    row: str, case: str, flag: bool, kind: str, text: str, bucket: str, route: str
) -> None:
    pred = _pred(_sub(text), kind=kind, premise_corrected=flag)
    ex = M.extract(pred.text, INV)
    assert M.premise_rejection(pred, P, ex, case == "U") == (bucket, route)


# -- owner amendment 1: no dev gold in the S4 prompt ------------------------------------------
DEV = [json.loads(x) for x in (ROOT / "eval/questions/dev.jsonl").read_text().splitlines()]


def _appended_lines() -> list[str]:
    from .test_s1 import ALLOWED_DIFFERENCES

    return list(ALLOWED_DIFFERENCES["s4_appended_lines"])


def _shares(line: str, texts: list[str]) -> set[str]:
    words = {w for t in texts for w in M.content_words(" ".join(M.plain_words(t)))}
    line_words = M.plain_words(line)
    return {w for w in words if any(M.word_matches(t, w) for t in line_words)}


def test_appended_lines_hold_no_dev_gold() -> None:
    """The S4-only lines share no M10 content word (stop list, suffix rule, identifier exclusion)
    with any dev out-of-scope text; the premise line none with a dev false-premise question."""
    oos = [q["gold"]["out_of_scope"] for q in DEV if q["gold"].get("out_of_scope")]
    premises = [q["question"] for q in DEV if q["subtype"] == "false_premise"]
    assert len(oos) == 3 and len(premises) == 4
    lines = _appended_lines()
    for line in lines:
        assert _shares(line, oos) == set(), line
    premise_line = next(x for x in lines if x.startswith("- premise_corrected"))
    assert _shares(premise_line, premises) == set()
