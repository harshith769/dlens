"""S0 on synthetic_shop's 96 dev questions (S10 step 3): S0-gold is exact on every set and
verdict metric, and the records are deterministic apart from timings."""

import json
from pathlib import Path
from typing import Any

import pytest

import metrics as M
from dlens.graph import LineageGraph
from systems import s0

pytestmark = pytest.mark.integration

QUESTIONS = [json.loads(x) for x in s0.QUESTIONS.read_text().splitlines() if x.strip()]
SET_AND_VERDICT = {
    "headline_f1",
    "upstream_f1",
    "inputs_f1",
    "columns_f1",
    "models_f1",
    "exposures_f1",
    "yesno_correct",
    "refusal_correct",
    "chain_correct",
    "clarify_correct",
    "premise_rejected",
    "path_node_coverage",
}


def strip_timings(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in r.items() if k != "timings"} for r in records]


@pytest.fixture(scope="module")
def G(synthetic_graph: LineageGraph, synthetic_project: Path) -> s0.Graph:
    return s0.Graph.from_graph(synthetic_graph, synthetic_project)


def test_s0_gold_is_exact_on_sets_and_verdicts(G: s0.Graph, synthetic_project: Path) -> None:
    records = s0.run("s0-gold", QUESTIONS, G)
    assert len(records) == 84  # every non-Ask question
    out = M.score_run(records, QUESTIONS, corpus_dir=synthetic_project)
    assert out["complete"]
    for row in out["rows"]:
        for k, v in row["metrics"].items():
            if k in SET_AND_VERDICT:
                assert v == 1.0, (row["id"], k, v)
            if k in ("false_refusal", "has_hallucination"):
                assert v == 0.0, (row["id"], k)


@pytest.mark.parametrize("system", ["s0-gold", "s0-linked"])
def test_s0_is_deterministic(G: s0.Graph, system: str) -> None:
    assert strip_timings(s0.run(system, QUESTIONS, G)) == strip_timings(
        s0.run(system, QUESTIONS, G)
    )


def test_s0_linked_never_calls_hybrid(G: s0.Graph) -> None:
    records = s0.run("s0-linked", QUESTIONS, G)
    assert all(r["params"]["hybrid"] is False for r in records)
    assert all(r["tokens"]["llm_calls"] == 0 for r in records)
