"""The code search_docs step behind a gate (S13c F6, s13c-design.md). When the tool phase ends
with no citable evidence, code may call search_docs with the question, as a recorded ``code``
step (rule ``docs_evidence``), only if an index exists, no dotted ``a.b`` in the question names an
unknown model, and the linker returns a candidate for the question. The fixtures are the 5 qwen
Ask refusals, dev-41, dev-66 and dev-93–96 (dev question texts).

Two layers:
- CI: a real SearchIndex over the fixture artifacts with the fake embedder, so search_docs runs
  for real. The linker's decision is stubbed per question to its measured outcome with the bge
  index (s13c-design.md, F6 table), so these tests pin the loop's plumbing, not the embedder.
- Local: the real decision on the 11 questions with the real bge index; skipped when no local
  index exists (CI).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("bm25s")

from dlens.agent import loop  # noqa: E402
from dlens.agent.loop import Agent  # noqa: E402
from dlens.agent.tools import Toolbox  # noqa: E402
from dlens.graph import build_graph_from_artifacts  # noqa: E402
from dlens.retrieval.dense import FakeEmbedder  # noqa: E402
from dlens.retrieval.index import SearchIndex  # noqa: E402

from .conftest import call, done, draft  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]
SS_TARGET = ROOT / "tests" / "fixtures" / "artifacts" / "synthetic_shop"
SS_PROJECT = ROOT / "corpora" / "synthetic_shop"
QS = {
    q["id"]: q["question"]
    for q in (json.loads(x) for x in (ROOT / "eval/questions/dev.jsonl").read_text().splitlines())
}
RUN = ["dev-66", "dev-78", "dev-82", "dev-84", "dev-86"]  # measured: the linker has a candidate
NO_CANDIDATE = ["dev-41", "dev-87", "dev-94", "dev-95"]  # measured: no linker candidate
UNKNOWN_MODEL = ["dev-93", "dev-96"]  # a dotted id with an unknown model (gate condition 1)


@pytest.fixture(scope="module")
def ss_box(tmp_path_factory: pytest.TempPathFactory) -> Toolbox:
    graph = build_graph_from_artifacts(SS_TARGET)[0]
    tmp = tmp_path_factory.mktemp("gate")
    gfile = tmp / "graph.json"
    graph.save(gfile)
    idx, _ = SearchIndex.open(
        graph=graph,
        graph_file=gfile,
        target_dir=SS_TARGET,
        project_dir=SS_PROJECT,
        index_dir=tmp / "index",
        embedder=FakeEmbedder(),
    )
    return Toolbox(graph, SS_PROJECT, idx)


@pytest.fixture
def measured_linker(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """``loop.link`` returns one candidate for the RUN questions, none for the others, and
    fails for UNKNOWN_MODEL (condition 1 must decide those before the linker runs)."""
    asked: list[str] = []

    def fake(_g: Any, text: str, _index: Any = None) -> tuple[list[Any], dict[str, Any]]:
        asked.append(text)
        if text in {QS[i] for i in UNKNOWN_MODEL}:
            raise AssertionError("the linker ran for an unknown dotted model")
        return ([object()] if text in {QS[i] for i in RUN} else []), {}

    monkeypatch.setattr(loop, "link", fake)
    return asked


def answer() -> Any:
    return draft("The documentation describes it.", [], reach_verdict=None)


def code_steps(run: Any) -> list[Any]:
    return [s for s in run.record.steps if s.phase == "code"]


@pytest.mark.parametrize("qid", RUN)
def test_gate_runs_search_docs_as_a_code_step(
    qid: str, ss_box: Toolbox, make_client: Any, measured_linker: list[str]
) -> None:
    client, prov = make_client([done(), answer()])
    run = Agent(client, ss_box).ask(QS[qid])
    steps = code_steps(run)
    assert [s.tool_calls[0]["name"] for s in steps] == ["search_docs"]
    assert steps[0].results[0].rule == "docs_evidence" and steps[0].results[0].code_initiated
    assert "+docs_evidence" in run.record.stop_reason
    assert any(i.startswith("c_") for i in run.record.evidence["ids"])
    assert prov.requests[-1]["schema"] is not None  # the answer phase ran on the hits
    assert run.record.llm_calls == 2  # the code step is not an LLM call


@pytest.mark.parametrize("qid", NO_CANDIDATE + UNKNOWN_MODEL)
def test_gate_blocks_and_the_refusal_is_unchanged(
    qid: str, ss_box: Toolbox, make_client: Any, measured_linker: list[str]
) -> None:
    client, prov = make_client([done()])
    run = Agent(client, ss_box).ask(QS[qid])
    assert not code_steps(run)
    assert run.answer.refused and "no lineage evidence" in (run.answer.refusal_reason or "")
    assert "+docs_evidence" not in (run.record.stop_reason or "")
    if qid in UNKNOWN_MODEL:
        assert QS[qid] not in measured_linker  # decided by condition 1 alone


def test_without_an_index_the_refusal_is_unchanged(box: Toolbox, make_client: Any) -> None:
    def fail(*_: Any, **__: Any) -> Any:
        raise AssertionError("the gate ran without an index")

    client, _ = make_client([done()])
    agent = Agent(client, box)
    loop_link, loop.link = loop.link, fail  # type: ignore[assignment]
    try:
        run = agent.ask("What does the order total mean?")
    finally:
        loop.link = loop_link  # type: ignore[assignment]
    assert run.answer.refused and not code_steps(run)


def test_a_lineage_question_with_evidence_never_runs_it(
    ss_box: Toolbox, make_client: Any, measured_linker: list[str]
) -> None:
    script = [call("trace_upstream", column_id="stg_payments.amount_usd"), done(), answer()]
    client, _ = make_client(script)
    run = Agent(client, ss_box).ask("Where does stg_payments.amount_usd come from?")
    assert all(s.tool_calls[0]["name"] != "search_docs" for s in code_steps(run))
    assert "+docs_evidence" not in (run.record.stop_reason or "")
    assert not measured_linker  # evidence existed: the gate was never consulted


# -- local only: the real decision with the bge index -----------------------------------------


def _real_index() -> Toolbox | None:
    try:
        import sys

        sys.path.insert(0, str(ROOT / "eval"))
        from dlens.retrieval.index import project_index_dir
        from systems.s4 import open_graph

        if not project_index_dir(SS_PROJECT).is_dir():
            return None
        graph, index, _ = open_graph(SS_PROJECT, hybrid=True)
        return Toolbox(graph, SS_PROJECT, index)
    except Exception:  # noqa: BLE001 - no local ingest / index / model: skip
        return None


def test_real_gate_decision_on_the_11_fixtures() -> None:
    box = _real_index()
    if box is None:
        pytest.skip("no local synthetic_shop index (the decision is measured in s13c-design.md)")
    gate = Agent.__new__(Agent)
    gate.toolbox = box
    got = {qid: gate._docs_gate(QS[qid]) for qid in RUN + NO_CANDIDATE + UNKNOWN_MODEL}
    assert {q for q, ok in got.items() if ok} == set(RUN)
