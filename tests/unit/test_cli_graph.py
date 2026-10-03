import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dlens.cli import app
from dlens.graph import LineageGraph
from dlens.graph.cache import cache_path

runner = CliRunner()


@pytest.fixture
def project(tmp_path: Path, tiny_graph: LineageGraph) -> Path:
    """A project whose cache is fresh, so the CLI never runs dbt."""
    (tmp_path / "target").mkdir()
    manifest = tmp_path / "target" / "manifest.json"
    manifest.write_text("{}")
    os.utime(manifest, (2_000_000_000 - 10, 2_000_000_000 - 10))
    tiny_graph.save(cache_path(tmp_path))
    os.utime(cache_path(tmp_path), (2_000_000_000, 2_000_000_000))
    return tmp_path


def test_trace_prints_the_tree(project: Path) -> None:
    r = runner.invoke(app, ["trace", "fct.total", "-p", str(project)])
    assert r.exit_code == 0, r.output
    assert r.stdout.splitlines()[0] == "fct.total"
    assert "[AGGREGATION]" in r.stdout and "[RENAME]" in r.stdout
    assert "models/fct.sql:3-3" in r.stdout


def test_trace_depth_option(project: Path) -> None:
    r = runner.invoke(app, ["trace", "fct.total", "-p", str(project), "--depth", "1"])
    assert r.exit_code == 0
    assert "[RENAME]" not in r.stdout and "cut at --depth 1" in r.stdout


def test_impact_prints_tree_and_summary(project: Path) -> None:
    r = runner.invoke(app, ["impact", "raw.x", "-p", str(project)])
    assert r.exit_code == 0, r.output
    assert "fct.total" in r.stdout
    assert "2 affected column(s)" in r.stdout
    assert "exposures: exposure.p.dash" in r.stdout


def test_unknown_column_exits_2_with_suggestions(project: Path) -> None:
    r = runner.invoke(app, ["trace", "fct.totl", "-p", str(project)])
    assert r.exit_code == 2
    assert (
        "no column matches" in r.stderr and "Did you mean" in r.stderr and "fct.total" in r.stderr
    )
    assert r.stdout == ""


def test_ambiguous_column_exits_2_with_candidates(project: Path) -> None:
    r = runner.invoke(app, ["impact", "stg.x2", "-p", str(project)])
    assert r.exit_code == 2
    assert "model.p.stg.x2" in r.stderr and "model.q.stg.x2" in r.stderr


def test_full_id_disambiguates(project: Path) -> None:
    r = runner.invoke(app, ["trace", "model.p.stg.x2", "-p", str(project)])
    assert r.exit_code == 0, r.output


def test_depth_must_be_positive(project: Path) -> None:
    r = runner.invoke(app, ["trace", "fct.total", "-p", str(project), "-d", "0"])
    assert r.exit_code == 2
