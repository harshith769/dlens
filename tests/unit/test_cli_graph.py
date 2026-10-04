import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from conftest import with_indirect
from dlens.cli import app
from dlens.graph import LineageGraph
from dlens.graph.cache import cache_path

runner = CliRunner()


def _project(tmp_path: Path, graph: LineageGraph) -> Path:
    """A project whose cache is fresh, so the CLI never runs dbt."""
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "target").mkdir()
    manifest = tmp_path / "target" / "manifest.json"
    manifest.write_text("{}")
    os.utime(manifest, (2_000_000_000 - 10, 2_000_000_000 - 10))
    graph.save(cache_path(tmp_path))
    os.utime(cache_path(tmp_path), (2_000_000_000, 2_000_000_000))
    return tmp_path


@pytest.fixture
def project(tmp_path: Path, tiny_graph: LineageGraph) -> Path:
    return _project(tmp_path, tiny_graph)


@pytest.fixture
def mixed(tmp_path: Path, tiny_graph: LineageGraph) -> Path:
    """The same project, with indirect edges raw.y -> fct.total (JOIN, GROUP_BY)."""
    return _project(tmp_path / "mixed", with_indirect(tiny_graph))


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


@pytest.mark.parametrize(
    "args", [["trace", "fct.total"], ["impact", "raw.y"], ["impact", "raw.x", "--depth", "1"]]
)
def test_output_without_the_flag_ignores_indirect_edges(
    tmp_path: Path, tiny_graph: LineageGraph, args: list[str]
) -> None:
    """Default off: byte-identical output whether or not the graph holds indirect edges."""
    plain = _project(tmp_path / "plain", tiny_graph)
    mixed = _project(tmp_path / "mixed", with_indirect(tiny_graph))
    a = runner.invoke(app, [*args, "-p", str(plain)])
    b = runner.invoke(app, [*args, "-p", str(mixed)])
    assert a.exit_code == b.exit_code == 0, a.output + b.output
    assert a.stdout == b.stdout
    assert "indirect" not in b.stdout


def test_trace_include_indirect_marks_hops_with_type_and_clause(mixed: Path) -> None:
    r = runner.invoke(app, ["trace", "fct.total", "-p", str(mixed), "--include-indirect"])
    assert r.exit_code == 0, r.output
    lines = r.stdout.splitlines()
    assert "├─ raw.y  [indirect JOIN]  on raw.y = stg.x2  models/fct.sql:4-5" in lines
    assert "└─ raw.y  [indirect GROUP_BY]  group by raw.y  models/fct.sql:6-6" in lines
    assert "[AGGREGATION]" in r.stdout  # direct hops are still there
    assert "2 indirect hop(s) (join/filter/group/sort/window keys)" in lines


def test_impact_include_indirect_reaches_rows_decided_by_a_key(mixed: Path) -> None:
    off = runner.invoke(app, ["impact", "raw.y", "-p", str(mixed)])
    on = runner.invoke(app, ["impact", "raw.y", "-p", str(mixed), "--include-indirect"])
    assert off.exit_code == on.exit_code == 0, off.output + on.output
    assert "1 affected column(s)" in off.stdout
    assert "2 affected column(s)" in on.stdout
    assert "fct.total  [indirect JOIN]  on raw.y = stg.x2  models/fct.sql:4-5" in on.stdout
    assert "1 column(s) reached by an indirect hop" in on.stdout
