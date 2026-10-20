"""s12-design A1: the model's ``clarification_candidates`` count only when code made no linking
decision (no ambiguity policy, no exact column in the question, no resolve_entity candidates) and
every candidate is an exact graph column."""

from dlens.agent.loop import ask
from dlens.agent.tools import Toolbox

from .conftest import call, done, draft, make_chain_shop

CANDS = ["fct.total", "fct_star.total"]


def test_all_real_candidates_without_a_code_link_become_a_clarification(box, make_client):
    client, _ = make_client(
        [
            call("trace_upstream", column_id="fct.total"),
            done(),
            draft(clarification_candidates=CANDS),
        ]
    )
    run = ask("Where does the total come from?", client, box)
    clar = run.answer.clarification
    assert clar is not None and clar.candidates == CANDS
    assert run.answer.claims == [] and run.record.clarification == clar.model_dump()
    assert run.record.stop_reason.endswith("+llm_clarification")
    assert run.record.validation is None  # a clarification is not validated


def test_code_ambiguity_decision_wins(shop_root, make_client):
    box = Toolbox(make_chain_shop(), shop_root)
    cands = ["r_stg.refund_amt", "r_int.refund_amount"]
    client, _ = make_client(
        [
            call("resolve_entity", text="refunds amount"),
            done(),
            draft(clarification_candidates=cands),
        ]
    )
    run = ask("Where does refunds amount come from?", client, box)
    assert run.record.ambiguity is not None and run.record.ambiguity["mode"] == "chain"
    assert run.answer.clarification is None
    assert run.record.stop_reason.endswith("+candidates_ignored")


def test_a_unique_exact_target_wins(box, make_client):
    client, _ = make_client(
        [
            call("trace_upstream", column_id="fct.total"),
            done(),
            draft(clarification_candidates=CANDS),
        ]
    )
    run = ask("Where does fct.total come from?", client, box)
    assert run.answer.clarification is None and not run.answer.refused
    assert run.record.stop_reason.endswith("+candidates_ignored")
    assert run.record.draft is not None and run.record.draft["clarification_candidates"] == CANDS


def test_an_unknown_candidate_is_ignored(box, make_client):
    client, _ = make_client(
        [
            call("trace_upstream", column_id="fct.total"),
            done(),
            draft(clarification_candidates=["fct.total", "nope.col"]),
        ]
    )
    run = ask("Where does the total come from?", client, box)
    assert run.answer.clarification is None
    assert run.record.stop_reason.endswith("+candidates_ignored")
