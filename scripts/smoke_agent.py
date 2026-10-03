"""Run the agent smoke questions (tests/fixtures/agent_smoke.yaml) on a corpus and report.

uv run python scripts/smoke_agent.py                      # Ollama, synthetic_shop
uv run python scripts/smoke_agent.py --only a,d --show    # also print the rendered answers
uv run python scripts/smoke_agent.py --inject-bad-draft all   # fault injection on question a

Per question: LLM calls, max estimated input tokens per call, cited ids, whether every cited id
is in the ledger, structural checks (refused / ambiguity mode) and the quality expectation
(cites a gold edge). Uses the normal LLM cache, so re-runs are free. Dev smoke only: these are not
eval questions. Never point this at a quota-limited provider without checking the counter.

--inject-bad-draft KIND is a TEST HOOK of this script only (not a dlens CLI flag): it replaces the
first answer-phase draft with a fixture-made bad draft (built from the real ledger of the run),
then lets the real model make the regenerate call, so the validator's regenerate / salvage path
runs live. Kinds: fake_id, hallucinated, laundering, all_bad (or "all" for every kind).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from dlens.agent.answer import render
from dlens.agent.llm import LLMClient, LLMResponse, Message, ToolSpec, make_client
from dlens.agent.loop import AgentRun, ask
from dlens.agent.runlog import RunLogger, runs_dir
from dlens.agent.tools import Toolbox
from dlens.agent.validator import Entity, ValidationContext
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
    forbidden = {(e["from"], e["to"]) for e in expect.get("forbid_edges", [])}
    if forbidden:
        structural["no_forbidden_edge"] = not any(
            (short_id(r.get("from", "")), short_id(r.get("to", ""))) in forbidden
            for i in cited
            if (r := toolbox.record(i) or {})
        )

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
    notes: list[str] = []
    if expect.get("quality_or_refused") and a.refused:
        quality = True
    for name in expect.get("names", []):
        ctx = ValidationContext.build(toolbox)
        prose = " ".join([a.answer_text, *(c.text for c in a.claims)]).lower()
        ent = Entity(name, "column", name)
        named = name in prose
        backed = any(ctx.touches(i, ent) for i in cited)
        notes.append(f"{name}: named={'y' if named else 'n'} supported={'y' if backed else 'n'}")
        quality = bool(quality is not False and named and backed)
    for f, t in forbidden:
        for c in a.claims:
            low = c.text.lower()
            if (
                f in low
                and t in low
                and "direct" in low
                and not any(w in low for w in ("not ", "indirect", "no direct", "isn't", "is not"))
            ):
                notes.append(f"claim may assert a direct {f} -> {t}: {c.text!r}")
                quality = False
    return {
        "id_list": cited,
        "structural": structural,
        "structural_ok": all(structural.values()),
        "quality": quality,
        "notes": notes,
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
        f"     validator: {validator_line(run)}\n"
        + "".join(f"     note: {n}\n" for n in result.get("notes", []))
        + f"     answer: {outcome}"
    )


RULES = ["R1", "R2", "R3", "R4.hallucinated", "R4.unsupported", "R5", "R6", "R7"]


def validator_stats(run: AgentRun) -> dict[str, Any]:
    """Draft failures by rule, repairs, regenerate, claims before/after for one run."""
    v = run.record.validation or {}
    draft_claims = len((run.record.draft or {}).get("claims", []))
    return {
        "checked": bool(v),
        "counts": dict(v.get("counts") or {}),
        "repairs": list(v.get("repairs") or []),
        "regenerated": bool(v.get("regenerated")),
        "warning": bool(v.get("warning")),
        "claims_before": draft_claims,
        "claims_after": 0 if run.answer.refused else len(run.answer.claims),
    }


def validator_line(run: AgentRun) -> str:
    s = validator_stats(run)
    if not s["checked"]:
        return "not run (refused or clarified before the answer was validated)"
    counts = ", ".join(f"{k}={n}" for k, n in sorted(s["counts"].items())) or "none"
    repairs = ", ".join(f"{r['from']}->{r['to']}" for r in s["repairs"]) or "none"
    return (
        f"draft failures: {counts}; repairs: {repairs}; "
        f"regenerated={'y' if s['regenerated'] else 'n'}; warning={'y' if s['warning'] else 'n'}; "
        f"claims kept {s['claims_after']}/{s['claims_before']}"
    )


def stats_line(runs: list[AgentRun]) -> str:
    stats = [validator_stats(r) for r in runs]
    before = sum(s["claims_before"] for s in stats)
    after = sum(s["claims_after"] for s in stats)
    totals = {rule: sum(s["counts"].get(rule, 0) for s in stats) for rule in RULES}
    return (
        f"validator stats: claims {before} -> {after}; "
        + " ".join(f"{k}={n}" for k, n in totals.items())
        + f"; repairs={sum(len(s['repairs']) for s in stats)}"
        + f"; regenerated={sum(s['regenerated'] for s in stats)}"
        + f"; warnings={sum(s['warning'] for s in stats)}"
    )


# -- fault injection (test hook of this script only) -------------------------------------------

KINDS = ["fake_id", "hallucinated", "laundering", "all_bad"]
FAKE_COLUMN = "fct_orders.discount_pct"  # not in DESIGN.md


def bad_draft(kind: str, toolbox: Toolbox) -> dict[str, Any]:
    """A deliberately invalid answer draft built from this run's real ledger."""
    g = toolbox.graph
    edges = sorted(i for i in toolbox.emitted_ids if i.startswith("e_"))
    if len(edges) < 2:
        raise RuntimeError("fault injection needs >= 2 emitted edges (use question a)")

    def ends(i: str) -> tuple[str, str]:
        rec = toolbox.record(i) or {}
        return g.display_name(rec["from"]), g.display_name(rec["to"])

    e1 = edges[0]
    src, dst = ends(e1)
    good = {"text": f"{dst} is derived from {src}", "ids": [e1]}
    # an emitted edge sharing no column with e1: cited for e1's claim it touches nothing
    e2 = next(i for i in edges if not set(ends(i)) & {src, dst})
    fake = {"text": f"{dst} is derived from {src}", "ids": ["e_deadbeef"]}
    halluc = {"text": f"{FAKE_COLUMN} is derived from {src}", "ids": [e1]}
    laundered = {"text": f"{dst} is derived from {src}", "ids": [e2]}
    text = f"{dst} is derived from {src}."
    claims = {
        "fake_id": [good, fake],
        "hallucinated": [good, halluc],
        "laundering": [good, laundered],
        "all_bad": [fake, halluc, laundered],
    }[kind]
    if kind in ("hallucinated", "all_bad"):
        text = f"{dst} is derived from {src}; it also feeds {FAKE_COLUMN}."
    return {"answer_text": text, "claims": claims, "confidence": "high", "refused": False}


class InjectingClient:
    """Wraps the real client; the FIRST answer-phase call (the one with a response schema)
    returns the injected bad draft instead of calling the model. Everything else, including
    the regenerate call, goes to the real model."""

    def __init__(self, real: LLMClient, kind: str, toolbox: Toolbox) -> None:
        self.real, self.kind, self.toolbox = real, kind, toolbox
        self.provider = real.provider
        self.max_input_tokens = real.max_input_tokens
        self.injected = False

    def chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        if response_schema is not None and not self.injected:
            self.injected = True
            return LLMResponse(text=json.dumps(bad_draft(self.kind, self.toolbox)))
        return self.real.chat(messages, tools, response_schema)


def injection_row(kind: str, run: AgentRun) -> str:
    v = run.record.validation or {}
    first = (v.get("first") or {}).get("counts") or {}
    second = v.get("second")
    fmt = lambda c: ", ".join(f"{k}={n}" for k, n in sorted(c.items())) or "none"  # noqa: E731
    a = run.answer
    if a.refused:
        final = f"refused ({a.refusal_reason})"
    else:
        final = f"{len(a.claims)} claims"
    second_txt = (
        "n/a"
        if second is None
        else ("passed" if second.get("passed") else fmt(second.get("counts") or {}))
    )
    return (
        f"| {kind} | {fmt(first)} | {'y' if v.get('regenerated') else 'n'} | {second_txt} | "
        f"{final} | {'y' if a.validation_warning else 'n'} | {run.record.llm_calls} |"
    )


def run_injection(kinds: list[str], spec: dict[str, Any], project: Path, graph: Any) -> int:
    q = next(q for q in spec["questions"] if q["id"] == "a")
    real = make_client("ollama")
    logger = RunLogger(runs_dir())
    print("| kind | first-draft failures | regenerated | second draft | final | warning | calls |")
    print("|---|---|---|---|---|---|---|")
    ok = True
    for kind in kinds:
        toolbox = Toolbox(graph, project)
        client = InjectingClient(real, kind, toolbox)
        run = ask(q["question"], client, toolbox, logger, project=str(project))  # type: ignore[arg-type]
        ok &= run.record.llm_calls <= 8 and client.injected
        print(injection_row(kind, run))
        if "--show" in sys.argv:
            print("\n" + render(run.answer) + "\n")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--provider", default="ollama")
    ap.add_argument("--only", help="comma-separated question ids")
    ap.add_argument("--show", action="store_true", help="print each rendered answer")
    ap.add_argument(
        "--inject-bad-draft",
        choices=[*KINDS, "all"],
        help="test hook: replace the first answer draft of question a with a bad one",
    )
    ns = ap.parse_args()
    if ns.provider != "ollama":
        print("smoke_agent: only the local ollama provider is allowed here", file=sys.stderr)
        return 2

    spec = load_questions()
    project = ROOT / "corpora" / spec["corpus"]
    graph = load_or_build(project)
    if ns.inject_bad_draft:
        kinds = KINDS if ns.inject_bad_draft == "all" else [ns.inject_bad_draft]
        return run_injection(kinds, spec, project, graph)
    client = make_client(ns.provider)
    logger = RunLogger(runs_dir())
    only = set(ns.only.split(",")) if ns.only else None
    ok = True
    runs: list[AgentRun] = []
    for q in spec["questions"]:
        if only and q["id"] not in only:
            continue
        toolbox = Toolbox(graph, project)
        run = ask(q["question"], client, toolbox, logger, project=str(project))
        result = check(q["expect"], run, toolbox)
        ok &= result["structural_ok"]
        runs.append(run)
        print(report_row(q["id"], run, result))
        if ns.show:
            print("\n" + render(run.answer) + "\n")
    print(stats_line(runs))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
