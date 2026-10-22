"""R8c completion over indirect edges (S13c F1 (d1), s13c-design.md): an indirect edge may bridge
only if an ``impact_downstream`` result showed it (ADR 0026's allowlist: impact direct + indirect,
trace direct), never for a claim with derivation wording; the anchor, the directed-bridge, the
4-hop bound and the "directly" guards are unchanged. Dev cases replay the committed records."""

from __future__ import annotations

from dlens.agent.answer import Answer, Claim, attach
from dlens.agent.loop import _parse_draft
from dlens.agent.validator import validate

from .. import pilot_records as P


def dev53():
    rec = P.record("dev-53")
    led = P.ledger(rec)
    return rec, led, P.first_answer(rec, led)


def with_claim_text(a: Answer, k: int, text: str) -> Answer:
    claims = list(a.claims)
    claims[k] = Claim(text=text, edge_ids=claims[k].edge_ids, chunk_ids=claims[k].chunk_ids)
    return a.model_copy(update={"claims": claims})


def r8(res, k: int) -> bool:
    return any(f.rule == "R8" and f.claim_index == k for f in res.failures)


def test_dev53_impact_claims_complete_through_a_join_and_pass() -> None:
    rec, led, a = dev53()
    res = validate(a, led, rec["question"])
    assert res.passed and res.dropped_claims == []
    added = {c["claim_index"]: c["added"] for c in res.completions}
    assert set(added) == {1, 2, 3, 4}
    assert any((led.record(i) or {}).get("indirect") for i in added[2])  # bridged through a JOIN
    assert all(res.cleaned_answer.claims[k].origin == "completed" for k in added)


def test_dev71_gemini_depends_on_claims_pass() -> None:
    rec = P.record("dev-71", "gemini")
    led = P.ledger(rec)
    res = validate(P.first_answer(rec, led), led, rec["question"])
    assert res.passed and not res.dropped_claims


def test_derivation_wording_never_bridges_through_an_indirect_edge() -> None:
    rec, led, a = dev53()
    bad = with_claim_text(
        a, 2, "fct_product_performance.product_id is derived from stg_product_costs.product_id."
    )
    assert r8(validate(bad, led, rec["question"]), 2)


def test_aggregated_wording_is_blocked_too() -> None:
    rec, led, a = dev53()
    bad = with_claim_text(
        a, 2, "stg_product_costs.product_id is aggregated into fct_product_performance.product_id."
    )
    res = validate(bad, led, rec["question"])
    assert 2 in res.dropped_claims


def test_indirect_edge_not_shown_by_impact_downstream_never_bridges() -> None:
    """The same ledger with the impact result's provenance removed (the ids stay emitted, as if
    another tool had shown them): the JOIN edge is off the allowlist, so claim 2 fails R8."""
    rec, led, a = dev53()
    for r in led.log:
        if r.tool == "impact_downstream":
            r.tool = "get_model_sql"
    assert r8(validate(a, led, rec["question"]), 2)


def test_directly_over_an_indirect_bridge_fails() -> None:
    rec, led, a = dev53()
    bad = with_claim_text(
        a, 2, "stg_product_costs.product_id directly affects fct_product_performance.product_id."
    )
    assert r8(validate(bad, led, rec["question"]), 2)


def test_dev65_sibling_claims_still_fail() -> None:
    """Second round: 'X is downstream of Y' for two columns of one model that only share
    ancestors; no directed path, indirect or not."""
    rec = P.record("dev-65")
    led = P.ledger(rec)
    second = attach(_parse_draft(P.regenerate_text(rec)), led)
    res = validate(second, led, rec["question"])
    assert all(r8(res, k) for k in (9, 10, 11, 12))
