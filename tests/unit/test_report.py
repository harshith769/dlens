import json
import os
from pathlib import Path

from typer.testing import CliRunner

from conftest import edge, make_graph
from dlens.cli import app
from dlens.graph import LineageGraph
from dlens.graph.cache import cache_path
from dlens.graph.render import render_report
from dlens.graph.report import build_report
from dlens.lineage import Confidence, EdgeKind, ModelParse, ParseQuality

runner = CliRunner()


def _graph() -> LineageGraph:
    ok = edge("seed.p.raw.x", "model.p.good.x", EdgeKind.IDENTITY)
    low = edge("seed.p.raw.y", "model.p.good.y", EdgeKind.RENAME).model_copy(
        update={"confidence": Confidence.LOW, "model_level_citation": True}
    )
    agg = edge("model.p.good.x", "model.p.gap.t", EdgeKind.AGGREGATION)
    g = make_graph([ok, low, agg], extra_columns=["model.p.bad.z"])
    return LineageGraph(
        columns={c: g.nx_graph.nodes[c] for c in g.columns()},
        edges=g.edges(),
        depends_on=[],
        consumes=[],
        models={},
        exposures={},
        parse={
            "model.p.good": ModelParse(
                unique_id="model.p.good",
                quality=ParseQuality.FULL,
                constants=["currency"],
                citation_gaps=["FILTER where amt > 100: key 'amt' not in source lines 3-3"],
            ),
            "model.p.gap": ModelParse(
                unique_id="model.p.gap",
                quality=ParseQuality.TABLE_ONLY,
                reason="t <- table db.main.q is not a dbt node",
                gaps=["t <- table db.main.q is not a dbt node"],
            ),
            "model.p.bad": ModelParse(
                unique_id="model.p.bad", quality=ParseQuality.FAILED, reason="ParseError: boom"
            ),
        },
        deferred=[],
    )


def test_totals() -> None:
    t = build_report(_graph()).totals
    assert t.models_by_quality == {"FULL": 1, "TABLE_ONLY": 1, "FAILED": 1}
    assert t.edges == 3
    assert t.edges_by_kind == {"AGGREGATION": 1, "IDENTITY": 1, "RENAME": 1}
    assert t.model_level_citations == 1
    assert t.low_confidence_edges == 1
    assert t.constants == 1


def test_render_lists_problems_first_with_reasons() -> None:
    out = render_report(build_report(_graph()))
    lines = out.splitlines()
    assert lines[1].split()[:2] == ["bad", "FAILED"]
    assert "reason: ParseError: boom" in out
    assert "gap: t <- table db.main.q is not a dbt node" in out
    assert "Low-confidence edges: 1" in out
    assert "citation gap: FILTER where amt > 100: key 'amt' not in source lines 3-3" in out
    assert "Indirect edges: 0  (model-level citations: 0)" in out


def test_cli_report_json_and_text(tmp_path: Path) -> None:
    (tmp_path / "target").mkdir()
    manifest = tmp_path / "target" / "manifest.json"
    manifest.write_text("{}")
    os.utime(manifest, (2_000_000_000 - 10, 2_000_000_000 - 10))
    _graph().save(cache_path(tmp_path))
    os.utime(cache_path(tmp_path), (2_000_000_000, 2_000_000_000))
    j = runner.invoke(app, ["report", "-p", str(tmp_path), "--json"])
    assert j.exit_code == 0, j.output
    assert json.loads(j.stdout)["totals"]["edges"] == 3
    t = runner.invoke(app, ["report", "-p", str(tmp_path)])
    assert t.exit_code == 0 and "TABLE_ONLY" in t.stdout
