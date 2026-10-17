"""Set-E corpus (fivetran/dbt_jira @ v1.10.2, corpora/dbt_jira/SOURCE.md): it builds offline
from the vendored packages with dbt-duckdb, and artifact ingest reads it (S06, E4a).
Coverage numbers are recorded, not gold: set-E gold is D5b's. S06b: package models cite lines in
their files under dbt_packages/jira/, and lineage and the chunker agree on those paths."""

import shutil
from pathlib import Path

import pytest

from dlens.agent.tools.provenance import Provenance
from dlens.graph import LineageGraph, build_graph_from_artifacts
from dlens.graph.citations import KEY_NOT_IN_LINES, NO_CLAUSE, NOT_LOCATED, citation_coverage
from dlens.graph.report import coverage_summary
from dlens.ingest.runner import run_dbt
from dlens.retrieval.chunks import build_chunks

pytestmark = pytest.mark.integration

CORPUS = Path(__file__).parents[2] / "corpora" / "dbt_jira"


@pytest.fixture(scope="module")
def jira(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, LineageGraph]:
    """(target dir, artifact graph), built once for the module."""
    project = tmp_path_factory.mktemp("jira") / "dbt_jira"
    # symlinks=True: integration_tests/dbt_packages/jira is a relative link to the package root.
    shutil.copytree(
        CORPUS,
        project,
        symlinks=True,
        ignore=shutil.ignore_patterns("target", "logs", "*.duckdb"),
    )
    target = run_dbt(project / "integration_tests").target_dir
    graph, info = build_graph_from_artifacts(target)
    assert (info.dialect, info.catalog_less) == ("duckdb", False)
    return target, graph


def test_dbt_jira_builds_offline_and_ingests(jira: tuple[Path, LineageGraph]) -> None:
    graph = jira[1]
    kinds = [graph.model_info(u) or {} for u in graph.model_ids()]
    assert sum(k.get("resource_type") == "model" for k in kinds) == 61
    counts = coverage_summary(graph).counts
    assert counts["FAILED"] == 0 and counts["FULL"] >= 60, counts
    # 13 ephemeral models: their columns are graph nodes, reached through their own edges.
    assert any(
        c.startswith("model.jira.int_jira__issue_multiselect_history.") for c in graph.columns()
    )


def test_chunks_and_lineage_agree_on_every_model_file(jira: tuple[Path, LineageGraph]) -> None:
    target, graph = jira
    chunks = build_chunks(graph, target, target.parent).chunks
    models = [
        u for u in graph.model_ids() if (graph.model_info(u) or {}).get("resource_type") == "model"
    ]
    assert len(models) == 61
    for uid in models:
        file = (graph.model_info(uid) or {}).get("file")
        assert file and file.startswith("dbt_packages/jira/models/"), (uid, file)
        got = {c.file for c in chunks if c.kind == "model" and c.model == uid}
        assert got == {file}, uid
        assert {e.file for e in graph.edges() if graph.model_of(e.to_column) == uid} <= {file}


def test_package_citations_are_line_level_except_macro_built_sql(
    jira: tuple[Path, LineageGraph],
) -> None:
    """Recorded S06b numbers (not gold). Every model-level citation left is SQL a macro writes:
    the 18 stg_*_tmp models are one fivetran_utils.union_connections call, and some clause keys
    come from dbt_utils.group_by(n) or a Jinja loop."""
    target, graph = jira
    cov = citation_coverage(graph, target.parent)
    assert (cov.columns.total, cov.direct.total, cov.indirect.total) == (764, 761, 4830)
    assert (cov.columns.line, cov.direct.line, cov.indirect.line) == (613, 628, 3998)
    assert set(cov.columns.reasons) == set(cov.direct.reasons) == {NOT_LOCATED}
    assert set(cov.indirect.reasons) <= {KEY_NOT_IN_LINES, NO_CLAUSE}
    prov = Provenance(graph, target.parent)
    whole = {e.file for e in graph.edges() if prov.edge_citation(e).level == "model"}
    assert len(whole) == 18 and all(f.endswith("_tmp.sql") for f in whole)
