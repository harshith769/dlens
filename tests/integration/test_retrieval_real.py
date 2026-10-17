"""The real embedder (S07, ADR 0021): bge-small-en-v1.5 on onnxruntime at the pinned revision.

Needs the retrieval extra and the model (downloaded once into the HF cache; CI caches it).
Checks: agreement with sentence-transformers reference vectors, the tokenizer gate on
synthetic_shop, byte-identical rebuilds at the default thread count, and a sane top hit.
"""

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration
np = pytest.importorskip("numpy")
pytest.importorskip("onnxruntime")
pytest.importorskip("bm25s")

from dlens.graph import build_graph_from_artifacts  # noqa: E402
from dlens.retrieval.dense import DEFAULT_THREADS, OnnxEmbedder  # noqa: E402
from dlens.retrieval.index import SearchIndex  # noqa: E402

ROOT = Path(__file__).parents[2]
REF = ROOT / "tests" / "fixtures" / "retrieval"
SS_TARGET = ROOT / "tests" / "fixtures" / "artifacts" / "synthetic_shop"
SS_PROJECT = ROOT / "corpora" / "synthetic_shop"


@pytest.fixture(scope="module")
def embedder() -> OnnxEmbedder:
    return OnnxEmbedder(DEFAULT_THREADS)


def test_matches_sentence_transformers_reference(embedder: OnnxEmbedder) -> None:
    ref = json.loads((REF / "st_reference.json").read_text())
    want = np.load(REF / "st_reference.npy")
    got = embedder.embed(ref["texts"])
    cos = (got * want).sum(axis=1)
    assert cos.min() >= 0.9999, cos
    assert np.allclose(np.linalg.norm(got, axis=1), 1.0, atol=1e-5)
    assert embedder.max_length == 512


def test_index_gate_determinism_and_top_hit(embedder: OnnxEmbedder, tmp_path: Path) -> None:
    graph = build_graph_from_artifacts(SS_TARGET)[0]
    gfile = tmp_path / "graph.json"
    graph.save(gfile)
    built = []
    for name in ("a", "b"):
        idx, status = SearchIndex.open(
            graph=graph,
            graph_file=gfile,
            target_dir=SS_TARGET,
            project_dir=SS_PROJECT,
            index_dir=tmp_path / name,
            embedder=embedder,
        )
        assert status == "rebuilt: no index yet"
        built.append(idx)
    stats = built[0].meta["stats"]
    assert stats["wordpieces_over_max"] == 0
    assert stats["wordpieces_max"] <= 512
    for f in ("chunks.jsonl", "dense.npy", "meta.json"):
        assert (tmp_path / "a" / f).read_bytes() == (tmp_path / "b" / f).read_bytes(), f
    hits = built[0].search("stg_payments.amount_usd", k=3)
    assert hits[0].chunk.column == "model.synthetic_shop.stg_payments.amount_usd"
