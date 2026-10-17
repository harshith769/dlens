"""The search index: chunks + dense vectors cached next to the graph, rebuilt only when its key
changes (docs/plans/retrieval-design.md §4).

Layout (written only inside the index dir):
  ``meta.json``    the key, each of its parts, build stats
  ``chunks.jsonl`` chunks sorted by id (rows of ``dense.npy`` follow this order)
  ``dense.npy``    float32 (n, dim), L2-normalised

The key holds the sha256 of graph.json, manifest.json, catalog.json and every chunked file, plus
the model id and revision, CHUNKER_VERSION, the embedding runtime and versions, max length,
thread count, and a hash of all chunk ids (content hashes, so any chunker change rebuilds).
A rebuild names the first part that changed ("rebuilt: manifest changed").
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from dlens.graph import LineageGraph
from dlens.retrieval.chunks import CHUNKER_VERSION, Chunk, build_chunks, refit
from dlens.retrieval.dense import Embedder

if TYPE_CHECKING:
    import numpy as np

INDEX_FORMAT = 1
Mode = Literal["hybrid", "bm25", "dense"]
KINDS = ("model", "column", "doc")


def project_index_dir(project_dir: Path) -> Path:
    return project_dir / "target" / "dlens_index"


def artifact_index_dir(cache_dir: Path) -> Path:
    return cache_dir / "index"


def _sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _p95(values: list[int]) -> int:
    if not values:
        return 0
    s = sorted(values)
    return s[int(0.95 * (len(s) - 1))]


_KEY_ORDER = (
    ("format", "index format"),
    ("chunker_version", "chunker version"),
    ("model", "model revision"),
    ("runtime", "embedding runtime"),
    ("max_length", "max length"),
    ("threads", "thread count"),
    ("graph_sha256", "graph"),
    ("manifest_sha256", "manifest"),
    ("catalog_sha256", "catalog"),
)
_AFTER_FILES = (("chunks_sha256", "chunks"),)


def rebuild_reason(old: dict[str, Any] | None, new: dict[str, Any]) -> str | None:
    """None if the keys match, else what changed first (in a fixed order)."""
    if old is None:
        return "no index yet"
    for part, label in _KEY_ORDER:
        if old.get(part) != new.get(part):
            return f"{label} changed"
    of, nf = old.get("files", {}), new.get("files", {})
    for f in sorted(set(of) | set(nf)):
        if f not in of:
            return f"{f} added"
        if f not in nf:
            return f"{f} removed"
        if of[f] != nf[f]:
            return f"{f} changed"
    for part, label in _AFTER_FILES:
        if old.get(part) != new.get(part):
            return f"{label} changed"
    return None


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    rank: int
    score: float
    bm25_rank: int | None
    dense_rank: int | None
    cosine: float | None = None  # dense similarity to the query (None in bm25 mode); S08 linker


class SearchIndex:
    def __init__(
        self, chunks: list[Chunk], vectors: np.ndarray, meta: dict[str, Any], embedder: Embedder
    ) -> None:
        from dlens.retrieval.bm25 import Bm25

        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors differ in length")
        self.chunks = chunks
        self.vectors = vectors
        self.meta = meta
        self.embedder = embedder
        self._bm25 = Bm25([c.indexed_text for c in chunks])
        self._kind = [c.kind for c in chunks]

    # -- lifecycle -----------------------------------------------------------------------------

    @classmethod
    def open(
        cls,
        *,
        graph: LineageGraph,
        graph_file: Path,
        target_dir: Path,
        project_dir: Path | None,
        index_dir: Path,
        embedder: Embedder,
        dialect: str = "duckdb",
        rebuild: bool = False,
    ) -> tuple[SearchIndex, str]:
        """The cached index if its key is unchanged, else a fresh build written to
        ``index_dir``. Returns the index and ``"index reused"`` or ``"rebuilt: <reason>"``."""
        import numpy as np

        cs = build_chunks(graph, target_dir, project_dir, dialect)
        key: dict[str, Any] = {
            "format": INDEX_FORMAT,
            "chunker_version": CHUNKER_VERSION,
            "model": embedder.model,
            "runtime": embedder.name,
            "max_length": embedder.max_length,
            "threads": embedder.threads,
            "graph_sha256": _sha256(graph_file),
            "manifest_sha256": _sha256(target_dir / "manifest.json"),
            "catalog_sha256": _sha256(target_dir / "catalog.json"),
            "files": cs.files,
            # chunk ids hash their content: catches a chunker change even without a version bump
            "chunks_sha256": hashlib.sha256(
                "\n".join(sorted(c.id for c in cs.chunks)).encode()
            ).hexdigest(),
        }
        old = None
        try:
            old = json.loads((index_dir / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        reason = "--rebuild" if rebuild else rebuild_reason((old or {}).get("key"), key)
        if old is not None and reason is None:
            try:
                chunks = [
                    Chunk.from_json(json.loads(line))
                    for line in (index_dir / "chunks.jsonl").read_text("utf-8").splitlines()
                ]
                vectors = np.load(index_dir / "dense.npy")
                return cls(chunks, vectors, old, embedder), "index reused"
            except (OSError, ValueError, KeyError, TypeError):
                reason = "unreadable index"

        # Gate (rule 4): every chunk fits the model in its own tokenizer; split, never truncate.
        chunks, n_split = refit(cs.chunks, lambda t: embedder.n_tokens(t) <= embedder.max_length)
        pieces = [embedder.n_tokens(c.indexed_text) for c in chunks]
        over = sum(n > embedder.max_length for n in pieces)
        if over:
            raise ValueError(f"{over} chunk(s) still exceed {embedder.max_length} wordpieces")
        vectors = np.ascontiguousarray(
            embedder.embed([c.indexed_text for c in chunks]), dtype=np.float32
        )
        stats = {
            **cs.stats,
            "chunks": len(chunks),
            "split_by_tokenizer": n_split,
            "wordpieces_max": max(pieces, default=0),
            "wordpieces_p95": _p95(pieces),
            "wordpieces_over_max": over,
            "dim": int(vectors.shape[1]) if len(vectors) else 0,
        }
        meta = {"key": key, "stats": stats}
        _write(index_dir, chunks, vectors, meta)
        return cls(chunks, vectors, meta, embedder), f"rebuilt: {reason}"

    # -- search --------------------------------------------------------------------------------

    def _mask(self, kinds: list[str] | None) -> np.ndarray:
        import numpy as np

        if not kinds:
            return np.ones(len(self.chunks), dtype=bool)
        return np.array([k in kinds for k in self._kind], dtype=bool)

    def bm25_ranked(self, query: str, kinds: list[str] | None = None) -> list[int]:
        import numpy as np

        scores = self._bm25.scores(query)
        keep = self._mask(kinds) & (scores > 0)
        idx = np.flatnonzero(keep)
        # chunks are sorted by id, so a stable sort breaks score ties by id
        order = idx[np.argsort(-scores[idx], kind="stable")]
        return [int(i) for i in order]

    def dense_ranked(self, query: str, kinds: list[str] | None = None) -> list[int]:
        return self._dense(query, kinds)[0]

    def _dense(self, query: str, kinds: list[str] | None) -> tuple[list[int], np.ndarray | None]:
        import numpy as np

        if not len(self.chunks):
            return [], None
        q = self.embedder.embed([query], query=True)[0]
        sims = self.vectors @ q
        idx = np.flatnonzero(self._mask(kinds))
        order = idx[np.argsort(-sims[idx], kind="stable")]
        return [int(i) for i in order], sims

    def search(
        self, query: str, k: int = 8, kinds: list[str] | None = None, mode: Mode = "hybrid"
    ) -> list[Hit]:
        from dlens.retrieval.fusion import DEPTH, rrf

        bm = self.bm25_ranked(query, kinds) if mode in ("hybrid", "bm25") else []
        de, sims = self._dense(query, kinds) if mode in ("hybrid", "dense") else ([], None)
        bm_rank = {i: r for r, i in enumerate(bm[:DEPTH], 1)}
        de_rank = {i: r for r, i in enumerate(de[:DEPTH], 1)}
        if mode == "bm25":
            ranked = [(i, 1.0 / r) for i, r in bm_rank.items()]
        elif mode == "dense":
            ranked = [(i, 1.0 / r) for i, r in de_rank.items()]
        else:
            ids = [self.chunks[i].id for i in range(len(self.chunks))]
            pos = {cid: i for i, cid in enumerate(ids)}
            fused = rrf([[ids[i] for i in bm], [ids[i] for i in de]])
            ranked = [(pos[cid], s) for cid, s in fused]
        return [
            Hit(
                self.chunks[i],
                r,
                float(s),
                bm_rank.get(i),
                de_rank.get(i),
                None if sims is None else float(sims[i]),
            )
            for r, (i, s) in enumerate(ranked[:k], 1)
        ]


def _write(index_dir: Path, chunks: list[Chunk], vectors: np.ndarray, meta: dict[str, Any]) -> None:
    """chunks and vectors first, meta.json last: a half-written index fails the key check."""
    import numpy as np

    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / "meta.json").unlink(missing_ok=True)
    tmp = index_dir / f".chunks.{os.getpid()}.tmp"
    tmp.write_text(
        "".join(json.dumps(c.to_json(), sort_keys=True, ensure_ascii=False) + "\n" for c in chunks),
        encoding="utf-8",
    )
    os.replace(tmp, index_dir / "chunks.jsonl")
    tmp_npy = index_dir / f".dense.{os.getpid()}.tmp.npy"
    np.save(tmp_npy, vectors)
    os.replace(tmp_npy, index_dir / "dense.npy")
    (index_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
