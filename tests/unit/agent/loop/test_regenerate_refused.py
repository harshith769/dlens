"""A refused regenerate after a non-refused first draft goes to salvage (S13b F3,
post-pilot-fixes.md). Only the routing in ``Agent._validate`` changed: salvage is unchanged, so
the kept claims are the first draft's passing ones, and a verdict is code's only when salvage
ran after an R9 failure on an ``r_`` fact. The dev case is dev-75 from the committed qwen pilot
record, replayed without a model: the first draft is validated, the regenerate returns the
recorded refusal."""

from __future__ import annotations

from dlens.agent.llm.types import LLMResponse
from dlens.agent.loop import Agent, ask
from dlens.agent.runlog import RunRecord
from dlens.agent.tools import Toolbox
from dlens.agent.validator import validate

from .. import pilot_records as P
from ..validator.conftest import eid
from .conftest import call, done, draft

Q = "where does fct.total come from?"


def test_dev75_refused_regenerate_is_salvaged_from_the_first_draft(make_client) -> None:
    rec = P.record("dev-75")
    led = P.ledger(rec)
    first = P.first_answer(rec, led)
    assert not first.refused and not validate(first, led, rec["question"]).passed
    client, prov = make_client([LLMResponse(text=P.regenerate_text(rec))])
    agent = Agent(client, Toolbox(P.graph(), P.SS_PROJECT))
    agent.toolbox = led  # type: ignore[assignment]  # the recorded ledger (Ledger protocol)
    agent.record = RunRecord(run_id="t", started_at="t", question=rec["question"])
    out = agent._validate(rec["question"], [], first, partial=False)

    assert len(prov.requests) == 1  # the regenerate was sent once, and it refused
    v = agent.record.validation
    assert v["regenerated"] and v["second"] is not None and v["warning"] and not v["passed"]
    assert v["dropped_claims"] == [0]  # the first draft's R8 failure
    assert "+regenerate_refused" in agent.record.stop_reason
    assert not out.refused and out.validation_warning
    kept = [c.text for c in out.claims]
    assert kept == [c["text"] for c in rec["draft"]["claims"][1:]]  # its two passing claims
    assert all(c.origin == "model" for c in out.claims)
    # no r_ fact on dev-75: unchanged salvage keeps the model's own field; code sets nothing
    assert (out.reach_verdict, out.reach_verdict_source) == ("no", "llm")


def test_raw_draft_stays_the_first_draft(box: Toolbox, make_client) -> None:
    def first():
        agg = eid(box, "stg.amount", "fct.total")
        return draft(
            "fct.total sums stg.amount.",
            [
                ("fct.total aggregates stg.amount", [agg]),
                ("fct.total comes from raw.amt", ["e_deadbeef"]),
            ],
        )

    refusal = draft("I cannot say.", [], refused=True, refusal_reason="unsure")
    client, _ = make_client([call("trace_upstream", column_id="fct.total"), done(), first, refusal])
    run = ask(Q, client, box)
    assert run.record.draft is not None and not run.record.draft["refused"]  # raw view
    assert '"refused": true' in (run.record.regenerate_draft_raw or "")
    assert not run.answer.refused and [c.text for c in run.answer.claims] == [
        "fct.total aggregates stg.amount"
    ]
    assert run.answer.validation_warning


def test_refused_regenerate_with_no_passing_first_claim_stays_a_refusal(
    box: Toolbox, make_client
) -> None:
    bad = draft("fct.total comes from raw.amt.", [("fct.total comes from raw.amt", ["e_deadbeef"])])
    refusal = draft("I cannot say.", [], refused=True, refusal_reason="unsure")
    client, _ = make_client([call("trace_upstream", column_id="fct.total"), done(), bad, refusal])
    run = ask(Q, client, box)
    assert run.answer.refused and "no verifiable claims" in (run.answer.refusal_reason or "")


def test_r9_failure_then_refused_regenerate_gets_code_verdict(box: Toolbox, make_client) -> None:
    """The verdict source is ``code`` only from a reachability fact after an R9 failure."""
    q = "Does raw.id affect fct.total?"  # code makes an r_ fact: raw.id does NOT reach fct.total
    wrong = draft("Yes, raw.id affects fct.total.", [], reach_verdict="yes")
    refusal = draft("I cannot say.", [], refused=True, refusal_reason="unsure")
    client, _ = make_client([call("trace_upstream", column_id="fct.total"), done(), wrong, refusal])
    run = ask(q, client, box)
    assert not run.answer.refused
    assert (run.answer.reach_verdict, run.answer.reach_verdict_source) == ("no", "code")
    assert run.answer.claims[0].origin == "verdict"


def test_first_draft_refusal_is_unchanged(box: Toolbox, make_client) -> None:
    refusal = draft("The evidence does not say.", [], refused=True, refusal_reason="no path")
    client, prov = make_client([call("trace_upstream", column_id="fct.total"), done(), refusal])
    run = ask(Q, client, box)
    assert run.answer.refused and run.record.validation["skipped"]
    assert [s.phase for s in run.record.steps].count("regenerate") == 0


def test_regenerate_that_passes_is_unchanged(box: Toolbox, make_client) -> None:
    def make(*extra):
        def build():
            agg = eid(box, "stg.amount", "fct.total")
            return draft(
                "fct.total sums stg.amount.", [("fct.total aggregates stg.amount", [agg]), *extra]
            )

        return build

    script = [
        call("trace_upstream", column_id="fct.total"),
        done(),
        make(("fct.total comes from raw.amt", ["e_deadbeef"])),
        make(),
    ]
    client, _ = make_client(script)
    run = ask(Q, client, box)
    v = run.record.validation
    assert v["regenerated"] and v["passed"] and not v["warning"]
    assert "+regenerate_refused" not in run.record.stop_reason
