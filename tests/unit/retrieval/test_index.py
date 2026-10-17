"""Search index (S07, retrieval-design.md §3-4): BM25 tokens, RRF, the cache key and rebuild
reasons, determinism, the tokenizer gate, and the missing-extra error. Uses FakeEmbedder: no
model download."""

import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("bm25s")
pytest.importorskip("numpy")

from dlens.graph import build_graph_from_artifacts  # noqa: E402
from dlens.retrieval.bm25 import tokenize  # noqa: E402
from dlens.retrieval.dense import (  # noqa: E402
    FakeEmbedder,
    RetrievalUnavailable,
    get_embedder,
    require_extra,
)
from dlens.retrieval.fusion import rrf  # noqa: E402
from dlens.retrieval.index import SearchIndex, rebuild_reason  # noqa: E402

from .conftest import EPH_PROJECT  # noqa: E402


def test_tokenize_keeps_identifiers_whole() -> None:
    toks = tokenize("Where does fct_orders.revenue_finance come from?")
    for t in (
        "fct",
        "orders",
        "revenue",
        "finance",
        "fct_orders",
        "revenue_finance",
        "fct_orders.revenue_finance",
        "come",
    ):
        assert t in toks
    assert "where" not in toks and "does" not in toks


def test_rrf_math_and_tie_break() -> None:
    fused = rrf([["a", "b"], ["b", "c"]], k=60)
    assert [i for i, _ in fused] == ["b", "a", "c"]
    assert fused[0][1] == pytest.approx(1 / 62 + 1 / 61)
    assert [i for i, _ in rrf([["y"], ["x"]])] == ["x", "y"]  # equal scores: by id
    assert rrf([["a", "b", "c"]], depth=2) == [("a", 1 / 61), ("b", 1 / 62)]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    p = tmp_path / "eph_shop"
    shutil.copytree(EPH_PROJECT, p)
    return p


def _open(project: Path, emb=None, **kw):  # type: ignore[no-untyped-def]
    target = project / "target"
    graph = build_graph_from_artifacts(target)[0]
    gfile = project / "target" / "dlens_graph.json"
    if not gfile.exists():
        graph.save(gfile)
    return SearchIndex.open(
        graph=graph,
        graph_file=gfile,
        target_dir=target,
        project_dir=project,
        index_dir=project / "target" / "dlens_index",
        embedder=emb or FakeEmbedder(),
        **kw,
    )


def _tree(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_build_then_reuse_then_rebuild_reasons(project: Path) -> None:
    idx, status = _open(project)
    assert status == "rebuilt: no index yet" and idx.chunks
    assert _open(project)[1] == "index reused"
    assert _open(project, rebuild=True)[1] == "rebuilt: --rebuild"

    schema = project / "models" / "schema.yml"
    schema.write_text(schema.read_text() + "\n# edited\n")
    assert _open(project)[1] == "rebuilt: models/schema.yml changed"

    emb = FakeEmbedder()
    emb.threads = 2
    assert _open(project, emb)[1] == "rebuilt: thread count changed"


def test_reasons_follow_a_fixed_order() -> None:
    base = {"model": "m@1", "manifest_sha256": "a", "files": {"x.sql": "1"}}
    assert rebuild_reason(None, base) == "no index yet"
    assert rebuild_reason(base, base) is None
    assert rebuild_reason(base, {**base, "manifest_sha256": "b"}) == "manifest changed"
    assert rebuild_reason(base, {**base, "model": "m@2"}) == "model revision changed"
    assert rebuild_reason(base, {**base, "files": {}}) == "x.sql removed"
    assert rebuild_reason(base, {**base, "files": {"x.sql": "1", "y.md": "2"}}) == "y.md added"


def test_writes_only_inside_the_index_dir(project: Path) -> None:
    gfile = project / "target" / "dlens_graph.json"
    build_graph_from_artifacts(project / "target")[0].save(gfile)
    before = _tree(project)
    _open(project)
    after = {k: v for k, v in _tree(project).items() if not k.startswith("target/dlens_index/")}
    assert after == before
    assert sorted(p.name for p in (project / "target" / "dlens_index").iterdir()) == [
        "chunks.jsonl",
        "dense.npy",
        "meta.json",
    ]


def test_two_builds_are_byte_identical(tmp_path: Path) -> None:
    trees = []
    for name in ("one", "two"):
        p = tmp_path / name
        shutil.copytree(EPH_PROJECT, p)
        _open(p)
        trees.append(_tree(p / "target" / "dlens_index"))
    assert trees[0] == trees[1]


def test_search_modes_and_kind_filter(project: Path) -> None:
    idx, _ = _open(project)
    hits = idx.search("customer_orders order_seq", k=5)
    assert hits and len(hits) <= 5
    assert [h.rank for h in hits] == list(range(1, len(hits) + 1))
    assert any(h.chunk.column == "model.eph_shop.customer_orders.order_seq" for h in hits)
    for kind in ("model", "column", "doc"):
        assert all(h.chunk.kind == kind for h in idx.search("customer orders", 20, [kind]))
    bm = idx.search("order_seq", k=3, mode="bm25")
    assert bm and all(h.bm25_rank is not None and h.dense_rank is None for h in bm)
    de = idx.search("order_seq", k=3, mode="dense")
    assert de and all(h.dense_rank is not None and h.bm25_rank is None for h in de)
    assert idx.search("zzzz qqqq", mode="bm25") == []


def test_tokenizer_gate_splits_instead_of_truncating(project: Path) -> None:
    class Tight(FakeEmbedder):
        max_length = 24

    idx, _ = _open(project, Tight())
    stats = idx.meta["stats"]
    assert stats["split_by_tokenizer"] > 0
    assert stats["wordpieces_over_max"] == 0
    assert stats["wordpieces_max"] <= 24
    assert all(Tight().n_tokens(c.indexed_text) <= 24 for c in idx.chunks)


def test_meta_records_key_parts_and_wordpieces(project: Path) -> None:
    idx, _ = _open(project)
    key = idx.meta["key"]
    for part in (
        "graph_sha256",
        "manifest_sha256",
        "files",
        "model",
        "chunker_version",
        "runtime",
        "max_length",
        "threads",
    ):
        assert part in key
    assert "models/schema.yml" in key["files"] and "models/docs.md" in key["files"]
    assert idx.meta["stats"]["wordpieces_p95"] <= idx.meta["stats"]["wordpieces_max"]


def test_missing_extra_names_the_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "onnxruntime", None)
    with pytest.raises(RetrievalUnavailable, match=r"dlens-lineage\[retrieval\]"):
        require_extra()


def test_fake_embedder_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DLENS_EMBEDDER", "fake")
    assert isinstance(get_embedder(), FakeEmbedder)
