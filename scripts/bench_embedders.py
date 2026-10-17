"""S07 step 2: compare embedding runtimes for BAAI/bge-small-en-v1.5 (docs/plans/retrieval-design.md).

Runs in throwaway venvs, one per runtime, so it imports nothing from dlens and only the
runtime under test. Modes:

  texts    provisional chunk texts for a corpus (stdlib only; the real chunker lands in step 3):
           model SQL in <=900-char line windows, column cards (model.column/type/description)
           from YAML + catalog.json, model/exposure/docs-block descriptions.
  embed    embed texts with one runtime (st | ort | fastembed); prints timings as JSON and
           writes float32 vectors (.npy) in input order.
  compare  per-text cosine between two vector files (min/mean) and whether the bytes match.
  onnx     dtypes of the ONNX file's initializers (fp32 check).

Usage: see docs/plans/retrieval-design.md, section "Runtime measurement".
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

MODEL_ID = "BAAI/bge-small-en-v1.5"
REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
MAX_CHARS = 900
BATCH = 32


# -- texts -------------------------------------------------------------------------------------


def _windows(lines: list[str], limit: int) -> list[str]:
    out: list[str] = []
    cur: list[str] = []
    size = 0
    for line in lines:
        if cur and size + len(line) + 1 > limit:
            out.append("\n".join(cur))
            cur, size = [], 0
        cur.append(line[:limit])
        size += len(line) + 1
    if cur:
        out.append("\n".join(cur))
    return out


def texts(project: Path, target: Path, out: Path) -> None:
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    catalog_path = target / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8")) if catalog_path.is_file() else {}
    root_name = manifest["metadata"].get("project_name")

    def root_of(pkg: str) -> Path:
        return project if pkg == root_name else project / "dbt_packages" / pkg

    rows: list[str] = []
    nodes = {**manifest["nodes"], **manifest.get("sources", {})}
    cat = {**catalog.get("nodes", {}), **catalog.get("sources", {})}
    for uid in sorted(nodes):
        n = nodes[uid]
        if n["resource_type"] not in ("model", "seed", "source"):
            continue
        path = n.get("original_file_path") or ""
        if n["resource_type"] == "model" and path.endswith(".sql"):
            src = root_of(n["package_name"]) / path
            if src.is_file():
                lines = src.read_text(encoding="utf-8", errors="replace").splitlines()
                rows += [f"{n['name']}\n{w}" for w in _windows(lines, MAX_CHARS)]
        if n.get("description"):
            rows.append(f"{n['name']}\n{n['description']}"[:MAX_CHARS])
        cols = {
            c.lower(): (c, v.get("data_type") or "", v.get("description") or "")
            for c, v in n.get("columns", {}).items()
        }
        for c, v in cat.get(uid, {}).get("columns", {}).items():
            name, dtype, desc = cols.get(c.lower(), (c, "", ""))
            cols[c.lower()] = (name, v.get("type") or dtype, desc)
        for name, dtype, desc in sorted(cols.values()):
            card = f"{n['name']}.{name}"
            if dtype:
                card += f"\ntype: {dtype}"
            if desc:
                card += f"\ndescription: {desc}"
            rows.append(card[:MAX_CHARS])
    for x in manifest.get("exposures", {}).values():
        rows.append(f"exposure {x['name']} ({x['type']})\n{x.get('description', '')}"[:MAX_CHARS])
    for d in manifest.get("docs", {}).values():
        if d["package_name"] != "dbt":
            rows += [
                f"docs {d['name']}\n{w}"
                for w in _windows(d["block_contents"].splitlines(), MAX_CHARS)
            ]
    with out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(json.dumps({"texts": len(rows), "chars": sum(map(len, rows))}))


# -- embed -------------------------------------------------------------------------------------


def _load_texts(path: Path) -> list[str]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def embed(runtime: str, path: Path, out: Path, threads: int) -> None:
    os.environ["OMP_NUM_THREADS"] = str(threads)
    rows = _load_texts(path)
    t0 = time.perf_counter()
    import numpy as np

    if runtime == "st":
        import torch
        from sentence_transformers import SentenceTransformer

        torch.set_num_threads(threads)
        t1 = time.perf_counter()
        model = SentenceTransformer(MODEL_ID, revision=REVISION, device="cpu")
        t2 = time.perf_counter()
        vecs = model.encode(
            rows, batch_size=BATCH, normalize_embeddings=True, convert_to_numpy=True
        )
        version = f"sentence-transformers {sys.modules['sentence_transformers'].__version__}"
        version += f" + torch {torch.__version__}"
    elif runtime == "ort":
        import onnxruntime as ort
        from huggingface_hub import snapshot_download
        from tokenizers import Tokenizer

        t1 = time.perf_counter()
        local = Path(
            snapshot_download(
                MODEL_ID,
                revision=REVISION,
                allow_patterns=[
                    "onnx/model.onnx",
                    "tokenizer.json",
                    "config.json",
                    "sentence_bert_config.json",
                    "1_Pooling/config.json",
                ],
            )
        )
        max_len = json.loads((local / "sentence_bert_config.json").read_text())["max_seq_length"]
        pooling = json.loads((local / "1_Pooling" / "config.json").read_text())
        assert pooling["pooling_mode_cls_token"] and not pooling["pooling_mode_mean_tokens"]
        tok = Tokenizer.from_file(str(local / "tokenizer.json"))
        tok.enable_truncation(max_len)
        tok.enable_padding(pad_id=0, pad_token="[PAD]")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = 1
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        sess = ort.InferenceSession(
            str(local / "onnx" / "model.onnx"), opts, providers=["CPUExecutionProvider"]
        )
        names = {i.name for i in sess.get_inputs()}
        t2 = time.perf_counter()
        # Same batching as sentence-transformers: sort by length, batch, restore order.
        order = sorted(range(len(rows)), key=lambda i: -len(rows[i]))
        vecs = np.zeros((len(rows), 384), dtype=np.float32)
        for s in range(0, len(order), BATCH):
            idx = order[s : s + BATCH]
            enc = tok.encode_batch([rows[i] for i in idx])
            feed = {
                "input_ids": np.array([e.ids for e in enc], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64),
            }
            if "token_type_ids" in names:
                feed["token_type_ids"] = np.array([e.type_ids for e in enc], dtype=np.int64)
            hidden = sess.run(None, feed)[0]
            cls = hidden[:, 0, :]
            vecs[idx] = cls / np.linalg.norm(cls, axis=1, keepdims=True)
        version = f"onnxruntime {ort.__version__}"
    elif runtime == "fastembed":
        from fastembed import TextEmbedding

        t1 = time.perf_counter()
        model = TextEmbedding(
            MODEL_ID, threads=threads, cache_dir=os.environ.get("FASTEMBED_CACHE")
        )
        t2 = time.perf_counter()
        vecs = np.array(list(model.embed(rows, batch_size=BATCH)), dtype=np.float32)
        import fastembed

        version = f"fastembed {fastembed.__version__}"
    else:
        raise SystemExit(f"unknown runtime {runtime}")
    t3 = time.perf_counter()
    vecs = np.ascontiguousarray(vecs, dtype=np.float32)
    np.save(out, vecs)
    print(
        json.dumps(
            {
                "runtime": version,
                "threads": threads,
                "n": len(rows),
                "import_s": round(t1 - t0, 2),
                "load_s": round(t2 - t1, 2),
                "cold_start_s": round(t2 - t0, 2),
                "embed_s": round(t3 - t2, 2),
            }
        )
    )


# -- compare / onnx ----------------------------------------------------------------------------


def compare(a: Path, b: Path) -> None:
    import numpy as np

    x, y = np.load(a), np.load(b)
    cos = (x * y).sum(axis=1) / (np.linalg.norm(x, axis=1) * np.linalg.norm(y, axis=1))
    print(
        json.dumps(
            {
                "n": len(cos),
                "min_cos": float(cos.min()),
                "mean_cos": float(cos.mean()),
                "argmin": int(cos.argmin()),
                "bytes_identical": a.read_bytes() == b.read_bytes(),
            }
        )
    )


def onnx_dtypes(path: Path) -> None:
    import onnx

    m = onnx.load(str(path))
    kinds: dict[str, int] = {}
    for init in m.graph.initializer:
        name = onnx.TensorProto.DataType.Name(init.data_type)
        kinds[name] = kinds.get(name, 0) + 1
    print(json.dumps({"initializers": kinds, "opset": [o.version for o in m.opset_import]}))


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="mode", required=True)
    t = sub.add_parser("texts")
    t.add_argument("--project", type=Path, required=True)
    t.add_argument("--target", type=Path, required=True)
    t.add_argument("--out", type=Path, required=True)
    e = sub.add_parser("embed")
    e.add_argument("--runtime", required=True)
    e.add_argument("--texts", type=Path, required=True)
    e.add_argument("--out", type=Path, required=True)
    e.add_argument("--threads", type=int, default=4)
    c = sub.add_parser("compare")
    c.add_argument("a", type=Path)
    c.add_argument("b", type=Path)
    o = sub.add_parser("onnx")
    o.add_argument("path", type=Path)
    args = p.parse_args()
    if args.mode == "texts":
        texts(args.project, args.target, args.out)
    elif args.mode == "embed":
        embed(args.runtime, args.texts, args.out, args.threads)
    elif args.mode == "compare":
        compare(args.a, args.b)
    else:
        onnx_dtypes(args.path)


if __name__ == "__main__":
    main()
