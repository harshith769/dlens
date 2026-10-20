"""How often the answer phase trims evidence, before and after the regenerate reserve
(s12-design A6). Offline, no LLM.

For each record that reached the answer phase, the recorded tool calls are replayed on a fresh
Toolbox with TODAY's tools (so today's payload shapes), the answer-phase evidence and directives
are rebuilt, and the prompt is measured with today's ANSWER_SYSTEM + DRAFT_SCHEMA. An offline
approximation: the tool calls are the recorded ones, the linker's hybrid stage is off.

    uv run python scripts/replay_answer_budget.py --records <runs>/2026-10-18.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from dlens.agent import prompts
from dlens.agent.answer import DRAFT_SCHEMA
from dlens.agent.evidence import build_evidence, render_evidence
from dlens.agent.llm.tokens import MAX_INPUT_TOKENS, estimate_tokens
from dlens.agent.llm.types import Message
from dlens.agent.loop import REGENERATE_RESERVE
from dlens.agent.tools import Toolbox
from dlens.graph import load_or_build

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "corpora" / "synthetic_shop"
REJECTED_RESERVE = 803  # the worst-case reserve the owner rejected (s12-design A6), for the record
LABEL = "offline approximation: 18 Oct tool calls, today's tools, hybrid off"


def directives(record: dict[str, Any]) -> list[str]:
    amb = record.get("ambiguity") or {}
    if amb.get("mode") == "chain":
        return [prompts.chain_directive(amb["candidates"], amb["downstream"])]
    if amb.get("mode") == "per_candidate":
        return [prompts.per_candidate_directive(amb["candidates"])]
    return []


def answer_tokens(record: dict[str, Any], box: Toolbox) -> int:
    box.reset()
    for step in record["steps"]:
        for r in step["results"]:
            if not r.get("deduped"):
                code = step["phase"] == "code" or bool(r.get("code_initiated"))
                box.call(r["tool"], r["args"], code=code, rule=r.get("rule"))
    items = build_evidence(box)
    user = prompts.answer_user(record["question"], render_evidence(items), directives(record))
    msgs = [
        Message(role="system", content=prompts.ANSWER_SYSTEM),
        Message(role="user", content=user),
    ]
    return estimate_tokens(msgs, None, DRAFT_SCHEMA)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--records", type=Path, required=True)
    ns = ap.parse_args(argv)
    records = [json.loads(x) for x in ns.records.read_text().splitlines() if x.strip()]
    reached = [r for r in records if r.get("draft_raw") is not None]
    box = Toolbox(load_or_build(CORPUS), CORPUS)
    qid = {
        json.loads(x)["question"]: json.loads(x)["id"]
        for x in (ROOT / "eval/questions/dev.jsonl").read_text().splitlines()
    }
    sizes = {qid.get(r["question"], r["run_id"][:8]): answer_tokens(r, box) for r in reached}
    cap = MAX_INPUT_TOKENS
    print(f"{LABEL}; {len(reached)} answer-phase records of {len(records)}")
    for name, reserve in (
        ("old: cap", 0),
        ("new: cap - reserve", REGENERATE_RESERVE),
        ("rejected: cap - 803", REJECTED_RESERVE),
    ):
        over = sorted(k for k, t in sizes.items() if t > cap - reserve)
        print(f"  {name} (> {cap - reserve} est.): {len(over)} / {len(sizes)} trim {over}")
    top = sorted(sizes.items(), key=lambda kv: -kv[1])[:5]
    print("  largest answer prompts (est. tokens):", ", ".join(f"{k} {t}" for k, t in top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
