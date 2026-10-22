"""S13b step 9: the post-fix dev diagnostic report (qwen, local). NOT a result: one labelled
re-run of the dev questions after the approved post-pilot fixes (F2-F5), shown next to the
pilot's qwen S4 row for information only. It does not replace the pilot table.

Scores both record files with metrics.py exactly as ``scripts/pilot_table.py`` does (its
``score``), and adds per-question attribution only where a record shows the mechanism:
- F3: ``stop_reason`` has ``+regenerate_refused``;
- F4: a validation round repaired a 5- or 6-hex id prefix;
- F2: a counterfactual replay of the diagnostic record's own drafts with the alias skip turned
  off (in-process, the record's ledger) shows which claims pass only because of F2.

    uv run --extra agent python scripts/s13b_diagnostic_report.py \\
        --out eval/reports/s13b/diagnostic_dev.md
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
sys.path.insert(0, str(ROOT / "tests" / "unit" / "agent"))

import pilot_table as PT  # noqa: E402

PILOT = "eval/runs/s4/s4-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl"
DIAG = "eval/runs/s4/diagnostic/s13b-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl"
SYSTEM = "s4-qwen3-4b"
VIEWS = ("raw", "validated", "augmented")
LABEL = "post-fix dev diagnostic"
ROWS = [
    ("node-set F1", "node_f1"),
    ("trace F1", "trace_f1"),
    ("impact F1", "impact_f1"),
    ("hallucination rate", "hallucination_rate"),
    ("citation valid (answer)", "citation_valid_answer"),
    ("false refusal", "false_refusal"),
    ("yes/no", "yesno_correct"),
    ("chain", "chain_correct"),
    ("clarify", "clarify_correct"),
]


def load(rel: str) -> list[dict[str, Any]]:
    return [json.loads(x) for x in (ROOT / rel).read_text().splitlines() if x.strip()]


def scored(rel: str, tmp: Path) -> dict[str, dict[str, Any]]:
    return {v: PT.score(PT.Row(f"S4 {v}", rel, SYSTEM, v), tmp) for v in VIEWS}


def hop6(result: Mapping[str, Any]) -> Mapping[str, Any]:
    hb = result["summary"]["node_f1_by"]["hop_bucket"]
    return hb.get("6+") or {}


def kind(rec: Mapping[str, Any]) -> str:
    fa = rec.get("final_answer") or {}
    if fa.get("refused"):
        return "refused"
    return "clarification" if fa.get("clarification") else "answered"


def refusals_by_family(recs: list[dict[str, Any]], qs: Mapping[str, Any]) -> Counter[str]:
    return Counter(qs[r["question_id"]]["type"] for r in recs if kind(r) == "refused")


def short_hex_repairs(rec: Mapping[str, Any]) -> list[str]:
    v = rec.get("validation") or {}
    out = []
    for rnd in ("first", "second"):
        for r in (v.get(rnd) or {}).get("repairs") or []:
            bad = str(r.get("from", ""))
            if bad[:2] in ("e_", "s_", "r_", "c_") and len(bad) - 2 in (5, 6):
                out.append(f"{rnd}: {bad} → {r.get('to')}")
    return out


def f2_counterfactual(rec: dict[str, Any]) -> list[str]:
    """Rounds of this record whose dropped claims grow when the alias skip is turned off."""
    import pilot_records as P

    from dlens.agent import validator as v
    from dlens.agent.answer import attach
    from dlens.agent.loop import _parse_draft

    val = rec.get("validation") or {}
    if not val or rec.get("draft") is None or val.get("skipped"):
        return []
    led = P.ledger(rec)
    answers = [("first", P.first_answer(rec, led))]
    if val.get("second") and rec.get("regenerate_draft_raw"):
        try:
            answers.append(("second", attach(_parse_draft(rec["regenerate_draft_raw"]), led)))
        except Exception:  # noqa: BLE001 - an unparseable regenerate has no second round
            pass
    out = []
    real = v.ValidationContext.aliases
    for name, ans in answers:
        on = v.validate(ans, led, rec["question"])
        v.ValidationContext.aliases = lambda self: set()  # type: ignore[method-assign]
        try:
            off = v.validate(ans, led, rec["question"])
        finally:
            v.ValidationContext.aliases = real  # type: ignore[method-assign]
        extra = sorted(set(off.dropped_claims) - set(on.dropped_claims))
        text = off.answer_text_failed and not on.answer_text_failed
        if extra or text:
            what = [f"claim {k}" for k in extra] + (["answer_text"] if text else [])
            out.append(f"{name}: {', '.join(what)} pass only through the alias skip")
    return out


def per_q(result: Mapping[str, Any], name: str) -> dict[str, float]:
    return PT.per_question(result, name)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ns = ap.parse_args(argv)

    qs = {q["id"]: q for q in load("eval/questions/dev.jsonl")}
    pilot, diag = load(PILOT), load(DIAG)
    pman = json.loads((ROOT / PILOT.replace(".jsonl", ".manifest.json")).read_text())
    dman = json.loads((ROOT / DIAG.replace(".jsonl", ".manifest.json")).read_text())
    with tempfile.TemporaryDirectory() as t:
        P_ = scored(PILOT, Path(t) / "pilot")
        D_ = scored(DIAG, Path(t) / "diag")

    L = [
        f"# S13b {LABEL} (qwen, dev): not a result",
        "",
        f"> **{LABEL}.** One labelled re-run of the 96 dev questions after the approved post-pilot"
        " fixes (F2, F3, F4, F5; F1 and F6 deferred). **Not a result; it does not replace the"
        " pilot table**, and no fix was adjusted in response to it. The honest check is the test"
        " set after the 7 Dec 2026 freeze. Every number below is a post-fix dev diagnostic"
        " number unless its column says pilot.",
        "",
        "| | pilot qwen S4 (S13 table) | post-fix dev diagnostic |",
        "|---|---|---|",
        f"| records | `{Path(PILOT).name}` | `{Path(DIAG).name}` |",
        f"| agent sha | `{pman['agent_code_sha256'][:8]}…` | `{dman['agent_code_sha256'][:8]}…` |",
        f"| model digest | `{pman['model_identity']['digest'][:12]}` |"
        f" `{dman['model_identity']['digest'][:12]}` |",
        f"| sampling | {json.dumps(pman['model_identity'].get('sampling'))} |"
        f" {json.dumps(dman['model_identity'].get('sampling'))} |",
        f"| index | {pman.get('index_status')} | {dman.get('index_status')} |",
        f"| cache (hits / misses) | {pman['cache']['hits']} / {pman['cache']['misses']} |"
        f" {dman['cache']['hits']} / {dman['cache']['misses']} |",
        f"| records / LLM calls | {len(pilot)} / {sum(r['tokens'].get('llm_calls', 0) for r in pilot)} |"
        f" {len(diag)} / {sum(r['tokens'].get('llm_calls', 0) for r in diag)} |",
        f"| purpose | – | {dman.get('purpose')} |",
        "",
        "## Rows (mean [95% CI] (n)), pilot vs post-fix dev diagnostic",
        "",
        "| row | " + " | ".join(f"{v}: pilot | {v}: {LABEL}" for v in VIEWS) + " |",
        "|---|" + "---|---|" * len(VIEWS),
    ]
    for label, key in ROWS:
        cells = []
        for v in VIEWS:
            cells += [
                PT.cell(P_[v]["summary"]["metrics"].get(key) or {}),
                PT.cell(D_[v]["summary"]["metrics"].get(key) or {}),
            ]
        L.append(f"| {label} | " + " | ".join(cells) + " |")
    L.append(
        "| node-set F1, hop 6+ | "
        + " | ".join(c for v in VIEWS for c in (PT.cell(hop6(P_[v])), PT.cell(hop6(D_[v]))))
        + " |"
    )
    L.append("")

    pf, df = refusals_by_family(pilot, qs), refusals_by_family(diag, qs)
    fams = sorted(set(pf) | set(df) | {"ask"})
    L += ["## Refusals by family (final answers; the validated view)", ""]
    L += ["| family | pilot | " + LABEL + " |", "|---|---|---|"]
    L += [f"| {f} | {pf.get(f, 0)} | {df.get(f, 0)} |" for f in fams]
    L += [
        "",
        f"**Ask refusal count:** pilot {pf.get('ask', 0)} of 12, {LABEL} {df.get('ask', 0)} of 12."
        " Ask is not re-scored (the AI-scored sheet is frozen).",
        "",
    ]

    # ---- per question
    pv, dv = P_["validated"], D_["validated"]
    pn, dn = per_q(pv, "node_f1"), per_q(dv, "node_f1")
    pc, dc = per_q(pv, "fully_correct"), per_q(dv, "fully_correct")
    pr = {r["question_id"]: r for r in pilot}
    moved = []
    for r in diag:
        qid = r["question_id"]
        a, b = pn.get(qid), dn.get(qid)
        c, d = pc.get(qid), dc.get(qid)
        if (
            (a is not None and b is not None and abs(a - b) > 1e-9)
            or (c is not None and d is not None and c != d)
            or kind(pr[qid]) != kind(r)
        ):
            moved.append((qid, a, b, c, d, kind(pr[qid]), kind(r)))
    same_draft = sum((pr[r["question_id"]].get("draft_raw") == r.get("draft_raw")) for r in diag)
    L += [
        "## Per question (validated view), pilot → " + LABEL,
        "",
        f"First drafts identical to the pilot's: {same_draft} of {len(diag)} (temperature 0; a"
        " differing draft means the model output itself changed, not a fix).",
        "",
        "| id | family | node-set F1 | fully correct | answer kind | moved |",
        "|---|---|---|---|---|---|",
    ]
    wrong_way = []
    for qid, a, b, c, d, k1, k2 in moved:
        down = (
            (a is not None and b is not None and b < a)
            or (c is not None and d is not None and d < c)
            or (
                k1 == "answered"
                and k2 != "answered"
                and qs[qid]["gold"].get("verdict") == "answered"
            )
        )
        if down:
            wrong_way.append(qid)
        L.append(
            f"| {qid} | {qs[qid]['type']} | {PT._f(a)} → {PT._f(b)} | {PT._f(c)} → {PT._f(d)} |"
            f" {k1} → {k2} | {'**down**' if down else 'up / changed'} |"
        )
    L += [
        "",
        "**Moved the wrong way:** " + (", ".join(wrong_way) if wrong_way else "none") + ".",
        "",
        "## Per-fix attribution (only where the record shows the mechanism)",
        "",
    ]
    f3 = [r["question_id"] for r in diag if "+regenerate_refused" in (r.get("stop_reason") or "")]
    f4 = {r["question_id"]: x for r in diag if (x := short_hex_repairs(r))}
    f2 = {r["question_id"]: x for r in diag if (x := f2_counterfactual(r))}
    L.append(
        "- **F3** (refused regenerate → salvage; `stop_reason` `+regenerate_refused`): "
        + (", ".join(f3) if f3 else "no question in this run")
        + "."
    )
    L.append(
        "- **F4** (5–6 hex prefix repaired by R2r): "
        + (
            "; ".join(f"{q}: {', '.join(x)}" for q, x in f4.items())
            if f4
            else "no question in this run"
        )
        + "."
    )
    L.append(
        "- **F2** (counterfactual replay of this record's drafts with the alias skip off): "
        + (
            "; ".join(f"{q}: {'; '.join(x)}" for q, x in f2.items())
            if f2
            else "no question in this run"
        )
        + "."
    )
    gem = sum(
        1
        for r in diag
        for s in r.get("steps") or []
        if "gemini call failed" in (s.get("error") or "")
    )
    L.append(
        f"- **F5** (Gemini transport errors): not exercised by a local qwen run ({gem} steps)."
    )
    L.append("")
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.write_text("\n".join(L) + "\n")
    print(f"wrote {ns.out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
