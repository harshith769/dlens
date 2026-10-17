"""Golden (S06b): citations for a model that lives in a dbt package.

eph_shop vendors a local package ``eph_pkg`` under ``dbt_packages/``. dbt records the package
model's ``original_file_path`` relative to the package (``models/pkg_customer_names.sql``), so the
file a user opens is ``dbt_packages/eph_pkg/models/pkg_customer_names.sql``. The expected lines
below are written by hand from that file, not from engine output:

    1  {{ config(materialized='view') }}
    2
    3  -- eph_pkg: a package model; dbt records its path relative to the package.
    4  select
    5      customer_id,
    6      upper(full_name) as name_upper
    7  from {{ ref('stg_customers') }}
    8  where customer_id is not null

and the root model that reads it, ``models/customer_names.sql``:

    1  select
    2      n.customer_id,
    3      n.name_upper as display_name
    4  from {{ ref('pkg_customer_names') }} as n
"""

from pathlib import Path

import pytest

from dlens.agent.tools.provenance import Provenance
from dlens.graph import LineageGraph, build_graph_from_artifacts

EPH_PROJECT = Path(__file__).parents[1] / "fixtures" / "artifacts" / "eph_shop"
PKG_FILE = "dbt_packages/eph_pkg/models/pkg_customer_names.sql"
ROOT_FILE = "models/customer_names.sql"
STG = "model.eph_shop.stg_customers"
PKG = "model.eph_pkg.pkg_customer_names"
NAMES = "model.eph_shop.customer_names"

# (from, to) -> (file, lines, model_level)
EXPECTED_PKG_DIRECT = {
    (f"{STG}.customer_id", f"{PKG}.customer_id"): (PKG_FILE, (5, 5), False),
    (f"{STG}.full_name", f"{PKG}.name_upper"): (PKG_FILE, (6, 6), False),
}
# (from, to, kind) -> (file, lines, model_level)
EXPECTED_PKG_INDIRECT = {
    (f"{STG}.customer_id", f"{PKG}.name_upper", "FILTER"): (PKG_FILE, (8, 8), False),
}
# column -> (file, line_start, line_end, level), as the agent's Provenance cites it
EXPECTED_PKG_COLUMNS = {
    f"{PKG}.customer_id": (PKG_FILE, 5, 5, "line"),
    f"{PKG}.name_upper": (PKG_FILE, 6, 6, "line"),
}
EXPECTED_ROOT_DIRECT = {
    (f"{PKG}.customer_id", f"{NAMES}.customer_id"): (ROOT_FILE, (2, 2), False),
    (f"{PKG}.name_upper", f"{NAMES}.display_name"): (ROOT_FILE, (3, 3), False),
}


@pytest.fixture(scope="module")
def graph() -> LineageGraph:
    return build_graph_from_artifacts(EPH_PROJECT / "target")[0]


def _direct(
    graph: LineageGraph, into: str
) -> dict[tuple[str, str], tuple[str, tuple[int, int], bool]]:
    return {
        (e.from_column, e.to_column): (e.file, e.lines, e.model_level_citation)
        for e in graph.edges()
        if e.to_column.startswith(into + ".")
    }


def test_package_model_direct_edges_cite_lines_in_the_package(graph: LineageGraph) -> None:
    assert _direct(graph, PKG) == EXPECTED_PKG_DIRECT


def test_package_model_indirect_edges_cite_lines_in_the_package(graph: LineageGraph) -> None:
    got = {
        (e.from_column, e.to_column, str(e.kind)): (e.file, e.lines, e.model_level_citation)
        for e in graph.indirect_edges()
        if e.to_column.startswith(PKG + ".")
    }
    assert got == EXPECTED_PKG_INDIRECT


def test_package_model_file_and_column_citations(graph: LineageGraph) -> None:
    assert (graph.model_info(PKG) or {}).get("file") == PKG_FILE
    prov = Provenance(graph, EPH_PROJECT)
    for col, (file, a, b, level) in EXPECTED_PKG_COLUMNS.items():
        c = prov.column_citation(col)
        assert (c.file, c.line_start, c.line_end, c.level) == (file, a, b, level), col
    for e in graph.edges():
        if e.to_column.startswith(PKG + "."):
            assert prov.edge_citation(e).level == "line"


def test_root_model_reading_a_package_model_cites_its_own_file(graph: LineageGraph) -> None:
    assert _direct(graph, NAMES) == EXPECTED_ROOT_DIRECT
