"""Pure UI helpers (no Streamlit)."""

import json
from pathlib import Path

from dlens.agent.answer import Answer, Claim
from dlens.agent.tools import Toolbox
from dlens.agent.tools.provenance import Citation
from dlens.ui import style, view

from ..tools.conftest import make_shop


def _report(ids):
    return {"rows": [{"id": i, "pass": True} for i in ids]}


def test_examples_group_passing_dev_questions_of_the_project(tmp_path: Path):
    qs = [
        {"id": "a", "corpus": "p", "subtype": "upstream", "question": "Q-a"},
        {"id": "b", "corpus": "p", "subtype": "downstream", "question": "Q-b"},
        {"id": "c", "corpus": "p", "subtype": "downstream", "question": "Q-failed"},
        {"id": "d", "corpus": "other", "subtype": "upstream", "question": "Q-other"},
        {"id": "e", "corpus": "p", "subtype": "nonexistent_column", "question": "Q-e"},
    ]
    (tmp_path / "q.jsonl").write_text("\n".join(map(json.dumps, qs)))
    (tmp_path / "r.json").write_text(json.dumps(_report(["a", "b", "d", "e"])))
    got = view.examples("p", tmp_path / "q.jsonl", tmp_path / "r.json")
    assert [(g.label, g.questions) for g in got] == [
        ("Where a column comes from", ("Q-a",)),
        ("What a column affects", ("Q-b",)),
        ("Should refuse", ("Q-e",)),
    ]
    assert all(g.hint for g in got)
    assert view.examples("p", tmp_path / "none.jsonl", tmp_path / "r.json") == []


def test_real_examples_for_synthetic_shop():
    got = view.examples("synthetic_shop")
    flat = [q for g in got for q in g.questions]
    assert len(got) >= 4 and len(set(flat)) == len(flat)
    assert all(len(g.questions) <= view.EXAMPLES_PER_GROUP for g in got)


def test_project_stats():
    s = view.project_stats(make_shop())
    assert (s.models, s.columns, s.edges) == (3, 8, 6)
    assert s.line == "3 models · 8 columns · 6 edges · parse coverage n/a"
    assert view.Stats(1, 1, 1, parsed=3, reported=4).line.endswith("parse coverage 75%")


def test_error_hint_for_ollama_failures():
    down = view.error_hint("ProviderError: ollama call failed: Failed to connect to Ollama.")
    assert down and "not reachable" in down.title and "ollama serve" in down.commands
    missing = view.error_hint("ProviderError: ollama call failed: model 'x' not found", "m:1")
    assert missing and missing.commands == ("ollama pull m:1",)
    assert (
        view.error_hint("ModuleNotFoundError: No module named 'ollama'")
        .commands[0]
        .startswith("uv sync")
    )
    assert view.error_hint("unknown column: fct.nope") is None
    assert view.error_hint(None) is None


def test_project_problem(monkeypatch, tmp_path: Path):
    assert view.project_problem("synthetic_shop") is None
    unknown = view.project_problem("nope")
    assert unknown and unknown.title == "Unknown project: nope"
    monkeypatch.setitem(view.PROJECTS, "gone", tmp_path / "gone")
    gone = view.project_problem("gone")
    assert gone and gone.commands == ("make ingest CORPUS=gone",)


def test_badge_escapes_its_label():
    html = style.badge("<script>alert(1)</script>", "verified")
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert style.VERIFIED in html


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
