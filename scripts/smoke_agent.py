"""Run the agent smoke questions (tests/fixtures/agent_smoke.yaml) on a corpus and report.

uv run python scripts/smoke_agent.py                      # Ollama, synthetic_shop
uv run python scripts/smoke_agent.py --only a,d --show    # also print the rendered answers

Per question: LLM calls, max estimated input tokens per call, cited ids, whether every cited id
is in the ledger, structural checks (refused / ambiguity mode) and the quality expectation
(cites a gold edge). Uses the normal LLM cache, so re-runs are free. Dev smoke only: these are not
eval questions. Never point this at a quota-limited provider without checking the counter.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from dlens.agent.answer import render
from dlens.agent.llm import make_client
from dlens.agent.loop import AgentRun, ask
from dlens.agent.runlog import RunLogger, runs_dir
from dlens.agent.tools import Toolbox
from dlens.graph import load_or_build
from dlens.lineage import short_id

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "agent_smoke.yaml"


def load_questions(path: Path = FIXTURE) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def check(expect: dict[str, Any], run: AgentRun, toolbox: Toolbox) -> dict[str, Any]:
    """Structural checks (asserted by the live test) and quality checks (reported only)."""
    a, rec = run.answer, run.record
    cited = [i for c in a.claims for i in c.ids]
    amb = rec.ambiguity or {}
    structural: dict[str, bool] = {
        "all_cited_in_ledger": all(i in toolbox.emitted_ids for i in cited),
        "calls_under_cap": all(s.est_input_tokens <= 3000 for s in rec.steps),
        "record_written": run.log_path is not None and run.log_path.exists(),
    }
    if "refused" in expect:
        structural["refused"] = a.refused == expect["refused"]
    if "mode" in expect:
        structural["mode"] = amb.get("mode") == expect["mode"]
    if "downstream" in expect:
        structural["downstream"] = amb.get("downstream") == expect["downstream"]
    if expect.get("clarification") is False:
        structural["no_clarification"] = a.clarification is None

    quality: bool | None = None
    gold = {(e["from"], e["to"]) for e in expect.get("cites_any_edge", [])}
    if gold or "cites_excerpt_of" in expect:
        hit_edge = False
        for i in cited:
            rec_i = toolbox.record(i) or {}
            if (
                i.startswith("e_")
                and (short_id(rec_i.get("from", "")), short_id(rec_i.get("to", ""))) in gold
            ):
                hit_edge = True
        hit_sql = False
        model = expect.get("cites_excerpt_of")
        if model:
            for r in toolbox.log:
                if (
                    r.tool == "get_model_sql"
                    and not r.is_error
                    and r.llm_payload.get("model") == model
                ):
                    hit_sql = hit_sql or any(
                        w["excerpt_id"] in cited for w in r.llm_payload["windows"]
                    )
        quality = hit_edge or hit_sql
    return {
        "id_list": cited,
        "structural": structural,
        "structural_ok": all(structural.values()),
        "quality": quality,
    }


def report_row(qid: str, run: AgentRun, result: dict[str, Any]) -> str:
    rec = run.record
    per_call = [s.est_input_tokens for s in rec.steps if s.is_llm_call]
    a = run.answer
    if a.clarification:
        outcome = "clarification"
    elif a.refused:
        outcome = f"refused: {a.refusal_reason}"
    else:
        outcome = a.answer_text
    q = {None: "n/a", True: "yes", False: "no"}[result["quality"]]
    bad = [k for k, v in result["structural"].items() if not v]
    return (
        f"[{qid}] calls={rec.llm_calls} est_in/call={per_call} max={max(per_call, default=0)} "
        f"mode={(rec.ambiguity or {}).get('mode')} stop={rec.stop_reason}\n"
        f"     cited={result['id_list']}\n"
        f"     in_ledger={'yes' if result['structural']['all_cited_in_ledger'] else 'NO'} "
        f"structural={'ok' if not bad else 'FAIL ' + ','.join(bad)} gold_edge_cited={q}\n"
        f"     answer: {outcome}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--provider", default="ollama")
    ap.add_argument("--only", help="comma-separated question ids")
    ap.add_argument("--show", action="store_true", help="print each rendered answer")
    ns = ap.parse_args()
    if ns.provider != "ollama":
        print("smoke_agent: only the local ollama provider is allowed here", file=sys.stderr)
        return 2

    spec = load_questions()
    project = ROOT / "corpora" / spec["corpus"]
    graph = load_or_build(project)
    client = make_client(ns.provider)
    logger = RunLogger(runs_dir())
    only = set(ns.only.split(",")) if ns.only else None
    ok = True
    for q in spec["questions"]:
        if only and q["id"] not in only:
            continue
        toolbox = Toolbox(graph, project)
        run = ask(q["question"], client, toolbox, logger, project=str(project))
        result = check(q["expect"], run, toolbox)
        ok &= result["structural_ok"]
        print(report_row(q["id"], run, result))
        if ns.show:
            print("\n" + render(run.answer) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
