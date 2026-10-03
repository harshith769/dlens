"""R9 verdict consistency, and r_ reachability facts in R2/R3/R7/R8 (session 5a-final)."""

import pytest

from dlens.agent.tools import Toolbox
from dlens.agent.validator import ValidationContext, answer_verdict, rule_verdict, validate

from .conftest import answer, eid


def rules(result) -> list[str]:
    return sorted(f.rule for f in result.failures)


def fact(box: Toolbox, src: str, dst: str) -> str:
    """Run the code-only reachability check and return its r_ id."""
    r = box.call("reachability", {"from_column": src, "to_column": dst}, code=True)
    return r.llm_payload["fact_id"]


@pytest.fixture
def unreached(box: Toolbox) -> tuple[Toolbox, str]:
    """raw.id does NOT reach fct.total (it only reaches the x_id chain)."""
    box.call("trace_upstream", {"column_id": "fct.total"})
    return box, fact(box, "raw.id", "fct.total")


@pytest.fixture
def reached(box: Toolbox) -> tuple[Toolbox, str]:
    """raw.amt reaches fct_star.total in 3 hops."""
    return box, fact(box, "raw.amt", "fct_star.total")


# -- the verdict heuristic ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("Yes, it does.", "yes"),
        ("Yes. raw.amt does not reach it directly, but through stg.amount.", "yes"),
        ("No.", "no"),
        ("No, raw.id does not affect fct.total.", "no"),
        ("raw.id does not affect fct.total.", "no"),
        ("raw.id doesn't feed fct.total.", "no"),
        ("There is no lineage path from raw.id to fct.total.", "no"),
        ("raw.amt affects fct_star.total through stg.amount and fct.total.", "yes"),
        ("raw.amt flows into fct.total. It does not reach x_id.", "yes"),  # first sentence only
        ("fct.total is the sum of stg.amount.", None),
        ("", None),
    ],
)
def test_answer_verdict(text, want):
    assert answer_verdict(text) == want


# -- R9 ----------------------------------------------------------------------------------------


def test_negation_passes_and_r8_does_not_demand_a_path(unreached):
    """A correct "No, X does not affect Y" names two UNCONNECTED columns: the r_ fact links them
    for R7/R8, and nothing checks connectivity on answer_text."""
    box, rid = unreached
    a = answer(
        "No, raw.id does not affect fct.total.",
        ("raw.id does not reach fct.total", [rid]),
    )
    r = validate(a, box, "Does raw.id affect fct.total?")
    assert r.passed, r.failures
    assert r.cleaned_answer.claims[0].chunk_ids == [rid]


def test_wrong_verdict_fails_r9_with_the_fact(unreached):
    box, rid = unreached
    agg = eid(box, "stg.amount", "fct.total")
    a = answer("Yes, raw.id affects fct.total.", ("fct.total aggregates stg.amount", [agg]))
    r = validate(a, box, "Does raw.id affect fct.total?")
    [f] = r.failures
    assert (f.rule, f.claim_index, f.item_id) == ("R9", None, rid)
    assert "says yes" in f.message and "raw.id does NOT reach fct.total" in f.message
    assert r.fact is not None and r.fact["fact_id"] == rid


def test_no_verdict_fails_r9(reached):
    box, _ = reached
    a = answer("The column is renamed and then aggregated.")
    assert rules(validate(a, box, "Does raw.amt affect fct_star.total?")) == ["R9"]


def test_yes_passes_when_the_fact_reaches(reached):
    box, rid = reached
    a = answer(
        "Yes: raw.amt reaches fct_star.total in 3 hops.",
        ("raw.amt reaches fct_star.total", [rid]),
    )
    assert validate(a, box).passed


def test_a_claim_citing_the_fact_with_the_opposite_verdict_fails(unreached):
    box, rid = unreached
    a = answer("No.", ("raw.id affects fct.total", [rid]))
    r = validate(a, box)
    assert [(f.rule, f.claim_index) for f in r.failures] == [("R9", 0)]


def test_no_fact_no_r9(box: Toolbox):
    box.call("trace_upstream", {"column_id": "fct.total"})
    ctx = ValidationContext.build(box, "Does raw.id affect fct.total?")
    assert ctx.fact is None
    assert rule_verdict(answer("Yes, definitely."), ctx) == []


# -- r_ in R2 / R3 / R7 / R8 -------------------------------------------------------------------


def test_r2_accepts_and_repairs_r_ids(unreached):
    box, rid = unreached
    a = answer(
        "No, raw.id does not affect fct.total.", ("raw.id does not reach fct.total", [rid[:-1]])
    )
    r = validate(a, box)
    assert r.passed and r.repairs == [{"claim_index": 0, "from": rid[:-1], "to": rid}]


def test_r2_checks_r_ids_written_in_prose(unreached):
    box, _ = unreached
    a = answer("No (r_deadbeef): raw.id does not affect fct.total.")
    assert rules(validate(a, box)) == ["R2"]


def test_r3_reruns_the_graph_check(unreached):
    box, rid = unreached
    box.record(rid)["reaches"] = True  # a forged / stale fact record
    a = answer("No.", ("raw.id does not reach fct.total", [rid]))
    r = validate(a, box)
    assert "R3" in rules(r)
    assert any("no longer holds" in f.message for f in r.failures if f.rule == "R3")


def test_r7_a_fact_does_not_touch_other_columns(unreached):
    box, rid = unreached
    a = answer("No.", ("stg.amount is not related to fct_star.x_id", [rid]))
    assert "R7" in rules(validate(a, box))


def test_r8_a_fact_connects_only_its_own_two_columns(unreached):
    box, rid = unreached
    a = answer("No.", ("raw.id does not reach fct.total or stg.amount", [rid]))
    assert rules(validate(a, box)) == ["R8"]


def test_r8c_a_fact_is_not_an_anchor_for_completion(unreached):
    """With an edge as anchor the same claim would be completed (stg.amount -> fct.total is in
    the ledger); a cited r_ fact alone must not license that bridge."""
    box, rid = unreached
    r = validate(answer("No.", ("raw.id does not reach fct.total or stg.amount", [rid])), box)
    assert r.completions == []
