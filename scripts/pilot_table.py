"""S13 pilot table (metrics-design M16; docs/plans/pilot-design.md §1): score every row of one
panel with ``eval/metrics.py`` (its CLI, unchanged, 1.3.0) and assemble the tables. This script
adds no definition: every number is a metrics.py output or a metrics.py function (``stat``,
``paired_bootstrap``, ``mcnemar_exact``) applied to its per-question rows.

    uv run python scripts/pilot_table.py --panel qwen    # -> eval/reports/s13/pilot_qwen.md

Rows (pilot-design §1): S0-gold, S0-linked (hybrid on, the S4 runs' linker flag, M14), S1 (the
pilot run), S4 raw / validated / augmented. S1 vs S4 is compared within the panel only (§2).
Per-row metrics reports go to ``eval/reports/s13/<panel>/``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

import metrics as M  # noqa: E402

OUT = ROOT / "eval" / "reports" / "s13"


@dataclass(frozen=True)
class Row:
    label: str
    records: str  # repo-relative
    system: str  # metrics.py --system (picks the adapter)
    view: str = "validated"

    @property
    def slug(self) -> str:
        return self.label.lower().replace(" ", "_").replace("(", "").replace(")", "")


S0 = [
    Row("S0-gold", "eval/runs/s0/s0-gold-dev.jsonl", "s0-gold"),
    Row("S0-linked (hybrid on)", "eval/runs/s0/s0-linked-hybrid-dev.jsonl", "s0-linked"),
]


def _panel(s1: str, s4: str, model: str) -> list[Row]:
    return [
        *S0,
        Row("S1", s1, f"s1-{model}"),
        *(Row(f"S4 {v}", s4, f"s4-{model}", v) for v in ("raw", "validated", "augmented")),
    ]


PANELS: dict[str, dict[str, Any]] = {
    "qwen": {
        "title": "qwen3:4b-instruct-2507-q4_K_M (local, Ollama)",
        "rows": _panel(
            "eval/runs/s1/pilot/s1-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl",
            "eval/runs/s4/s4-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl",
            "qwen3-4b",
        ),
    },
    "gemini": {
        "title": "gemini-3.5-flash-lite (cloud, free tier)",
        "rows": _panel(
            "eval/runs/s1/pilot/s1-gemini-3-5-flash-lite-dev.jsonl",
            "eval/runs/s4/s4-gemini-3-5-flash-lite-dev.jsonl",
            "gemini-3-5-flash-lite",
        ),
    },
}

QUALITY = [
    ("node-set F1", "node_f1"),
    ("trace F1", "trace_f1"),
    ("impact F1", "impact_f1"),
    ("yes/no", "yesno_correct"),
    ("refusal acc.", "refusal_correct"),
    ("false refusal", "false_refusal"),
    ("premise rejected", "premise_rejected"),
    ("uncovered part", "uncovered_part_correct"),
    ("chain", "chain_correct"),
    ("clarify", "clarify_correct"),
]
EVIDENCE = [
    ("path node cov.", "path_node_coverage"),
    ("hallucination rate", "hallucination_rate"),
    ("citation valid (answer)", "citation_valid_answer"),
    ("citation coverage", "citation_coverage"),
]
COMPARE = [("S1", "S4 raw"), ("S1", "S4 validated")]


# ---------------------------------------------------------------------------- scoring
def score(row: Row, out_dir: Path) -> dict[str, Any]:
    """One metrics.py run (its CLI, so the result is exactly what metrics.py reports)."""
    out = out_dir / row.slug
    argv = ["--records", str(ROOT / row.records), "--system", row.system, "--view", row.view]
    argv += ["--out", str(out), "--title", f"{row.label} (pilot dev)"]
    if M.main(argv) != 0:
        raise SystemExit(f"pilot_table: metrics.py failed on {row.label}")
    return dict(json.loads(out.with_suffix(".json").read_text()))


# ---------------------------------------------------------------------------- per question
def per_question(result: Mapping[str, Any], name: str) -> dict[str, float]:
    """``{id: value}`` of one metric, from the rows metrics.py wrote (``node_f1`` = the composite
    questions' headline F1, as ``metrics._values``)."""
    out = {}
    for r in result["rows"]:
        mm = r["metrics"]
        v = (
            (mm.get("headline_f1") if r["composite"] else None)
            if name == "node_f1"
            else mm.get(name)
        )
        if v is not None:
            out[r["id"]] = float(v)
    return out


def compare(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
    """M13: paired bootstrap on node-set F1 (b − a), exact McNemar on ``fully_correct``."""
    fa, fb = per_question(a, "fully_correct"), per_question(b, "fully_correct")
    return {
        "paired": M.paired_bootstrap(per_question(a, "node_f1"), per_question(b, "node_f1")),
        "mcnemar": M.mcnemar_exact(
            {k: v == 1.0 for k, v in fa.items()}, {k: v == 1.0 for k, v in fb.items()}
        ),
        "n_binary": len(set(fa) & set(fb)),
    }


def losses(s1: Mapping[str, Any], s4: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every question where S4 scores below S1: headline F1 for composite questions, else
    ``fully_correct`` (verdicts, refusals, clarify)."""
    out = []
    for name in ("node_f1", "fully_correct"):
        a, b = per_question(s1, name), per_question(s4, name)
        for qid in sorted(set(a) & set(b)):
            if name == "fully_correct" and qid in per_question(s1, "node_f1"):
                continue  # composite questions are compared on F1
            if b[qid] < a[qid]:
                out.append({"id": qid, "metric": name, "s1": a[qid], "s4": b[qid]})
    rows = {r["id"]: r for r in s4["rows"]}
    for x in out:
        x["subtype"], x["kind"] = rows[x["id"]]["subtype"], rows[x["id"]]["kind"]
    return sorted(out, key=lambda x: (x["id"], x["metric"]))


# ---------------------------------------------------------------------------- render
def _f(v: float | None, digits: int = 3) -> str:
    return "–" if v is None else f"{v:.{digits}f}"


def _p(p: float) -> str:
    return f"{p:.4f}" if p >= 0.001 else f"{p:.1e}"


def cell(s: Mapping[str, Any]) -> str:
    if not s or not s.get("n"):
        return "–"
    ci = f" [{_f(s['ci'][0], 2)}, {_f(s['ci'][1], 2)}]" if s.get("ci") else ""
    return f"{_f(s['mean'])}{ci} ({s['n']})"


def _sampling(result: Mapping[str, Any]) -> str:
    man = result.get("manifest") or {}
    ident = man.get("model_identity") or {}
    params = man.get("params") or {}
    parts = [f"temperature {params.get('temperature', '–')}"]
    if ident.get("digest"):
        parts.append(f"digest {ident['digest'][:12]}")
    if "request" in ident:
        parts.append(f"thinkingConfig {json.dumps(ident['request']['thinking_config'])}")
    if man.get("quota", {}).get("daily_budget") is not None:
        parts.append(f"daily budget {man['quota']['daily_budget']}")
    return ", ".join(parts)


def render(
    panel: str, title: str, rows: Sequence[Row], results: Mapping[str, Mapping[str, Any]]
) -> str:
    first = next(iter(results.values()))
    v = first["versions"]
    lines = [
        f"# Pilot (dev), {panel}: {title}",
        "",
        f"> **pilot (dev), {panel}.** 96 dev questions; not a test-set result. "
        "S1 vs S4 is compared within this panel only (pilot-design §2).",
        "",
        f"metrics-design {v['design']} · metrics.py {v['metrics']} · dev.jsonl sha256 "
        f"{first['questions_sha256'][:12]} · bootstrap {M.RESAMPLES}×, seed {M.SEED}, CI only for "
        f"n ≥ {M.MIN_CI_N} · generated by `scripts/pilot_table.py --panel {panel}`",
        "",
        "Temperature: the local qwen panel runs at **temperature 0**, the Gemini panel at **1.0** "
        "(provider default, pilot-design §2). A single temperature-1.0 run carries more "
        "run-to-run noise than the ±0.04 seen between qwen runs.",
        "",
        "## Rows",
        "",
        "| row | records | complete | records / calls cached | sampling |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        r = results[row.label]
        man = r["manifest"]
        cache = man.get("cache") or {}
        cached = (
            f"{man['record_count']} / {cache['hits']} of {cache['hits'] + cache['misses']}"
            if cache
            else f"{man['record_count']} / –"
        )
        if row.system.startswith("s1"):
            lat = r["summary"].get("latency_ms") or {}
            cached = (
                f"{man['record_count']} / {lat.get('n_cached', '–')} records with a cached call"
            )
        llm = not row.system.startswith("s0")
        lines.append(
            f"| {row.label} | `{row.records}` | {r['complete']}"
            + (f" (missing {', '.join(r['missing'])})" if r["missing"] else "")
            + f" | {cached} | {_sampling(r) if llm else 'no LLM'} |"
        )
    for heading, cols in (("Answers", QUALITY), ("Evidence", EVIDENCE)):
        lines += ["", f"## {heading} (mean [95% CI] (n))", ""]
        lines.append("| row | " + " | ".join(c for c, _ in cols) + " |")
        lines.append("|---|" + "---|" * len(cols))
        for row in rows:
            m = results[row.label]["summary"]["metrics"]
            lines.append(f"| {row.label} | " + " | ".join(cell(m[k]) for _, k in cols) + " |")
    lines += ["", "## Cost (uncached runs only for latency, M15)", ""]
    lines += [
        "| row | latency p50 / p95 (s) | uncached / cached records | tokens / question mean (p95) | LLM calls / question |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        if row.system.startswith("s0"):
            lines.append(f"| {row.label} | – | – | – | 0 |")
            continue
        s = results[row.label]["summary"]
        lat, tok = s["latency_ms"], s["tokens"]
        p50 = _f(lat["p50"] / 1000, 1) if lat["p50"] is not None else "–"
        p95 = _f(lat["p95"] / 1000, 1) if lat["p95"] is not None else "–"
        lines.append(
            f"| {row.label} | {p50} / {p95} | {lat['n_uncached']} / {lat['n_cached']} | "
            f"{_f(tok['mean'], 0)} ({_f(tok['p95'], 0)}) | {_f(tok['llm_calls_mean'], 2)} |"
        )
    buckets = sorted(
        {
            k
            for r in results.values()
            for k in r["summary"]["node_f1_by"]["hop_bucket"]
            if k != "None"
        }
    )
    lines += ["", "## node-set F1 by hop bucket (the headline chart's data)", ""]
    lines += [
        "| row | " + " | ".join(f"hop {b}" for b in buckets) + " |",
        "|---|" + "---|" * len(buckets),
    ]
    for row in rows:
        hb = results[row.label]["summary"]["node_f1_by"]["hop_bucket"]
        lines.append(f"| {row.label} | " + " | ".join(cell(hb.get(b, {})) for b in buckets) + " |")
    lines += ["", "## S1 vs S4 (paired, within this panel; M13)", ""]
    lines += [
        "| comparison | node-set F1 diff (S4 − S1) [95% CI] (n) | McNemar on fully correct: S1 only / S4 only, p (n) |",
        "|---|---|---|",
    ]
    for a, b in COMPARE:
        c = compare(results[a], results[b])
        p, mc = c["paired"], c["mcnemar"]
        ci = f" [{_f(p['ci'][0])}, {_f(p['ci'][1])}]" if p["ci"] else ""
        lines.append(
            f"| {b} vs {a} | {_f(p['diff'], 3)}{ci} ({p['n']}) | {mc['b']} / {mc['c']}, p = {_p(mc['p'])} ({c['n_binary']}) |"
        )
    lines += [
        "",
        "## Pass routes (field / prose / both / neither) and spurious fields (not scored)",
        "",
    ]
    lines += [
        "| row | uncovered part | premise rejection | interpretation | spurious `uncovered_parts` | spurious `premise_corrected` |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        s = results[row.label]["summary"]
        pr, sp = s["pass_routes"], s["spurious_fields"]

        def route(rule: str, pr: Mapping[str, Any] = pr) -> str:
            c = pr.get(rule) or {}
            return (
                " / ".join(str(c.get(k, 0)) for k in ("field", "prose", "both", "neither"))
                if c
                else "n/a"
            )

        lines.append(
            f"| {row.label} | {route('uncovered')} | {route('premise')} | {route('interpretation')} | "
            f"{sp['uncovered_nonempty']['flagged']} / {sp['uncovered_nonempty']['n']} | "
            f"{sp['premise_flag']['flagged']} / {sp['premise_flag']['n']} |"
        )
    for view in ("S4 raw", "S4 validated", "S4 augmented"):
        lo = losses(results["S1"], results[view])
        lines += ["", f"## Losses: {view} below S1 ({len(lo)} questions)", ""]
        lines += [
            "| id | subtype | metric | S1 | S4 | S4 answer kind |",
            "|---|---|---|---|---|---|",
        ]
        for x in lo:
            lines.append(
                f"| {x['id']} | {x['subtype']} | {x['metric']} | {_f(x['s1'])} | {_f(x['s4'])} | {x['kind']} |"
            )
    lines += [
        "",
        "Ask questions (12) are hand-scored by the owner (M11) and reported in the final table.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--panel", choices=sorted(PANELS), required=True)
    ap.add_argument("--out", type=Path, default=OUT)
    ns = ap.parse_args(argv)
    spec = PANELS[ns.panel]
    missing = [r.records for r in spec["rows"] if not (ROOT / r.records).exists()]
    if missing:
        print(f"pilot_table: missing records {sorted(set(missing))}", file=sys.stderr)
        return 2
    results = {row.label: score(row, ns.out / ns.panel) for row in spec["rows"]}
    path = ns.out / f"pilot_{ns.panel}.md"
    path.write_text(render(ns.panel, spec["title"], spec["rows"], results))
    print(
        f"pilot_table: {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path.name}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
