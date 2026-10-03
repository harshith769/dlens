"""R8c citation completion: what it adds, what it refuses to add, and that rules re-check it.

The hand-built shop's chain is raw.amt -RENAME-> stg.amount -AGGREGATION-> fct.total
-IDENTITY-> fct_star.total.
"""

from pathlib import Path

import pytest

from dlens.agent import validator as v
from dlens.agent.tools import Toolbox
from dlens.agent.validator import validate

from .conftest import answer, eid

Q = "Where does fct_star.total come from?"


def rules(result) -> list[str]:
    return sorted(f.rule for f in result.failures)


def test_skipped_hop_is_completed_and_reported(traced: Toolbox):
    last = eid(traced, "fct.total", "fct_star.total")
    agg = eid(traced, "stg.amount", "fct.total")
    r = validate(answer("t", ("fct_star.total comes from stg.amount", [last])), traced, Q)
    assert r.passed and not r.repairs
    assert r.completions == [{"claim_index": 0, "added": [agg]}]
    claim = r.cleaned_answer.claims[0]
    assert claim.edge_ids == [last, agg]  # the model's ids first, completed ones after
    assert agg in r.cleaned_answer.citations and agg in r.cleaned_answer.subgraph


def test_a_two_hop_bridge(traced: Toolbox):
    last = eid(traced, "fct.total", "fct_star.total")
    ren, agg = eid(traced, "raw.amt", "stg.amount"), eid(traced, "stg.amount", "fct.total")
    r = validate(answer("t", ("fct_star.total traces back to raw.amt", [last])), traced, Q)
    assert r.passed and r.completions == [{"claim_index": 0, "added": [ren, agg]}]


def test_the_input_answer_is_not_modified(traced: Toolbox):
    last = eid(traced, "fct.total", "fct_star.total")
    a = answer("t", ("fct_star.total comes from stg.amount", [last]))
    validate(a, traced, Q)
    assert a.claims[0].edge_ids == [last]  # the raw draft stays untouched for the ablation


def test_directly_over_more_than_one_hop_is_not_completed(traced: Toolbox):
    last = eid(traced, "fct.total", "fct_star.total")
    for text in (
        "fct_star.total comes directly from raw.amt",  # the false-premise shape
        "fct_star.total is a direct copy of stg.amount",  # bridge stg.amount -> fct_star = 2 hops
        "fct_star.total does not come directly from stg.amount",  # negation is not parsed
    ):
        r = validate(answer("t", (text, [last])), traced, Q)
        assert rules(r) == ["R8"] and not r.completions, text


def test_directly_with_a_one_hop_bridge_is_completed(traced: Toolbox):
    last = eid(traced, "fct.total", "fct_star.total")
    agg = eid(traced, "stg.amount", "fct.total")
    text = "fct.total is computed directly from stg.amount and feeds fct_star.total"
    r = validate(answer("t", (text, [last])), traced, Q)
    assert r.passed and r.completions == [{"claim_index": 0, "added": [agg]}]


def test_indirectly_is_not_the_direct_guard(traced: Toolbox):
    last = eid(traced, "fct.total", "fct_star.total")
    r = validate(answer("t", ("fct_star.total depends indirectly on raw.amt", [last])), traced, Q)
    assert r.passed and len(r.completions[0]["added"]) == 2


def test_completed_edges_are_rechecked_by_r5(traced: Toolbox):
    # "renamed" with the IDENTITY edge cited; completion adds AGGREGATION: still no RENAME.
    last = eid(traced, "fct.total", "fct_star.total")
    r = validate(answer("t", ("fct_star.total is renamed from stg.amount", [last])), traced, Q)
    assert "R5" in rules(r) and not r.passed
    assert r.completions  # recorded even though the claim is then dropped by R5


def test_completed_edges_are_rechecked_by_r3(traced: Toolbox):
    last = eid(traced, "fct.total", "fct_star.total")
    agg = eid(traced, "stg.amount", "fct.total")
    rec = traced.record(agg)
    rec["citation"]["line_start"] += 500
    rec["citation"]["line_end"] += 500
    r = validate(answer("t", ("fct_star.total comes from stg.amount", [last])), traced, Q)
    assert rules(r) == ["R3"] and r.completions


def test_no_anchor_no_completion(traced: Toolbox):
    # The claim's only citation touches none of its columns: completion would launder it.
    unrelated = eid(traced, "raw.id", "stg.x_id")
    r = validate(answer("t", ("fct.total comes from stg.amount", [unrelated])), traced, Q)
    assert {"R7", "R8"} <= set(rules(r)) and not r.completions


def test_siblings_sharing_a_descendant_are_not_connected(shop_root: Path):
    from dlens.lineage import Edge, EdgeKind

    from ..loop.conftest import P, _extend
    from ..tools.conftest import make_shop

    extra = Edge(
        from_column=f"{P}.stg.x_id",
        to_column=f"{P}.fct.total",
        kind=EdgeKind.TRANSFORMATION,
        expression="sum(amount) + x_id",
        file="models/fct.sql",
        lines=(3, 3),
    )
    box = Toolbox(_extend(make_shop(), {}, {}, [extra]), shop_root)
    box.call("trace_upstream", {"column_id": "fct.total"})
    a_in, b_in = eid(box, "stg.amount", "fct.total"), eid(box, "stg.x_id", "fct.total")
    # false: neither feeds the other; only an undirected path through fct.total exists
    r = validate(answer("t", ("stg.amount comes from stg.x_id", [a_in])), box)
    assert rules(r) == ["R8"] and not r.completions
    # true: "both feed fct.total" is completed with the second input edge
    r = validate(answer("t", ("stg.amount and stg.x_id both feed fct.total", [a_in])), box)
    assert r.passed and r.completions == [{"claim_index": 0, "added": [b_in]}]


def test_hop_cap(traced: Toolbox, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(v, "MAX_COMPLETION_HOPS", 1)
    last = eid(traced, "fct.total", "fct_star.total")
    r = validate(answer("t", ("fct_star.total traces back to raw.amt", [last])), traced, Q)
    assert rules(r) == ["R8"] and not r.completions


def test_only_ledger_edges_are_used(box: Toolbox):
    # fct_star was never traced: the fct.total -> fct_star.total edge is not in the ledger.
    box.call("trace_upstream", {"column_id": "fct.total"})
    agg = eid(box, "stg.amount", "fct.total")
    q = "Where does fct_star.total come from?"  # names fct_star.total, so R4 does not fire
    r = validate(answer("t", ("fct_star.total comes from stg.amount", [agg])), box, q)
    assert rules(r) == ["R8"] and not r.completions


def test_passing_claims_get_no_completion(traced: Toolbox):
    last = eid(traced, "fct.total", "fct_star.total")
    agg = eid(traced, "stg.amount", "fct.total")
    r = validate(answer("t", ("fct_star.total comes from stg.amount", [agg, last])), traced, Q)
    assert r.passed and r.completions == []
