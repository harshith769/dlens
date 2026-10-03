"""Property: a mutated valid answer never passes, unless the mutation is a uniquely repairable
single-character id change (the repair is reported) or a dropped middle edge of a chain claim
that R8c completes from the ledger (the completion is reported)."""

import copy
import re

from hypothesis import HealthCheck, assume, event, given, settings
from hypothesis import strategies as st

from dlens.agent.answer import Answer
from dlens.agent.tools import Toolbox
from dlens.agent.validator import ValidationContext, validate

from .conftest import answer, eid

Q = "Where does fct_star.total come from?"
HEX = "0123456789abcdef"
MUTATIONS = [
    "drop_middle_edge",
    "drop_middle_edge_direct",
    "swap_char",
    "fake_identifier",
    "shift_prose_line",
    "citation_past_eof",
    "unrelated",
]
CHAIN = 3  # index of the multi-edge chain claim in valid_answer


def valid_answer(box: Toolbox) -> Answer:
    agg = eid(box, "stg.amount", "fct.total")
    ren = eid(box, "raw.amt", "stg.amount")
    star = eid(box, "fct.total", "fct_star.total")
    sid = next(i for i in box.emitted_ids if i.startswith("s_"))
    return answer(
        "fct_star.total passes fct.total through; fct.total aggregates stg.amount on line 3.",
        ("fct_star.total is the same value as fct.total", [star]),
        ("fct.total aggregates stg.amount on line 3", [agg, sid]),
        ("stg.amount renames raw.amt", [ren]),
        ("fct_star.total traces back to raw.amt through stg.amount", [ren, agg, star]),
    )


def _cited_ranges(box: Toolbox, a: Answer, k: int | None) -> list[tuple[int, int]]:
    """Line ranges of the ledger citations in scope (whole answer, or claim ``k``)."""
    ids = [i for c in a.claims for i in c.ids] if k is None else a.claims[k].ids
    cites = [(box.record(i) or {}).get("citation") for i in ids]
    return [(c["line_start"], c["line_end"]) for c in cites if c and c["level"] != "model"]


@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(data=st.data())
def test_mutated_answers_never_pass_unless_uniquely_repaired(traced: Toolbox, data):
    base = valid_answer(traced)
    assert validate(base, traced, Q).passed  # the fixture itself is clean
    a = copy.deepcopy(base)
    kind = data.draw(st.sampled_from(MUTATIONS), label="mutation")
    expected_repair = None
    expected_completion = None
    restore = None

    if kind == "swap_char":
        k = data.draw(st.integers(0, len(a.claims) - 1))
        ids = a.claims[k].ids
        j = data.draw(st.integers(0, len(ids) - 1))
        orig = ids[j]
        pos = data.draw(st.integers(2, len(orig) - 1))
        ch = data.draw(st.sampled_from([c for c in HEX if c != orig[pos]]))
        mutated = orig[:pos] + ch + orig[pos + 1 :]
        assume(mutated not in traced.emitted_ids)  # a collision would be a different real id
        field = "edge_ids" if orig.startswith("e_") else "chunk_ids"
        lst = getattr(a.claims[k], field)
        lst[lst.index(orig)] = mutated
        expected_repair = {"claim_index": k, "from": mutated, "to": orig}

    elif kind == "fake_identifier":
        name = data.draw(st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=3, max_size=10))
        col = f"fct.{name}_x"
        assume(not traced.graph.has_column(f"model.p.fct.{name}_x"))
        where = data.draw(st.integers(-1, len(a.claims) - 1))
        if where < 0:
            a.answer_text += f" It also feeds {col}."
        else:
            a.claims[where].text += f" and {col}"

    elif kind == "shift_prose_line":
        where = data.draw(st.sampled_from([None, 1]))
        n = data.draw(st.integers(1, 500))
        assume(not any(lo <= n <= hi for lo, hi in _cited_ranges(traced, a, where)))
        if where is None:
            a.answer_text = a.answer_text.replace("line 3", f"line {n}")
        else:
            a.claims[1].text = a.claims[1].text.replace("line 3", f"line {n}")

    elif kind == "citation_past_eof":
        cited = [i for c in a.claims for i in c.ids]
        i = data.draw(st.sampled_from(cited))
        rec = traced.record(i)
        saved = copy.deepcopy(rec["citation"])
        shift = data.draw(st.integers(10, 10_000))
        rec["citation"]["line_start"] += shift
        rec["citation"]["line_end"] += shift

        def restore() -> None:
            rec["citation"] = saved

    elif kind == "drop_middle_edge":  # break the chain raw.amt -> stg.amount -> fct.total -> ...
        dropped = a.claims[CHAIN].edge_ids.pop(1)
        expected_completion = {"claim_index": CHAIN, "added": [dropped]}

    elif kind == "drop_middle_edge_direct":  # same, but the claim now says "directly"
        a.claims[CHAIN].edge_ids.pop(1)
        a.claims[CHAIN].text = "fct_star.total comes directly from raw.amt through stg.amount"

    else:  # unrelated: a real emitted id that touches none of the claim's entities
        ctx = ValidationContext.build(traced, Q)
        k = data.draw(st.integers(0, len(a.claims) - 1))
        named = [e for e in ctx.entities(a.claims[k].text) if ctx.in_graph(e)]
        pool = sorted(
            i
            for i in traced.emitted_ids
            if i.startswith("e_") and not any(ctx.touches(i, e) for e in named)
        )
        assume(named and pool)
        new = data.draw(st.sampled_from(pool))
        a.claims[k].edge_ids = [new]
        a.claims[k].chunk_ids = []

    try:
        r = validate(a, traced, Q)
    finally:
        if restore:
            restore()
    event(f"{kind}: {'passed (repaired/completed)' if r.passed else 'rejected'}")
    if r.passed:
        assert kind in ("swap_char", "drop_middle_edge"), (kind, a)
        if kind == "swap_char":
            assert expected_repair in r.repairs and not r.completions
        else:
            assert r.completions == [expected_completion] and not r.repairs
    if kind == "drop_middle_edge":
        assert r.passed  # the ledger has the edge: completion always applies here
    if kind == "drop_middle_edge_direct":
        assert "R8" in r.counts and not r.completions
    if kind == "fake_identifier":
        assert "R4.hallucinated" in r.counts
    if kind == "shift_prose_line":
        assert "R6" in r.counts
    if kind == "citation_past_eof":
        assert "R3" in r.counts
    if kind == "unrelated":
        assert "R7" in r.counts
    assert re.fullmatch(r"[es]_[0-9a-f]{8}", r.repairs[0]["to"]) if r.repairs else True
