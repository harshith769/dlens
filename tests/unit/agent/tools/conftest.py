"""A tiny project on disk plus a graph built by hand (no dbt), for fast tool tests."""

from pathlib import Path

import pytest

from dlens.agent.tools import Toolbox
from dlens.graph import LineageGraph
from dlens.lineage import Edge, EdgeKind, IndirectEdge, IndirectKind

STG = """select
    id as x_id,
    amt as amount
from {{ ref('raw') }}
"""
FCT = """-- totals
select
    sum(amount) as total,
    x_id
from {{ ref('stg') }}
group by x_id
"""
STAR = "select * from {{ ref('fct') }}\n"
RAW = "id,amt\n1,5\n"

P = "model.p"


def edge(src: str, dst: str, kind: EdgeKind, file: str, lines: tuple[int, int], expr: str) -> Edge:
    return Edge(from_column=src, to_column=dst, kind=kind, expression=expr, file=file, lines=lines)


# fct groups by x_id: an indirect GROUP_BY edge from stg.x_id to fct.total (ADR 0020).
GROUP_BY_X_ID = IndirectEdge(
    from_column=f"{P}.stg.x_id",
    to_column=f"{P}.fct.total",
    kind=IndirectKind.GROUP_BY,
    key="stg.x_id",
    expression="group by x_id",
    file="models/fct.sql",
    lines=(6, 6),
    model_level_citation=False,
)


def make_shop(indirect: list[IndirectEdge] | None = None) -> LineageGraph:
    cols = {
        "seed.p.raw.id": ("seed.p.raw", "id"),
        "seed.p.raw.amt": ("seed.p.raw", "amt"),
        f"{P}.stg.x_id": (f"{P}.stg", "x_id"),
        f"{P}.stg.amount": (f"{P}.stg", "amount"),
        f"{P}.fct.total": (f"{P}.fct", "total"),
        f"{P}.fct.x_id": (f"{P}.fct", "x_id"),
        f"{P}.fct_star.total": (f"{P}.fct_star", "total"),
        f"{P}.fct_star.x_id": (f"{P}.fct_star", "x_id"),
    }
    models = {
        "seed.p.raw": {"resource_type": "seed", "name": "raw", "file": "seeds/raw.csv"},
        f"{P}.stg": {"resource_type": "model", "name": "stg", "file": "models/stg.sql"},
        f"{P}.fct": {"resource_type": "model", "name": "fct", "file": "models/fct.sql"},
        f"{P}.fct_star": {"resource_type": "model", "name": "fct_star", "file": "models/star.sql"},
    }
    k = EdgeKind
    edges = [
        edge("seed.p.raw.id", f"{P}.stg.x_id", k.RENAME, "models/stg.sql", (2, 2), "id AS x_id"),
        edge("seed.p.raw.amt", f"{P}.stg.amount", k.RENAME, "models/stg.sql", (3, 3), "amt"),
        edge(
            f"{P}.stg.amount",
            f"{P}.fct.total",
            k.AGGREGATION,
            "models/fct.sql",
            (3, 3),
            "sum(amount)",
        ),
        edge(f"{P}.stg.x_id", f"{P}.fct.x_id", k.IDENTITY, "models/fct.sql", (4, 4), "x_id"),
        edge(
            f"{P}.fct.total", f"{P}.fct_star.total", k.IDENTITY, "models/star.sql", (1, 1), "total"
        ),
        edge(f"{P}.fct.x_id", f"{P}.fct_star.x_id", k.IDENTITY, "models/star.sql", (1, 1), "x_id"),
    ]
    return LineageGraph(
        columns={c: {"model": m, "name": n, "type": "int"} for c, (m, n) in cols.items()},
        edges=edges,
        depends_on=[],
        consumes=[("exposure.p.dash", f"{P}.fct_star")],
        models=models,
        exposures={"exposure.p.dash": {"name": "dash", "type": "dashboard"}},
        parse={},
        indirect=indirect,
    )


@pytest.fixture
def shop_dir(tmp_path: Path) -> Path:
    (tmp_path / "models").mkdir()
    (tmp_path / "seeds").mkdir()
    (tmp_path / "models/stg.sql").write_text(STG)
    (tmp_path / "models/fct.sql").write_text(FCT)
    (tmp_path / "models/star.sql").write_text(STAR)
    (tmp_path / "seeds/raw.csv").write_text(RAW)
    return tmp_path


@pytest.fixture
def shop(shop_dir: Path) -> LineageGraph:
    return make_shop()


@pytest.fixture
def toolbox(shop: LineageGraph, shop_dir: Path) -> Toolbox:
    return Toolbox(shop, shop_dir)
