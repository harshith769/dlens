"""S08 linker report: v1 vs v2 (without / with hybrid) on the linker set (design §7).

uv run --extra retrieval python scripts/linker_report.py [--work DIR] [--no-jira]

Writes eval/reports/linker.md and eval/reports/linker.json. Report only: these are not benchmark
metrics (eval/metrics.py is not involved). No LLM call. The hybrid system needs the retrieval
extra and builds/reuses the S07 index (synthetic_shop: target/dlens_index; dbt_jira: under
--work). dbt_jira is built offline from the vendored packages into --work (a scratch dir), as in
tests/integration/test_dbt_jira.py.

Metrics, per (system, set):
- top-1 / top-3 on cases with gold: the first / any of the first 3 candidates is a gold id;
- no-match accuracy on gold-[] cases: no candidate at all;
- ambiguity: share of positive cases flagged ``ambiguous``; recall of ``expect_ambiguous`` cases;
  false ambiguity (flagged while not expected).
Broken down by variant and by the winning stage of the top-1 candidate. Phrase rules are shown
on linker-test separately. The tau / COS_MIN evidence uses linker-dev only (design §4).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
import tempfile
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
LINKER = ROOT / "eval" / "linker"
OUT_MD = ROOT / "eval" / "reports" / "linker.md"
OUT_JSON = ROOT / "eval" / "reports" / "linker.json"
SYNTH = ROOT / "corpora" / "synthetic_shop"
JIRA = ROOT / "corpora" / "dbt_jira"


def load(name: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (LINKER / name).read_text().splitlines()]


def _v1() -> Any:
    spec = importlib.util.spec_from_file_location("linker_v1", LINKER / "v1.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# -- running ----------------------------------------------------------------------------------


def short(cid: str) -> str:
    return ".".join(cid.split(".")[-2:])


def run_case(resolve: Callable[[str], Any], case: dict[str, Any]) -> dict[str, Any]:
    out = resolve(case["mention"])
    p, side = out.payload, out.side
    ids = [short(c["id"]) if c["kind"] == "column" else c["id"] for c in p["candidates"]]
    gold = set(case["gold"])
    top_parts = (side.get("parts") or {}).get(p["candidates"][0]["id"]) if p["candidates"] else None
    stage = (
        (top_parts or {}).get("tier")
        if top_parts
        else (p["candidates"][0]["match"] if p["candidates"] else "none")
    )
    return {
        "id": case["id"],
        "variant": case.get("variant", case.get("wording", "")),
        "rule": case.get("rule"),
        "mention": case["mention"],
        "gold": case["gold"],
        "expect_ambiguous": case["expect_ambiguous"],
        "top": ids[:5],
        "scores": [c["score"] for c in p["candidates"][:5]],
        "ambiguous": p["ambiguous"],
        "hybrid": p.get("hybrid"),
        "stage": stage,
        "top1": bool(gold) and bool(ids) and ids[0] in gold,
        "top3": bool(gold) and any(i in gold for i in ids[:3]),
        "no_match_ok": (not gold) and not ids,
    }


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pos = [r for r in rows if r["gold"]]
    neg = [r for r in rows if not r["gold"]]
    exp = [r for r in pos if r["expect_ambiguous"]]
    not_exp = [r for r in pos if not r["expect_ambiguous"]]

    def rate(xs: list[Any], f: Callable[[Any], bool]) -> tuple[int, int]:
        return sum(1 for x in xs if f(x)), len(xs)

    return {
        "n": len(rows),
        "top1": rate(pos, lambda r: r["top1"]),
        "top3": rate(pos, lambda r: r["top3"]),
        "no_match": rate(neg, lambda r: r["no_match_ok"]),
        "ambiguous_rate": rate(pos, lambda r: r["ambiguous"]),
        "ambiguous_recall": rate(exp, lambda r: r["ambiguous"]),
        "false_ambiguous": rate(not_exp, lambda r: r["ambiguous"]),
    }


def fmt(pair: tuple[int, int]) -> str:
    k, n = pair
    return "–" if n == 0 else f"{k}/{n} = {k / n:.2f}"


# -- corpora ------------------------------------------------------------------------------------


def synthetic(with_hybrid: bool) -> tuple[Any, Any, Any]:
    from dlens.agent.tools.provenance import Provenance
    from dlens.graph import load_or_build
    from dlens.graph.cache import cache_path

    graph = load_or_build(SYNTH)
    index = None
    if with_hybrid:
        from dlens.retrieval.dense import get_embedder
        from dlens.retrieval.index import SearchIndex, project_index_dir

        index, _ = SearchIndex.open(
            graph=graph,
            graph_file=cache_path(SYNTH),
            target_dir=SYNTH / "target",
            project_dir=SYNTH,
            index_dir=project_index_dir(SYNTH),
            embedder=get_embedder(),
        )
    return graph, Provenance(graph, SYNTH), index


def jira(work: Path, with_hybrid: bool) -> tuple[Any, Any, Any]:
    from dlens.agent.tools.provenance import Provenance
    from dlens.graph import build_graph_from_artifacts
    from dlens.ingest.runner import run_dbt

    project = work / "dbt_jira"
    target = project / "integration_tests" / "target"
    if not (target / "manifest.json").exists():
        shutil.copytree(JIRA, project, symlinks=True, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("target", "logs", "*.duckdb"))  # fmt: skip
        target = run_dbt(project / "integration_tests").target_dir
    graph, _ = build_graph_from_artifacts(target)
    index = None
    if with_hybrid:
        from dlens.retrieval.dense import get_embedder
        from dlens.retrieval.index import SearchIndex

        gfile = work / "jira_graph.json"
        graph.save(gfile)
        index, _ = SearchIndex.open(
            graph=graph,
            graph_file=gfile,
            target_dir=target,
            project_dir=target.parent,
            index_dir=work / "jira_index",
            embedder=get_embedder(),
        )
    return graph, Provenance(graph, target.parent), index


# -- evidence (linker-dev only) -----------------------------------------------------------------


def tau_evidence(graph: Any, cases: list[dict[str, Any]]) -> dict[str, list[float]]:
    """Top raw score with the threshold off: no-match cases vs positive cases (v2, no hybrid)."""
    from dlens.agent.tools import entity

    saved = entity.NO_MATCH
    entity.NO_MATCH = -1.0
    try:
        out: dict[str, list[float]] = {"no_match": [], "positive": []}
        for c in cases:
            ranked, _ = entity.link(graph, c["mention"], None)
            top = round(ranked[0].raw, 3) if ranked else 0.0
            out["positive" if c["gold"] else "no_match"].append(top)
        return out
    finally:
        entity.NO_MATCH = saved


def cosine_evidence(graph: Any, index: Any, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dense cosine of the gold card vs the best wrong card (design §4.3), linker-dev
    description-worded and no-match cases."""
    import numpy as np

    cols = [i for i, ch in enumerate(index.chunks) if ch.kind == "column" and ch.column]
    rows = []
    for c in cases:
        if c["variant"] not in ("description", "no_match"):
            continue
        q = index.embedder.embed([c["mention"]], query=True)[0]
        sims = index.vectors @ q
        gold_i = [i for i in cols if short(index.chunks[i].column) in set(c["gold"])]
        wrong_i = [i for i in cols if i not in gold_i]
        rows.append({
            "id": c["id"], "variant": c["variant"], "mention": c["mention"],
            "gold_cos": round(float(np.max(sims[gold_i])), 3) if gold_i else None,
            "best_wrong_cos": round(float(np.max(sims[wrong_i])), 3),
        })  # fmt: skip
    return rows


def dev15(graph: Any) -> dict[str, Any]:
    from dlens.agent.tools import entity
    from dlens.agent.tools.provenance import Provenance

    text = "number of orders per customer"
    out = entity.resolve_entity(Provenance(graph, SYNTH), {"text": text, "k": 10})
    return {
        "forms": [{"rule": f.rule, "surface": list(f.surface)} for f in entity.forms(text)],
        "rewritten_tokens": entity.tokens(text),
        "payload": out.payload,
        "parts": out.side["parts"],
    }


# -- main -------------------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--work", type=Path, help="scratch dir for the dbt_jira build and index")
    ap.add_argument("--no-jira", action="store_true")
    args = ap.parse_args()
    work = args.work or Path(tempfile.mkdtemp(prefix="linker_report_"))
    work.mkdir(parents=True, exist_ok=True)

    from dlens.agent.tools import entity

    v1 = _v1()
    cases = load("cases.jsonl")
    sets = {
        "linker-dev": [c for c in cases if c["split"] == "linker-dev"],
        "linker-test": [c for c in cases if c["split"] == "linker-test"],
        "dev mentions": load("dev_mentions.jsonl"),
    }
    graph, prov, index = synthetic(with_hybrid=True)
    systems: dict[str, Callable[[str], Any]] = {
        "v1": lambda t: v1.resolve_entity(prov, {"text": t}),
        "v2 (no hybrid)": lambda t: entity.resolve_entity(prov, {"text": t}),
        "v2 (hybrid)": lambda t: entity.resolve_entity(prov, {"text": t}, index),
    }
    results: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(dict)
    for sname, run in systems.items():
        for setname, cs in sets.items():
            results[sname][setname] = [run_case(run, c) for c in cs]
    if not args.no_jira:
        jg, jprov, jidx = jira(work, with_hybrid=True)
        jcases = load("jira_sample.jsonl")
        jsys: dict[str, Callable[[str], Any]] = {
            "v1": lambda t: v1.resolve_entity(jprov, {"text": t}),
            "v2 (no hybrid)": lambda t: entity.resolve_entity(jprov, {"text": t}),
            "v2 (hybrid)": lambda t: entity.resolve_entity(jprov, {"text": t}, jidx),
        }
        for sname, run in jsys.items():
            results[sname]["dbt_jira sample"] = [run_case(run, c) for c in jcases]

    evidence = {
        "tau": tau_evidence(graph, sets["linker-dev"]),
        "cosine": cosine_evidence(graph, index, sets["linker-dev"]),
    }
    report = {
        "index_key": index.meta.get("key") if index is not None else None,
        "metrics": {s: {k: metrics(v) for k, v in by.items()} for s, by in results.items()},
        "rows": results,
        "evidence": evidence,
        "dev15": dev15(graph),
        "constants": {"NO_MATCH": entity.NO_MATCH, "AMBIGUOUS_GAP": entity.AMBIGUOUS_GAP,
                      "COS_MIN": entity.COS_MIN},
    }  # fmt: skip
    OUT_JSON.write_text(json.dumps(report, indent=1))
    OUT_MD.write_text(render(report))
    print(OUT_MD.read_text())
    return 0


# -- rendering --------------------------------------------------------------------------------


def render(r: dict[str, Any]) -> str:
    m = r["metrics"]
    systems = list(m)
    sets = list(m[systems[0]])
    L = [
        "# Entity linker report (S08)",
        "",
        "Report only: not benchmark metrics. Generated by `scripts/linker_report.py` from",
        "`eval/linker/` (owner-reviewed cases). No LLM call. v1 = frozen `eval/linker/v1.py`;",
        "v2 = `src/dlens/agent/tools/entity.py`; hybrid = v2 with the S07 index.",
        f"Constants: tau (NO_MATCH) {r['constants']['NO_MATCH']}, delta (AMBIGUOUS_GAP) "
        f"{r['constants']['AMBIGUOUS_GAP']}, COS_MIN {r['constants']['COS_MIN']}.",
        "",
        "## Headline",
        "",
        "| set | system | top-1 | top-3 | no-match | ambiguous (all pos.) | ambiguous recall | false ambiguous |",
        "|---|---|---|---|---|---|---|---|",
    ]  # fmt: skip
    for st in sets:
        for s in systems:
            x = m[s].get(st)
            if x is None:
                continue
            L.append(
                f"| {st} | {s} | {fmt(x['top1'])} | {fmt(x['top3'])} | {fmt(x['no_match'])} | "
                f"{fmt(x['ambiguous_rate'])} | {fmt(x['ambiguous_recall'])} | "
                f"{fmt(x['false_ambiguous'])} |"
            )
    for st in ("linker-dev", "linker-test"):
        L += ["", f"## Per variant: {st}", "", "| variant | n | " + " | ".join(
            f"{s} top-1 | {s} top-3" for s in systems) + " |", "|---|---|" + "---|---|" * len(systems)]  # fmt: skip
        variants = sorted({row["variant"] for row in r["rows"][systems[0]][st]})
        for v in variants:
            cells = []
            n = 0
            for s in systems:
                rows = [x for x in r["rows"][s][st] if x["variant"] == v]
                n = len(rows)
                mm = metrics(rows)
                if v == "no_match":
                    cells += [fmt(mm["no_match"]), "–"]
                else:
                    cells += [fmt(mm["top1"]), fmt(mm["top3"])]
            L.append(f"| {v} | {n} | " + " | ".join(cells) + " |")
    L += ["", "## Per winning stage of the top-1 (v2 with hybrid, linker-dev + linker-test)", "",
          "| stage / tier | n | top-1 correct |", "|---|---|---|"]  # fmt: skip
    by_stage: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for st in ("linker-dev", "linker-test"):
        for x in r["rows"]["v2 (hybrid)"][st]:
            if x["gold"]:
                by_stage[x["stage"]].append(x)
    for k, rows in sorted(by_stage.items()):
        L.append(f"| {k} | {len(rows)} | {sum(x['top1'] for x in rows)} |")
    L += ["", "## Phrase rules on linker-test (separately from dev)", "",
          "| rule | n | " + " | ".join(f"{s} top-1" for s in systems) + " |",
          "|---|---|" + "---|" * len(systems)]  # fmt: skip
    for rule in ("P1", "P2", "P3", "P4"):
        cells = []
        n = 0
        for s in systems:
            rows = [x for x in r["rows"][s]["linker-test"] if x["rule"] == rule]
            n = len(rows)
            cells.append(fmt(metrics(rows)["top1"]))
        L.append(f"| {rule} | {n} | " + " | ".join(cells) + " |")
    L += ["", "## Dev mentions (20 dev targets)", "", "| id | mention | gold | v1 top-1 | v2 top-1 | v2 ambiguous |", "|---|---|---|---|---|---|"]  # fmt: skip
    for a, b in zip(
        r["rows"]["v1"]["dev mentions"], r["rows"]["v2 (no hybrid)"]["dev mentions"], strict=True
    ):
        L.append(f"| {a['id']} | {a['mention']} | {', '.join(a['gold']) or '(none)'} | "
                 f"{(a['top'] or ['(none)'])[0]} | {(b['top'] or ['(none)'])[0]} | {b['ambiguous']} |")  # fmt: skip
    t = r["evidence"]["tau"]
    L += ["", "## Evidence for tau (linker-dev, v2 without hybrid, threshold off)", "",
          f"Top raw score, no-match cases (n={len(t['no_match'])}): {sorted(t['no_match'])}", "",
          f"Top raw score, positive cases (n={len(t['positive'])}): min {min(t['positive'])}, "
          f"below tau: {sum(s < r['constants']['NO_MATCH'] for s in t['positive'])}", ""]  # fmt: skip
    L += ["## Evidence for COS_MIN (linker-dev description and no-match cases)", "",
          "| id | variant | mention | gold card cos | best wrong card cos |", "|---|---|---|---|---|"]  # fmt: skip
    for x in r["evidence"]["cosine"]:
        L.append(
            f"| {x['id']} | {x['variant']} | {x['mention']} | {x['gold_cos']} | {x['best_wrong_cos']} |"
        )
    d = r["dev15"]
    L += ["", "## dev-15 in full", "", f"Text forms: {d['forms']}", "",
          f"Ambiguous: {d['payload']['ambiguous']}", "",
          "| candidate | match | score | parts |", "|---|---|---|---|"]  # fmt: skip
    for c in d["payload"]["candidates"]:
        L.append(
            f"| {c['id']} | {c['match']} | {c['score']} | `{json.dumps(d['parts'][c['id']])}` |"
        )
    L += ["", "## Misses (v2 with hybrid, linker-dev + linker-test + dev mentions)", "",
          "| id | variant | mention | gold | top (scores) | ambiguous |", "|---|---|---|---|---|---|"]  # fmt: skip
    for st in ("linker-dev", "linker-test", "dev mentions"):
        for x in r["rows"]["v2 (hybrid)"][st]:
            miss = (x["gold"] and not x["top1"]) or (not x["gold"] and not x["no_match_ok"])
            if miss:
                tops = ", ".join(
                    f"{i} {s}" for i, s in zip(x["top"][:3], x["scores"][:3], strict=False)
                )
                L.append(f"| {x['id']} | {x['variant']} | {x['mention']} | {', '.join(x['gold']) or '(none)'} | {tops} | {x['ambiguous']} |")  # fmt: skip
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())
