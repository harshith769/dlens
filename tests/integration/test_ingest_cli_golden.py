"""`dlens ingest PROJECT_DIR` (DLens runs dbt) is unchanged by S06: its output equals the text
captured on main before artifact ingest landed."""

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dlens.cli import app

pytestmark = pytest.mark.integration

CORPUS = Path(__file__).parents[2] / "corpora" / "jaffle_shop"
# Captured on main at 3f6394a (S06 step 0).
GOLDEN = """models:      5
seeds:       3
sources:     0
exposures:   0
columns:     38
unmapped relations: 0
"""


def test_ingest_project_output_matches_main(tmp_path: Path) -> None:
    project = tmp_path / "jaffle_shop"
    shutil.copytree(CORPUS, project, ignore=shutil.ignore_patterns("target", "*.duckdb", "logs"))
    r = CliRunner().invoke(app, ["ingest", str(project)])
    assert r.exit_code == 0, r.output
    assert r.output == GOLDEN
