"""Citation coverage (S06b): line-level vs model-level citations and grouped reasons."""

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dlens.cli import app
from dlens.graph import build_graph_from_artifacts
from dlens.graph.citations import (
    KEY_NOT_IN_LINES,
    NO_CLAUSE,
    NO_PROJECT,
    NOT_FOUND,
    NOT_LOCATED,
    LevelCounts,
    _clause_reason,
    citation_coverage,
)

EPH = Path(__file__).parents[1] / "fixtures" / "artifacts" / "eph_shop"
PKG_SQL = "dbt_packages/eph_pkg/models/pkg_customer_names.sql"
runner = CliRunner()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    shutil.copytree(EPH, tmp_path / "eph_shop")
    return tmp_path / "eph_shop"


def test_eph_shop_is_all_line_level_including_the_package_model() -> None:
    graph = build_graph_from_artifacts(EPH / "target")[0]
    cov = citation_coverage(graph, EPH)
    for n in (cov.columns, cov.direct, cov.indirect):
        assert n.total > 0 and n.line == n.total and n.reasons == {}
    # 3 seeds (raw_customers 3 + raw_orders 4 + raw_payments 3 columns): whole CSV by design
    assert cov.seed_source_columns.total == 10
    assert cov.columns.total == 19


def test_no_project_means_every_citation_is_model_level() -> None:
    graph = build_graph_from_artifacts(EPH / "target")[0]
    cov = citation_coverage(graph, None)
    assert cov.columns.line == cov.direct.line == cov.indirect.line == 0
    assert cov.columns.reasons == {NO_PROJECT: cov.columns.total}
    assert cov.indirect.reasons == {NO_PROJECT: cov.indirect.total}


def test_missing_package_file_is_reported_as_not_found(project: Path) -> None:
    (project / PKG_SQL).unlink()
    graph = build_graph_from_artifacts(project / "target")[0]
    cov = citation_coverage(graph, project)
    # pkg_customer_names: 2 columns, 2 direct edges, 1 FILTER edge
    assert cov.columns.reasons == {NOT_FOUND: 2}
    assert cov.direct.reasons == {NOT_FOUND: 2}
    assert cov.indirect.reasons == {NOT_FOUND: 1}


def test_macro_built_select_is_reported_as_such(project: Path) -> None:
    """The source is one macro call (like dbt_jira's stg_*_tmp): no SELECT item to cite."""
    (project / PKG_SQL).write_text("{{ build_names() }}\n")
    graph = build_graph_from_artifacts(project / "target")[0]
    cov = citation_coverage(graph, project)
    assert cov.columns.reasons == {NOT_LOCATED: 2}
    assert cov.direct.reasons == {NOT_LOCATED: 2}
    assert sum(cov.indirect.reasons.values()) == 1
    assert set(cov.indirect.reasons) <= {KEY_NOT_IN_LINES, NO_CLAUSE}


def test_clause_reasons_are_grouped() -> None:
    assert _clause_reason("GROUP_BY GROUP BY 1: source file not found") == NOT_FOUND
    assert _clause_reason("FILTER WHERE x > 0: key 'x' not in source lines 4-4") == KEY_NOT_IN_LINES
    assert _clause_reason("JOIN ON a = b: clause not found in the compiled SQL") == NO_CLAUSE
    assert _clause_reason("JOIN ON a = b: clause lines have no source counterpart") == NO_CLAUSE


def test_level_counts_percent() -> None:
    n = LevelCounts()
    assert n.percent == 100.0  # nothing to cite
    n.add(True)
    n.add(False, "why")
    n.add(False, "why")
    assert (n.total, n.line, n.model, n.reasons) == (3, 1, 2, {"why": 2})
    assert round(n.percent, 1) == 33.3


def test_ingest_and_report_print_citation_coverage(project: Path) -> None:
    target = project / "target"
    r = runner.invoke(app, ["ingest", "--artifacts", str(target)])
    assert r.exit_code == 0, r.output
    assert "citations:   line-level / total" in r.output
    assert "  columns          19 / 19     100.0% line-level" in r.output
    assert "  seed/source      10 columns cite a whole CSV or YAML file (by design)" in r.output
    rep = runner.invoke(app, ["report", "--artifacts", str(target), "--json"])
    assert rep.exit_code == 0, rep.output
    cites = json.loads(rep.output)["citations"]
    assert cites["direct"]["line"] == cites["direct"]["total"] == 19
    text = runner.invoke(app, ["report", "--artifacts", str(target)])
    assert "  indirect         32 / 32     100.0% line-level" in text.output
