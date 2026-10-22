"""S13c: the post-S13c dev diagnostic report (qwen, local) and the S0-linked hybrid-on
diagnostic. NOT a result: labelled re-runs after the S13c changes, shown next to the pilot and the
post-S13b diagnostic for information only. They do not replace the pilot table.

Scores every record file with metrics.py exactly as ``scripts/pilot_table.py`` does, and gives
per-change attribution only where a record shows the mechanism:
- F6: ``stop_reason`` has ``+docs_evidence`` (a code search_docs step);
- F1 (d1): a validation round completed a claim with an indirect edge;
- L1 / L2: a resolve_entity result whose top candidate is ``qualified``, or whose note says no
  model has the dotted name.

    uv run --extra agent python scripts/s13c_diagnostic_report.py --out eval/reports/s13c/diagnostic_dev.md
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "eval"))

import pilot_table as PT  # noqa: E402

RUNS = {
    "pilot": "eval/runs/s4/s4-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl",
    "post-S13b": "eval/runs/s4/diagnostic/s13b-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl",
    "post-S13c": "eval/runs/s4/diagnostic/s13c-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl",
}
S0 = {
    "pilot": "eval/runs/s0/s0-linked-hybrid-dev.jsonl",
    "post-S13c": "eval/runs/s0/diagnostic/s13c/s0-linked-hybrid-dev.jsonl",
}
SYSTEM = "s4-qwen3-4b"
VIEWS = ("raw", "validated", "augmented")
LABEL = "post-S13c dev diagnostic"
ROWS = [
    ("node-set F1", "node_f1"),
    ("trace F1", "trace_f1"),
    ("impact F1", "impact_f1"),
    ("hallucination rate", "hallucination_rate"),
    ("citation valid (answer)", "citation_valid_answer"),
    ("false refusal", "false_refusal"),
    ("refusal acc.", "refusal_correct"),
    ("yes/no", "yesno_correct"),
    ("chain", "chain_correct"),
    ("clarify", "clarify_correct"),
]


def load(rel: str) -> list[dict[str, Any]]:
    return [json.loads(x) for x in (ROOT / rel).read_text().splitlines() if x.strip()]


def manifest(rel: str) -> dict[str, Any]:
    return dict(json.loads((ROOT / rel.replace(".jsonl", ".manifest.json")).read_text()))


def kind(rec: Mapping[str, Any]) -> str:
    fa = rec.get("final_answer") or rec.get("answer") or {}
    if fa.get("refused"):
        return "refused"
    return "clarification" if fa.get("clarification") else "answered"


def hop6(result: Mapping[str, Any]) -> Mapping[str, Any]:
    return result["summary"]["node_f1_by"]["hop_bucket"].get("6+") or {}


def qid(rec: Mapping[str, Any]) -> str:
    return str(rec.get("question_id") or rec["run_id"].rsplit("-dev-", 1)[-1])


def indirect_completions(rec: Mapping[str, Any]) -> list[str]:
    """Claims a validation round completed through an indirect edge (added, or the claim's own
    cited one, which the pre-S13c direct-only adjacency could never bridge through)."""
    edges: dict[str, bool] = {}
    for s in rec.get("steps") or []:
        for r in s.get("results") or []:
            for i, e in ((r.get("side_records") or {}).get("edges") or {}).items():
                edges[i] = edges.get(i, False) or bool(e.get("indirect"))
    cited: dict[str, list[list[str]]] = {"first": [], "second": []}
    if rec.get("draft"):
        cited["first"] = [c.get("ids") or [] for c in rec["draft"].get("claims") or []]
    try:
        regen = json.loads(rec.get("regenerate_draft_raw") or "{}")
        cited["second"] = [c.get("ids") or [] for c in regen.get("claims") or []]
    except ValueError:
        pass
    out = []
    for rnd in ("first", "second"):
        for c in ((rec.get("validation") or {}).get(rnd) or {}).get("completions") or []:
            k = c["claim_index"]
            own = cited[rnd][k] if k < len(cited[rnd]) else []
            # the bridge uses an indirect edge: one it added, or the claim's own cited one
            if any(edges.get(i) for i in [*(c.get("added") or []), *own]):
                out.append(f"{rnd} #{k}")
    return out


def linker_marks(rec: Mapping[str, Any]) -> list[str]:
    out = []
    for s in rec.get("steps") or []:
        for r in s.get("results") or []:
            if r.get("tool") != "resolve_entity":
                continue
            p, side = r.get("llm_payload") or {}, r.get("side_records") or {}
            cands = p.get("candidates") or []
            if (
                cands
                and (side.get("parts") or {}).get(cands[0]["id"], {}).get("tier") == "qualified"
            ):
                out.append(f"L1 `{p.get('query')}` → {cands[0]['id']}")
            if any("no model, seed or source" in n for n in p.get("notes") or []):
                out.append(f"L2 `{p.get('query')}` → no candidate")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ns = ap.parse_args(argv)
    qs = {q["id"]: q for q in load("eval/questions/dev.jsonl")}
    recs = {k: load(v) for k, v in RUNS.items()}
    mans = {k: manifest(v) for k, v in RUNS.items()}
    with tempfile.TemporaryDirectory() as t:
        res = {
            k: {v: PT.score(PT.Row(f"S4 {v}", rel, SYSTEM, v), Path(t) / k) for v in VIEWS}
            for k, rel in RUNS.items()
        }
        s0 = {k: PT.score(PT.Row("S0-linked (hybrid on)", rel, "s0-linked"), Path(t) / f"s0{k}")
              for k, rel in S0.items()}  # fmt: skip

    L = [
        f"# S13c {LABEL} (qwen, dev): not a result",
        "",
        f"> **{LABEL}.** One labelled re-run of the 96 dev questions after the S13c changes"
        " (A1, A2, L2, L1, F1 (d1), F6 gate, seed 42). **Not a result; it does not replace the"
        " pilot table**, and no change was adjusted in response to it. The honest check is the"
        " test set after the 7 Dec 2026 freeze.",
        "",
        "| | pilot | post-S13b | post-S13c |",
        "|---|---|---|---|",
        "| agent sha | " + " | ".join(f"`{mans[k]['agent_code_sha256'][:8]}…`" for k in RUNS) + " |",
        "| model digest | " + " | ".join(f"`{mans[k]['model_identity']['digest'][:12]}`" for k in RUNS) + " |",
        "| sampling | " + " | ".join(json.dumps(mans[k]["model_identity"].get("sampling")) for k in RUNS) + " |",
        "| cache hits / misses | " + " | ".join(f"{mans[k]['cache']['hits']} / {mans[k]['cache']['misses']}" for k in RUNS) + " |",
        "| LLM calls | " + " | ".join(str(sum(r["tokens"].get("llm_calls", 0) for r in recs[k])) for k in RUNS) + " |",
        "",
        "## S4 rows (mean [95% CI] (n))",
        "",
    ]  # fmt: skip
    for v in VIEWS:
        L += [f"### {v}", "", "| row | pilot | post-S13b | " + LABEL + " |", "|---|---|---|---|"]
        for label, key in ROWS:
            L.append(f"| {label} | " + " | ".join(
                PT.cell(res[k][v]["summary"]["metrics"].get(key) or {}) for k in RUNS) + " |")  # fmt: skip
        L.append(
            "| node-set F1, hop 6+ | " + " | ".join(PT.cell(hop6(res[k][v])) for k in RUNS) + " |"
        )
        L.append("")
    fam = {k: Counter(qs[qid(r)]["type"] for r in recs[k] if kind(r) == "refused") for k in RUNS}
    L += ["## Refusals by family (final answers)", "", "| family | pilot | post-S13b | " + LABEL + " |",
          "|---|---|---|---|"]  # fmt: skip
    for f in sorted(set().union(*fam.values()) | {"ask"}):
        L.append(f"| {f} | " + " | ".join(str(fam[k].get(f, 0)) for k in RUNS) + " |")
    L += ["", "**Ask refusals:** " + ", ".join(f"{k} {fam[k].get('ask', 0)} / 12" for k in RUNS)
          + ". Ask is not re-scored (the AI-scored sheet is frozen).", ""]  # fmt: skip

    # per question, post-S13b -> post-S13c (validated)
    pb, pc = res["post-S13b"]["validated"], res["post-S13c"]["validated"]
    nb, nc = PT.per_question(pb, "node_f1"), PT.per_question(pc, "node_f1")
    fb, fc = PT.per_question(pb, "fully_correct"), PT.per_question(pc, "fully_correct")
    rb = {qid(r): r for r in recs["post-S13b"]}
    L += ["## Per question (validated), post-S13b → " + LABEL, "",
          "| id | family | node-set F1 | fully correct | answer kind | moved | record shows |",
          "|---|---|---|---|---|---|---|"]  # fmt: skip
    wrong = []
    for r in recs["post-S13c"]:
        q = qid(r)
        a, b, c, d = nb.get(q), nc.get(q), fb.get(q), fc.get(q)
        k1, k2 = kind(rb[q]), kind(r)
        if not ((a != b and a is not None and b is not None) or (c != d) or k1 != k2):
            continue
        down = (a is not None and b is not None and b < a) or (
            c is not None and d is not None and d < c
        )
        if down:
            wrong.append(q)
        shows = [*linker_marks(r)]
        if "+docs_evidence" in (r.get("stop_reason") or ""):
            shows.append("F6 docs_evidence")
        if ic := indirect_completions(r):
            shows.append("F1 indirect completion " + ", ".join(ic))
        L.append(f"| {q} | {qs[q]['type']} | {PT._f(a)} → {PT._f(b)} | {PT._f(c)} → {PT._f(d)} | "
                 f"{k1} → {k2} | {'**down**' if down else 'up / changed'} | {'; '.join(shows) or '–'} |")  # fmt: skip
    L += ["", "**Moved the wrong way:** " + (", ".join(wrong) if wrong else "none") + ".", ""]
    att = {
        "F6 (`+docs_evidence`)": [qid(r) for r in recs["post-S13c"] if "+docs_evidence" in (r.get("stop_reason") or "")],
        "F1 (indirect completion)": [qid(r) for r in recs["post-S13c"] if indirect_completions(r)],
        "L1 / L2 (linker)": [qid(r) for r in recs["post-S13c"] if linker_marks(r)],
    }  # fmt: skip
    L += ["## Attribution over all 96 (where the record shows the mechanism)", ""]
    L += [f"- **{k}:** {', '.join(v) if v else 'none'}" for k, v in att.items()]
    L += ["", "## S0-linked (hybrid on), no LLM: pilot vs post-S13c", "",
          "| row | pilot | post-S13c |", "|---|---|---|"]  # fmt: skip
    for label, key in ROWS[:1] + [("trace F1", "trace_f1"), ("impact F1", "impact_f1"),
                                  ("refusal acc.", "refusal_correct"), ("false refusal", "false_refusal"),
                                  ("clarify", "clarify_correct")]:  # fmt: skip
        L.append(f"| {label} | " + " | ".join(
            PT.cell(s0[k]["summary"]["metrics"].get(key) or {}) for k in S0) + " |")  # fmt: skip
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.write_text("\n".join(L) + "\n")
    print(f"wrote {ns.out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
