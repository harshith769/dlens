import json
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from dlens.cli import app
from dlens.graph import LineageGraph
from dlens.graph.report import build_report

pytestmark = pytest.mark.integration

runner = CliRunner()
JAFFLE = Path(__file__).parents[2] / "corpora" / "jaffle_shop"
GAPS = Path(__file__).parents[2] / "corpora" / "synthetic_shop" / "engine_gaps.yml"


def test_report_on_synthetic_shop(synthetic_project: Path, synthetic_graph: LineageGraph) -> None:
    r = build_report(synthetic_graph)
    assert r.totals.models_by_quality == {"FULL": 49, "TABLE_ONLY": 0, "FAILED": 0}
    assert r.totals.edges == len(synthetic_graph.edges()) == sum(r.totals.edges_by_kind.values())
    # model-level citations are listed in engine_gaps.yml (none since S04)
    known = yaml.safe_load(GAPS.read_text())["model_level_citations"]
    assert r.totals.model_level_citations == len(known)
    assert r.totals.low_confidence_edges == 0
    # S04: the window-key count, computed from WINDOW indirect edges since deferred_indirect was
    # retired, equals its pre-retirement value (14 pairs; checked equal pair by pair before).
    assert r.totals.deferred_indirect == 14
    assert r.totals.indirect_edges == 621 and r.totals.indirect_model_level_citations == 0
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
    assert data["totals"]["deferred_indirect"] == 0  # pre-retirement value (S04)
    assert data["totals"]["indirect_model_level_citations"] == 0  # the {% for %} loop is fine
    text = runner.invoke(app, ["report", "-p", str(project)])
    assert "Parse quality per model:" in text.stdout
