import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

import pytest
import yaml

from dlens.ingest import ingest
from dlens.ingest.runner import find_dbt

pytestmark = pytest.mark.integration

CORPUS = Path(__file__).parents[2] / "corpora" / "synthetic_shop"


def _spec_columns() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """(models, seeds) -> column names, taken from the gold spec's edge endpoints (names only)."""
    edges = yaml.safe_load((CORPUS / "lineage_spec.yml").read_text())["edges"]
    models: dict[str, set[str]] = defaultdict(set)
    seeds: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        models[edge["to"].split(".")[0]].add(edge["to"].split(".")[1])
        src_table, src_col = edge["from"].split(".")
        if src_table.startswith("raw_"):
            seeds[src_table].add(src_col)
    return dict(models), dict(seeds)


def test_catalog_matches_gold_spec(tmp_path: Path) -> None:
    project = tmp_path / "synthetic_shop"  # copy so the repo stays free of target/ and *.duckdb
    shutil.copytree(CORPUS, project)
    spec_models, spec_seeds = _spec_columns()
    assert len(spec_models) == 15

    r = ingest(project)
    assert r.unmapped == []
    assert {m.name for m in r.manifest.models} == set(spec_models)
    assert {s.name for s in r.manifest.seeds} == set(spec_seeds)

    built = {t.name: {c.name for c in t.columns} for t in r.catalog.tables}
    for name, expected in {**spec_models, **spec_seeds}.items():
        actual = built[name]
        assert not expected - actual, f"{name}: missing columns {sorted(expected - actual)}"
        assert not actual - expected, f"{name}: extra columns {sorted(actual - expected)}"


def test_dbt_tests_pass(tmp_path: Path) -> None:
    """`ingest` skips tests, so run a full build (seeds, models, tests) on real data."""
    project = tmp_path / "synthetic_shop"
    shutil.copytree(CORPUS, project)
    cmd = [str(find_dbt()), "build", "--project-dir", str(project), "--profiles-dir", str(project)]
    result = subprocess.run(cmd, cwd=project, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-1000:]
