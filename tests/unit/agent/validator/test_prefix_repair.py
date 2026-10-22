"""R2r with a 5-hex prefix (S13b F4, post-pilot-fixes.md): a truncated id is repaired only when it
is a unique same-prefix match of >= 5 hex characters in this question's ledger. The dev case is
dev-16 from the committed qwen pilot record, replayed without a model."""

from __future__ import annotations

from dlens.agent import validator as v
from dlens.agent.validator import repair_candidates, validate

from .. import pilot_records as P


def test_min_prefix_is_five() -> None:
    assert v.MIN_PREFIX_HEX == 5


def test_dev16_truncated_target_id_is_repaired_and_the_claim_passes() -> None:
    rec = P.record("dev-16")
    led = P.ledger(rec)
    ans = P.first_answer(rec, led)
    assert "e_81a3f" in ans.claims[0].ids  # the target claim, cut to 5 hex
    res = validate(ans, led, rec["question"])
    assert {"claim_index": 0, "from": "e_81a3f", "to": "e_81a3f693"} in res.repairs
    assert 0 not in res.dropped_claims
    assert not [f for f in res.failures if f.claim_index == 0]  # then checked by R3/R5/R7 as usual
    assert res.cleaned_answer.claims[0].origin == "repaired"
    assert "fct_orders.previous_order_date" in res.cleaned_answer.claims[0].text  # the target


def test_two_ids_sharing_the_5_hex_prefix_are_ambiguous() -> None:
    assert repair_candidates("e_81a3f", ["e_81a3f693", "e_81a3f0aa"]) == [
        "e_81a3f0aa",
        "e_81a3f693",
    ]  # >= 2 candidates: R2r refuses the repair


def test_dev16_with_a_second_id_on_the_same_prefix_still_fails_r2() -> None:
    rec = P.record("dev-16")
    led = P.ledger(rec)
    led._emitted["e_81a3f0aa"] = dict(led._emitted["e_81a3f693"])  # a twin on the same prefix
    res = validate(P.first_answer(rec, led), led, rec["question"])
    assert ("R2", "e_81a3f") in [(f.rule, f.item_id) for f in res.failures if f.claim_index == 0]
    assert not [r for r in res.repairs if r["from"] == "e_81a3f"]


def test_a_4_hex_prefix_is_not_repaired() -> None:
    assert repair_candidates("e_81a3", ["e_81a3f693"]) == []


def test_the_prefix_must_match_the_id_kind() -> None:
    assert repair_candidates("s_81a3f", ["e_81a3f693"]) == []
