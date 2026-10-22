"""S13c design measurements (docs/plans/s13c-design.md). Read-only: no source change, nothing
written under eval/runs. Every part but ``seed`` is offline (no LLM). ``seed`` sends answer-phase
prompts to the LOCAL Ollama model only (no cloud provider, no quota).

    uv run --extra agent --extra retrieval python scripts/s13c_measure.py --part f1
    ... --part f6 | linker | seed

Each part prints a markdown section to stdout; the design doc quotes them.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "corpora" / "synthetic_shop"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "eval"))

QS = {
    q["id"]: q
    for q in (json.loads(x) for x in (ROOT / "eval/questions/dev.jsonl").read_text().splitlines())
}
# F1(d): claim wording that asserts a value derivation (a JOIN path never makes these true)
DERIVATION = re.compile(
    r"\b(deriv\w*|comes? from|computed|calculat\w*|sourced|originat\w*|aggregat\w*|renam\w*|"
    r"identity|copied|passed? through)\b",
    re.IGNORECASE,
)


def esc(x: Any) -> str:
    return str(x).replace("|", "\\|").replace("\n", " ")


# -- F1 option (d) -------------------------------------------------------------------------------


def f1() -> None:
    import s13_prep_audit as pa
    import s13b_diagnose as D

    import metrics as M
    from dlens.agent import validator as v
    from dlens.graph import load_or_build

    graph = load_or_build(CORPUS)
    inv, _ = M.load_inventory(CORPUS)
    by_text = {q["question"]: q for q in QS.values()}

    def impact_edges(led: Any) -> set[str]:
        """Indirect edge ids an impact_downstream result showed (the A5 direct+indirect tool)."""
        out: set[str] = set()
        for r in led.log:
            if r.tool == "impact_downstream" and not r.is_error:
                out |= {
                    i for i, rec in r.side_records.get("edges", {}).items() if rec.get("indirect")
                }
        return out

    def adjacency(variant: str, wording_ok: bool):
        def adj(ctx: Any) -> dict[str, list[tuple[str, str]]]:
            allowed = (
                impact_edges(ctx.ledger) if variant.startswith("tool") and wording_ok else set()
            )
            out: dict[str, list[tuple[str, str]]] = {}
            for i in sorted(ctx.ledger.emitted_ids):
                rec = ctx.ledger.record(i) or {}
                if not i.startswith("e_") or (ends := v._edge_ends(i, ctx)) is None:
                    continue
                if rec.get("indirect") and i not in allowed:
                    continue
                out.setdefault(ends[0], []).append((ends[1], i))
            return out

        return adj

    rows = []
    for model, stem in D.RUNS.items():
        for r in D.load_jsonl(Path(f"{stem}.jsonl")):
            q = QS.get(r.get("question_id")) or by_text[r["question"]]
            rp = D.replay(model, r, q, graph)
            for rnd in rp.rounds:
                for f in rnd.result.failures:
                    if f.rule != "R8" or f.claim_index is None:
                        continue
                    k = f.claim_index
                    text = rnd.answer.claims[k].text
                    deriv = bool(DERIVATION.search(text))
                    res = {}
                    for name, wording_ok in (("tool", True), ("tool+wording", not deriv)):
                        real = v._ledger_adjacency
                        v._ledger_adjacency = adjacency(name, wording_ok)  # type: ignore[assignment]
                        try:
                            out = v.validate(rnd.answer, rp.ledger, r["question"])
                        finally:
                            v._ledger_adjacency = real  # type: ignore[assignment]
                        res[name] = (k not in out.dropped_claims,
                                     next((c["added"] for c in out.completions
                                           if c["claim_index"] == k), []))  # fmt: skip
                    rows.append({
                        "model": model, "id": q["id"], "family": q["type"], "round": rnd.name,
                        "k": k, "class": pa.gold_class(pa.dotted(text, inv), pa.gold_nodes(q)),
                        "deriv": deriv, "tool": res["tool"][0], "tw": res["tool+wording"][0],
                        "added": len(res["tool"][1]), "text": text,
                    })  # fmt: skip
    print("## F1 (d) measured\n")
    print(
        "| model | id | family | round | # | class | derivation wording | (d) tool | (d) tool+wording | edges added | claim |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for x in rows:
        print(f"| {x['model']} | {x['id']} | {x['family']} | {x['round']} | {x['k']} | {x['class']} | "
              f"{'yes' if x['deriv'] else 'no'} | {'pass' if x['tool'] else '–'} | "
              f"{'pass' if x['tw'] else '–'} | {x['added']} | {esc(x['text'])[:110]} |")  # fmt: skip
    print()
    for label, key in (("(d) tool", "tool"), ("(d) tool+wording", "tw")):
        c = Counter((x["class"] == "consistent", x[key]) for x in rows)
        print(f"- {label}: consistent pass {c[(True, True)]} / {c[(True, True)] + c[(True, False)]};"
              f" not consistent pass {c[(False, True)]} / {c[(False, True)] + c[(False, False)]}")  # fmt: skip
    fam = Counter((x["family"], x["tool"]) for x in rows)
    print(f"- by family (tool variant): {dict(fam)}")


# -- F6 gate ---------------------------------------------------------------------------------------

F6_IDS = ["dev-41", "dev-66", "dev-78", "dev-82", "dev-84", "dev-86", "dev-87",
          "dev-93", "dev-94", "dev-95", "dev-96"]  # fmt: skip


def f6() -> None:
    from dlens.agent.tools.entity import NO_MATCH, link
    from dlens.graph import load_or_build

    graph = load_or_build(CORPUS)
    sys.path.insert(0, str(ROOT / "eval"))
    from systems.s4 import open_graph

    _, index, _ = open_graph(CORPUS, hybrid=True)
    ids = F6_IDS + [
        i for i, q in QS.items() if q["type"] in ("ask", "unanswerable") and i not in F6_IDS
    ]
    print("## F6 gate signals (offline)\n")
    print(
        "| id | family | verdict | stage 1-2 top (no hybrid) | hybrid top | dotted ids | question |"
    )
    print("|---|---|---|---|---|---|---|")
    for i in ids:
        q = QS[i]
        text = q["question"]
        nh, _ = link(graph, text, None)
        hy, info = link(graph, text, index)
        dotted = re.findall(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\b", text)
        dstat = []
        for m, c in dotted:
            known_m = any((graph.model_info(u) or {}).get("name") == m for u in graph.model_ids())
            dstat.append(f"{m}.{c}: model {'known' if known_m else 'UNKNOWN'}")
        top = lambda cs: f"{cs[0].row['id']} {cs[0].tier} {cs[0].raw:.3f}" if cs else "none"  # noqa: E731
        print(f"| {i} | {q['type']} | {q['gold'].get('verdict')} | {top(nh)} | {top(hy)} | "
              f"{'; '.join(dstat) or '–'} | {esc(text)} |")  # fmt: skip
    print(f"\n(NO_MATCH tau = {NO_MATCH}; link() is run on the whole question text.)")


# -- linker items ----------------------------------------------------------------------------------

LINKER_IDS = ["dev-15", "dev-29", "dev-40", "dev-56", "dev-71", "dev-75", "dev-93"]


def linker() -> None:
    from dlens.agent.tools.entity import AMBIGUOUS_GAP, link
    from dlens.graph import load_or_build

    sys.path.insert(0, str(ROOT / "eval"))
    from systems.s4 import open_graph

    graph = load_or_build(CORPUS)
    _, index, _ = open_graph(CORPUS, hybrid=True)
    ments = [
        json.loads(x) for x in (ROOT / "eval/linker/dev_mentions.jsonl").read_text().splitlines()
    ]
    by_id: dict[str, list[dict[str, Any]]] = {}
    for m in ments:
        by_id.setdefault(m["id"], []).append(m)
    print("## Linker cases (dev mentions; hybrid off vs on; top 4)\n")
    for i in LINKER_IDS:
        for m in by_id.get(i, []):
            print(
                f"**{i}** mention `{m['mention']}` gold {m['gold']} expect_ambiguous {m['expect_ambiguous']}\n"
            )
            for label, idx in (("off", None), ("on", index)):
                cs, info = link(graph, m["mention"], idx)
                amb = len(cs) > 1 and cs[0].raw - cs[1].raw < AMBIGUOUS_GAP
                desc = "; ".join(f"{c.row['id']} {c.tier} {c.raw:.3f}" for c in cs[:4]) or "none"
                print(f"- hybrid {label} ({info.get('hybrid')}): ambiguous={amb}: {desc}")
            print()


# -- seed (LOCAL Ollama only) ----------------------------------------------------------------------

DIFFERED = ["dev-17", "dev-18", "dev-20", "dev-21", "dev-22", "dev-24", "dev-27", "dev-28"]
SEED_FIXED = 42
MODEL = "qwen3:4b-instruct-2507-q4_K_M"


def control_ids(pilot: dict[str, Any], diag: dict[str, Any]) -> list[str]:
    """Rule stated before the run (owner, S13c): the 4 lowest dev ids among the 88 whose first
    drafts did not differ, that reached the answer phase (have a first draft)."""
    same = [i for i in sorted(pilot, key=lambda x: int(x.split("-")[1]))
            if pilot[i].get("draft_raw") is not None
            and pilot[i]["draft_raw"] == diag[i].get("draft_raw") and i not in DIFFERED]  # fmt: skip
    return same[:4]


def answer_messages(rec: dict[str, Any], box: Any) -> list[dict[str, str]]:
    """The answer-phase prompt, built once from the record's tool calls (re-run on today's
    tools). Not claimed to equal the pilot's prompt byte for byte: only the outputs of one saved
    prompt are compared with each other."""
    from dlens.agent import prompts
    from dlens.agent.evidence import build_evidence, render_evidence

    box.reset()
    for step in rec["steps"]:
        for r in step.get("results") or []:
            if not r.get("deduped"):
                code = step["phase"] == "code" or bool(r.get("code_initiated"))
                box.call(r["tool"], r["args"], code=code, rule=r.get("rule"))
    amb = rec.get("ambiguity") or {}
    directives = []
    if amb.get("mode") == "chain":
        directives = [prompts.chain_directive(amb["candidates"], amb["downstream"])]
    elif amb.get("mode") == "per_candidate":
        directives = [prompts.per_candidate_directive(amb["candidates"])]
    user = prompts.answer_user(rec["question"], render_evidence(build_evidence(box)), directives)
    return [{"role": "system", "content": prompts.ANSWER_SYSTEM}, {"role": "user", "content": user}]


def loaded(host: str) -> str:
    import httpx

    ps = httpx.get(f"{host}/api/ps", timeout=10).json().get("models", [])
    m = next((x for x in ps if x.get("name") == MODEL), None)
    return f"loaded (digest {m['digest'][:12]}, expires {m['expires_at']})" if m else "not loaded"


def seed(reps: int, save_dir: Path) -> None:
    import os

    import ollama

    from dlens.agent.answer import DRAFT_SCHEMA
    from dlens.agent.tools import Toolbox

    sys.path.insert(0, str(ROOT / "eval"))
    from systems.s4 import open_graph

    graph, index, _ = open_graph(CORPUS, hybrid=True)
    box = Toolbox(graph, CORPUS, index)

    def recs(rel: str) -> dict[str, Any]:
        lines = (ROOT / rel).read_text().splitlines()
        return {json.loads(x)["question_id"]: json.loads(x) for x in lines if x.strip()}

    pilot = recs("eval/runs/s4/s4-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl")
    diag = recs("eval/runs/s4/diagnostic/s13b-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl")
    ids = DIFFERED + control_ids(pilot, diag)
    save_dir.mkdir(parents=True, exist_ok=True)
    prompts_ = {}
    for i in ids:  # build each prompt ONCE, save it, and send only the saved copy
        path = save_dir / f"{i}.json"
        path.write_text(json.dumps(answer_messages(pilot[i], box), indent=1))
        prompts_[i] = json.loads(path.read_text())

    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    host = host if host.startswith("http") else f"http://{host}"
    client = ollama.Client(host=host)
    base = {"temperature": 0, "num_ctx": 8192}
    print(f"## Seed experiment (local Ollama, {MODEL}, temperature 0, num_ctx 8192)\n")
    print(f"- {reps} sends per cell, strictly one request at a time (a single-threaded loop).")
    print(f"- Before the run: {loaded(host)}.")
    print(
        f"- Prompts saved once under the scratch dir, then sent unchanged; seed fixed = {SEED_FIXED}."
    )
    print(f"- Controls (rule: the 4 lowest dev ids among the 88 unchanged drafts): "
          f"{', '.join(ids[len(DIFFERED):])}.\n")  # fmt: skip
    print(
        "| id | group | seed null: distinct / sends | seed 42: distinct / sends | null vs 42: same output set | model state before the cell |"
    )
    print("|---|---|---|---|---|---|")
    for i in ids:
        out: dict[Any, list[str]] = {}
        state = loaded(host)
        for s in (None, SEED_FIXED):
            opts = dict(base) if s is None else {**base, "seed": s}
            out[s] = [
                client.chat(model=MODEL, messages=prompts_[i], format=DRAFT_SCHEMA, options=opts,
                            think=False).message.content
                for _ in range(reps)
            ]  # fmt: skip
        group = "differed" if i in DIFFERED else "control"
        same = set(out[None]) == set(out[SEED_FIXED])
        print(f"| {i} | {group} | {len(set(out[None]))} / {reps} | {len(set(out[SEED_FIXED]))} / {reps} | "
              f"{'yes' if same else 'no'} | {state} |")  # fmt: skip
        sys.stdout.flush()


# -- linker sets before / after (S13c L1, L2; the committed S08 report is not regenerated) ----------


def linkerset(out: Path) -> None:
    """Per case: v2 top-1 id and the ambiguous flag, hybrid off and on, for linker-dev,
    linker-test (reported only, never used to choose a rule) and the dev mentions. Written to a
    scratch JSON so two code versions can be compared."""
    import linker_report as LR

    from dlens.agent.tools import entity

    graph, prov, index = LR.synthetic(with_hybrid=True)
    cases = LR.load("cases.jsonl")
    sets = {
        "linker-dev": [c for c in cases if c["split"] == "linker-dev"],
        "linker-test": [c for c in cases if c["split"] == "linker-test"],
        "dev mentions": LR.load("dev_mentions.jsonl"),
    }
    res: dict[str, Any] = {}
    for name, cs in sets.items():
        for c in cs:
            for label, idx in (("off", None), ("on", index)):
                p = entity.resolve_entity(prov, {"text": c["mention"]}, idx).payload
                top = p["candidates"][0]["id"] if p["candidates"] else None
                res[f"{name}|{c['id']}|{c['mention']}|{label}"] = {
                    "top": top, "ambiguous": p["ambiguous"], "gold": c["gold"],
                }  # fmt: skip
    out.write_text(json.dumps(res, indent=1, sort_keys=True))
    print(f"wrote {len(res)} rows to {out.name}")


def linkerdiff(a: Path, b: Path) -> None:
    A, B = json.loads(a.read_text()), json.loads(b.read_text())
    for name in ("linker-dev", "linker-test", "dev mentions"):
        for label in ("off", "on"):
            keys = [k for k in A if k.startswith(name + "|") and k.endswith("|" + label)]

            def top1(d: dict[str, Any]) -> int:
                return sum(1 for k in keys if d[k]["gold"] and d[k]["top"] in d[k]["gold"])

            def nomatch(d: dict[str, Any]) -> int:
                return sum(1 for k in keys if not d[k]["gold"] and d[k]["top"] is None)

            amb = lambda d: sum(1 for k in keys if d[k]["ambiguous"])  # noqa: E731
            pos = sum(1 for k in keys if A[k]["gold"])
            neg = len(keys) - pos
            print(f"- {name}, hybrid {label}: top-1 {top1(A)} -> {top1(B)} / {pos}; "
                  f"no-match {nomatch(A)} -> {nomatch(B)} / {neg}; ambiguous {amb(A)} -> {amb(B)}")  # fmt: skip
            for k in keys:
                if A[k] != B[k]:
                    print(f"  - {k.split('|')[1]} `{k.split('|')[2]}`: {A[k]['top']} "
                          f"(amb {A[k]['ambiguous']}) -> {B[k]['top']} (amb {B[k]['ambiguous']}); "
                          f"gold {A[k]['gold']}")  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument(
        "--part", choices=["f1", "f6", "linker", "seed", "linkerset", "linkerdiff"], required=True
    )
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--out", type=Path, default=None, help="linkerset: the JSON to write")
    ap.add_argument("--a", type=Path, default=None, help="linkerdiff: before")
    ap.add_argument("--b", type=Path, default=None, help="linkerdiff: after")
    ap.add_argument("--save-dir", type=Path, default=None, help="seed: where the prompts are saved")
    ns = ap.parse_args(argv)
    if ns.part == "linkerset":
        linkerset(ns.out)
    elif ns.part == "linkerdiff":
        linkerdiff(ns.a, ns.b)
    else:
        {"f1": f1, "f6": f6, "linker": linker}.get(ns.part, lambda: seed(ns.reps, ns.save_dir))()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
