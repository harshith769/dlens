import json
import os
import random
from pathlib import Path

import pytest

from conftest import edge, make_graph
from dlens import __version__
from dlens.graph import AmbiguousColumn, ColumnNotFound, LineageGraph
from dlens.graph.cache import cache_path, is_stale, load_or_build
from dlens.graph.graph import FORMAT_VERSION
from dlens.graph.render import render_impact, render_trace
from dlens.lineage import EdgeKind

RAW_X = "seed.p.raw.x"
STG = "model.p.stg.x2"
TOTAL = "model.p.fct.total"


def test_upstream_walks_to_the_seed(tiny_graph: LineageGraph) -> None:
    paths = tiny_graph.upstream(TOTAL)
    assert len(paths) == 1
    p = paths[0]
    assert (p.start, p.end, p.depth) == (TOTAL, RAW_X, 2)
    assert [e.kind for e in p.edges] == [EdgeKind.AGGREGATION, EdgeKind.RENAME]
    assert not paths.truncated and not paths.depth_limited


def test_upstream_of_a_source_column_is_empty(tiny_graph: LineageGraph) -> None:
    assert tiny_graph.upstream(RAW_X) == []


def test_upstream_max_depth_cuts_and_flags(tiny_graph: LineageGraph) -> None:
    paths = tiny_graph.upstream(TOTAL, max_depth=1)
    assert [p.depth for p in paths] == [1]
    assert paths.depth_limited and not paths.truncated


def test_upstream_max_paths_stops_and_flags() -> None:
    # fan-in of 3 parents at each of 3 levels: 27 paths
    edges = []
    for lvl in range(3):
        for i in range(3):
            for j in range(3):
                edges.append(edge(f"model.p.l{lvl + 1}.c{j}", f"model.p.l{lvl}.c{i}"))
    g = make_graph(edges)
    assert len(g.upstream("model.p.l0.c0")) == 27
    capped = g.upstream("model.p.l0.c0", max_paths=5)
    assert len(capped) == 5 and capped.truncated
    exact = g.upstream("model.p.l0.c0", max_paths=27)
    assert len(exact) == 27 and not exact.truncated


def test_downstream_depths_models_and_exposures(tiny_graph: LineageGraph) -> None:
    r = tiny_graph.downstream(RAW_X)
    assert r.columns_by_depth == {1: [STG], 2: [TOTAL]}
    assert r.models == ["model.p.fct", "model.p.stg"]
    assert r.exposures == ["exposure.p.dash"]
    assert not r.truncated
    assert r.via[TOTAL].from_column == STG


def test_downstream_max_depth_truncates(tiny_graph: LineageGraph) -> None:
    r = tiny_graph.downstream(RAW_X, max_depth=1)
    assert r.columns == [STG] and r.truncated
    assert r.exposures == []  # fct is not reached within the depth


def test_downstream_uses_shortest_depth() -> None:
    g = make_graph([edge("m.a.x", "m.b.y"), edge("m.b.y", "m.c.z"), edge("m.a.x", "m.c.z")])
    assert g.downstream("m.a.x").columns_by_depth == {1: ["m.b.y", "m.c.z"]}


def test_root_model_exposure_counts() -> None:
    g = make_graph(
        [], extra_columns=["model.p.fct.total"], consumes=[("exposure.p.d", "model.p.fct")]
    )
    assert g.downstream("model.p.fct.total").exposures == ["exposure.p.d"]


def test_resolve_short_full_and_case(tiny_graph: LineageGraph) -> None:
    assert tiny_graph.resolve("fct.total") == TOTAL
    assert tiny_graph.resolve(TOTAL) == TOTAL
    assert tiny_graph.resolve("  FCT.Total ") == TOTAL
    assert tiny_graph.resolve("p.stg.x2") == STG


def test_resolve_ambiguous_lists_candidates(tiny_graph: LineageGraph) -> None:
    with pytest.raises(AmbiguousColumn) as e:
        tiny_graph.resolve("stg.x2")
    assert e.value.candidates == ["model.p.stg.x2", "model.q.stg.x2"]
    assert "model.q.stg.x2" in str(e.value)


def test_resolve_unknown_suggests_three_closest(tiny_graph: LineageGraph) -> None:
    with pytest.raises(ColumnNotFound) as e:
        tiny_graph.resolve("fct.totl")
    assert len(e.value.suggestions) == 3
    assert e.value.suggestions[0] == "fct.total"


def test_bare_column_name_is_not_accepted(tiny_graph: LineageGraph) -> None:
    with pytest.raises(ColumnNotFound):
        tiny_graph.resolve("total")


def test_display_name_falls_back_to_full_id_when_short_is_ambiguous(
    tiny_graph: LineageGraph,
) -> None:
    assert tiny_graph.display_name(TOTAL) == "fct.total"
    assert tiny_graph.display_name(STG) == STG


def test_save_load_round_trip_and_stable_bytes(tiny_graph: LineageGraph, tmp_path: Path) -> None:
    a, b = tmp_path / "a.json", tmp_path / "b" / "b.json"
    tiny_graph.save(a)
    loaded = LineageGraph.load(a)
    assert loaded == tiny_graph
    loaded.save(b)
    assert a.read_bytes() == b.read_bytes()
    assert a.read_text().endswith("}\n")


def test_save_is_independent_of_input_order(tmp_path: Path) -> None:
    edges = [edge(f"m.a.c{i}", f"m.b.c{i}") for i in range(6)]
    shuffled = edges[:]
    random.Random(1).shuffle(shuffled)
    make_graph(edges).save(tmp_path / "1.json")
    make_graph(shuffled).save(tmp_path / "2.json")
    assert (tmp_path / "1.json").read_bytes() == (tmp_path / "2.json").read_bytes()


def test_load_rejects_unknown_version(tmp_path: Path) -> None:
    p = tmp_path / "g.json"
    p.write_text('{"version": 99}')
    with pytest.raises(ValueError, match="version"):
        LineageGraph.load(p)


def _project(tmp_path: Path, graph: LineageGraph) -> Path:
    (tmp_path / "target").mkdir()
    (tmp_path / "models").mkdir()
    (tmp_path / "target" / "manifest.json").write_text("{}")
    (tmp_path / "models" / "m.sql").write_text("select 1")
    graph.save(cache_path(tmp_path))
    now = 2_000_000_000
    os.utime(tmp_path / "target" / "manifest.json", (now - 20, now - 20))
    os.utime(tmp_path / "models" / "m.sql", (now - 20, now - 20))
    os.utime(cache_path(tmp_path), (now, now))
    return tmp_path


def test_cache_is_fresh_then_stale_when_manifest_or_source_is_newer(
    tmp_path: Path, tiny_graph: LineageGraph
) -> None:
    p = _project(tmp_path, tiny_graph)
    assert not is_stale(p)
    assert load_or_build(p) == tiny_graph  # served from cache: no dbt in a fake project
    os.utime(p / "models" / "m.sql", (2_000_000_100, 2_000_000_100))
    assert is_stale(p)
    os.utime(p / "models" / "m.sql", (1_999_999_000, 1_999_999_000))
    os.utime(p / "target" / "manifest.json", (2_000_000_100, 2_000_000_100))
    assert is_stale(p)


@pytest.mark.parametrize(
    ("key", "value"), [("dlens_version", "0.0.0-old"), ("version", 1), ("dlens_version", None)]
)
def test_cache_from_another_version_is_rebuilt(
    tmp_path: Path,
    tiny_graph: LineageGraph,
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    value: object,
) -> None:
    p = _project(tmp_path, tiny_graph)
    raw = json.loads(cache_path(p).read_text())
    raw[key] = value
    cache_path(p).write_text(json.dumps(raw))
    now = 2_000_000_000
    os.utime(cache_path(p), (now, now))  # still fresh by mtime: only the header is wrong
    assert not is_stale(p)
    with pytest.raises(ValueError):
        LineageGraph.load(cache_path(p))
    calls: list[Path] = []

    def fake_build(project_dir: Path, dialect: str = "duckdb") -> LineageGraph:
        calls.append(project_dir)
        return tiny_graph

    monkeypatch.setattr("dlens.graph.cache.build_graph", fake_build)
    assert load_or_build(p) == tiny_graph
    assert calls == [p]
    rewritten = json.loads(cache_path(p).read_text())
    assert (rewritten["version"], rewritten["dlens_version"]) == (FORMAT_VERSION, __version__)
    os.utime(cache_path(p), (now, now))  # the rewrite stamped real time; keep it fresh
    calls.clear()
    assert load_or_build(p) == tiny_graph  # rewritten cache is now reused
    assert calls == []


def test_cache_missing_is_stale(tmp_path: Path) -> None:
    assert is_stale(tmp_path)


def test_trace_render_shows_hops_with_kind_expression_and_citation(
    tiny_graph: LineageGraph,
) -> None:
    out = render_trace(tiny_graph, TOTAL, tiny_graph.upstream(TOTAL), 10)
    lines = out.splitlines()
    assert lines[0] == "fct.total"
    assert lines[1].startswith("└─ ") and "[AGGREGATION]" in lines[1]
    assert "f(x2)" in lines[1] and "models/fct.sql:3-3" in lines[1]
    assert "[RENAME]" in lines[2] and lines[2].startswith("   └─ ")
    assert "1 path(s), deepest 2 hop(s), 1 origin column(s)" in out


def test_trace_render_merges_shared_prefixes() -> None:
    g = make_graph([edge("m.a.x", "m.b.y"), edge("m.a.z", "m.b.y"), edge("m.b.y", "m.c.out")])
    out = render_trace(g, "m.c.out", g.upstream("m.c.out"), 10)
    assert out.count("a.x") == 1 and out.count("b.y") == 1
    assert "2 path(s)" in out


def test_trace_render_notes_for_source_and_limits(tiny_graph: LineageGraph) -> None:
    assert "is a source" in render_trace(tiny_graph, RAW_X, tiny_graph.upstream(RAW_X), 10)
    assert "cut at --depth 1" in render_trace(
        tiny_graph, TOTAL, tiny_graph.upstream(TOTAL, max_depth=1), 1
    )


def test_trace_render_truncates_long_expressions_and_tags_low_confidence() -> None:
    e = edge("m.a.x", "m.b.y").model_copy(update={"expression": "x" * 200, "confidence": "low"})
    g = make_graph([e])
    out = render_trace(g, "m.b.y", g.upstream("m.b.y"), 10)
    assert "…" in out and "x" * 61 not in out and "(low confidence)" in out


def test_impact_render_summary(tiny_graph: LineageGraph) -> None:
    out = render_impact(tiny_graph, tiny_graph.downstream(RAW_X), 10)
    assert "2 affected column(s), 2 model(s)" in out
    assert "depth 1: 1 column(s)" in out
    assert "exposures: exposure.p.dash" in out
    assert "warning" not in out
    assert "warning" in render_impact(tiny_graph, tiny_graph.downstream(RAW_X, max_depth=1), 1)


def test_model_and_exposure_info_are_copies(tiny_graph: LineageGraph) -> None:
    info = tiny_graph.model_info("model.p.fct")
    assert info == {"resource_type": "model", "name": "fct", "file": ""}
    assert info is not None
    info["name"] = "changed"
    assert tiny_graph.model_info("model.p.fct") == {
        "resource_type": "model",
        "name": "fct",
        "file": "",
    }
    assert tiny_graph.model_info("model.p.nope") is None
    assert "model.p.fct" in tiny_graph.model_ids()
    assert tiny_graph.exposure_info("exposure.p.dash") == {
        "name": "exposure.p.dash",
        "type": "dashboard",
    }
    assert tiny_graph.exposure_info("exposure.p.nope") is None


# -- indirect edges (ADR 0020) and format v3 -----------------------------------------------

REPO = Path(__file__).parents[2]


def _with_indirect(g: LineageGraph) -> LineageGraph:
    """The same graph plus indirect edges, built through the public constructor."""
    from dlens.lineage import IndirectEdge, IndirectKind

    indirect = [
        IndirectEdge(
            from_column="seed.p.raw.y",
            to_column=TOTAL,
            kind=IndirectKind.JOIN,
            key="raw.y",
            expression="on raw.y = stg.x2",
            file="models/fct.sql",
            lines=(1, 5),
        ),
        IndirectEdge(
            from_column="seed.p.raw.y",
            to_column=TOTAL,
            kind=IndirectKind.GROUP_BY,
            key="raw.y",
            expression="group by raw.y",
            file="models/fct.sql",
            lines=(1, 5),
        ),
    ]
    return LineageGraph(
        columns={c: dict(g.nx_graph.nodes[c]) for c in g.columns()},
        edges=g.edges(),
        depends_on=g.depends_on(),
        consumes=g.consumes(),
        models={m: g.model_info(m) or {} for m in g.model_ids()},
        exposures={x: g.exposure_info(x) or {} for x, _ in g.consumes()},
        parse={},
        deferred=[],
        indirect=indirect,
    )


def test_indirect_edges_round_trip_in_format_v3(tmp_path: Path, tiny_graph: LineageGraph) -> None:
    g = _with_indirect(tiny_graph)
    g.save(tmp_path / "g.json")
    raw = json.loads((tmp_path / "g.json").read_text())
    assert raw["version"] == FORMAT_VERSION == 3
    assert [e["kind"] for e in raw["indirect"]] == ["GROUP_BY", "JOIN"]  # sorted
    loaded = LineageGraph.load(tmp_path / "g.json")
    assert loaded == g and loaded.indirect_edges() == g.indirect_edges()


def test_a_v2_file_still_loads_with_no_indirect_edges(
    tmp_path: Path, tiny_graph: LineageGraph
) -> None:
    tiny_graph.save(tmp_path / "g.json")
    raw = json.loads((tmp_path / "g.json").read_text())
    del raw["indirect"]
    raw["version"] = 2
    (tmp_path / "v2.json").write_text(json.dumps(raw))
    loaded = LineageGraph.load(tmp_path / "v2.json")
    assert loaded == tiny_graph and loaded.indirect_edges() == []


def test_the_committed_v2_demo_graph_loads_unchanged() -> None:
    """demo/synthetic_shop/graph.json was written by dlens 0.2 (format v2); the demo reads it."""
    from dlens.ui import demo

    path = REPO / "demo" / demo.PROJECT / demo.GRAPH_FILE
    before = path.read_bytes()
    assert json.loads(before)["version"] == 2
    g = demo.load_graph(path.parent)
    assert len(g.edges()) == 115 and g.indirect_edges() == []
    assert path.read_bytes() == before


def test_traversal_ignores_indirect_edges(tiny_graph: LineageGraph) -> None:
    """S03: no user-facing behaviour change. include_indirect is still a no-op."""
    g = _with_indirect(tiny_graph)
    for col in g.columns():
        for flag in (False, True):
            assert g.upstream(col, include_indirect=flag) == tiny_graph.upstream(col)
            assert g.downstream(col, include_indirect=flag) == tiny_graph.downstream(col)
    assert sorted(g.nx_graph.edges) == sorted(tiny_graph.nx_graph.edges)


def test_a_v2_cache_is_rebuilt(
    tmp_path: Path, tiny_graph: LineageGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LineageGraph.load reads v2, but a v2 *cache* is rebuilt so it gains indirect edges."""
    p = _project(tmp_path, tiny_graph)
    raw = json.loads(cache_path(p).read_text())
    raw["version"] = 2
    del raw["indirect"]
    cache_path(p).write_text(json.dumps(raw))
    os.utime(cache_path(p), (2_000_000_000, 2_000_000_000))
    assert not is_stale(p)
    calls: list[Path] = []

    def fake_build(project_dir: Path, dialect: str = "duckdb") -> LineageGraph:
        calls.append(project_dir)
        return tiny_graph

    monkeypatch.setattr("dlens.graph.cache.build_graph", fake_build)
    assert load_or_build(p) == tiny_graph
    assert calls == [p]
    assert json.loads(cache_path(p).read_text())["version"] == FORMAT_VERSION
