import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

import pytest
import yaml

from dlens.ingest import IngestResult, ingest
from dlens.ingest.runner import find_dbt
from dlens.lineage import ParseQuality, compare, extract_lineage

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


@pytest.fixture(scope="module")
def ingested(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, IngestResult]:
    project = tmp_path_factory.mktemp("ss") / "synthetic_shop"  # keep the repo free of target/
    shutil.copytree(CORPUS, project, ignore=shutil.ignore_patterns("target", "*.duckdb", "logs"))
    return project, ingest(project)


def test_catalog_matches_gold_spec(ingested: tuple[Path, IngestResult]) -> None:
    spec_models, spec_seeds = _spec_columns()
    assert len(spec_models) == 15

    _, r = ingested
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


def test_lineage_matches_gold_spec(ingested: tuple[Path, IngestResult]) -> None:
    """Gate (spec §14, v0.1): direct-edge F1 >= 0.95 against the hand-written gold spec."""
    project, r = ingested
    result = extract_lineage(r, project)
    assert all(p.quality == ParseQuality.FULL for p in result.parse_report.values())
    assert not any(e.model_level_citation for e in result.edges)
    gold = yaml.safe_load((CORPUS / "lineage_spec.yml").read_text())["edges"]
    report = compare(result.edges, [g for g in gold if g["phase"] == "v0.1"])
    detail = f"missing={report.missing} extra={report.extra} kinds={report.kind_mismatches}"
    assert report.f1 >= 0.95, detail
    assert report.kind_accuracy >= 0.95, detail
