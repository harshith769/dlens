# 0021. Embeddings run on onnxruntime with BAAI's own ONNX export, not sentence-transformers + torch

- Status: Accepted (owner pick, 17 Oct 2026)
- Date: 2026-10-17
- Amends: ADR 0014 ("the `retrieval` extra installs the CPU torch wheel"); spec §12, Embeddings row
- Implemented in: S07 (B1)
- Evidence: docs/plans/retrieval-design.md §3.4, scripts/bench_embedders.py

## Context

ADR 0014 put `bge-small-en-v1.5` on CPU through sentence-transformers and the CPU torch wheel.
In S07 step 2 that was measured against onnxruntime running the model repo's own
`onnx/model.onnx`. The revision is pinned at `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`, and the
file there is fp32: 197 FLOAT initializers, 133 MB. Both were measured as a uv install from this
repo and as a plain `pip install` of the extra from a built wheel. Plain pip ignores
`[tool.uv.sources]`, so on Linux it installs CUDA torch.

| | sentence-transformers 6.1.0 + torch 2.14.1 | onnxruntime 1.31.0 + tokenizers 0.23.3 |
|---|---|---|
| Extra size, uv (torch from the CPU index) | +1,037 MB | +151 MB |
| Extra size, plain pip, fresh Linux venv | +6,010 MB (torch+cu130, 15 nvidia-* wheels, triton) | +176 MB |
| Cold start | 3.95 s | 0.6 s |
| Embed synthetic_shop / dbt_jira (4 threads) | 4.6 s / 17.5–18.1 s | 3.5 s / 14.6–15.6 s |
| Cosine vs sentence-transformers, min | – | 0.99999988 (gate ≥ 0.999 on every chunk: passed) |
| Same vectors twice at 4 threads | byte-identical | byte-identical |

## Decision

The dense embedder is onnxruntime (CPU execution provider, fixed intra-op threads, sequential
execution), with the `tokenizers` library loading the repo's `tokenizer.json`. The model files
come from `huggingface_hub` at the pinned revision. The model's own configs are reproduced in
code: CLS pooling (`1_Pooling/config.json`), L2 normalisation (`modules.json`: `Normalize`), and
`max_seq_length` 512 (`sentence_bert_config.json`). The `retrieval` extra is `bm25s`,
`onnxruntime`, `tokenizers`, `huggingface-hub` and `numpy`. torch, sentence-transformers and
lancedb leave it, so no pytorch-cpu index is needed.

## Consequences

- A user's `pip install dlens-lineage[retrieval]` adds about 176 MB instead of about 6 GB, and
  needs no index-URL instructions.
- We own about 60 lines (tokenise, pad, CLS pool, normalise) that sentence-transformers did for
  us. A test pins them against reference vectors from sentence-transformers.
- Vectors depend on the onnxruntime and tokenizers versions. Both are in the index key, so an
  upgrade rebuilds the index.
- The spec's ablation model `all-MiniLM-L6-v2` uses mean pooling. When it is needed, the embedder
  reads the pooling mode from the model's config instead of assuming CLS, and gets its own
  agreement check.
- Neither option has Intel-mac wheels at these versions, so platform coverage is unchanged.

## Alternatives rejected

- sentence-transformers + CPU torch: 7× larger with uv, 34× larger with plain pip (CUDA torch),
  and 6× slower to start, for vectors that agree to 1e-7.
- fastembed: its default bge-small is a re-export from another repo, not the pinned BAAI
  revision, and it was 3–5× slower here. It was measured as a reference only.
