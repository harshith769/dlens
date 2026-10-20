"""S1 pipeline health and retrieval diagnostic (S11 step 5). Report only.

Reads the S1 records, their metrics report and dev.jsonl, and writes
``eval/reports/s1_smoke_dev_health.{md,json}``:

* **Pipeline health**: answered / refused / clarification, JSON repairs and failures, provider
  retries, k used, unused budget and stop reason, tokens, LLM calls, latency (uncached only, M15),
  seed-card citations and uncited ids.
* **Retrieval diagnostic**: for each question with a gold ``target`` that has a column card,
  whether that card was shown to the model, retrieved but not shown (it didn't fit), or not
  retrieved, and its rank in the fused list. S1 losses (``fully_correct`` = 0) are then split into
  "retrieval miss" (card not shown) and "LLM miss" (card shown), overall and by wording.

The ranking is recomputed with S1's own frozen settings on the same index, and checked against
the ranks each record stored. This script is outside metrics.py, and nothing here feeds back into
S1's settings (s1-design.md B8).

    uv run --extra retrieval python scripts/s1_diagnostics.py
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

import metrics as M  # noqa: E402
from systems import s1  # noqa: E402

RECORDS = ROOT / "eval" / "runs" / "s1" / "s1-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl"
REPORT = ROOT / "eval" / "reports" / "s1_smoke_dev.json"
OUT = ROOT / "eval" / "reports" / "s1_smoke_dev_health"


def short(column_id: str | None) -> str:
    return ".".join((column_id or "").split(".")[-2:]).lower()


def dist(values: Sequence[float]) -> dict[str, Any]:
    vs = sorted(values)
    if not vs:
        return {"n": 0}
    return {
        "n": len(vs),
        "min": vs[0],
        "p50": M.percentile(vs, 50),
        "p95": M.percentile(vs, 95),
        "max": vs[-1],
        "mean": round(sum(vs) / len(vs), 1),
    }


def health(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    kinds: Counter[str] = Counter()
    stop_reason: Counter[str] = Counter(r["stop_reason"] for r in records)
    budget_stop: Counter[str] = Counter(r["evidence"]["stop"] for r in records)
    seed_cites = uncited = cited_ids = 0
    for r in records:
        a = r["final_answer"]
        kinds[
            "clarification" if a.get("clarification") else "refused" if a["refused"] else "answered"
        ] += 1
        for c in a["claims"]:
            for i in [*c["edge_ids"], *c["chunk_ids"]]:
                cited_ids += 1
                uncited += i not in a["citations"]
        seed_cites += sum(1 for c in a["citations"].values() if c["file"].endswith(".csv"))
    steps = [s for r in records for s in r["steps"]]
    uncached = [r for r in records if r["tokens"]["cached_calls"] == 0]
    return {
        "records": len(records),
        "answer_kinds": dict(kinds),
        "stop_reason": dict(stop_reason),
        "json_parse_failures_first_try": sum(
            any(s["phase"] == "repair" for s in r["steps"]) for r in records
        ),
        "repairs_succeeded": stop_reason.get("repaired", 0),
        "json_failed_after_repair": stop_reason.get("invalid_json", 0),
        "provider_errors_retried": sum(1 for s in steps if s.get("error")),
        "llm_calls": dict(Counter(r["tokens"]["llm_calls"] for r in records)),
        "llm_calls_total": sum(r["tokens"]["llm_calls"] for r in records),
        "k_used": dist([r["evidence"]["k_used"] for r in records]),
        "candidates": dist([r["evidence"]["candidates"] for r in records]),
        "unused_budget_tokens": dist([r["evidence"]["unused_budget_tokens"] for r in records]),
        "budget_stop": dict(budget_stop),
        "est_input_tokens": dist([r["tokens"]["max_est_input"] for r in records]),
        "input_tokens_reported": dist([r["tokens"]["sum_input"] for r in records]),
        "output_tokens": dist([r["tokens"]["sum_output"] for r in records]),
        "latency_ms_uncached": dist([r["timings"]["total_ms"] for r in uncached]),
        "uncached_records": len(uncached),
        "cited_ids": cited_ids,
        "uncited_ids": uncited,
        "seed_card_citations": seed_cites,
    }


def retrieval(
    records: Mapping[str, Mapping[str, Any]],
    questions: Sequence[Mapping[str, Any]],
    rows: Mapping[str, Mapping[str, Any]],
    index: Any,
) -> dict[str, Any]:
    cards: dict[str, str] = {}
    for c in index.chunks:
        if c.kind == "column" and c.column:
            cards.setdefault(short(c.column), c.id)
    per_q: list[dict[str, Any]] = []
    mismatched: list[str] = []
    for q in questions:
        rec = records.get(q["id"])
        if rec is None or not q.get("target"):
            continue
        hits = index.search(q["question"], k=s1.CANDIDATES, kinds=s1.KINDS, mode=s1.MODE)
        ids = [h.chunk.id for h in hits]
        ev = rec["evidence"]
        if [ids[r - 1] for r in ev["ranks"]] != ev["ids"]:
            mismatched.append(q["id"])
        card = cards.get(q["target"].lower())
        rank = ids.index(card) + 1 if card in ids else None
        status = (
            "no card"
            if card is None
            else "shown"
            if card in ev["ids"]
            else "retrieved, not shown"
            if rank is not None
            else "not retrieved"
        )
        fc = (rows.get(q["id"]) or {}).get("metrics", {}).get("fully_correct")
        per_q.append({"id": q["id"], "type": q["type"], "wording": q["wording"],
                      "target": q["target"], "status": status, "rank": rank,
                      "fully_correct": fc})  # fmt: skip

    def split(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        losses = [x for x in items if x["fully_correct"] == 0.0 and x["status"] != "no card"]
        retrieval_miss = sum(1 for x in losses if x["status"] != "shown")
        return {
            "with_card": sum(1 for x in items if x["status"] != "no card"),
            "card_shown": sum(1 for x in items if x["status"] == "shown"),
            "losses": len(losses),
            "retrieval_miss": retrieval_miss,
            "llm_miss": len(losses) - retrieval_miss,
        }

    by_wording: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for x in per_q:
        by_wording[x["wording"]].append(x)
    return {
        "rank_check_mismatches": mismatched,
        "status": dict(Counter(x["status"] for x in per_q)),
        "overall": split(per_q),
        "by_wording": {w: split(xs) for w, xs in sorted(by_wording.items())},
        "questions": per_q,
    }


def _d(d: Mapping[str, Any]) -> str:
    if not d.get("n"):
        return "–"
    return f"{d['min']} / {d['p50']} / {d['p95']} / {d['max']} (mean {d['mean']})"


def _share(a: int, b: int) -> str:
    return f"{a}/{b} = {a / b:.2f}" if b else "–"


def render(result: Mapping[str, Any]) -> str:
    h, r = result["health"], result["retrieval"]
    out = [
        "# S1 smoke run: pipeline health and retrieval diagnostic (S11 step 5)",
        "",
        "Report only; not a metric (scores: `s1_smoke_dev.md`). Generated by "
        "`scripts/s1_diagnostics.py` from the S1 records. Nothing here changes S1's settings "
        "(s1-design.md B8).",
        "",
        "## Pipeline health",
        "",
        "| item | value |",
        "|---|---|",
        f"| records | {h['records']} |",
        f"| answered / refused / clarification | {h['answer_kinds'].get('answered', 0)} / "
        f"{h['answer_kinds'].get('refused', 0)} / {h['answer_kinds'].get('clarification', 0)} |",
        f"| JSON parse failures (first try) | {h['json_parse_failures_first_try']} |",
        f"| repairs that succeeded / still invalid after repair | {h['repairs_succeeded']} / "
        f"{h['json_failed_after_repair']} |",
        f"| provider errors retried | {h['provider_errors_retried']} |",
        f"| LLM calls (total; per question) | {h['llm_calls_total']}; "
        f"{', '.join(f'{k}: {v}' for k, v in sorted(h['llm_calls'].items()))} |",
        f"| k used (min / p50 / p95 / max) | {_d(h['k_used'])} |",
        f"| candidates in the fused list | {_d(h['candidates'])} |",
        f"| unused budget tokens | {_d(h['unused_budget_tokens'])} |",
        f"| budget stop | {', '.join(f'{k}: {v}' for k, v in sorted(h['budget_stop'].items()))} |",
        f"| est. input tokens per call (cap 3000) | {_d(h['est_input_tokens'])} |",
        f"| input tokens reported by the model | {_d(h['input_tokens_reported'])} |",
        f"| output tokens | {_d(h['output_tokens'])} |",
        f"| latency ms, uncached ({h['uncached_records']} records) | "
        f"{_d(h['latency_ms_uncached'])} |",
        f"| cited ids / uncited (not in the shown chunks) | {h['cited_ids']} / "
        f"{h['uncited_ids']} |",
        f"| citations of seed cards (CSV header line) | {h['seed_card_citations']} |",
        f"| stop reasons | {', '.join(f'{k}: {v}' for k, v in sorted(h['stop_reason'].items()))} |",
        "",
        "## Retrieval diagnostic: was the gold target's own column card shown?",
        "",
        "Status over the questions with a gold `target`: "
        + ", ".join(f"{k}: {v}" for k, v in sorted(r["status"].items()))
        + f". Rank check against the records: {len(r['rank_check_mismatches'])} mismatches.",
        "",
        "A loss is a question S1 did not get fully correct (M6 binary). A **retrieval miss** is a "
        "loss where the card was not shown; an **LLM miss** is a loss where it was shown. A "
        "shown card is not the whole evidence a question needs (a trace needs every hop), so "
        "this split is a lower bound on retrieval's share.",
        "",
        "| wording | with card | card shown | losses | retrieval miss | LLM miss |",
        "|---|---|---|---|---|---|",
    ]
    for name, sp in [("**all**", r["overall"]), *r["by_wording"].items()]:
        out.append(
            f"| {name} | {sp['with_card']} | {_share(sp['card_shown'], sp['with_card'])} | "
            f"{sp['losses']} | {_share(sp['retrieval_miss'], sp['losses'])} | "
            f"{_share(sp['llm_miss'], sp['losses'])} |"
        )
    out += [
        "",
        "Per question (rank in the fused list of ≤ 200; – if not retrieved):",
        "",
        "| id | type | wording | target | card | rank | fully correct |",
        "|---|---|---|---|---|---|---|",
    ]
    for x in r["questions"]:
        fc = "–" if x["fully_correct"] is None else f"{x['fully_correct']:.0f}"
        out.append(
            f"| {x['id']} | {x['type']} | {x['wording']} | `{x['target']}` | {x['status']} | "
            f"{x['rank'] or '–'} | {fc} |"
        )
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--records", type=Path, default=RECORDS)
    ap.add_argument("--report", type=Path, default=REPORT)
    ap.add_argument("--out", type=Path, default=OUT)
    ns = ap.parse_args(argv)
    records = [json.loads(x) for x in ns.records.read_text().splitlines() if x.strip()]
    questions = [json.loads(x) for x in s1.QUESTIONS.read_text().splitlines() if x.strip()]
    rows = {r["id"]: r for r in json.loads(ns.report.read_text())["rows"]}
    by_q = {q["id"]: rec for q in questions for rec in records if rec["question"] == q["question"]}
    _, index, status = s1.open_index(s1.ROOT / s1.CORPUS)
    result = {"health": health(records), "retrieval": retrieval(by_q, questions, rows, index),
              "index_status": status}  # fmt: skip
    ns.out.with_suffix(".json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    ns.out.with_suffix(".md").write_text(render(result))
    print(render(result).split("## Retrieval")[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
