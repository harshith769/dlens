import shutil
from pathlib import Path

import pytest

from dlens.graph import LineageGraph, build_graph
from dlens.graph.cache import cache_path
from dlens.lineage import Edge, EdgeKind, IndirectEdge, IndirectKind

SYNTHETIC = Path(__file__).parents[1] / "corpora" / "synthetic_shop"


def edge(
    src: str, dst: str, kind: EdgeKind = EdgeKind.IDENTITY, lines: tuple[int, int] = (3, 3)
) -> Edge:
    return Edge(
        from_column=src,
        to_column=dst,
        kind=kind,
        expression=f"f({src.rsplit('.', 1)[-1]})",
        file=f"models/{dst.split('.')[-2]}.sql",
        lines=lines,
    )


def make_graph(
    edges: list[Edge],
    extra_columns: list[str] | None = None,
    consumes: list[tuple[str, str]] | None = None,
) -> LineageGraph:
    """A LineageGraph from edges alone; every endpoint becomes a column of its model."""
    ids = {c for e in edges for c in (e.from_column, e.to_column)} | set(extra_columns or [])
    columns = {
        c: {"model": c.rsplit(".", 1)[0], "name": c.rsplit(".", 1)[1], "type": "int"} for c in ids
    }
    models = {
        m: {"resource_type": "model", "name": m.split(".")[-1], "file": ""}
        for m in {v["model"] for v in columns.values()}
    }
    return LineageGraph(
        columns=columns,
        edges=edges,
        depends_on=[],
        consumes=consumes or [],
        models=models,
        exposures={x: {"name": x, "type": "dashboard"} for x, _ in consumes or []},
        parse={},
    )


@pytest.fixture
def tiny_graph() -> LineageGraph:
    """seed raw.x -> stg.x2 (RENAME) -> fct.total (AGG); raw.y -> fct.flag; exposure on fct;
    model.q.stg.x2 shares its short id with model.p.stg.x2."""
    return make_graph(
        [
            edge("seed.p.raw.x", "model.p.stg.x2", EdgeKind.RENAME),
            edge("model.p.stg.x2", "model.p.fct.total", EdgeKind.AGGREGATION),
            edge("seed.p.raw.y", "model.p.fct.flag", EdgeKind.TRANSFORMATION),
        ],
        extra_columns=["model.q.stg.x2"],
        consumes=[("exposure.p.dash", "model.p.fct")],
    )


@pytest.fixture(scope="session")
def synthetic_project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """synthetic_shop copied out of the repo, built once, graph cached in its target/."""
    project = tmp_path_factory.mktemp("graph") / "synthetic_shop"
    shutil.copytree(SYNTHETIC, project, ignore=shutil.ignore_patterns("target", "*.duckdb", "logs"))
    build_graph(project).save(cache_path(project))
    return project


@pytest.fixture(scope="session")
def synthetic_graph(synthetic_project: Path) -> LineageGraph:
    return LineageGraph.load(cache_path(synthetic_project))


def with_indirect(g: LineageGraph) -> LineageGraph:
    """The same graph plus indirect edges, built through the public constructor: raw.y decides
    fct.total's rows by a JOIN and a GROUP BY (two types, one pair)."""
    indirect = [
        IndirectEdge(
            from_column="seed.p.raw.y",
            to_column="model.p.fct.total",
            kind=IndirectKind.JOIN,
            key="raw.y",
            expression="on raw.y = stg.x2",
            file="models/fct.sql",
            lines=(4, 5),
            model_level_citation=False,
        ),
        IndirectEdge(
            from_column="seed.p.raw.y",
            to_column="model.p.fct.total",
            kind=IndirectKind.GROUP_BY,
            key="raw.y",
            expression="group by raw.y",
            file="models/fct.sql",
            lines=(6, 6),
            model_level_citation=False,
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
        indirect=indirect,
    )
