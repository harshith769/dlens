"""Pure UI helpers (no Streamlit)."""

import json
from pathlib import Path
from types import SimpleNamespace

from dlens.agent.answer import Answer, Claim
from dlens.agent.tools.provenance import Citation, edge_id
from dlens.graph import LineageGraph
from dlens.lineage import EdgeKind
from dlens.ui import style, view

from ..tools.conftest import edge, make_shop


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


def _layered() -> LineageGraph:
    """raw seed -> staging/stg_orders -> int_orders (by prefix) -> marts/fct_orders."""
    m = {
        "seed.p.raw": {"resource_type": "seed", "name": "raw", "file": "seeds/raw.csv"},
        "model.p.stg_orders": {
            "resource_type": "model",
            "name": "stg_orders",
            "file": "models/staging/stg_orders.sql",
        },
        "model.p.int_orders": {
            "resource_type": "model",
            "name": "int_orders",
            "file": "models/int_orders.sql",
        },
        "model.p.fct_orders": {
            "resource_type": "model",
            "name": "fct_orders",
            "file": "models/marts/fct_orders.sql",
        },
        "model.p.misc": {"resource_type": "model", "name": "misc", "file": "models/misc.sql"},
    }
    cols = {f"{uid}.{n}": (uid, n) for uid in m for n in ("a", "b")}
    k = EdgeKind
    edges = [
        edge("seed.p.raw.a", "model.p.stg_orders.a", k.RENAME, "x.sql", (1, 1), "a"),
        edge("model.p.stg_orders.a", "model.p.int_orders.a", k.IDENTITY, "x.sql", (1, 1), "a"),
        edge(
            "model.p.int_orders.a",
            "model.p.fct_orders.a",
            k.TRANSFORMATION,
            "x.sql",
            (1, 1),
            'case when "a" > 0 then a * 100 else 0 end',
        ),
    ]
    return LineageGraph(
        columns={c: {"model": u, "name": n, "type": "int"} for c, (u, n) in cols.items()},
        edges=edges,
        depends_on=[],
        consumes=[],
        models=m,
        exposures={},
        parse={},
        deferred=[],
    )


def test_layer_of_by_resource_type_folder_then_prefix():
    g = _layered()
    got = {u: view.layer_of(g, u) for u in g.model_ids()}
    assert got == {
        "seed.p.raw": "Seeds",
        "model.p.stg_orders": "Staging",
        "model.p.int_orders": "Intermediate",
        "model.p.fct_orders": "Marts",
        "model.p.misc": "Models",
    }


def test_lineage_dot_clusters_ports_kind_colors_and_focus():
    g = make_shop()
    edges = g.edges()
    agg = next(e for e in edges if e.kind.value == "AGGREGATION")
    d = view.build_lineage_dot(
        g, edges, focus="model.p.fct.total", highlight=frozenset([edge_id(agg)])
    )
    dot = d.dot
    assert dot.startswith("digraph lineage {") and dot.rstrip().endswith("}")
    assert "rankdir=LR" in dot
    assert dot.count("subgraph cluster_") == 4  # Seeds, Models, Marts (fct_star), legend
    assert 'label="Seeds"' in dot and 'label="Marts"' in dot and 'label="Edge kinds"' in dot
    assert dot.count("<TABLE") == 4 + 1  # four models + the legend
    assert 'PORT="c' in dot and ":e -> " in dot and ":w [" in dot
    for kind in ("IDENTITY", "RENAME", "AGGREGATION"):
        assert style.KIND_COLORS[kind] in dot
    assert 'label="sum(amount)"' in dot
    assert 'label="x_id"' not in dot  # identity edges carry no label
    agg_line = next(line for line in dot.splitlines() if "sum(amount)" in line)
    assert "penwidth=2.6" in agg_line and dot.count("penwidth") == 1
    focus_row = next(line for line in dot.splitlines() if 'BORDER="2"' in line)
    assert "<B>total</B>" in focus_row and "fct" in focus_row
    assert (d.shown, d.total, d.note) == (6, 6, None)


def test_lineage_dot_cap_label_length_and_escaping():
    g = _layered()
    d = view.build_lineage_dot(g, g.edges(), cap=2)
    assert (d.shown, d.total) == (2, 3) and d.note == "Showing the 2 nearest of 3 edges."
    full = view.build_lineage_dot(g, g.edges()).dot
    label = next(line for line in full.splitlines() if "case when" in line)
    assert 'case when \\"a\\" > 0 then a * 10…"' in label
    assert len(view.short_expression("x" * 80)) == view.LABEL_CHARS
    assert view.short_expression("a\n   +  b") == "a + b"


def test_lineage_dot_escapes_html_in_names():
    g = make_shop()
    g.nx_graph.nodes["model.p.fct.total"]["name"] = "<script>x</script>"
    dot = view.build_lineage_dot(g, g.edges()).dot
    assert "<script>" not in dot and "&lt;script&gt;" in dot


def test_lineage_dot_with_no_edges_still_shows_the_focus():
    d = view.build_lineage_dot(make_shop(), [], focus="model.p.fct.total")
    assert d.shown == 0 and 'BORDER="2"' in d.dot


def test_neighborhood_nearest_first_and_depth():
    g = make_shop()
    star = "model.p.fct_star.total"
    assert [e.to_column for e in view.neighborhood(g, star, "upstream", 1)] == [star]
    up = view.neighborhood(g, star, "upstream", 10)
    assert [e.to_column for e in up] == [star, "model.p.fct.total", "model.p.stg.amount"]
    down = view.neighborhood(g, "seed.p.raw.amt", "downstream", 10)
    assert [e.from_column for e in down][0] == "seed.p.raw.amt" and len(down) == 3
    both = view.neighborhood(g, "model.p.fct.total", "both", 1)
    assert {(e.from_column, e.to_column) for e in both} == {
        ("model.p.stg.amount", "model.p.fct.total"),
        ("model.p.fct.total", "model.p.fct_star.total"),
    }


def test_edges_by_id_keeps_order_and_skips_unknown():
    g = make_shop()
    a, b = g.edges()[:2]
    assert view.edges_by_id(g, [edge_id(b), "r_x", edge_id(a), edge_id(b)]) == [b, a]


def _run_with(*results):
    steps = [SimpleNamespace(results=[SimpleNamespace(tool=t, args=a) for t, a in results])]
    return SimpleNamespace(record=SimpleNamespace(steps=steps))


def test_focus_column_from_the_first_resolvable_tool_call():
    g = make_shop()
    run = _run_with(
        ("resolve_entity", {"query": "total"}),
        ("trace_upstream", {"column_id": "nope.nothing"}),
        ("impact_downstream", {"column_id": "stg.amount"}),
    )
    assert view.focus_column(run, g) == ("model.p.stg.amount", "downstream")
    assert view.focus_column(_run_with(), g) == (None, "upstream")


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


def _run(answer, validation=None, **record):
    rec = {"steps": [], "ambiguity": None, "draft_raw": None, "regenerate_draft_raw": None}
    return SimpleNamespace(
        answer=answer, record=SimpleNamespace(**{**rec, "validation": validation, **record})
    )


def _v(**kw):
    return {
        "passed": True,
        "regenerated": False,
        "warning": False,
        "repairs": [],
        "completions": [],
        "dropped_claims": [],
        "skipped": False,
        **kw,
    }


def test_verdict_from_real_fields_only():
    ok = Answer(answer_text="x")
    assert view.verdict(_run(ok)) == view.Badge("Answered", "primary")
    assert view.verdict(_run(Answer.refusal("no"))).label == "Refused"
    clar = Answer(answer_text="which?", clarification={"question": "q", "candidates": ["a"]})
    assert view.verdict(_run(clar)).label == "Clarification"
    assert view.verdict(_run(ok, ambiguity={"mode": "chain"})).label == "Chain mode"
    assert view.verdict(_run(ok, ambiguity={"mode": "per_candidate"})).label == "Answered"


def test_verification_badge():
    a = Answer(answer_text="x")
    assert view.verification(_run(a, None)).label == "Not checked"
    assert view.verification(_run(a, _v(skipped=True))).label == "Not checked"
    assert view.verification(_run(a, _v())) == view.Badge("Verified", "verified")
    rep = _v(repairs=[{"claim_index": 0}], completions=[{"claim_index": 1}], regenerated=True)
    assert view.verification(_run(a, rep)).label == "Repaired 1 · Completed 1 · Regenerated"
    part = view.verification(_run(a, _v(passed=False, warning=True)))
    assert part == view.Badge("Partially removed", "warning")
    gone = Answer.refusal("no verifiable claims").model_copy(update={"validation_warning": True})
    assert view.verification(_run(gone, _v(passed=False, warning=True))).label == (
        "Nothing verifiable"
    )


def test_claim_rows_map_status_through_dropped_claims():
    cite = Citation(file="models/a.sql", line_start=3, line_end=3, level="line")
    ans = Answer(
        answer_text="x",
        claims=[
            Claim(text=" kept0 ", edge_ids=["e_1", "e_1"]),
            Claim(text="kept2", edge_ids=["e_1"], chunk_ids=["r_9"]),
        ],
        citations={"e_1": cite},
    )
    # the draft had 3 claims; claim 1 was dropped, claim 2 was repaired
    v = _v(passed=False, warning=True, dropped_claims=[1], repairs=[{"claim_index": 2}])
    rows = view.claim_rows(_run(ans, v))
    assert [(r.text, r.status) for r in rows] == [("kept0", "verified"), ("kept2", "repaired")]
    assert rows[0].chips == (("e_1", "[models/a.sql:3]"),)
    assert rows[1].chips == (("e_1", "[models/a.sql:3]"), ("r_9", "[graph check]"))


def test_removed_claims_use_the_round_the_loop_kept():
    first = {
        "claims": 2,
        "dropped_claims": [0, 1],
        "failures": [{"claim_index": 0, "rule": "R8"}, {"claim_index": 1, "rule": "R7"}],
    }
    second = {
        "claims": 2,
        "dropped_claims": [1],
        "failures": [
            {"claim_index": 1, "rule": "R4.hallucinated"},
            {"claim_index": 1, "rule": "R4.unsupported"},
        ],
    }
    regen = '```json\n{"answer_text": "y", "claims": [{"text": "a"}, {"text": " b "}]}\n```'
    run = _run(
        Answer(answer_text="y", claims=[Claim(text="a", edge_ids=["e_1"])]),
        _v(passed=False, warning=True, dropped_claims=[1], first=first, second=second),
        draft_raw='{"claims": [{"text": "first-a"}, {"text": "first-b"}]}',
        regenerate_draft_raw=regen,
    )
    assert view.removed_claims(run) == [view.RemovedClaim("b", ("R4",))]
    assert view.removed_claims(_run(Answer(answer_text="x"), _v())) == []
    only_first = _run(
        Answer(answer_text="x"),
        _v(passed=False, warning=True, dropped_claims=[0, 1], first=first, second=None),
        draft_raw="not json",
    )
    assert view.removed_claims(only_first) == [
        view.RemovedClaim(None, ("R8",)),
        view.RemovedClaim(None, ("R7",)),
    ]


def test_claim_line_escapes_and_marks_status():
    html = style.claim_line("<script>alert(1)</script>", "repaired")
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "⚠" in html and "repaired" in html
    assert "✓" in style.claim_line("ok", "verified")
