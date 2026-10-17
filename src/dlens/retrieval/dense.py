"""Dense embeddings: BAAI/bge-small-en-v1.5 on onnxruntime at a pinned revision (ADR 0021).

The model repo's own fp32 ``onnx/model.onnx`` runs on the CPU execution provider with a fixed
thread count. ``tokenizer.json`` is loaded with ``tokenizers``. The model's configs are
reproduced here: CLS pooling, L2 normalisation, ``max_seq_length`` 512. sentence-transformers
is not used; ``tests/fixtures/retrieval/st_reference.npy`` pins agreement with it.

The only network access in DLens retrieval is the first ``snapshot_download`` of the model
into the Hugging Face cache (``$HF_HOME/hub``). With ``HF_HUB_OFFLINE=1`` it never connects.

``DLENS_EMBEDDER=fake`` swaps in :class:`FakeEmbedder` (tests only; the CLI warns loudly).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import numpy as np

MODEL_ID = "BAAI/bge-small-en-v1.5"
MODEL_REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
MODEL_FILES = (
    "onnx/model.onnx",
    "tokenizer.json",
    "config.json",
    "modules.json",
    "sentence_bert_config.json",
    "1_Pooling/config.json",
)
DEFAULT_THREADS = 4  # step 2: two builds at 4 threads are byte-identical (design §3.4)
BATCH = 32
FAKE_WARNING = "fake embedder: test mode, results are not real"


class RetrievalUnavailable(RuntimeError):
    """The retrieval extra (or the model files, offline) is missing; the message says what to do."""


INSTALL_HINT = 'retrieval needs the extra: pip install "dlens-lineage[retrieval]"'


def require_extra() -> None:
    try:
        import bm25s  # noqa: F401
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
        import tokenizers  # noqa: F401
    except ImportError as e:
        raise RetrievalUnavailable(f"{INSTALL_HINT} ({e.name} is not installed)") from e


def threads_from_env() -> int:
    raw = os.environ.get("DLENS_EMBED_THREADS", "")
    return int(raw) if raw.isdigit() and int(raw) > 0 else DEFAULT_THREADS


class Embedder(Protocol):
    name: str  # runtime + versions: part of the index key
    model: str  # model id + revision: part of the index key
    max_length: int
    threads: int

    def embed(self, texts: list[str], query: bool = False) -> np.ndarray: ...

    def n_tokens(self, text: str) -> int: ...


def model_dir(local_files_only: bool | None = None) -> Path:
    """The pinned model snapshot in the HF cache, downloading it once if allowed."""
    from huggingface_hub import snapshot_download

    offline = os.environ.get("HF_HUB_OFFLINE", "").lower() in ("1", "true", "yes")
    try:
        path = snapshot_download(
            MODEL_ID,
            revision=MODEL_REVISION,
            allow_patterns=list(MODEL_FILES),
            local_files_only=offline if local_files_only is None else local_files_only,
        )
    except Exception as e:  # huggingface_hub raises several types for "not cached, offline"
        raise RetrievalUnavailable(
            f"model {MODEL_ID}@{MODEL_REVISION[:12]} is not in the Hugging Face cache and "
            "cannot be downloaded now. Run `dlens search` once with network access (unset "
            "HF_HUB_OFFLINE) to download it (~133 MB, cached under $HF_HOME/hub)."
        ) from e
    return Path(path)


class OnnxEmbedder:
    def __init__(self, threads: int | None = None, local_files_only: bool | None = None) -> None:
        self.threads = threads or threads_from_env()
        os.environ["OMP_NUM_THREADS"] = str(self.threads)
        require_extra()
        import onnxruntime as ort
        import tokenizers

        root = model_dir(local_files_only)
        modules = json.loads((root / "modules.json").read_text())
        pooling = json.loads((root / "1_Pooling" / "config.json").read_text())
        if not pooling.get("pooling_mode_cls_token") or pooling.get("pooling_mode_mean_tokens"):
            raise RetrievalUnavailable(f"{MODEL_ID}: expected CLS pooling, got {pooling}")
        self._normalize = any(m["type"].endswith("Normalize") for m in modules)
        self.max_length = int(
            json.loads((root / "sentence_bert_config.json").read_text())["max_seq_length"]
        )
        self._tok = tokenizers.Tokenizer.from_file(str(root / "tokenizer.json"))
        self._tok.no_truncation()
        self._tok.no_padding()
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = self.threads
        opts.inter_op_num_threads = 1
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self._sess = ort.InferenceSession(
            str(root / "onnx" / "model.onnx"), opts, providers=["CPUExecutionProvider"]
        )
        self._inputs = {i.name for i in self._sess.get_inputs()}
        self.name = f"onnxruntime {ort.__version__} + tokenizers {tokenizers.__version__}"
        self.model = f"{MODEL_ID}@{MODEL_REVISION}"

    def n_tokens(self, text: str) -> int:
        """Wordpieces including [CLS]/[SEP], with no truncation."""
        return len(self._tok.encode(text).ids)

    def embed(self, texts: list[str], query: bool = False) -> np.ndarray:
        import numpy as np

        if query:
            texts = [QUERY_PREFIX + t for t in texts]
        encs = [self._tok.encode(t) for t in texts]
        too_long = [i for i, e in enumerate(encs) if len(e.ids) > self.max_length]
        if too_long:  # never truncate silently: the chunker must have split these
            raise ValueError(f"{len(too_long)} text(s) exceed {self.max_length} wordpieces")
        out = np.zeros((len(texts), 384), dtype=np.float32)
        # sentence-transformers' batching: longest first, so a batch pads to similar lengths.
        order = sorted(range(len(texts)), key=lambda i: (-len(encs[i].ids), i))
        for s in range(0, len(order), BATCH):
            idx = order[s : s + BATCH]
            width = max(len(encs[i].ids) for i in idx)
            ids = np.zeros((len(idx), width), dtype=np.int64)
            mask = np.zeros((len(idx), width), dtype=np.int64)
            for r, i in enumerate(idx):
                n = len(encs[i].ids)
                ids[r, :n] = encs[i].ids
                mask[r, :n] = 1
            feed: dict[str, Any] = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self._inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            cls = self._sess.run(None, feed)[0][:, 0, :]
            if self._normalize:
                cls = cls / np.linalg.norm(cls, axis=1, keepdims=True)
            out[idx] = cls
        return out


_WORD = re.compile(r"[a-z0-9]+")


class FakeEmbedder:
    """Deterministic hashed bag of words (64 dims, normalised). Tests only: no download, no
    model; similar wording gives similar vectors, which is enough to test the plumbing."""

    name = "fake 1"
    model = "fake"
    max_length = 512
    threads = 1
    dim = 64

    def n_tokens(self, text: str) -> int:
        return len(_WORD.findall(text.lower())) + 2

    def embed(self, texts: list[str], query: bool = False) -> np.ndarray:
        import numpy as np

        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for r, t in enumerate(texts):
            for w in _WORD.findall(t.lower()):
                h = int(hashlib.sha1(w.encode()).hexdigest()[:8], 16)
                out[r, h % self.dim] += 1.0 if (h >> 8) % 2 else -1.0
            norm = float(np.linalg.norm(out[r]))
            if norm:
                out[r] /= norm
        return out


def get_embedder(threads: int | None = None) -> Embedder:
    """``DLENS_EMBEDDER=fake`` (tests) or the real onnxruntime embedder."""
    if os.environ.get("DLENS_EMBEDDER") == "fake":
        return FakeEmbedder()
    return OnnxEmbedder(threads)
