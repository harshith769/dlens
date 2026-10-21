"""S13 prep audit (Phase A): what validation removed from the S12b S4 dev run. Read-only: no LLM,
no S4 change (pilot freeze); it reads records and gold and imports metrics.py helpers only.

1. Every claim of the raw draft (``record.draft``) that is not in the validated answer, by
   outcome:
   - ``dropped``: removed by the validator. Rule = the R-codes the first draft's validation gave
     that claim index; for a regenerated record the second draft's counterpart is shown too.
   - ``rewritten``: regenerated record whose final answer has a model claim with the same dotted
     mentions but other text (owner amendment 5). Counted apart, not in the rule × class table.
   - ``omitted``: the first draft's check passed the claim, the record was regenerated, and the
     regenerated draft has no counterpart.
   - ``not_validated``: the answer was replaced without a check (clarification, refusal).
   Gold class of a dropped claim, from its dotted mentions (M3 extractor, negated mentions
   included): ``consistent`` (every one is in the question's gold set for its primary mode),
   ``inconsistent``, ``no mention``, or ``no gold set`` (Ask, unanswerable).
2. yes/no, 3. dev-46, 4. chain: raw vs validated scores (metrics.score_question) with the
   validation trail of each question that changed.

    uv run python scripts/s13_prep_audit.py \\
        --records eval/runs/s4/s4-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl \\
        --out eval/reports/s13/prep_audit
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

import metrics as M  # noqa: E402

DOTTED_KINDS = ("column", "unknown", "cte")
MODEL_ORIGINS = (None, "model", "repaired", "completed")  # model text; ids repaired or R8c-completed
CLASSES = ("consistent", "inconsistent", "no mention", "no gold set")


def norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().rstrip(".").lower()


def dotted(text: str, inv: M.Inventory) -> list[M.Mention]:
    return [m for m in M.extract(text, inv).mentions if m.kind in DOTTED_KINDS]


def gold_nodes(q: Mapping[str, Any]) -> set[str] | None:
    """The question's gold node set in its primary mode: target, the upstream / downstream /
    inputs sets present, ambiguity candidates and the yes/no endpoints and path. None for Ask and
    unanswerable questions (no primary mode)."""
    mode = M.primary_mode(q)
    if mode is None:
        return None
    gold = q["gold"]
    out = {M.short_id(q["target"])} if q.get("target") else set()
    for name in ("upstream", "downstream"):
        if isinstance(gold.get(name), Mapping):
            out |= M.gold_set(gold, name, mode)
    if gold.get("inputs"):
        out |= M.gold_set(gold, "inputs", mode)
    out |= M.norm(gold.get("candidates") or [])
    reach = gold.get("reach") or {}
    out |= M.norm([x for x in (reach.get("from"), reach.get("to")) if x])
    out |= M.norm(reach.get("path") or [])
    return out


def gold_class(mentions: Sequence[M.Mention], gold: set[str] | None) -> str:
    if gold is None:
        return "no gold set"
    if not mentions:
        return "no mention"
    return "consistent" if all(m.node in gold for m in mentions) else "inconsistent"


def _claim_ids(c: Mapping[str, Any]) -> list[str]:
    return list(c.get("ids") or [*c.get("edge_ids", []), *c.get("chunk_ids", [])])


def _rules(summary: Mapping[str, Any] | None, index: int) -> list[str]:
    if not summary:
        return []
    return sorted({f["rule"] for f in summary.get("failures", []) if f["claim_index"] == index})


def _regen_claims(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = record.get("regenerate_draft_raw")
    if not raw:
        return []
    try:
        return list(
            json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())).get("claims") or []
        )
    except (json.JSONDecodeError, AttributeError):
        return []


def audit_claims(
    record: Mapping[str, Any], q: Mapping[str, Any], inv: M.Inventory
) -> list[dict[str, Any]]:
    """One row per raw-draft claim that is not in the validated answer."""
    draft = record.get("draft") or {}
    claims = draft.get("claims") or []
    if not claims:
        return []
    final = record.get("final_answer") or {}
    model_final = [c for c in final.get("claims") or [] if c.get("origin") in MODEL_ORIGINS]
    final_texts = {norm_text(c.get("text", "")) for c in model_final}
    v = record.get("validation") or {}
    regenerated = bool(v.get("regenerated"))
    gold = gold_nodes(q)
    final_mentions = [
        frozenset(m.node for m in dotted(c.get("text", ""), inv)) for c in model_final
    ]
    regen = _regen_claims(record) if regenerated else []
    regen_mentions = [frozenset(m.node for m in dotted(c.get("text", ""), inv)) for c in regen]
    out = []
    for i, c in enumerate(claims):
        text = c.get("text", "")
        if norm_text(text) in final_texts:
            continue
        ms = dotted(text, inv)
        nodes = frozenset(m.node for m in ms)
        rules = _rules(v.get("first"), i)
        row: dict[str, Any] = {
            "id": q["id"],
            "subtype": q["subtype"],
            "claim_index": i,
            "text": text,
            "ids": _claim_ids(c),
            "mentions": sorted(nodes),
            "negated": sorted({m.node for m in ms if m.negated}),
            "rules": rules,
            "regenerated": regenerated,
            "class": gold_class(ms, gold),
        }
        if not v or v.get("skipped"):
            row["outcome"] = "not_validated"
        elif regenerated and nodes in final_mentions:
            row["outcome"] = "rewritten"
        elif rules or not regenerated:
            row["outcome"] = "dropped"
        else:
            row["outcome"] = "omitted"
        if regenerated and row["outcome"] == "dropped":
            j = next((k for k, n in enumerate(regen_mentions) if n == nodes), None)
            row["second"] = (
                "no counterpart"
                if j is None
                else ("failed " + ", ".join(_rules(v.get("second"), j)))
                if _rules(v.get("second"), j)
                else "passed, not kept"
            )
        out.append(row)
    return out


def score_views(
    record: Mapping[str, Any], q: Mapping[str, Any], inv: M.Inventory, view: Any, corpus: Path
) -> dict[str, dict[str, Any]]:
    out = {}
    for name in ("raw", "validated"):
        row = M.score_question(q, M.from_record(record, name), inv, view, corpus)
        out[name] = {"kind": row["kind"], **row["metrics"]}
    return out


def trail(record: Mapping[str, Any]) -> dict[str, Any]:
    v = record.get("validation") or {}
    return {
        "stop_reason": record.get("stop_reason"),
        "error": record.get("error"),
        "regenerated": v.get("regenerated"),
        "passed": v.get("passed"),
        "first": [
            (f["claim_index"], f["rule"], f["item_id"], f["message"])
            for f in (v.get("first") or {}).get("failures", [])
        ],
        "second": [
            (f["claim_index"], f["rule"], f["item_id"], f["message"])
            for f in (v.get("second") or {}).get("failures", [])
        ],
        "draft_verdict": (record.get("draft") or {}).get("reach_verdict"),
        "final_verdict": (record.get("final_answer") or {}).get("reach_verdict"),
        "final_verdict_source": (record.get("final_answer") or {}).get("reach_verdict_source"),
        "draft_answer": (record.get("draft") or {}).get("answer_text"),
        "final_answer": (record.get("final_answer") or {}).get("answer_text"),
        "final_claims": [
            (c.get("origin"), c.get("text"))
            for c in (record.get("final_answer") or {}).get("claims") or []
        ],
    }


def run(
    records: Sequence[Mapping[str, Any]], questions: Sequence[Mapping[str, Any]], corpus: Path
) -> dict[str, Any]:
    inv, view = M.load_inventory(corpus)
    joined = M.join(records, questions)
    qs = {q["id"]: q for q in questions}
    rows: list[dict[str, Any]] = []
    changed: dict[str, list[dict[str, Any]]] = {"yesno": [], "chain": [], "clarify": []}
    for qid, rec in sorted(joined.items(), key=lambda kv: kv[0]):
        q = qs[qid]
        rows.extend(audit_claims(rec, q, inv))
        key = {"yesno": "yesno_correct", "chain": "chain_correct", "clarify": "clarify_correct"}
        scores = score_views(rec, q, inv, view, corpus)
        for name, metric in key.items():
            if metric in scores["raw"] and scores["raw"].get(metric) != scores["validated"].get(
                metric
            ):
                changed[name].append(
                    {"id": qid, "question": q["question"], "scores": scores, "trail": trail(rec)}
                )
    dropped = [r for r in rows if r["outcome"] == "dropped"]
    table: Counter[tuple[str, str]] = Counter()
    for r in dropped:
        for rule in r["rules"] or ["(no claim-level rule)"]:
            table[(rule, r["class"])] += 1
    dev46 = joined.get("dev-46")
    return {
        "outcomes": dict(Counter(r["outcome"] for r in rows)),
        "dropped_by_class": dict(Counter(r["class"] for r in dropped)),
        "rule_class": {f"{a} | {b}": n for (a, b), n in sorted(table.items())},
        "rows": rows,
        "consistent_dropped": [r for r in dropped if r["class"] == "consistent"],
        "changed": changed,
        "dev46": trail(dev46) if dev46 else None,
        "dev46_rows": [r for r in rows if r["id"] == "dev-46"],
    }


# ---------------------------------------------------------------------------- report
def _esc(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def render(res: Mapping[str, Any], records_name: str) -> str:
    rows = res["rows"]
    rules = sorted({k.split(" | ")[0] for k in res["rule_class"]})
    lines = [
        "# S13 prep audit: what validation removed (S12b S4 qwen dev run)",
        "",
        f"Records: `{records_name}`. Read-only: no LLM call, no S4 change (pilot freeze). "
        "Generated by `scripts/s13_prep_audit.py`.",
        "",
        "## 1. Raw-draft claims missing from the validated answer",
        "",
        "| outcome | claims |",
        "|---|---|",
        *(
            f"| {k} | {res['outcomes'].get(k, 0)} |"
            for k in ("dropped", "rewritten", "omitted", "not_validated")
        ),
        "",
        "Dropped claims by rule × gold class (a claim with several rules counts once per rule):",
        "",
        "| rule | " + " | ".join(CLASSES) + " | total |",
        "|---|" + "---|" * (len(CLASSES) + 1),
    ]
    for rule in rules:
        cells = [res["rule_class"].get(f"{rule} | {c}", 0) for c in CLASSES]
        lines.append(f"| {rule} | " + " | ".join(map(str, cells)) + f" | {sum(cells)} |")
    lines += [
        "",
        "Dropped claims by gold class (each claim once): "
        + ", ".join(f"{c} {res['dropped_by_class'].get(c, 0)}" for c in CLASSES)
        + ".",
        "",
        "### Questions where a gold-consistent claim was dropped",
        "",
        "| id | subtype | # | rules | 2nd draft | ids | claim |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in res["consistent_dropped"]:
        lines.append(
            f"| {r['id']} | {r['subtype']} | {r['claim_index']} | {', '.join(r['rules']) or '–'} | "
            f"{r.get('second', '–')} | {', '.join(r['ids'])} | {_esc(r['text'])} |"
        )
    lines += [
        "",
        "### Every missing claim",
        "",
        "| id | # | outcome | class | rules | mentions | claim |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['id']} | {r['claim_index']} | {r['outcome']} | {r['class']} | "
            f"{', '.join(r['rules']) or '–'} | {', '.join(r['mentions']) or '–'} | {_esc(r['text'])} |"
        )
    titles = {
        "yesno": "2. yes/no: raw vs validated",
        "chain": "4. Chain: raw vs validated",
        "clarify": "Clarify: raw vs validated",
    }
    for name in ("yesno", "chain", "clarify"):
        lines += ["", f"## {titles[name]}", ""]
        if not res["changed"][name]:
            lines.append("No question changed.")
        for c in res["changed"][name]:
            lines += _trail_lines(c["id"], c["question"], c["trail"], c["scores"])
    if res["dev46"]:
        lines += ["", "## 3. dev-46 (B7 candidate traces)", ""]
        lines += _trail_lines("dev-46", "", res["dev46"], None)
        for r in res["dev46_rows"]:
            lines.append(
                f"- claim {r['claim_index']} ({r['outcome']}, {r['class']}): rules {', '.join(r['rules']) or '–'}; mentions {', '.join(r['mentions'])}"
            )
    return "\n".join(lines) + "\n"


def _trail_lines(
    qid: str, question: str, t: Mapping[str, Any], scores: Mapping[str, Any] | None
) -> list[str]:
    out = [f"**{qid}**" + (f": {_esc(question)}" if question else "")]
    if scores:
        out.append(
            f"- scores raw {json.dumps(scores['raw'], sort_keys=True)}; validated {json.dumps(scores['validated'], sort_keys=True)}"
        )
    out += [
        f"- stop `{t['stop_reason']}`, error {t['error']!r}, regenerated {t['regenerated']}, passed {t['passed']}",
        f"- verdict draft {t['draft_verdict']!r} → final {t['final_verdict']!r} (source {t['final_verdict_source']!r})",
        f"- draft answer: {_esc(t['draft_answer'])}",
        f"- final answer: {_esc(t['final_answer'])}",
        "- first-draft failures: "
        + ("; ".join(f"[{i}] {r} {item}: {_esc(msg)}" for i, r, item, msg in t["first"]) or "none"),
        "- second-draft failures: "
        + (
            "; ".join(f"[{i}] {r} {item}: {_esc(msg)}" for i, r, item, msg in t["second"]) or "none"
        ),
        "- final claims: "
        + ("; ".join(f"({o}) {_esc(x)}" for o, x in t["final_claims"]) or "none"),
        "",
    ]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--records", type=Path, required=True)
    ap.add_argument("--questions", type=Path, default=ROOT / "eval/questions/dev.jsonl")
    ap.add_argument("--corpus", type=Path, default=ROOT / "corpora/synthetic_shop")
    ap.add_argument("--out", type=Path, required=True, help="output path without extension")
    ns = ap.parse_args(argv)
    records = [json.loads(x) for x in ns.records.read_text().splitlines() if x.strip()]
    questions = [json.loads(x) for x in ns.questions.read_text().splitlines() if x.strip()]
    res = run(records, questions, ns.corpus)
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.with_suffix(".json").write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
    ns.out.with_suffix(".md").write_text(render(res, ns.records.name))
    print(json.dumps({k: res[k] for k in ("outcomes", "dropped_by_class", "rule_class")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
