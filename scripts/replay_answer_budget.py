"""How often the answer phase trims evidence, before and after the regenerate reserve
(s12-design A6), and how close every tool-phase call comes to the cap (s12-design v1.2, owner
amendment 6). Offline, no LLM.

Answer phase: for each record that reached it, the recorded tool calls are replayed on a fresh
Toolbox with TODAY's tools (so today's payload shapes), the answer-phase evidence and directives
are rebuilt, and the prompt is measured with today's ANSWER_SYSTEM + DRAFT_SCHEMA.

Tool phase: each recorded tool-phase LLM call is rebuilt as the loop sends it (today's tool
prompt and specs, the history of earlier calls and results, the budget manager's compaction)
and measured before and after ``fit``. A call still over the cap after compaction would end the
tool phase (``budget``). With ``--hybrid`` the toolbox has the search index, so the tool prompt
and specs include search_docs (the S12b S4 configuration).

An offline approximation: the tool calls are the recorded ones (a model that had search_docs
might call it, which this cannot replay).

    uv run python scripts/replay_answer_budget.py --records <runs>/2026-10-18.jsonl [--hybrid]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from dlens.agent import prompts
from dlens.agent.answer import DRAFT_SCHEMA
from dlens.agent.context import History, fit
from dlens.agent.evidence import build_evidence, render_evidence
from dlens.agent.llm.tokens import MAX_INPUT_TOKENS, estimate_tokens
from dlens.agent.llm.types import Message, ToolCall
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


def tool_phase_tokens(record: dict[str, Any], box: Toolbox) -> list[tuple[int, int]]:
    """(before fit, after fit) est. tokens of each recorded tool-phase LLM call, rebuilt."""
    box.reset()
    specs = box.specs()
    history = History(
        [
            Message(role="system", content=prompts.tool_system(box.has_docs)),
            Message(role="user", content=record["question"]),
        ]
    )
    out: list[tuple[int, int]] = []
    for i, step in enumerate(record["steps"]):
        if step["phase"] not in ("tool", "repair"):
            continue
        before = history.tokens(specs)
        fit(history, specs, MAX_INPUT_TOKENS, i)
        out.append((before, history.tokens(specs)))
        calls = [ToolCall.model_validate(tc) for tc in step.get("tool_calls") or []]
        if not calls:
            continue
        history.messages.append(Message(role="assistant", content="", tool_calls=calls))
        for tc, r in zip(calls, step["results"], strict=False):
            result = box.call(r["tool"], r["args"])
            history.add_tool(result, tc.id)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--records", type=Path, required=True)
    ap.add_argument("--hybrid", action="store_true", help="toolbox with the S07 index (S12b S4)")
    ns = ap.parse_args(argv)
    records = [json.loads(x) for x in ns.records.read_text().splitlines() if x.strip()]
    reached = [r for r in records if r.get("draft_raw") is not None]
    index = None
    if ns.hybrid:
        sys.path.insert(0, str(ROOT / "eval"))
        from systems.s4 import open_graph

        graph, index, _ = open_graph(CORPUS, hybrid=True)
    else:
        graph = load_or_build(CORPUS)
    box = Toolbox(graph, CORPUS, index)
    label = LABEL.replace("hybrid off", "hybrid on (search_docs specs)") if ns.hybrid else LABEL
    qid = {
        json.loads(x)["question"]: json.loads(x)["id"]
        for x in (ROOT / "eval/questions/dev.jsonl").read_text().splitlines()
    }
    sizes = {qid.get(r["question"], r["run_id"][:8]): answer_tokens(r, box) for r in reached}
    cap = MAX_INPUT_TOKENS
    print(f"{label}; {len(reached)} answer-phase records of {len(records)}")
    for name, reserve in (
        ("old: cap", 0),
        ("new: cap - reserve", REGENERATE_RESERVE),
        ("rejected: cap - 803", REJECTED_RESERVE),
    ):
        over = sorted(k for k, t in sizes.items() if t > cap - reserve)
        print(f"  {name} (> {cap - reserve} est.): {len(over)} / {len(sizes)} trim {over}")
    top = sorted(sizes.items(), key=lambda kv: -kv[1])[:5]
    print("  largest answer prompts (est. tokens):", ", ".join(f"{k} {t}" for k, t in top))
    calls = {qid.get(r["question"], r["run_id"][:8]): tool_phase_tokens(r, box) for r in records}
    flat = [(k, b, a) for k, xs in calls.items() for b, a in xs]
    over = sorted({k for k, _, a in flat if a > cap})
    compacted = sorted({k for k, b, a in flat if a < b})
    print(f"  tool phase: {len(flat)} calls in {len(calls)} records, cap {cap}")
    if flat:
        k, b, _ = max(flat, key=lambda x: x[1])
        print(f"    max before compaction: {b} est. ({k}); max sent: {max(a for *_, a in flat)}")
    print(f"    compacted: {len(compacted)} records {compacted}")
    print(f"    over the cap after compaction: {len(over)} {over}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
