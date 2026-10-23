"""S13d design measurements (docs/plans/s13d-design.md). Read-only: no source change, nothing
written under eval/runs or eval/reports; only dev.jsonl is read. Parts ``m7``, ``s3`` and
``s2tokens`` are offline (no LLM). ``qwenfit`` and ``seeds`` send prompts to the LOCAL Ollama model
only (no cloud provider, no quota), straight through ``ollama.Client`` as s13c_measure's seed part
did: LLMClient's 3K cap would refuse the S2 prompt, which is what is being measured.

    uv run --extra agent --extra retrieval python scripts/s13d_measure.py --part m7
    ... --part s3 | s2tokens [--work <scratch>] | qwenfit [--variant all] | seeds

Each part prints a markdown section to stdout; the design doc quotes them.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "corpora" / "synthetic_shop"
JIRA = ROOT / "corpora" / "dbt_jira"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

QUESTIONS = ROOT / "eval" / "questions" / "dev.jsonl"
MODEL = "qwen3:4b-instruct-2507-q4_K_M"

S1_QWEN = "eval/runs/s1/pilot/s1-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl"
S1_GEMINI = "eval/runs/s1/pilot/s1-gemini-3-5-flash-lite-dev.jsonl"
S4_QWEN = "eval/runs/s4/s4-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl"
S4_GEMINI = "eval/runs/s4/s4-gemini-3-5-flash-lite-dev.jsonl"
S4_QWEN_S13B = "eval/runs/s4/diagnostic/s13b-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl"
S4_QWEN_S13C = "eval/runs/s4/diagnostic/s13c-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl"

# (label, records, system, views)
RECORD_SETS: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("S1 qwen pilot", S1_QWEN, "s1", ("validated",)),
    ("S1 Gemini pilot", S1_GEMINI, "s1", ("validated",)),
    ("S4 qwen pilot", S4_QWEN, "s4", ("raw", "validated", "augmented")),
    ("S4 Gemini pilot", S4_GEMINI, "s4", ("raw", "validated", "augmented")),
    ("S4 qwen post-S13c (diagnostic)", S4_QWEN_S13C, "s4", ("raw", "validated", "augmented")),
]


def esc(x: Any) -> str:
    return str(x).replace("|", "\\|").replace("\n", " ")


def load(rel: str) -> list[dict[str, Any]]:
    return [json.loads(x) for x in (ROOT / rel).read_text().splitlines() if x.strip()]


def questions() -> list[dict[str, Any]]:
    return [json.loads(x) for x in QUESTIONS.read_text().splitlines() if x.strip()]


def mean(xs: Sequence[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def fmt(x: float | None) -> str:
    return "–" if x is None else f"{x:.3f}"


# -- M7 vs the validator's chunk rule ------------------------------------------------------------


def index_chunks() -> dict[str, dict[str, Any]]:
    path = CORPUS / "target" / "dlens_index" / "chunks.jsonl"
    rows = (json.loads(x) for x in path.read_text().splitlines() if x.strip())
    return {r["id"]: r for r in rows}


def side_chunks(record: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The record's search_docs chunk side records and get_model_sql excerpt side records."""
    chunks: dict[str, Any] = {}
    excerpts: dict[str, Any] = {}
    for step in record.get("steps") or []:
        for res in step.get("results") or []:
            sr = res.get("side_records") or {}
            chunks.update(sr.get("chunks") or {})
            excerpts.update(sr.get("excerpts") or {})
    return chunks, excerpts


def chunk_rule_valid(
    cid: str,
    cit: Mapping[str, Any] | None,
    meta: Mapping[str, Any] | None,
    excerpt: Mapping[str, Any] | None,
    graph: Any,
) -> tuple[bool, str]:
    """Hypothetical M7 excerpt branch = the validator's R3 rule for c_ / s_ (validator.py
    ``_chunk_problem`` and the s_ hash), re-implemented here. M7's file, bounds, model-level
    (invalid) and star rules stay as they are."""
    from dlens.agent.tools.provenance import contains_word, text_sha1

    if cit is None:
        return False, "no citation attached"
    root = CORPUS.resolve()
    path = (root / str(cit.get("file", ""))).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return False, "file missing"
    text = path.read_text(errors="replace")
    lines = text.splitlines()
    a, b = int(cit.get("line_start", 0)), int(cit.get("line_end", 0))
    if not 1 <= a <= b <= len(lines):
        return False, "out of bounds"
    level = cit.get("level", "line")
    if level == "model":
        return False, "model-level citation"
    shown = "\n".join(lines[a - 1 : b])
    if level == "star":
        return ("*" in shown), "star"
    if cid.startswith("s_"):
        want = (excerpt or {}).get("text_sha1")
        if want is None:
            return False, "s_ without a recorded hash"
        return text_sha1(text, a, b) == want, "s_ hash"
    if meta is None:
        return False, "chunk metadata not found"
    if meta.get("kind") == "model":
        info = graph.model_info(str(meta.get("model", ""))) or {}
        return info.get("file") == cit.get("file"), "model chunk: its own file"
    entity = meta.get("column") or (
        meta.get("model") if meta.get("doc_kind") == "model_description" else None
    )
    name = str(entity or "").rsplit(".", 1)[-1]
    if name and not contains_word(shown, name):
        return False, "lines lack the chunk's entity"
    return True, "chunk entity" if name else "doc without an entity"


def m7() -> None:
    import metrics as M
    from dlens.graph import load_or_build

    qs = questions()
    inv, _ = M.load_inventory(CORPUS)
    graph = load_or_build(CORPUS)
    idx = index_chunks()
    print("## M7 vs the validator on chunk / excerpt citations (dev, offline, committed records)\n")
    print("Records are the committed pilot and diagnostic files; nothing is rescored or written.")
    print("A claim 'names a dotted column' when the M3 extractor finds a `model.column` in it.\n")

    split_rows: list[str] = []
    hyp_rows: list[str] = []
    drop_rows: list[str] = []
    for label, rel, system, views in RECORD_SETS:
        records = load(rel)
        joined = M.join(records, qs)
        adapter = M.adapter_for(system)
        official = M.score_run(
            records, qs, corpus_dir=CORPUS, view="validated", adapter=adapter, required=[]
        )
        off_rows = {r["id"]: r for r in official["rows"]}
        for view in views:
            if view != "validated":
                off = M.score_run(
                    records, qs, corpus_dir=CORPUS, view=view, adapter=adapter, required=[]
                )
                off_rows_v = {r["id"]: r for r in off["rows"]}
            else:
                off_rows_v = off_rows
            ans_all: list[float] = []
            ans_dot: list[float] = []
            ans_none: list[float] = []
            ans_hyp: list[float] = []
            micro = Counter[str]()
            changed: list[str] = []
            would_drop_claims = 0
            kept_claims = 0
            emptied: list[str] = []
            for qid, rec in joined.items():
                pred = adapter(rec, view)
                chunks, excerpts = side_chunks(rec)
                seen: dict[str, tuple[bool, bool, bool]] = {}  # cid -> (valid, dotted, hyp)
                claim_bad: list[bool] = []
                for claim in pred.claims:
                    cols = M.extract(claim.get("text", ""), inv).nodes("column")
                    bad_here = False
                    for cid in [i for i in claim.get("ids", []) if i]:
                        if cid.startswith("r_"):
                            continue
                        edge = pred.edges.get(cid)
                        cit = pred.citations.get(cid)
                        res = M.check_citation(cid, cit, edge, cols, CORPUS)
                        if edge is None and cid[:2] in ("c_", "s_") and not res.valid:
                            if res.reason == "excerpt names no column of its claim":
                                bad_here = True
                        if cid in seen:
                            continue
                        hyp = res.valid
                        if edge is None and cid[:2] in ("c_", "s_"):
                            meta = chunks.get(cid) or idx.get(cid)
                            hyp, _ = chunk_rule_valid(cid, cit, meta, excerpts.get(cid), graph)
                            kind = "dotted" if cols else "none"
                            micro[f"{cid[:2]}{kind}_n"] += 1
                            micro[f"{cid[:2]}{kind}_valid"] += res.valid
                        seen[cid] = (res.valid, bool(cols), hyp)
                    claim_bad.append(bad_here)
                answered = pred.kind == "answered"
                checked = len(seen)
                no_cite_no = pred.reach_verdict == "no" and checked == 0
                if not answered or no_cite_no:
                    continue
                v_all = float(checked > 0 and all(v for v, _, _ in seen.values()))
                ans_all.append(v_all)
                dot = [v for v, d, _ in seen.values() if d]
                none = [v for v, d, _ in seen.values() if not d]
                if dot:
                    ans_dot.append(float(all(dot)))
                if none:
                    ans_none.append(float(all(none)))
                v_hyp = float(checked > 0 and all(h for _, _, h in seen.values()))
                ans_hyp.append(v_hyp)
                if v_hyp != v_all:
                    changed.append(f"{qid} {int(v_all)}→{int(v_hyp)}")
                off_v = off_rows_v.get(qid, {}).get("citation_valid_answer")
                assert off_v is None or float(off_v) == v_all, (label, view, qid, off_v, v_all)
                if system == "s4" and view == "validated":
                    model_claims = [
                        b
                        for c, b in zip(pred.claims, claim_bad, strict=True)
                        if c.get("origin") in (None, "model", "repaired", "completed")
                    ]
                    kept_claims += len(model_claims)
                    would_drop_claims += sum(model_claims)
                    if model_claims and all(model_claims):
                        emptied.append(qid)
            summ = off["summary"] if view != "validated" else official["summary"]
            off_mean = (summ.get("citation_valid_answer") or {}).get("mean")
            assert off_mean is None or abs(off_mean - (mean(ans_all) or 0)) < 1e-9, (
                label,
                view,
                off_mean,
                mean(ans_all),
            )
            split_rows.append(
                f"| {label} | {view} | {fmt(mean(ans_all))} ({len(ans_all)}) | "
                f"{fmt(mean(ans_dot))} ({len(ans_dot)}) | "
                f"{fmt(mean(ans_none))} ({len(ans_none)}) | "
                f"c_ {micro['c_dotted_valid']}/{micro['c_dotted_n']}, "
                f"s_ {micro['s_dotted_valid']}/{micro['s_dotted_n']} | "
                f"c_ {micro['c_none_valid']}/{micro['c_none_n']}, "
                f"s_ {micro['s_none_valid']}/{micro['s_none_n']} |"
            )
            hyp_rows.append(
                f"| {label} | {view} | {fmt(mean(ans_all))} | {fmt(mean(ans_hyp))} | "
                f"{esc(', '.join(changed)) or 'none'} |"
            )
            if system == "s4" and view == "validated":
                drop_rows.append(
                    f"| {label} | {would_drop_claims} / {kept_claims} | "
                    f"{len(emptied)} ({esc(', '.join(emptied)) or '–'}) |"
                )

    print("### (a) The split (M7 unchanged; computed here, metrics.py untouched)\n")
    print(
        "Per-answer validity over answered answers (n). 'dotted only' = the answer's citations "
        "first cited by claims naming a dotted column; 'none only' = those first cited by claims "
        "naming none (an answer can be in both). Micro = valid / checked `c_` and `s_` citations "
        "(edges not shown). The unsplit column equals `score_run`'s `citation_valid_answer` "
        "(asserted per question and on the mean).\n"
    )
    print(
        "| records | view | M7 per answer (as scored) | dotted-claim citations only | "
        "no-column-claim citations only | micro, dotted claims | micro, no-column claims |"
    )
    print("|---|---|---|---|---|---|---|")
    print("\n".join(split_rows))
    print("\n### (b) Hypothetical: M7's excerpt branch replaced by the validator's chunk rule\n")
    print(
        "Not a rescoring: the committed pilot table is NOT recomputed. Shows which per-answer "
        "values (qid before→after) and which means would differ if it were.\n"
    )
    print("| records | view | M7 per answer today | under (b) | answers that change |")
    print("|---|---|---|---|---|")
    print("\n".join(hyp_rows))
    print("\n### (c) Validator aligned to M7: validator-kept claims that would fail\n")
    print(
        "S4 validated view, claims of origin model / repaired / completed whose `c_` / `s_` "
        "citation fails M7's 'names a column of its claim' test. Static estimate: no regenerate or "
        "salvage is re-run, so the real outcome could differ. 'Emptied' = every such claim of the "
        "answer fails (it would go to regenerate, then salvage or a 'no verifiable claims' "
        "refusal).\n"
    )
    print("| records | claims that would fail / kept model claims | answers emptied |")
    print("|---|---|---|")
    print("\n".join(drop_rows))
    print()


# -- S3: where S4's index-dependent components acted ---------------------------------------------


def s3() -> None:
    print("## S3: dev questions where S4 used an index-dependent component (offline)\n")
    print(
        "`Toolbox(index=None)` turns off search_docs, the linker's hybrid stage and the F6 docs "
        "step together. Per S4 record set: questions where search_docs ran (LLM-chosen / code "
        "`docs_evidence`), where resolve_entity ran its hybrid stage, and where a hybrid-sourced "
        "candidate was top-1. The union is where S3's tool inputs certainly differ from S4's; "
        "other questions can still differ through the tool prompt (no search_docs step).\n"
    )
    print(
        "| records | search_docs (LLM) | search_docs (code F6) | hybrid stage ran | "
        "hybrid top-1 | union |"
    )
    print("|---|---|---|---|---|---|")
    detail = []
    for label, rel, system, _ in RECORD_SETS:
        if system != "s4":
            continue
        sd_llm: set[str] = set()
        sd_code: set[str] = set()
        hyb: set[str] = set()
        hyb_top: set[str] = set()
        for rec in load(rel):
            qid = rec["question_id"]
            for step in rec.get("steps") or []:
                for res in step.get("results") or []:
                    if res.get("deduped"):
                        continue
                    if res["tool"] == "search_docs":
                        code = step.get("phase") == "code" or res.get("code_initiated")
                        (sd_code if code else sd_llm).add(qid)
                    if res["tool"] == "resolve_entity":
                        p = res.get("llm_payload") or {}
                        if p.get("hybrid") == "used":
                            hyb.add(qid)
                            cands = p.get("candidates") or []
                            if cands and cands[0].get("match") == "hybrid":
                                hyb_top.add(qid)
        union = sd_llm | sd_code | hyb
        key = lambda x: int(x.split("-")[1])  # noqa: E731
        print(
            f"| {label} | {len(sd_llm)} | {len(sd_code)} | {len(hyb)} | {len(hyb_top)} | "
            f"{len(union)} / 96 |"
        )
        detail.append(f"- {label}: union {', '.join(sorted(union, key=key))}")
    print()
    print("\n".join(detail))
    print()


# -- S2: the stuffed prompt -----------------------------------------------------------------------

VARIANTS = ("compiled_files", "model", "model_doc", "all")


def content_key(c: Any) -> tuple[str, int, str, str]:
    """The S2 ordering: file, first line, kind, entity. Never the chunk id."""
    return (c.file, c.line_start, c.kind, c.column or c.model or "")


def variant_chunks(chunks: Sequence[Any], variant: str) -> list[Any]:
    kinds = {"model": {"model"}, "model_doc": {"model", "doc"}, "all": {"model", "column", "doc"}}
    return sorted((c for c in chunks if c.kind in kinds[variant]), key=content_key)


def compiled_files(target: Path) -> list[str]:
    """Every compiled model .sql (tests excluded), as '-- path' + text, sorted by path."""
    out = []
    for p in sorted((target / "compiled").rglob("*.sql")):
        rel = p.relative_to(target / "compiled").as_posix()
        in_models = rel.split("/", 1)[-1].startswith("models/")
        if in_models and ".yml/" not in rel and ".yaml/" not in rel:  # not compiled tests
            out.append(f"-- {rel}\n{p.read_text()}")
    return out


def stuffed(chunks: Sequence[Any], project_dir: Path, variant: str, target: Path) -> list[str]:
    from systems.s1 import render_chunk

    if variant == "compiled_files":
        return compiled_files(target)
    return [render_chunk(c, project_dir) for c in variant_chunks(chunks, variant)]


def synthetic_chunks() -> list[Any]:
    from dlens.retrieval.chunks import Chunk

    return [Chunk.from_json(r) for r in index_chunks().values()]


def jira_build(work: Path) -> tuple[list[Any], Path, Path, int]:
    """dbt_jira built in the scratch dir (as scripts/linker_report.py), then chunked."""
    from dlens.graph import build_graph_from_artifacts
    from dlens.ingest.runner import run_dbt
    from dlens.retrieval.chunks import build_chunks

    project = work / "dbt_jira"
    target = project / "integration_tests" / "target"
    if not (target / "manifest.json").exists():
        shutil.copytree(JIRA, project, symlinks=True, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("target", "logs", "*.duckdb"))  # fmt: skip
        target = run_dbt(project / "integration_tests").target_dir
    graph, _ = build_graph_from_artifacts(target)
    cs = build_chunks(graph, target, target.parent)
    return list(cs.chunks), target.parent, target, len(list(graph.model_ids()))


def first_question() -> str:
    return questions()[0]["question"]


def s2_messages(evidence: Sequence[str]) -> list[Any]:
    from systems.s1 import messages

    return messages(first_question(), evidence)


def s2tokens(work: Path | None) -> None:
    from systems.s1 import est

    print("## S2: size of the stuffed prompt (offline)\n")
    print(
        "Counter: `estimate_tokens` (serialised JSON chars / 3, the per-call cap's counter; it "
        "over-counts), on S1's prompt (system + user template, the dev-01 question) plus the "
        "response schema, with every chunk rendered by S1's `render_chunk` (citation header + "
        "text), ordered by (file, line_start, kind, entity). `compiled_files` = the raw compiled "
        "model SQL from target/compiled (no ids, so it cannot be cited; size reference only).\n"
    )
    print("| corpus | variant | items | chars | est. tokens |")
    print("|---|---|---|---|---|")
    sets: list[tuple[str, list[Any], Path, Path]] = [
        ("synthetic_shop v2", synthetic_chunks(), CORPUS, CORPUS / "target")
    ]
    note = ""
    if work is not None:
        t0 = time.perf_counter()
        chunks, pdir, target, n_models = jira_build(work)
        secs = time.perf_counter() - t0
        note = f"set E (dbt_jira): {n_models} models in the graph, build + chunk {secs:.0f} s"
        sets.append(("set E (dbt_jira)", chunks, pdir, target))
    for name, chunks, pdir, target in sets:
        for v in VARIANTS:
            ev = stuffed(chunks, pdir, v, target)
            msgs = s2_messages(ev)
            chars = sum(len(e) for e in ev)
            print(f"| {name} | {v} | {len(ev)} | {chars:,} | {est(msgs):,} |")
    print()
    if note:
        print(f"- {note}")
    print()


# -- qwenfit (LOCAL Ollama only) ------------------------------------------------------------------

LADDER = (8192, 16384, 32768, 65536)
RUNG_TIMEOUT_S = 600
MIN_PROMPT_TPS = 50.0


def host() -> str:
    import os

    h = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    return h if h.startswith("http") else f"http://{h}"


def ps_state() -> dict[str, Any] | None:
    import httpx

    models = httpx.get(f"{host()}/api/ps", timeout=10).json().get("models", [])
    m = next((x for x in models if x.get("name") == MODEL), None)
    if m is None:
        return None
    size, vram = int(m.get("size", 0)), int(m.get("size_vram", 0))
    return {
        "size_gb": round(size / 1e9, 2),
        "vram_gb": round(vram / 1e9, 2),
        "gpu_pct": round(100 * vram / size, 1) if size else None,
        "context_length": m.get("context_length"),
        "expires_at": m.get("expires_at"),
    }


def ollama_ps_text() -> str:
    try:
        out = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=10)
        return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return "(ollama CLI not available)"


def qwenfit(variant: str) -> None:
    import ollama
    from pydantic import ValidationError

    from systems.s1 import S1_DRAFT_SCHEMA, S1Draft, est

    ev = stuffed(synthetic_chunks(), CORPUS, variant, CORPUS / "target")
    msgs = [m.model_dump(mode="json") for m in s2_messages(ev)]
    expected = est(s2_messages(ev))
    print(f"## S2 on local qwen: does the stuffed prompt fit? (variant `{variant}`)\n")
    print(f"- Model `{MODEL}`, temperature 0, seed 42, `num_predict` 1024, one send per rung.")
    print(f"- Prompt: {len(ev)} items, {expected:,} est. tokens (chars / 3).")
    print(f"- Server before: `{ps_state()}`")
    print(f"- `ollama ps` before:\n\n```\n{ollama_ps_text()}\n```\n")
    before = ps_state()
    client = ollama.Client(host=host(), timeout=RUNG_TIMEOUT_S)
    print(
        "| num_ctx | prompt_eval_count | truncated | done_reason | prompt tok/s | gen tok/s | "
        "size / VRAM (GB) | GPU % | valid S2 JSON | wall s |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|")
    verdict = "no rung reached"
    for n in LADDER:
        t0 = time.perf_counter()
        try:
            r = client.chat(
                model=MODEL,
                messages=msgs,
                format=S1_DRAFT_SCHEMA,
                options={"temperature": 0, "seed": 42, "num_ctx": n, "num_predict": 1024},
                think=False,
            )
        except Exception as e:  # the 10-minute rung timeout, or a server error
            wall = time.perf_counter() - t0
            msg = esc(str(e))[:240]
            name = esc(type(e).__name__)
            print(f"| {n} | – | error | {name}: {msg} | – | – | – | – | – | {wall:.0f} |")
            # Ollama 0.35 rejects a prompt longer than num_ctx (no silent truncation): that rung
            # does not hold it, so try the next one. Anything else (the timeout) stops the ladder.
            if isinstance(e, ollama.ResponseError) and "context" in str(e).lower():
                verdict = f"does not fit at num_ctx {n} (rejected by the server)"
                continue
            verdict = f"num_ctx {n}: {type(e).__name__} after {wall:.0f} s (stop)"
            break
        wall = time.perf_counter() - t0
        state = ps_state() or {}
        pe = int(r.prompt_eval_count or 0)
        p_tps = pe / (r.prompt_eval_duration / 1e9) if r.prompt_eval_duration else 0.0
        g_tps = (r.eval_count or 0) / (r.eval_duration / 1e9) if r.eval_duration else 0.0
        truncated = pe >= n - 1024 - 8  # Ollama keeps at most num_ctx - num_predict of the prompt
        try:
            S1Draft.model_validate_json(r.message.content or "{}")
            ok = "yes"
        except ValidationError:
            ok = "no"
        gpu = state.get("gpu_pct")
        print(
            f"| {n} | {pe:,} | {'yes' if truncated else 'no'} | {r.done_reason} | {p_tps:.0f} | "
            f"{g_tps:.1f} | {state.get('size_gb')} / {state.get('vram_gb')} | {gpu} | {ok} | "
            f"{wall:.0f} |"
        )
        sys.stdout.flush()
        if not truncated:
            verdict = f"fits at num_ctx {n} (GPU {gpu}%, prompt {p_tps:.0f} tok/s)"
            break
        if gpu is not None and gpu < 100 and p_tps < MIN_PROMPT_TPS:
            verdict = f"num_ctx {n}: CPU offload and prompt eval {p_tps:.0f} tok/s < 50 (stop)"
            break
    print(f"\n- Verdict: {verdict}.")
    # restore: unload, and reload at the default 8192 only if it was loaded before
    client.generate(model=MODEL, prompt="", keep_alive=0)
    if before is not None:
        client.chat(
            model=MODEL,
            messages=[{"role": "user", "content": "ok"}],
            options={"temperature": 0, "seed": 42, "num_ctx": 8192, "num_predict": 1},
            think=False,
        )
    print(f"- Server after the restore: `{ps_state()}`")
    print(f"- `ollama ps` after:\n\n```\n{ollama_ps_text()}\n```\n")


# -- seeds (LOCAL Ollama only) --------------------------------------------------------------------

SEEDS = (42, 43, 44)


def seeds(save_dir: Path) -> None:
    import ollama
    import s13c_measure as S13C

    from dlens.agent.answer import DRAFT_SCHEMA
    from dlens.agent.tools import Toolbox
    from systems.s4 import open_graph

    graph, index, _ = open_graph(CORPUS, hybrid=True)
    box = Toolbox(graph, CORPUS, index)
    pilot = {r["question_id"]: r for r in load(S4_QWEN)}
    diag = {r["question_id"]: r for r in load(S4_QWEN_S13B)}
    ids = S13C.DIFFERED + S13C.control_ids(pilot, diag)
    save_dir.mkdir(parents=True, exist_ok=True)
    prompts: dict[str, Any] = {}
    for i in ids:  # built ONCE from the pilot record's tool calls, saved, then sent unchanged
        path = save_dir / f"{i}.json"
        path.write_text(json.dumps(S13C.answer_messages(pilot[i], box), indent=1))
        prompts[i] = json.loads(path.read_text())
    client = ollama.Client(host=host())
    base = {"temperature": 0, "num_ctx": 8192}
    print("## Seeds 42 / 43 / 44 on local qwen (temperature 0, num_ctx 8192)\n")
    print(f"- The S13c 12 prompts ({', '.join(ids)}), rebuilt once on today's tools and saved.")
    print(
        "- Per prompt, strictly one request at a time, in this order: seed 42 (the prompt's first "
        "send: fresh KV cache), seed 42 again (the same prompt is now a cached prefix), 43, 44. "
        "42a vs 42b isolates the cache-state effect; 43 and 44 vs 42b the seed effect."
    )
    print(f"- Server before: `{ps_state()}`\n")
    print("| id | 42b = 42a (cache state) | 43 = 42b | 44 = 42b | 43 = 44 | distinct / 4 |")
    print("|---|---|---|---|---|---|")
    cache_diff = seed_diff = 0
    order = (("42a", 42), ("42b", 42), ("43", 43), ("44", 44))
    for i in ids:
        out = {
            k: client.chat(model=MODEL, messages=prompts[i], format=DRAFT_SCHEMA,
                           options={**base, "seed": s}, think=False).message.content
            for k, s in order
        }  # fmt: skip

        def yn(a: str, b: str, out: dict[str, Any] = out) -> str:
            return "yes" if out[a] == out[b] else "no"

        cache_diff += out["42a"] != out["42b"]
        seed_diff += out["43"] != out["42b"] or out["44"] != out["42b"]
        print(
            f"| {i} | {yn('42b', '42a')} | {yn('43', '42b')} | {yn('44', '42b')} | "
            f"{yn('43', '44')} | {len(set(out.values()))} |"
        )
        sys.stdout.flush()
    print(f"\n- Cache state changed the output on {cache_diff} / {len(ids)} prompts (42a vs 42b).")
    print(f"- A different seed changed it on {seed_diff} / {len(ids)} (43 or 44 vs 42b).\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--part", choices=["m7", "s3", "s2tokens", "qwenfit", "seeds"], required=True)
    ap.add_argument("--work", type=Path, default=None, help="s2tokens: scratch dir for dbt_jira")
    ap.add_argument("--variant", choices=VARIANTS[1:], default="all", help="qwenfit: S2 variant")
    ap.add_argument("--save-dir", type=Path, default=None, help="seeds: where prompts are saved")
    ns = ap.parse_args(argv)
    if ns.part == "seeds" and ns.save_dir is None:
        ap.error("--part seeds needs --save-dir (a scratch dir outside the repo)")
    parts: dict[str, Callable[[], None]] = {
        "m7": m7,
        "s3": s3,
        "s2tokens": lambda: s2tokens(ns.work),
        "qwenfit": lambda: qwenfit(ns.variant),
        "seeds": lambda: seeds(ns.save_dir),
    }
    parts[ns.part]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
