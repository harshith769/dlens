"""Set-E corpus (fivetran/dbt_jira @ v1.10.2, corpora/dbt_jira/SOURCE.md): it builds offline
from the vendored packages with dbt-duckdb, and artifact ingest reads it (S06, E4a).
Coverage numbers are recorded, not gold: set-E gold is D5b's."""

import shutil
from pathlib import Path

import pytest

from dlens.graph import build_graph_from_artifacts
from dlens.graph.report import coverage_summary
from dlens.ingest.runner import run_dbt

pytestmark = pytest.mark.integration

CORPUS = Path(__file__).parents[2] / "corpora" / "dbt_jira"


def test_dbt_jira_builds_offline_and_ingests(tmp_path: Path) -> None:
    project = tmp_path / "dbt_jira"
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
    kinds = [graph.model_info(u) or {} for u in graph.model_ids()]
    assert sum(k.get("resource_type") == "model" for k in kinds) == 61
    counts = coverage_summary(graph).counts
    assert counts["FAILED"] == 0 and counts["FULL"] >= 60, counts
    # 13 ephemeral models: their columns are graph nodes, reached through their own edges.
    assert any(
        c.startswith("model.jira.int_jira__issue_multiselect_history.") for c in graph.columns()
    )
