import json
import re
from pathlib import Path

from dlens.agent.answer import DRAFT_SCHEMA
from dlens.agent.evidence import build_evidence, render_evidence
from dlens.agent.llm.tokens import estimate_tokens
from dlens.agent.llm.types import LLMResponse, Message, ProviderError, QuotaExceeded
from dlens.agent.loop import MAX_LLM_CALLS, MAX_TOOL_PHASE_CALLS, Agent, ask
from dlens.agent.prompts import ANSWER_SYSTEM, PARTIAL_DIRECTIVE, answer_user
from dlens.agent.runlog import RunLogger
from dlens.agent.tools import Toolbox

from .conftest import call, calls, done, draft, make_chain_shop, make_totals_shop

ID = re.compile(r"\b[es]_[0-9a-f]{8}\b")


def answer_request(prov):
    reqs = [r for r in prov.requests if r["schema"] is not None]
    assert reqs, "no answer-phase call was made"
    return reqs[-1]


def first_edge(box: Toolbox) -> str:
    return sorted(i for i in box.emitted_ids if i.startswith("e_"))[0]


# -- call budget ------------------------------------------------------------------------------


def test_step_cap_stops_tool_phase_at_five_calls(box, make_client):
    cols = ["fct.total", "fct.x_id", "stg.amount", "stg.x_id", "fct_star.total"]
    client, prov = make_client([call("trace_upstream", column_id=c) for c in cols] + [draft()])
    run = ask("trace everything", client, box)
    assert [s.phase for s in run.record.steps] == ["tool"] * MAX_TOOL_PHASE_CALLS + ["answer"]
    assert MAX_TOOL_PHASE_CALLS == 5
    assert run.record.stop_reason == "step_cap"
    assert run.record.llm_calls <= MAX_LLM_CALLS
    assert not run.answer.refused


def test_hard_cap_counts_repairs(box, make_client):
    bad = LLMResponse(text="not json")
    script = [call("trace_upstream", column_id="fct.total"), done(), bad, bad]
    client, prov = make_client(script)
    run = ask("where does fct.total come from?", client, box)
    assert run.record.llm_calls == 4 <= MAX_LLM_CALLS
    assert run.answer.refused and "invalid answer JSON" in (run.answer.refusal_reason or "")


# -- dedupe -----------------------------------------------------------------------------------


def test_identical_calls_run_once(box, make_client):
    script = [
        call("trace_upstream", column_id="fct.total"),
        call("trace_upstream", column_id="FCT.TOTAL", max_depth="10"),
        done(),
    ]
    client, prov = make_client(script + [draft("t", [("c", [])])])
    run = ask("where does fct.total come from?", client, box)
    assert len(box.log) == 1
    second = run.record.steps[1].results[0]
    assert second.deduped and second.duplicate_of == 0
    # the duplicate got the earlier result's content back
    tool_msgs = [m for m in prov.requests[2]["messages"] if m.role == "tool"]
    assert tool_msgs[0].content == tool_msgs[1].content


def test_repeated_duplicates_end_the_tool_phase(box, make_client):
    c = call("trace_upstream", column_id="fct.total")
    client, prov = make_client([c, c, c, draft()])
    run = ask("where does fct.total come from?", client, box)
    assert run.record.stop_reason == "repeating"
    assert len([s for s in run.record.steps if s.phase == "tool"]) == 3


# -- token budget -----------------------------------------------------------------------------


def test_compaction_keeps_every_id_and_is_logged(box, make_client):
    script = [
        call("trace_upstream", column_id="fct_star.total"),
        call("impact_downstream", column_id="raw.amt"),
        call("get_model_sql", model_id="fct"),
        call("trace_upstream", column_id="fct_star.x_id"),
        done(),
        draft(),
    ]
    client, prov = make_client(script, cap=1100)
    run = ask("where does fct_star.total come from?", client, box)
    assert run.record.compactions, "the small cap should force compaction"
    assert all(s.est_input_tokens <= 1100 for s in run.record.steps)
    last_tool_req = [r for r in prov.requests if r["tools"]][-1]
    seen = set(ID.findall(" ".join(m.content for m in last_tool_req["messages"])))
    shown_before = set()
    for r in box.log[:-1]:
        shown_before |= set(ID.findall(r.content))
    assert shown_before <= seen


def test_answer_prompt_holds_only_ledger_ids(box, make_client):
    script = [
        calls(
            ("trace_upstream", {"column_id": "fct_star.total"}),
            ("get_model_sql", {"model_id": "fct", "around_column": "total"}),
        ),
        done("e_deadbeef is relevant"),  # an id the model typed itself must not leak
        draft(),
    ]
    client, prov = make_client(script)
    ask("how is fct_star.total computed?", client, box)
    req = answer_request(prov)
    assert req["tools"] is None
    text = " ".join(m.content for m in req["messages"])
    assert set(ID.findall(text)) <= box.emitted_ids
    assert set(ID.findall(text)) == box.emitted_ids
    assert "<evidence>" in req["messages"][1].content


def test_over_budget_answer_prompt_is_trimmed_and_flagged(box, make_client):
    holder = {}

    def shrink_then_done():
        # One token short of the full answer prompt: some evidence must be trimmed.
        items = build_evidence(box)
        user = answer_user("where does fct_star.total come from?", render_evidence(items), [])
        full = estimate_tokens(
            [Message(role="system", content=ANSWER_SYSTEM), Message(role="user", content=user)],
            None,
            DRAFT_SCHEMA,
        )
        holder["client"].max_input_tokens = full - 1
        return done()

    script = [call("trace_upstream", column_id="fct_star.total"), shrink_then_done, draft()]
    client, prov = make_client(script)
    holder["client"] = client
    run = ask("where does fct_star.total come from?", client, box)
    ev = run.record.evidence
    assert ev["partial_evidence"] and ev["dropped_ids"]
    assert run.answer.partial_evidence
    comp = run.record.compactions[-1]
    assert comp["phase"] == "answer" and comp["dropped_ids"] == ev["dropped_ids"]
    req = answer_request(prov)
    assert PARTIAL_DIRECTIVE in req["messages"][1].content
    trace = box.log[0].llm_payload["paths"][0]
    far = trace[-1].split(":", 1)[0]
    near = trace[0].split(":", 1)[0]
    assert far in ev["dropped_ids"] and near in ev["ids"]


# -- repair and refusals ----------------------------------------------------------------------


def test_bad_answer_json_is_repaired_once(box, make_client):
    script = [call("trace_upstream", column_id="fct.total"), done(), LLMResponse(text="{oops")]
    client, prov = make_client(script)
    holder = {"box": box}

    def good():
        return draft("t", [("c", [first_edge(holder["box"])])])

    prov.script.append(good)
    run = ask("where does fct.total come from?", client, box)
    assert not run.answer.refused and run.answer.claims
    repair = prov.requests[-1]["messages"]
    assert repair[-1].role == "user" and "not valid JSON" in repair[-1].content
    assert [s.phase for s in run.record.steps][-2:] == ["answer", "repair"]


def test_fenced_json_is_accepted(box, make_client):
    fenced = LLMResponse(
        text='```json\n{"answer_text":"t","claims":[],"confidence":"low","refused":false}\n```'
    )
    client, _ = make_client([call("trace_upstream", column_id="fct.total"), done(), fenced])
    assert not ask("q fct.total", client, box).answer.refused


def test_tool_call_written_as_text_is_repaired_then_refused(box, make_client):
    text = LLMResponse(text='<tool_call>{"name": "trace_upstream", "arguments": {}}</tool_call>')
    client, prov = make_client([text, text])
    run = ask("where does fct.total come from?", client, box)
    assert run.answer.refused and "malformed tool call" in (run.answer.refusal_reason or "")
    assert "malformed" in prov.requests[1]["messages"][-1].content

    box.reset()
    client, prov = make_client(
        [text, call("trace_upstream", column_id="fct.total"), done(), draft()]
    )
    run = ask("where does fct.total come from?", client, box)
    assert not run.answer.refused
    assert [s.phase for s in run.record.steps][:2] == ["tool", "repair"]


def test_ollama_tool_parse_error_gets_one_repair(box, make_client):
    err = ProviderError("ollama call failed: error parsing tool call: bad", status_code=500)
    client, prov = make_client([err, err])
    run = ask("where does fct.total come from?", client, box)
    assert run.answer.refused and "malformed tool call" in (run.answer.refusal_reason or "")


def test_tool_errors_go_back_to_the_model_and_no_evidence_refuses(box, make_client):
    client, prov = make_client([call("trace_upstream", column_id="fct.discount_pct"), done()])
    run = ask("where does fct.discount_pct come from?", client, box)
    tool_msg = prov.requests[1]["messages"][-1]
    assert tool_msg.role == "tool" and "unknown_column" in tool_msg.content
    assert run.answer.refused and "unknown_column" in (run.answer.refusal_reason or "")
    assert all(r["schema"] is None for r in prov.requests)  # no answer call


def test_provider_errors_become_refusals(box, make_client):
    client, _ = make_client([ProviderError("bad request", status_code=400)])
    run = ask("q", client, box)
    assert run.answer.refused and "bad request" in (run.answer.refusal_reason or "")

    flaky = ProviderError("busy", status_code=503, retryable=True)
    client, prov = make_client(
        [flaky, call("trace_upstream", column_id="fct.total"), done(), draft()]
    )
    run = ask("where does fct.total come from?", client, box)
    assert not run.answer.refused
    assert run.record.steps[0].error and run.record.steps[1].error is None

    client, _ = make_client([QuotaExceeded("gemini: daily budget used up")])
    assert "QuotaExceeded" in (ask("q", client, box).answer.refusal_reason or "")


# -- ambiguity policy -------------------------------------------------------------------------


def test_chain_mode_traces_the_downstream_candidate(shop_root, make_client):
    box = Toolbox(make_chain_shop(), shop_root)
    client, prov = make_client([call("resolve_entity", text="refund amt"), done(), draft()])
    run = ask("Where does refund amt come from?", client, box)
    amb = run.record.ambiguity
    assert amb["mode"] == "chain" and len(amb["candidates"]) == 4
    assert amb["downstream"] == "r_hist.refund_amount"
    assert run.answer.clarification is None
    code = [s for s in run.record.steps if s.phase == "code"]
    assert len(code) == 1 and code[0].results[0].args == {"column_id": "r_hist.refund_amount"}
    assert run.record.llm_calls == 3  # the code call is not an LLM call
    assert any(r.tool == "trace_upstream" for r in box.log) and box.emitted_ids
    prompt = answer_request(prov)["messages"][1].content
    assert "same column at different layers" in prompt and "r_hist.refund_amount" in prompt


def test_chain_mode_reuses_an_existing_trace(shop_root, make_client):
    box = Toolbox(make_chain_shop(), shop_root)
    script = [
        call("resolve_entity", text="refund amt"),
        call("trace_upstream", column_id="r_hist.refund_amount"),
        done(),
        draft(),
    ]
    client, _ = make_client(script)
    run = ask("Where does refund amt come from?", client, box)
    assert run.record.ambiguity["mode"] == "chain"
    assert not [s for s in run.record.steps if s.phase == "code"]


def test_three_ties_on_one_chain_also_take_chain_mode(box, make_client):
    client, _ = make_client([call("resolve_entity", text="x_id"), done(), draft()])
    run = ask("where does x_id come from?", client, box)
    assert run.record.ambiguity["mode"] == "chain"
    assert run.record.ambiguity["downstream"] == "fct_star.x_id"


def test_unrelated_ties_up_to_three_answer_per_candidate(shop_root, make_client):
    box = Toolbox(make_totals_shop(1), shop_root)
    script = [
        call("resolve_entity", text="total"),
        call("trace_upstream", column_id="fct.total"),
        done(),
        draft(),
    ]
    client, prov = make_client(script)
    run = ask("where does total come from?", client, box)
    assert run.record.ambiguity["mode"] == "per_candidate"
    assert "answer separately for each of" in answer_request(prov)["messages"][1].content


def test_more_than_three_unrelated_ties_ask_for_clarification(shop_root, make_client):
    box = Toolbox(make_totals_shop(2), shop_root)
    client, prov = make_client([call("resolve_entity", text="total"), done()])  # no answer call
    run = ask("where does total come from?", client, box)
    clar = run.answer.clarification
    assert clar is not None and len(clar.candidates) == 4 and not run.answer.refused
    assert all(r["schema"] is None for r in prov.requests)
    assert run.record.clarification == clar.model_dump()


def test_question_naming_one_candidate_is_not_ambiguous(box, make_client):
    script = [
        call("resolve_entity", text="x_id"),
        call("trace_upstream", column_id="stg.x_id"),
        done(),
        draft(),
    ]
    client, _ = make_client(script)
    run = ask("where does stg.x_id come from?", client, box)
    assert run.record.ambiguity is None


# -- citations and the run record -------------------------------------------------------------


def test_citations_come_from_the_ledger(box, make_client):
    client, prov = make_client([call("trace_upstream", column_id="fct.total"), done()])
    holder = {"box": box}
    prov.script.append(lambda: draft("t", [("c", [first_edge(holder["box"]), "e_deadbeef"])]))
    run = ask("where does fct.total come from?", client, box)
    e = first_edge(box)
    assert run.answer.citations[e].model_dump() == box.record(e)["citation"]
    assert "e_deadbeef" not in run.answer.citations
    v = run.record.validation
    assert v["passed"] is False and v["counts"] == {"R2": 1}  # e_deadbeef was never emitted


def test_jsonl_record_shape(box, make_client, tmp_path: Path):
    logger = RunLogger(tmp_path / "runs")
    client, _ = make_client([call("trace_upstream", column_id="fct.total"), done(), draft()])
    run = Agent(client, box, logger, project="shop").ask("where does fct.total come from?")
    lines = run.log_path.read_text().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    for key in (
        "schema_version",
        "run_id",
        "question",
        "provider",
        "model",
        "params",
        "steps",
        "compactions",
        "evidence",
        "draft_raw",
        "draft",
        "validation",
        "final_answer",
        "stop_reason",
        "timings",
        "tokens",
    ):
        assert key in rec, key
    step = rec["steps"][0]
    assert {"tool", "args", "llm_payload", "side_records"} <= set(step["results"][0])
    assert rec["draft_raw"] and rec["tokens"]["llm_calls"] == 3
    assert {"tool_ms", "answer_ms", "total_ms"} <= set(rec["timings"])

    client, _ = make_client([ProviderError("boom", status_code=400)])
    Agent(client, box, logger).ask("q")
    lines = run.log_path.read_text().splitlines()
    assert len(lines) == 2 and json.loads(lines[1])["final_answer"]["refused"]
