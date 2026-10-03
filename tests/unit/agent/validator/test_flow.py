"""The loop's validate -> regenerate once -> salvage flow, with a scripted provider."""

from dlens.agent.llm.types import LLMResponse, ProviderError
from dlens.agent.loop import MAX_LLM_CALLS, ask
from dlens.agent.tools import Toolbox

from ..loop.conftest import call, done, draft
from .conftest import eid

Q = "where does fct.total come from?"
GOOD = ("fct.total aggregates stg.amount", None)  # id filled in at send time
FAKE = ("fct.total is also renamed from raw.amt", ["e_deadbeef"])


def scripted(box: Toolbox, *claims, text: str = "fct.total sums stg.amount."):
    """A draft built when the provider is called (ids exist only after the tool ran)."""

    def make():
        agg = eid(box, "stg.amount", "fct.total")
        return draft(text, [(t, ids if ids is not None else [agg]) for t, ids in claims])

    return make


def phases(run) -> list[str]:
    return [s.phase for s in run.record.steps]


def test_first_fails_second_passes_is_regenerated(box, make_client):
    script = [
        call("trace_upstream", column_id="fct.total"),
        done(),
        scripted(box, GOOD, FAKE),
        scripted(box, GOOD),
    ]
    client, prov = make_client(script)
    run = ask(Q, client, box)
    v = run.record.validation
    assert v["regenerated"] and v["passed"] and not v["warning"]
    assert v["first"]["counts"]["R2"] == 1 and v["second"]["passed"]
    assert phases(run)[-1] == "regenerate"
    assert len(run.answer.claims) == 1 and not run.answer.validation_warning
    regen_prompt = prov.requests[-1]["messages"][-1].content
    assert "R2 e_deadbeef" in regen_prompt and "failed these checks" in regen_prompt
    assert "e_deadbeef" in run.record.draft_raw  # the pre-validation draft is kept untouched
    assert run.record.regenerate_draft_raw and "e_deadbeef" not in run.record.regenerate_draft_raw


def test_both_fail_keeps_passing_claims_with_a_warning(box, make_client):
    bad_text = "fct.discount_pct feeds fct.total."  # R4.hallucinated on the answer_text
    script = [
        call("trace_upstream", column_id="fct.total"),
        done(),
        scripted(box, GOOD, FAKE, text=bad_text),
        scripted(box, GOOD, FAKE, text=bad_text),
    ]
    client, _ = make_client(script)
    run = ask(Q, client, box)
    v = run.record.validation
    assert v["regenerated"] and v["warning"] and not v["passed"]
    assert v["dropped_claims"] == [1]
    a = run.answer
    assert a.validation_warning and [c.text for c in a.claims] == [GOOD[0]]
    assert a.answer_text == GOOD[0]  # rebuilt: the answer_text itself failed R4
    assert "e_deadbeef" not in a.citations


def test_all_claims_failing_is_refused(box, make_client):
    script = [
        call("trace_upstream", column_id="fct.total"),
        done(),
        scripted(box, FAKE),
        scripted(box, FAKE),
    ]
    client, _ = make_client(script)
    run = ask(Q, client, box)
    assert run.answer.refused and "no verifiable claims" in run.answer.refusal_reason
    assert run.record.validation["warning"]


def test_invalid_json_on_regenerate_salvages_the_first_draft(box, make_client):
    script = [
        call("trace_upstream", column_id="fct.total"),
        done(),
        scripted(box, GOOD, FAKE),
        LLMResponse(text="{nope"),
    ]
    client, _ = make_client(script)
    run = ask(Q, client, box)
    assert run.answer.validation_warning and len(run.answer.claims) == 1
    assert run.record.validation["second"] is None


COLS = ["fct.total", "fct.x_id", "stg.amount", "stg.x_id", "fct_star.total"]


def test_regenerate_is_the_eighth_call(box, make_client):
    script = [call("trace_upstream", column_id=c) for c in COLS]
    script += [LLMResponse(text="not json"), scripted(box, GOOD, FAKE), scripted(box, GOOD)]
    client, _ = make_client(script)
    run = ask(Q, client, box)
    assert phases(run)[-3:] == ["answer", "repair", "regenerate"]
    assert run.record.llm_calls == MAX_LLM_CALLS == 8
    assert run.record.validation["passed"]


def test_no_regenerate_when_the_budget_is_spent(box, make_client):
    busy = ProviderError("busy", status_code=503, retryable=True)
    script = [call("trace_upstream", column_id=c) for c in COLS]
    script += [busy, LLMResponse(text="not json"), scripted(box, GOOD, FAKE)]
    client, prov = make_client(script)
    run = ask(Q, client, box)
    assert run.record.llm_calls == 8 and "regenerate" not in phases(run)
    assert not prov.script  # nothing was asked beyond the cap
    v = run.record.validation
    assert not v["regenerated"] and v["warning"] and run.answer.validation_warning


def test_no_tool_calls_falls_back_to_a_code_trace_of_the_named_column(box, make_client):
    client, prov = make_client([done("I need a column id."), scripted(box, GOOD)])
    run = ask("Why is fct.total aggregated directly from raw.amt?", client, box)
    code = [s for s in run.record.steps if s.phase == "code"]
    assert len(code) == 1 and code[0].results[0].args == {"column_id": "fct.total"}
    assert run.record.llm_calls == 2  # the code trace is not an LLM call
    assert "fallback_trace" in run.record.stop_reason
    assert not run.answer.refused and run.record.validation["passed"]


def test_fallback_needs_an_exact_existing_column(box, make_client):
    for q in ("Why is fct.discount_pct so high?", "Where does revenue come from?"):
        box.reset()
        client, prov = make_client([done("no idea")])
        run = ask(q, client, box)
        assert not [s for s in run.record.steps if s.phase == "code"]
        assert run.answer.refused and "no lineage evidence" in run.answer.refusal_reason
