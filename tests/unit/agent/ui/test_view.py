"""Pure UI helpers (no Streamlit)."""

import json
from pathlib import Path

from dlens.agent.answer import Answer, Claim
from dlens.agent.tools import Toolbox
from dlens.agent.tools.provenance import Citation
from dlens.ui import view

from ..tools.conftest import make_shop


def _report(ids):
    return {"rows": [{"id": i, "pass": True} for i in ids]}


def test_presets_only_passing_dev_questions_of_the_project(tmp_path: Path):
    qs = [
        {"id": "a", "corpus": "p", "subtype": "upstream", "question": "Q-a"},
        {"id": "b", "corpus": "p", "subtype": "downstream", "question": "Q-b"},
        {"id": "c", "corpus": "p", "subtype": "downstream", "question": "Q-failed"},
        {"id": "d", "corpus": "other", "subtype": "upstream", "question": "Q-other"},
    ]
    (tmp_path / "q.jsonl").write_text("\n".join(map(json.dumps, qs)))
    (tmp_path / "r.json").write_text(json.dumps(_report(["a", "b", "d"])))
    assert view.presets("p", tmp_path / "q.jsonl", tmp_path / "r.json") == ["Q-a", "Q-b"]
    assert view.presets("p", tmp_path / "none.jsonl", tmp_path / "r.json") == []


def test_real_presets_for_synthetic_shop():
    got = view.presets("synthetic_shop")
    assert len(got) == view.PRESET_COUNT and len(set(got)) == len(got)


def test_load_source_and_cited_lines(shop_root: Path):
    src = view.load_source(
        shop_root, Citation(file="models/fct.sql", line_start=2, line_end=3, level="line")
    )
    assert src and src.range_label == "lines 2-3"
    assert src.cited.splitlines()[0].startswith("2 | ")
    whole = view.load_source(
        shop_root, Citation(file="models/fct.sql", line_start=1, line_end=1, level="model")
    )
    assert whole and whole.cited == "" and "whole file" in whole.range_label
    assert (
        view.load_source(
            shop_root, Citation(file="../x.sql", line_start=1, line_end=1, level="line")
        )
        is None
    )


def test_subgraph_dot_labels_edges_with_kind(shop_root: Path):
    g = make_shop()
    box = Toolbox(g, shop_root)
    box.call("trace_upstream", {"column_id": "fct.total"})
    eids = sorted(box.emitted_ids)
    ans = Answer(answer_text="x", claims=[Claim(text="t", edge_ids=eids)], subgraph=eids)
    dot = view.subgraph_dot(ans, box, selected=eids[0])
    assert dot.startswith("digraph G {") and dot.rstrip().endswith("}")
    assert 'label="AGGREGATION"' in dot and "->" in dot and "penwidth=3" in dot
    assert view.subgraph_dot(Answer(answer_text="x"), box).count("->") == 0


def test_chips_skip_graph_checks():
    cite = Citation(file="models/a.sql", line_start=3, line_end=4, level="line")
    ans = Answer(
        answer_text="x",
        claims=[
            Claim(text="t", edge_ids=["e_1"], chunk_ids=["r_1"]),
            Claim(text="u", edge_ids=["e_1"]),
        ],
        citations={"e_1": cite},
    )
    assert view.citation_chips(ans) == [("e_1", "[models/a.sql:3-4]")]
