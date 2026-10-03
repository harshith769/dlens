import shutil
from pathlib import Path

import pytest

from dlens.ingest import ingest
from dlens.lineage import ParseQuality, extract_lineage

pytestmark = pytest.mark.integration

CORPUS = Path(__file__).parents[2] / "corpora" / "jaffle_shop"


def test_ingest_jaffle_shop(tmp_path: Path) -> None:
    project = tmp_path / "jaffle_shop"  # copy so the repo stays free of target/ and *.duckdb
    shutil.copytree(CORPUS, project)
    r = ingest(project)
    assert len(r.manifest.models) == 5
    assert len(r.manifest.seeds) == 3
    assert r.unmapped == []
    assert r.schema["jaffle_shop"]["main"]["orders"]["order_id"] == "INTEGER"
    compiled = r.manifest.nodes["model.jaffle_shop.orders"].compiled_code
    assert compiled
    assert "limit 0" not in compiled  # docs generate recompiled without --empty wrappers

    result = extract_lineage(r, project)
    assert all(p.quality == ParseQuality.FULL for p in result.parse_report.values())
    assert len(result.depends_on) == 8
    assert result.edges
