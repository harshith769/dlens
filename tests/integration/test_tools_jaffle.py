"""Smoke: every tool runs on a real public-style project and honours the provenance contract."""

import shutil
from pathlib import Path

import pytest

from dlens.agent.tools import Toolbox
from dlens.graph import build_graph

pytestmark = pytest.mark.integration

CORPUS = Path(__file__).parents[2] / "corpora" / "jaffle_shop"


@pytest.fixture(scope="module")
def box(tmp_path_factory: pytest.TempPathFactory) -> Toolbox:
    project = tmp_path_factory.mktemp("jaffle") / "jaffle_shop"
    shutil.copytree(CORPUS, project, ignore=shutil.ignore_patterns("target", "*.duckdb", "logs"))
    return Toolbox(build_graph(project), project)


def test_every_tool_runs_without_error(box: Toolbox) -> None:
    graph = box.graph
    col = next(c for c in graph.columns() if c.endswith("orders.amount") and "model." in c)
    for tool, args in [
        ("resolve_entity", {"text": "order amount"}),
        ("trace_upstream", {"column_id": col}),
        ("impact_downstream", {"column_id": "raw_payments.amount"}),
        ("get_model_sql", {"model_id": "orders", "around_column": "amount"}),
    ]:
        r = box.call(tool, args)
        assert not r.is_error, (tool, r.llm_payload)
    assert box.emitted_ids


def test_every_citation_points_at_a_real_source_file(box: Toolbox) -> None:
    for e in box.graph.edges():
        c = box._prov.edge_citation(e)
        assert (box.project_dir / c.file).is_file() and c.file.startswith("models/")
        assert c.level in ("line", "star", "model")


def test_ids_are_stable_within_a_build(box: Toolbox) -> None:
    a = box.call("trace_upstream", {"column_id": "orders.amount"})
    b = box.call("trace_upstream", {"column_id": "orders.amount"})
    assert a.llm_payload == b.llm_payload and a.llm_payload["paths"]
