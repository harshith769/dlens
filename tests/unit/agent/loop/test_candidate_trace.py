"""B7 (dev-46, s12-design B7): per-candidate mode code-traces each tied candidate (rule
``candidate_trace``); if there is still no citable id, code returns the clarification, never the
"no lineage evidence" refusal. More than 3 candidates and chain mode are unchanged."""

from pathlib import Path

from dlens.agent.loop import ask
from dlens.agent.tools import Toolbox
from dlens.graph import LineageGraph

from .conftest import P, call, done, draft, make_totals_shop


def _rules(run) -> list[tuple[str, str]]:
    return [
        (r.tool, r.args["column_id"])
        for s in run.record.steps
        for r in s.results
        if r.rule == "candidate_trace"
    ]


def test_a_model_that_stops_still_gets_every_candidate_traced(shop_root: Path, make_client):
    box = Toolbox(make_totals_shop(1), shop_root)
    client, _ = make_client([call("resolve_entity", text="total"), done(), draft()])
    run = ask("where does total come from?", client, box)
    assert run.record.ambiguity["mode"] == "per_candidate"
    assert _rules(run) == [
        ("trace_upstream", "fct.total"),
        ("trace_upstream", "fct_star.total"),
        ("trace_upstream", "other.total"),
    ]
    assert not run.answer.refused and run.record.llm_calls == 3  # resolve, done, answer


def test_calls_already_in_the_log_are_skipped(shop_root: Path, make_client):
    box = Toolbox(make_totals_shop(1), shop_root)
    script = [
        call("resolve_entity", text="total"),
        call("trace_upstream", column_id="fct.total"),
        done(),
        draft(),
    ]
    client, _ = make_client(script)
    run = ask("where does total come from?", client, box)
    assert [c for _, c in _rules(run)] == ["fct_star.total", "other.total"]


def test_impact_wording_uses_impact_downstream(shop_root: Path, make_client):
    box = Toolbox(make_totals_shop(1), shop_root)
    client, _ = make_client([call("resolve_entity", text="total"), done(), draft()])
    run = ask("what does total affect?", client, box)
    assert {t for t, _ in _rules(run)} == {"impact_downstream"}


def _sourceless_ties() -> LineageGraph:
    """Two unrelated `total` columns with no edges: a tie whose traces find nothing."""
    models = {
        f"{P}.{m}": {"resource_type": "model", "name": m, "file": f"models/{m}.sql"}
        for m in ("other", "misc")
    }
    return LineageGraph(
        columns={
            f"{P}.{m}.total": {"model": f"{P}.{m}", "name": "total", "type": "int"}
            for m in ("other", "misc")
        },  # fmt: skip
        edges=[],
        depends_on=[],
        consumes=[],
        models=models,
        exposures={},
        parse={},
    )


def test_no_evidence_after_the_traces_gives_the_clarification(shop_root: Path, make_client):
    box = Toolbox(_sourceless_ties(), shop_root)
    client, prov = make_client([call("resolve_entity", text="total"), done()])  # no answer call
    run = ask("where does total come from?", client, box)
    assert len(_rules(run)) == 2
    clar = run.answer.clarification
    assert clar is not None and not run.answer.refused
    assert sorted(clar.candidates) == ["misc.total", "other.total"]
    assert run.record.stop_reason.endswith("+candidate_clarification")
    assert all(r["schema"] is None for r in prov.requests)


def test_more_than_three_candidates_are_not_traced(shop_root: Path, make_client):
    box = Toolbox(make_totals_shop(2), shop_root)
    client, _ = make_client([call("resolve_entity", text="total"), done()])
    run = ask("where does total come from?", client, box)
    assert run.answer.clarification is not None and _rules(run) == []
