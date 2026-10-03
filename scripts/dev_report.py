"""Dev-set report: run `ask` on eval/questions/dev.jsonl and score each answer against its gold.

uv run python scripts/dev_report.py                 # Ollama, cache in eval/cache
uv run python scripts/dev_report.py --only dev-05   # one question
uv run python scripts/dev_report.py --show          # also print each rendered answer
uv run python scripts/dev_report.py --json out.json # per-question rows as JSON

DEV-ONLY scoring for v0.2. It is NOT the benchmark metric (eval/metrics.py is owner-written for
v0.3); see docs/explain/eval-dev.md. Only the local ollama provider is allowed, and the LLM cache
defaults to eval/cache (DLENS_CACHE_DIR), so a re-run makes no model calls.

Per question: verdict correct, pass, gold-edge recall among the final cited edges, cited edges not
in gold, validator outcome, first-draft failures by rule, LLM calls, max estimated input tokens,
latency. Then a summary row, and the R8 measurement: first-draft claims dropped by R8 whose named
columns ARE connected by this question's ledger edges ("completable").

The yes/no check (`expect.yes_no`) is a regex on the first sentence of answer_text: HEURISTIC.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, deque
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
DEV = ROOT / "eval" / "questions" / "dev.jsonl"
RULES = ["R1", "R2", "R3", "R4.hallucinated", "R4.unsupported", "R5", "R6", "R7", "R8", "R9"]
COMPLETION_MAX_HOPS = 4
DECISION_THRESHOLD = 0.10  # fixed in advance (session 5a): completable R8 drops / all claims

Edge = tuple[str, str]  # (from, to) as model.column
EdgeOf = Callable[[str], Edge | None]

_NEGATION = ("not ", "indirect", "no direct", "isn't", "is not", "rather than")
_YES = re.compile(r"^\W*(yes)\b", re.IGNORECASE)
_NO = re.compile(r"^\W*(no)\b|\b(does not|doesn't|is not|isn't|not affect|no path)\b", re.I)


def load_questions(path: Path = DEV) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _pair(e: dict[str, Any]) -> Edge:
    return (e["from"], e["to"])


# -- scoring (pure: no model, no toolbox) -----------------------------------------------------


def verdict_of(answer: dict[str, Any], record: dict[str, Any]) -> str:
    if answer.get("clarification"):
        return "clarification"
    if answer.get("refused"):
        return "refused"
    if (record.get("ambiguity") or {}).get("mode") == "chain":
        return "chain"
    return "answered"


def verdict_ok(q: dict[str, Any], verdict: str, record: dict[str, Any]) -> bool:
    exp = q["expect"]
    want = exp["verdict"]
    if verdict == "refused":
        return want == "refused" or bool(exp.get("or_refused"))
    if want == "chain":
        amb = record.get("ambiguity") or {}
        return verdict == "chain" and amb.get("downstream") == exp.get("downstream")
    if want == "answered":
        mode = (record.get("ambiguity") or {}).get("mode")
        return verdict in ("answered", "chain") and mode in exp.get("modes_ok", [None])
    return verdict == want


def yes_no(answer_text: str) -> str | None:
    """HEURISTIC: 'yes' / 'no' from the first sentence of the answer, else None."""
    first = re.split(r"(?<=[.!?])\s", answer_text.strip(), maxsplit=1)[0]
    if _YES.search(first):
        return "yes"
    if _NO.search(first):
        return "no"
    return None


def direct_claims(q: dict[str, Any], claims: list[dict[str, Any]]) -> list[str]:
    """Claims asserting a forbidden edge 'directly' (no negation)."""
    out = []
    for f, t in (_pair(e) for e in q["expect"].get("forbid_edges", [])):
        for c in claims:
            low = c["text"].lower()
            if f in low and t in low and "direct" in low and not any(n in low for n in _NEGATION):
                out.append(c["text"])
    return out


def score(
    q: dict[str, Any],
    answer: dict[str, Any],
    record: dict[str, Any],
    edge_of: EdgeOf,
    excerpt_models: dict[str, str] | None = None,
) -> dict[str, Any]:
    """One question's row. ``answer`` / ``record`` are the JSON dumps of Answer and RunRecord;
    ``edge_of`` maps an edge id to (from, to); ``excerpt_models`` maps s_ ids to their model."""
    exp, gold = q["expect"], q["gold"]
    verdict = verdict_of(answer, record)
    v_ok = verdict_ok(q, verdict, record)
    claims = [] if answer.get("refused") else answer.get("claims", [])
    cited_ids = [i for c in claims for i in [*c.get("edge_ids", []), *c.get("chunk_ids", [])]]
    cited = {p for i in cited_ids if i.startswith("e_") and (p := edge_of(i)) is not None}
    gold_set = {_pair(e) for e in gold.get("edges", [])}
    also_ok = {_pair(e) for e in gold.get("also_ok", [])}
    recall = len(cited & gold_set) / len(gold_set) if gold_set and verdict != "refused" else None
    extra = sorted(cited - gold_set - also_ok)
    forbidden = {_pair(e) for e in exp.get("forbid_edges", [])}

    reasons: list[str] = []
    if not v_ok:
        reasons.append(f"verdict {verdict} != {exp['verdict']}")
    accepted_refusal = verdict == "refused" and v_ok
    if not accepted_refusal:
        excerpt_hit = bool(exp.get("or_excerpt_of")) and any(
            (excerpt_models or {}).get(i) == exp["or_excerpt_of"] for i in cited_ids
        )
        for group in exp.get("must_cite", []):
            if not cited & {_pair(e) for e in group} and not excerpt_hit:
                reasons.append("missing " + " | ".join(f"{a}->{b}" for a, b in map(_pair, group)))
        if cited & forbidden:
            reasons.append("cites a forbidden edge")
        if exp.get("no_direct_claim") and direct_claims(q, claims):
            reasons.append("claims a direct link")
        if "yes_no" in exp:
            got = yes_no(answer.get("answer_text", ""))
            if got != exp["yes_no"]:
                reasons.append(f"yes/no (heuristic) {got} != {exp['yes_no']}")
    return {
        "id": q["id"],
        "verdict": verdict,
        "verdict_ok": v_ok,
        "pass": not reasons,
        "reasons": reasons,
        "recall": recall,
        "cited_edges": sorted(cited),
        "extra_edges": extra,
        "outcome": validator_outcome(answer, record),
        "first_counts": dict((record.get("validation") or {}).get("counts") or {}),
        "completions": len((record.get("validation") or {}).get("completions") or []),
        "llm_calls": (record.get("tokens") or {}).get("llm_calls", 0),
        "max_in": (record.get("tokens") or {}).get("max_est_input", 0),
        "latency_ms": (record.get("timings") or {}).get("total_ms", 0.0),
        "cached": (record.get("tokens") or {}).get("cached_calls", 0),
    }


def validator_outcome(answer: dict[str, Any], record: dict[str, Any]) -> str:
    v = record.get("validation")
    if not v or v.get("skipped"):
        return "n/a"  # refused or clarified before validation
    if answer.get("refused"):
        return "refused"
    if v.get("warning"):
        return "warning"
    if v.get("regenerated"):
        return "regenerated"
    if v.get("completions"):
        return "completed"
    if v.get("repairs"):
        return "repaired"
    return "pass"


# -- R8 measurement ---------------------------------------------------------------------------


def shortest_path(edges: Iterable[Edge], a: str, b: str, max_hops: int | None) -> int | None:
    """Undirected hop count between columns a and b over ``edges``, or None."""
    adj: dict[str, set[str]] = {}
    for f, t in edges:
        adj.setdefault(f, set()).add(t)
        adj.setdefault(t, set()).add(f)
    if a not in adj or b not in adj:
        return None
    seen, todo = {a: 0}, deque([a])
    while todo:
        x = todo.popleft()
        if x == b:
            return seen[x]
        if max_hops is not None and seen[x] >= max_hops:
            continue
        for y in adj[x]:
            if y not in seen:
                seen[y] = seen[x] + 1
                todo.append(y)
    return None


def r8_drops(record: dict[str, Any], ledger_edges: list[Edge]) -> dict[str, int]:
    """First-draft claims, claims with an R8 failure, and how many of those are completable
    (every named column reaches the first through the ledger's edges; also within 4 hops).
    Claims R8c already completed are counted as completable R8 drops too (``completed``), so the
    rate means the same with and without completion."""
    v = record.get("validation") or {}
    first = v.get("first") or {}
    claims = len((record.get("draft") or {}).get("claims", [])) if v and not v.get("skipped") else 0
    completed = len(first.get("completions", []))
    out = {
        "claims": claims,
        "r8": completed,
        "r8_only": 0,
        "completable": completed,
        "completable_4": completed,
        "completed": completed,
    }
    by_claim: dict[int, list[dict[str, Any]]] = {}
    for f in first.get("failures", []):
        if f.get("claim_index") is not None:
            by_claim.setdefault(f["claim_index"], []).append(f)
    for fails in by_claim.values():
        r8 = [f for f in fails if f["rule"] == "R8"]
        if not r8:
            continue
        out["r8"] += 1
        out["r8_only"] += all(f["rule"] == "R8" for f in fails)
        cols = (r8[0].get("item_id") or "").split(",")
        hops = [shortest_path(ledger_edges, cols[0], c, None) for c in cols[1:]]
        hops4 = [shortest_path(ledger_edges, cols[0], c, COMPLETION_MAX_HOPS) for c in cols[1:]]
        out["completable"] += all(h is not None for h in hops)
        out["completable_4"] += all(h is not None for h in hops4)
    return out


def claim_tiers(record: dict[str, Any]) -> dict[str, int]:
    """First-draft claims split the way the benchmark reports them (spec §8): passing raw (no
    repair, no completion), passing only after an R2r repair, passing only after an R8c
    completion, and failing."""
    v = record.get("validation") or {}
    first = v.get("first") or {}
    out = {"raw": 0, "repaired": 0, "completed": 0, "failed": 0}
    if not v or v.get("skipped"):
        return out
    n = len((record.get("draft") or {}).get("claims", []))
    dropped = set(first.get("dropped_claims", []))
    repaired = {r["claim_index"] for r in first.get("repairs", [])}
    completed = {c["claim_index"] for c in first.get("completions", [])}
    for k in range(n):
        tier = (
            "failed"
            if k in dropped
            else "completed"
            if k in completed
            else "repaired"
            if k in repaired
            else "raw"
        )
        out[tier] += 1
    return out


# -- printing ---------------------------------------------------------------------------------


def _fmt_counts(c: dict[str, int]) -> str:
    return " ".join(f"{k}={n}" for k, n in sorted(c.items())) or "-"


def table(rows: list[dict[str, Any]]) -> str:
    head = (
        "| id | verdict | ok | pass | recall | extra edges | validator | first-draft failures "
        "| compl. | calls | max in | ms |"
    )
    lines = [head, "|" + "---|" * 12]
    for r in rows:
        rec = "-" if r["recall"] is None else f"{r['recall']:.2f}"
        lines.append(
            f"| {r['id']} | {r['verdict']} | {'y' if r['verdict_ok'] else 'n'} | "
            f"{'y' if r['pass'] else 'n'} | {rec} | {len(r['extra_edges'])} | {r['outcome']} | "
            f"{_fmt_counts(r['first_counts'])} | {r['completions']} | {r['llm_calls']} | "
            f"{r['max_in']} | {r['latency_ms']:.0f} |"
        )
    return "\n".join(lines)


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    recalls = [r["recall"] for r in rows if r["recall"] is not None]
    counts: Counter[str] = Counter()
    for r in rows:
        counts.update(r["first_counts"])
    return {
        "questions": len(rows),
        "verdict_ok": sum(r["verdict_ok"] for r in rows),
        "pass": sum(r["pass"] for r in rows),
        "mean_recall": round(sum(recalls) / len(recalls), 3) if recalls else None,
        "extra_edges": sum(len(r["extra_edges"]) for r in rows),
        "outcomes": dict(Counter(r["outcome"] for r in rows)),
        "first_counts": {k: counts[k] for k in RULES if counts[k]},
        "completions": sum(r["completions"] for r in rows),
        "llm_calls": sum(r["llm_calls"] for r in rows),
        "max_in": max((r["max_in"] for r in rows), default=0),
        "latency_ms": round(sum(r["latency_ms"] for r in rows)),
        "cached_calls": sum(r["cached"] for r in rows),
    }


def r8_line(r8: dict[str, int]) -> str:
    rate = r8["completable"] / r8["claims"] if r8["claims"] else 0.0
    done = r8.get("completed", 0)
    decision = "IMPLEMENT completion" if rate >= DECISION_THRESHOLD else "do NOT implement"
    return (
        f"R8: first-draft claims={r8['claims']}, dropped by R8 or completed={r8['r8']} "
        f"(completed by R8c={done}) "
        f"(R8 only={r8['r8_only']}), completable={r8['completable']} "
        f"(within {COMPLETION_MAX_HOPS} hops={r8['completable_4']}); "
        f"completable rate={rate:.1%} vs threshold {DECISION_THRESHOLD:.0%} -> {decision}"
    )


# -- running ----------------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--provider", default="ollama")
    ap.add_argument("--only", help="comma-separated question ids")
    ap.add_argument("--show", action="store_true", help="print each rendered answer")
    ap.add_argument("--json", type=Path, help="write per-question rows and the summary here")
    ns = ap.parse_args()
    if ns.provider != "ollama":
        print("dev_report: only the local ollama provider is allowed", file=sys.stderr)
        return 2
    os.environ.setdefault("DLENS_CACHE_DIR", str(ROOT / "eval" / "cache"))

    from dlens.agent.answer import render
    from dlens.agent.llm import make_client
    from dlens.agent.loop import ask
    from dlens.agent.runlog import RunLogger, runs_dir
    from dlens.agent.tools import Toolbox
    from dlens.graph import load_or_build
    from dlens.lineage import short_id

    questions = load_questions()
    only = set(ns.only.split(",")) if ns.only else None
    project = ROOT / "corpora" / questions[0]["corpus"]
    graph = load_or_build(project)
    client = make_client(ns.provider)
    logger = RunLogger(runs_dir())
    rows: list[dict[str, Any]] = []
    r8 = Counter[str]()
    tiers = Counter[str]()
    for q in questions:
        if only and q["id"] not in only:
            continue
        toolbox = Toolbox(graph, project)
        run = ask(q["question"], client, toolbox, logger, project=str(project))

        def edge_of(i: str, box: Toolbox = toolbox) -> Edge | None:
            rec = box.record(i)
            return (short_id(rec["from"]), short_id(rec["to"])) if rec and "from" in rec else None

        excerpts = {
            w["excerpt_id"]: str(r.llm_payload.get("model"))
            for r in toolbox.log
            if r.tool == "get_model_sql" and not r.is_error
            for w in r.llm_payload.get("windows", [])
        }
        ledger_edges = [p for i in toolbox.emitted_ids if i.startswith("e_") if (p := edge_of(i))]
        answer = run.answer.model_dump(mode="json")
        record = run.record.model_dump(mode="json")
        row = score(q, answer, record, edge_of, excerpts)
        drops = r8_drops(record, ledger_edges)
        r8.update(drops)
        row["r8"] = drops
        row["tiers"] = claim_tiers(record)
        tiers.update(row["tiers"])
        rows.append(row)
        print(f"{q['id']}: {'PASS' if row['pass'] else 'fail'} {'; '.join(row['reasons'])}")
        if ns.show:
            print("\n" + render(run.answer) + "\n")
    print()
    print(table(rows))
    s = summary(rows)
    print()
    print("summary:", json.dumps(s))
    print(r8_line(dict(r8)))
    t = {k: tiers[k] for k in ("raw", "repaired", "completed", "failed")}
    print("first-draft claims: " + " ".join(f"{k}={n}" for k, n in t.items()))
    if ns.json:
        out = {"rows": rows, "summary": s, "r8": dict(r8), "claim_tiers": t}
        ns.json.write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
