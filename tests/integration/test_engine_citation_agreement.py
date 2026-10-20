"""Engine agreement of the star citation rule (s12-design B8), in CI.

On a fresh ingest of synthetic_shop: for each of the 19 star pass-through cards, the engine's
pass-through edge into that column, cited by S4's provenance, has the same range and the same
level (star) as S1's ledger citation. The fixture artifacts can't stand in: their graphs have no
compiled -> source mapping, so their line ranges differ (s12-design §0 B8)."""

import shutil
import sys
from pathlib import Path

import pytest

from dlens.graph import build_graph_from_artifacts
from dlens.ingest import ingest
from dlens.retrieval.chunks import build_chunks

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import citation_audit as audit  # noqa: E402

pytestmark = pytest.mark.integration

CORPUS = Path(__file__).parents[2] / "corpora" / "synthetic_shop"


def test_star_level_matches_the_engine_pass_through_edge(tmp_path: Path) -> None:
    project = tmp_path / "synthetic_shop"  # keep the repo free of target/
    shutil.copytree(CORPUS, project, ignore=shutil.ignore_patterns("target", "*.duckdb", "logs"))
    ingest(project)
    graph = build_graph_from_artifacts(project / "target")[0]
    chunks = build_chunks(graph, project / "target", project).chunks
    assert audit.star_edge_check(chunks, graph, project) == {"star cards": 19, "match": 19}
