"""Rule linked_evidence (owner, 17 Oct 2026): code traces / impacts the one column resolve_entity
linked when the model didn't, for where-from / how-computed / impact questions only."""

from dlens.agent.loop import ask
from dlens.agent.tools import Toolbox

from .conftest import call, calls, done, draft


def code_steps(run):
    return [r for s in run.record.steps if s.phase == "code" for r in s.results]


def test_fires_when_the_model_stops_after_linking(box: Toolbox, make_client) -> None:
    """dev-14 shape: resolve_entity, then the model stops."""
    client, _ = make_client([call("resolve_entity", text="stg.amount"), done(), draft()])
    run = ask("Where does the stg amount come from?", client, box)
    [r] = code_steps(run)
    assert (r.tool, r.args, r.code_initiated, r.rule) == (
        "trace_upstream",
        {"column_id": "stg.amount"},
        True,
        "linked_evidence",
    )
    ledger = [x for x in box.log if x.code_initiated]
    assert [(x.tool, x.rule) for x in ledger] == [("trace_upstream", "linked_evidence")]
    assert run.record.llm_calls == 3  # 2 tool-phase + 1 answer: the code step is not an LLM call
    assert "+linked_evidence" in run.record.stop_reason
    assert box.emitted_ids  # the answer phase sees its edges like any tool result


def test_fires_when_the_model_only_read_sql(box: Toolbox, make_client) -> None:
    """dev-13 shape: resolve_entity + get_model_sql (citable excerpt) but no trace."""
    script = [
        calls(("resolve_entity", {"text": "fct.total"}), ("get_model_sql", {"model_id": "fct"})),
        done(),
        draft(),
    ]
    client, _ = make_client(script)
    run = ask("How is the fct total computed?", client, box)
    assert [(r.tool, r.rule) for r in code_steps(run)] == [("trace_upstream", "linked_evidence")]


def test_impact_wording_runs_impact(box: Toolbox, make_client) -> None:
    client, _ = make_client([call("resolve_entity", text="stg.amount"), done(), draft()])
    run = ask("What is affected if the stg amount changes?", client, box)
    assert [r.tool for r in code_steps(run)] == ["impact_downstream"]


def test_never_for_an_ambiguous_link(box: Toolbox, make_client) -> None:
    client, _ = make_client([call("resolve_entity", text="x_id"), done(), draft()])
    run = ask("Where does x id come from?", client, box)
    assert not [r for r in code_steps(run) if r.rule == "linked_evidence"]


def test_never_without_a_linked_column(box: Toolbox, make_client) -> None:
    client, _ = make_client([call("resolve_entity", text="zzzzqqqq"), done(), draft()])
    run = ask("Where does zzzzqqqq come from?", client, box)
    assert code_steps(run) == []
    client, _ = make_client([done(), draft()])
    assert code_steps(ask("Where does the total come from?", client, box)) == []


def test_never_for_meaning_questions(box: Toolbox, make_client) -> None:
    client, _ = make_client([call("resolve_entity", text="stg.amount"), done(), draft()])
    run = ask("What does the stg amount mean?", client, box)
    assert code_steps(run) == []


def test_not_when_the_column_was_already_traced(box: Toolbox, make_client) -> None:
    script = [
        calls(
            ("resolve_entity", {"text": "stg.amount"}),
            ("impact_downstream", {"column_id": "stg.amount"}),
        ),
        done(),
        draft(),
    ]
    client, _ = make_client(script)
    run = ask("Where does the stg amount come from?", client, box)
    assert code_steps(run) == []  # any trace/impact on the column counts


def test_not_when_two_different_columns_were_linked(box: Toolbox, make_client) -> None:
    script = [
        calls(
            ("resolve_entity", {"text": "stg.amount"}), ("resolve_entity", {"text": "fct.total"})
        ),
        done(),
        draft(),
    ]
    client, _ = make_client(script)
    run = ask("Where do the stg amount and the fct total come from?", client, box)
    assert code_steps(run) == []


def test_existing_code_steps_are_tagged_with_their_rule(box: Toolbox, make_client) -> None:
    client, _ = make_client([done(), draft()])
    run = ask("Where does fct.total come from?", client, box)
    assert [(r.tool, r.code_initiated, r.rule) for r in code_steps(run)] == [
        ("trace_upstream", True, "code_evidence")
    ]
