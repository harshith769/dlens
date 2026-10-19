"""S0 graph oracle (eval/systems/s0.py, S10 step 3) on hand-built graphs.

The full dev run on synthetic_shop is in tests/integration/test_s0_synthetic.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import metrics as M
from conftest import with_indirect
from dlens.graph import LineageGraph
from systems import s0


def q(subtype: str, target: str = "p.fct.total", **gold: Any) -> dict[str, Any]:
    qtype = {"downstream": "impact", "yesno": "impact"}.get(subtype, "trace")
    return {
        "id": "dev-x",
        "type": qtype,
        "subtype": subtype,
        "question": f"question about {target}",
        "target": target,
        "mention": target,
        "gold": {"verdict": "answered", **gold},
    }


def graph(g: LineageGraph, tmp_path: Path) -> s0.Graph:
    return s0.Graph.from_graph(g, tmp_path)


def test_trace_closure_by_mode(tiny_graph: LineageGraph, tmp_path: Path) -> None:
    G = graph(with_indirect(tiny_graph), tmp_path)
    total = "model.p.fct.total"
    direct, _ = G.closure(total, "direct", up=True)
    full, edges = G.closure(total, "all", up=True)
    assert direct == {"model.p.stg.x2", "seed.p.raw.x"}
    assert full == direct | {"seed.p.raw.y"}
    assert {e["kind"] for e in edges} >= {"JOIN", "GROUP_BY", "AGGREGATION"}


def test_indirect_edge_ids_use_the_e_scheme(tiny_graph: LineageGraph, tmp_path: Path) -> None:
    G = graph(with_indirect(tiny_graph), tmp_path)
    ind = [e for e in G.preds["all"]["model.p.fct.total"] if e["kind"] == "JOIN"]
    assert ind[0]["id"] == s0.edge_key("seed.p.raw.y", "model.p.fct.total", "JOIN")
    assert ind[0]["key"] == "raw.y" and ind[0]["citation"]["level"] == "line"


def test_impact_answer_lists_models_and_exposures(tiny_graph: LineageGraph, tmp_path: Path) -> None:
    G = graph(tiny_graph, tmp_path)
    d = s0.impact_answer(G, "seed.p.raw.x", "direct")
    assert d.sets["downstream"]["direct"]["exposures"] == ["exposure.p.dash"]
    assert "fct.total" in d.answer_text and "Models affected: fct, stg." in d.answer_text


def test_reach_answer_verdicts_and_path(tiny_graph: LineageGraph, tmp_path: Path) -> None:
    G = graph(with_indirect(tiny_graph), tmp_path)
    yes = s0.reach_answer(G, "seed.p.raw.y", "model.p.fct.total", "all")
    assert yes.reach_verdict == "yes" and yes.sets["reach"] == {"direct": "no", "all": "yes"}
    no = s0.reach_answer(G, "seed.p.raw.y", "model.p.fct.total", "direct")
    assert no.reach_verdict == "no" and no.edges == []


def test_false_premise_answer_negates_the_premise(tiny_graph: LineageGraph, tmp_path: Path) -> None:
    G = graph(tiny_graph, tmp_path)
    d = s0.computed_answer(G, "model.p.fct.total", "direct", premise="raw.y")
    assert d.answer_text.endswith("It does not use raw.y.")


def test_unknown_target_is_refused(tiny_graph: LineageGraph, tmp_path: Path) -> None:
    G = graph(tiny_graph, tmp_path)
    question = q("dotted_near_miss", target="fct.nope")
    question["type"] = "unanswerable"
    d = s0.s0_gold(G, question)
    assert d.refused and "fct.nope" in (d.refusal_reason or "")


def test_record_round_trips_through_the_metrics_adapter(
    tiny_graph: LineageGraph, tmp_path: Path
) -> None:
    G = graph(tiny_graph, tmp_path)
    question = q("upstream", target="fct.total")
    rec = s0.to_record(G, question, s0.s0_gold(G, question), "s0-gold", 1.23)
    assert rec["project"] == s0.CORPUS and rec["tokens"]["llm_calls"] == 0
    pred = M.from_record(rec)
    assert pred.kind == "answered"
    assert len(pred.claims) == len(rec["steps"][0]["results"][0]["side_records"]["edges"]) == 2
    assert all(i in pred.edges for c in pred.claims for i in c["ids"])


def test_yes_no_record_carries_the_structured_verdict(
    tiny_graph: LineageGraph, tmp_path: Path
) -> None:
    G = graph(tiny_graph, tmp_path)
    question = q("yesno", target="raw.x", reach={"from": "raw.x", "to": "fct.total"})
    rec = s0.to_record(G, question, s0.s0_gold(G, question), "s0-gold", 0.0)
    assert rec["structured"]["reach_verdict"] == "yes"
    assert M.from_record(rec).reach_verdict == "yes"


def test_ask_questions_get_no_record(tiny_graph: LineageGraph, tmp_path: Path) -> None:
    G = graph(tiny_graph, tmp_path)
    ask = {**q("meaning"), "type": "ask"}
    assert s0.run("s0-gold", [ask], G) == []


def test_clarify_gold_gives_a_clarification(tiny_graph: LineageGraph, tmp_path: Path) -> None:
    G = graph(tiny_graph, tmp_path)
    question = q("ambiguous", target="stg.x2", candidates=["stg.x2", "fct.total"])
    question["gold"]["verdict"] = "clarify"
    rec = s0.to_record(G, question, s0.s0_gold(G, question), "s0-gold", 0.0)
    pred = M.from_record(rec)
    assert pred.kind == "clarification" and pred.clarification == ["stg.x2", "fct.total"]
