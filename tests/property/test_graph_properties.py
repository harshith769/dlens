import networkx as nx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from conftest import edge, make_graph
from dlens.graph import LineageGraph
from dlens.lineage import Edge, EdgeKind

# --- random DAGs (no dbt): columns c0..c{n-1}, edges only from lower to higher index ----------


@st.composite
def dags(draw: st.DrawFn) -> LineageGraph:
    n = draw(st.integers(min_value=2, max_value=9))
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
    chosen = draw(st.lists(st.sampled_from(pairs), unique=True, max_size=14))
    kinds = list(EdgeKind)
    edges: list[Edge] = [
        edge(f"model.p.m{i}.c{i}", f"model.p.m{j}.c{j}", kinds[(i + j) % len(kinds)])
        for i, j in chosen
    ]
    return make_graph(edges, extra_columns=[f"model.p.m{i}.c{i}" for i in range(n)])


@given(g=dags())
def test_round_trip_equal_on_random_dags(
    g: LineageGraph, tmp_path_factory: pytest.TempPathFactory
) -> None:
    p = tmp_path_factory.mktemp("rt") / "g.json"
    g.save(p)
    assert LineageGraph.load(p) == g


@given(g=dags(), data=st.data(), depth=st.integers(min_value=1, max_value=10))
@settings(max_examples=100)
def test_upstream_paths_are_contiguous_and_bounded(
    g: LineageGraph, data: st.DataObject, depth: int
) -> None:
    col = data.draw(st.sampled_from(g.columns()))
    for p in g.upstream(col, max_depth=depth, max_paths=10_000):
        assert 1 <= p.depth <= depth
        assert p.start == col
        for a, b in zip(p.edges, p.edges[1:], strict=False):
            assert a.from_column == b.to_column
        assert all(g.nx_graph.has_edge(e.from_column, e.to_column) for e in p.edges)


@given(g=dags(), data=st.data())
@settings(max_examples=100)
def test_upstream_and_downstream_agree(g: LineageGraph, data: st.DataObject) -> None:
    col = data.draw(st.sampled_from(g.columns()))
    reached = set(g.downstream(col, max_depth=20).columns)
    # b is downstream of a  <=>  some upstream path of b passes through a
    for b in g.columns():
        through = {
            e.from_column for p in g.upstream(b, max_depth=20, max_paths=10_000) for e in p.edges
        }
        assert (b in reached) == (col in through)


@given(g=dags(), data=st.data())
@settings(max_examples=100)
def test_impact_depth_is_shortest_path_length(g: LineageGraph, data: st.DataObject) -> None:
    col = data.draw(st.sampled_from(g.columns()))
    r = g.downstream(col, max_depth=20)
    lengths = nx.single_source_shortest_path_length(g.nx_graph, col)
    for depth, cols in r.columns_by_depth.items():
        assert all(lengths[c] == depth for c in cols)
    assert set(r.columns) == set(lengths) - {col}
    assert not r.truncated


# --- the real built graph (integration: needs the dbt build) ----------------------------------


@pytest.mark.integration
def test_built_graph_is_acyclic(synthetic_graph: LineageGraph) -> None:
    assert nx.is_directed_acyclic_graph(synthetic_graph.nx_graph)


@pytest.mark.integration
def test_every_edge_endpoint_is_a_catalog_column(synthetic_graph: LineageGraph) -> None:
    g = synthetic_graph.nx_graph
    for u, v in g.edges:
        assert "model" in g.nodes[u], f"{u} is not a catalog column"
        assert "model" in g.nodes[v], f"{v} is not a catalog column"


@pytest.mark.integration
def test_every_model_column_has_an_upstream(synthetic_graph: LineageGraph) -> None:
    g = synthetic_graph.nx_graph
    orphans = [
        c
        for c in g.nodes
        if synthetic_graph.model_of(c).startswith("model.") and g.in_degree(c) == 0
    ]
    assert orphans == []


@pytest.mark.integration
@given(data=st.data(), depth=st.integers(min_value=1, max_value=10))
@settings(max_examples=40, deadline=None)
def test_built_graph_paths_are_contiguous(
    synthetic_graph: LineageGraph, data: st.DataObject, depth: int
) -> None:
    col = data.draw(st.sampled_from(synthetic_graph.columns()))
    paths = synthetic_graph.upstream(col, max_depth=depth)
    for p in paths:
        assert p.depth <= depth and p.start == col
        for a, b in zip(p.edges, p.edges[1:], strict=False):
            assert a.from_column == b.to_column
    if not paths.truncated and not paths.depth_limited and paths:
        # every origin of a complete trace has no upstream of its own
        assert all(synthetic_graph.nx_graph.in_degree(p.end) == 0 for p in paths)
