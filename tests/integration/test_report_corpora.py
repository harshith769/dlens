import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dlens.cli import app
from dlens.graph import LineageGraph
from dlens.graph.report import build_report

pytestmark = pytest.mark.integration

runner = CliRunner()
JAFFLE = Path(__file__).parents[2] / "corpora" / "jaffle_shop"


def test_report_on_synthetic_shop(synthetic_project: Path, synthetic_graph: LineageGraph) -> None:
    r = build_report(synthetic_graph)
    assert r.totals.models_by_quality == {"FULL": 15, "TABLE_ONLY": 0, "FAILED": 0}
    assert r.totals.edges == len(synthetic_graph.edges()) == sum(r.totals.edges_by_kind.values())
    assert r.totals.model_level_citations == 0
    assert r.totals.low_confidence_edges == 0
    out = runner.invoke(app, ["report", "-p", str(synthetic_project), "--json"])
    assert out.exit_code == 0, out.output
    assert json.loads(out.stdout) == json.loads(r.model_dump_json())


def test_report_on_jaffle_shop(tmp_path: Path) -> None:
    project = tmp_path / "jaffle_shop"  # copy so the repo stays free of target/ and *.duckdb
    shutil.copytree(JAFFLE, project)
    out = runner.invoke(app, ["report", "-p", str(project), "--json"])
    assert out.exit_code == 0, out.output
    data = json.loads(out.stdout)
    assert len(data["models"]) == 5
    assert data["totals"]["models_by_quality"]["FAILED"] == 0
    assert data["totals"]["edges"] > 0
    text = runner.invoke(app, ["report", "-p", str(project)])
    assert "Parse quality per model:" in text.stdout
