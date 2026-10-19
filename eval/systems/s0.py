"""S0 graph oracle (S10, v0.3 D2; metrics-design.md M14). No LLM, ever.

Two variants answer the dev questions from the DLens graph:

* ``s0-gold``: the gold target (no linker) → the graph. Its gaps from 1.0 are engine-vs-gold
  differences.
* ``s0-linked``: ``link`` (the resolve_entity linker) on the question's ``mention``, hybrid stage
  OFF in S10 (no index, no model download), with the code ambiguity policy (chain / per
  candidate / clarification). S0-gold − S0-linked is the linker loss. The second endpoint of a
  yes/no question and a false premise's column are taken from the gold (they are not the
  question's mention).

Records use the S4 run-record format (``RunRecord`` fields, plus the record-level ``structured``
key: ``reach_verdict`` and both modes' sets), so ``eval/metrics.py`` scores every system the same
way. Only what metrics needs is kept. Ask questions get no record (n/a).

    uv run python eval/systems/s0.py            # both variants → eval/runs/s0/
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dlens.agent.tools.entity import AMBIGUOUS_GAP, link
from dlens.agent.tools.provenance import Provenance
from dlens.graph import AmbiguousColumn, ColumnNotFound, LineageGraph, load_or_build

ROOT = Path(__file__).resolve().parents[2]
CORPUS = "corpora/synthetic_shop"
QUESTIONS = ROOT / "eval" / "questions" / "dev.jsonl"
OUT = ROOT / "eval" / "runs" / "s0"
MAX_DEPTH = 50  # M14: effectively unbounded (no dev closure needs more than 10 hops)
TRACE_FAMILY = {"upstream", "computed", "ambiguous", "multi_part", "false_premise"}
SCHEMA_VERSION = 1


def primary_mode(q: Mapping[str, Any]) -> str | None:
    """M4 (a), the approved Appendix A mapping (same rule as eval/metrics.py)."""
    if q["subtype"] in TRACE_FAMILY:
        return "direct"
    if q["subtype"] in ("downstream", "yesno"):
        return "all"
    return None


def edge_key(from_col: str, to_col: str, kind: str) -> str:
    """The ``e_`` id scheme of ``dlens.agent.tools.provenance.edge_id``, also used for indirect
    edges (which the tools never emit today)."""
    return "e_" + hashlib.sha1(f"{from_col}|{to_col}|{kind}".encode()).hexdigest()[:8]


@dataclass
class Graph:
    """The DLens graph seen as edge lists in both modes, with short names and citations."""

    g: LineageGraph
    prov: Provenance
    preds: dict[str, dict[str, list[dict[str, Any]]]] = field(default_factory=dict)
    succs: dict[str, dict[str, list[dict[str, Any]]]] = field(default_factory=dict)

    @classmethod
    def load(cls, project: Path) -> Graph:
        return cls.from_graph(load_or_build(project), project)

    @classmethod
    def from_graph(cls, g: LineageGraph, project: Path) -> Graph:
        self = cls(g, Provenance(g, project))
        for mode in ("direct", "all"):
            self.preds[mode] = defaultdict(list)
            self.succs[mode] = defaultdict(list)
        for e in g.edges():
            rec = self.prov.edge_record(e)
            row = {
                "id": rec["edge_id"],
                "from": e.from_column,
                "to": e.to_column,
                "kind": rec["kind"],
                "citation": rec["citation"],
            }
            for mode in ("direct", "all"):
                self.preds[mode][e.to_column].append(row)
                self.succs[mode][e.from_column].append(row)
        for x in g.indirect_edges():
            kind = str(x.kind)
            row = {
                "id": edge_key(x.from_column, x.to_column, kind),
                "from": x.from_column,
                "to": x.to_column,
                "kind": kind,
                "key": x.key,
                "citation": {
                    "file": x.file,
                    "line_start": x.lines[0],
                    "line_end": x.lines[1],
                    "level": "model" if x.model_level_citation else "line",
                },
            }
            self.preds["all"][x.to_column].append(row)
            self.succs["all"][x.from_column].append(row)
        return self

    def name(self, col: str) -> str:
        return self.g.display_name(col)

    def closure(self, start: str, mode: str, up: bool) -> tuple[set[str], list[dict[str, Any]]]:
        """Columns reachable from ``start`` (upstream or downstream) within MAX_DEPTH hops, and
        every edge among them (the answer's cited sub-graph)."""
        adj = self.preds[mode] if up else self.succs[mode]
        depth = {start: 0}
        todo = deque([start])
        while todo:
            c = todo.popleft()
            if depth[c] >= MAX_DEPTH:
                continue
            for e in adj.get(c, []):
                nxt = e["from"] if up else e["to"]
                if nxt not in depth:
                    depth[nxt] = depth[c] + 1
                    todo.append(nxt)
        nodes = set(depth) - {start}
        inside = nodes | {start}
        edges = {
            e["id"]: e
            for c in inside
            for e in adj.get(c, [])
            if e["from"] in inside and e["to"] in inside
        }
        return nodes, sorted(edges.values(), key=lambda e: (e["from"], e["to"], e["kind"]))

    def inputs(self, target: str, mode: str) -> list[dict[str, Any]]:
        return sorted(self.preds[mode].get(target, []), key=lambda e: (e["from"], e["kind"]))

    def path(self, a: str, b: str, mode: str) -> list[dict[str, Any]] | None:
        """Edges of a shortest path a → b, or None if b is not reachable."""
        prev: dict[str, dict[str, Any] | None] = {a: None}
        todo = deque([a])
        while todo:
            c = todo.popleft()
            if c == b:
                out = []
                while (e := prev[c]) is not None:
                    out.append(e)
                    c = e["from"]
                return out[::-1]
            for e in self.succs[mode].get(c, []):
                if e["to"] not in prev:
                    prev[e["to"]] = e
                    todo.append(e["to"])
        return None

    def exposures(self, models: Iterable[str]) -> list[str]:
        """Exposure names reading any of ``models`` (full model ids)."""
        hit = set(models)
        names = set()
        for x, m in self.g.consumes():
            if m in hit:
                names.add((self.g.exposure_info(x) or {}).get("name", x.split(".")[-1]))
        return sorted(names)

    def resolve(self, text: str) -> str | None:
        try:
            return self.g.resolve(text)
        except (ColumnNotFound, AmbiguousColumn):
            return None


# ------------------------------------------------------------------------------- answers
@dataclass
class Draft:
    """What one S0 answer holds before it becomes a record."""

    answer_text: str = ""
    edges: list[dict[str, Any]] = field(default_factory=list)
    refused: bool = False
    refusal_reason: str | None = None
    clarification: list[str] | None = None
    reach_verdict: str | None = None
    ambiguity: dict[str, Any] | None = None
    sets: dict[str, Any] = field(default_factory=dict)


def _list(names: Iterable[str]) -> str:
    items = list(names)
    return ", ".join(items) if items else "nothing"


def trace_answer(G: Graph, target: str, mode: str) -> Draft:
    nodes, edges = G.closure(target, mode, up=True)
    names = sorted(G.name(c) for c in nodes)
    sets = {
        m: sorted(G.name(c) for c in G.closure(target, m, up=True)[0]) for m in ("direct", "all")
    }
    text = (
        f"{G.name(target)} comes from {_list(names)}."
        if names
        else f"{G.name(target)} has no upstream columns: it is a source."
    )
    return Draft(answer_text=text, edges=edges, sets={"upstream": sets})


def computed_answer(G: Graph, target: str, mode: str, premise: str | None = None) -> Draft:
    edges = G.inputs(target, mode)
    names = sorted({G.name(e["from"]) for e in edges})
    text = f"{G.name(target)} is computed from {_list(names)}."
    if premise:
        text += f" It does not use {premise}."
    sets = {m: sorted({G.name(e["from"]) for e in G.inputs(target, m)}) for m in ("direct", "all")}
    return Draft(answer_text=text, edges=edges, sets={"inputs": sets})


def impact_answer(G: Graph, source: str, mode: str) -> Draft:
    nodes, edges = G.closure(source, mode, up=False)
    names = sorted(G.name(c) for c in nodes)
    models = sorted({G.g.model_of(c) for c in nodes})
    exposures = G.exposures(models)
    parts = [f"If {G.name(source)} changes, these columns are affected: {_list(names)}."]
    parts.append(f"Models affected: {_list(m.split('.')[-1] for m in models)}.")
    if exposures:
        parts.append(f"Dashboards affected: {_list(exposures)}.")
    sets = {}
    for m in ("direct", "all"):
        ns = G.closure(source, m, up=False)[0]
        ms = sorted({G.g.model_of(c) for c in ns})
        sets[m] = {
            "columns": sorted(G.name(c) for c in ns),
            "models": [x.split(".")[-1] for x in ms],
            "exposures": G.exposures(ms),
        }
    return Draft(answer_text=" ".join(parts), edges=edges, sets={"downstream": sets})


def reach_answer(G: Graph, a: str, b: str, mode: str) -> Draft:
    verdicts = {m: "yes" if G.path(a, b, m) is not None else "no" for m in ("direct", "all")}
    path = G.path(a, b, mode)
    if path is not None:
        text = f"Yes: {G.name(a)} reaches {G.name(b)} in {len(path)} hops."
        edges = path
    else:
        text = f"No: {G.name(a)} does not reach {G.name(b)}."
        edges = []
    return Draft(
        answer_text=text, edges=edges, reach_verdict=verdicts[mode], sets={"reach": verdicts}
    )


def refusal(reason: str) -> Draft:
    return Draft(answer_text=f"I can't answer this: {reason}", refused=True, refusal_reason=reason)


# --------------------------------------------------------------------------- the two variants
def answer_for(G: Graph, q: Mapping[str, Any], target: str) -> Draft:
    """Answer the question for a resolved full column id (both variants end here)."""
    gold, sub, mode = q["gold"], q["subtype"], primary_mode(q)
    assert mode is not None
    if sub in ("upstream", "multi_part", "ambiguous"):
        return trace_answer(G, target, mode)
    if sub == "computed":
        return computed_answer(G, target, mode)
    if sub == "false_premise":
        return computed_answer(G, target, mode, premise=gold["premise"]["edge"]["from"])
    if sub == "downstream":
        return impact_answer(G, target, mode)
    if sub == "yesno":
        other = G.resolve(gold["reach"]["to"])
        if other is None:
            return refusal(f"{gold['reach']['to']} is not a column")
        return reach_answer(G, target, other, mode)
    raise ValueError(f"S0 has no answer for subtype {sub}")


def s0_gold(G: Graph, q: Mapping[str, Any]) -> Draft:
    gold = q["gold"]
    if q["type"] == "unanswerable":
        target = G.resolve(str(q.get("target") or ""))
        if target is None:
            return refusal(f"{q.get('target')} is not a column in this project")
    if gold["verdict"] == "clarify":
        return Draft(
            answer_text="Which column do you mean?",
            clarification=list(gold["candidates"]),
            ambiguity={"mode": "clarification", "candidates": list(gold["candidates"])},
        )
    target = G.resolve(q["target"])
    if target is None:
        return refusal(f"{q['target']} is not a column in this project")
    d = answer_for(G, q, target)
    if gold["verdict"] == "chain":
        d.ambiguity = {
            "mode": "chain",
            "candidates": list(gold["candidates"]),
            "downstream": G.name(target),
        }
    return d


def chain_end(G: Graph, cols: list[str]) -> str | None:
    """The most downstream column if all ``cols`` lie on one direct lineage chain (the loop's
    rule, ``_chain_end``), else None."""
    ups = {c: G.closure(c, "direct", up=True)[0] for c in cols}
    for i, a in enumerate(cols):
        for b in cols[i + 1 :]:
            if a not in ups[b] and b not in ups[a]:
                return None
    ends = [c for c in cols if all(o in ups[c] for o in cols if o != c)]
    return ends[0] if ends else None


def s0_linked(G: Graph, q: Mapping[str, Any]) -> Draft:
    mention = str(q.get("mention") or q.get("target") or "")
    cands, info = link(G.g, mention, None)  # hybrid OFF (S10)
    if not cands:
        return refusal(f"no column matches {mention!r}")
    top = cands[0]
    tie = [c for c in cands[:5] if top.raw - c.raw < AMBIGUOUS_GAP] if len(cands) > 1 else [top]
    lead = ""
    if any(n.startswith("interpreted ") for n in info.get("notes", [])):
        lead = f"Interpreted {mention} as {G.name(top.cid)}. "
    if len(tie) > 1:
        names = [G.name(c.cid) for c in tie]
        cols = [c.cid for c in tie if G.g.nx_graph.has_node(c.cid)]
        end = chain_end(G, cols) if len(cols) == len(tie) else None
        if end is not None:
            d = answer_for(G, q, end)
            d.ambiguity = {"mode": "chain", "candidates": names, "downstream": G.name(end)}
            return d
        if len(tie) <= 3 and len(cols) == len(tie):
            parts = [answer_for(G, q, c) for c in cols]
            d = Draft(
                answer_text=" ".join(p.answer_text for p in parts),
                edges=[e for p in parts for e in p.edges],
                ambiguity={"mode": "per_candidate", "candidates": names},
            )
            return d
        return Draft(
            answer_text="Which column do you mean?",
            clarification=names,
            ambiguity={"mode": "clarification", "candidates": names},
        )
    if not G.g.nx_graph.has_node(top.cid):
        return refusal(f"{mention!r} names a model, not a column")
    d = answer_for(G, q, top.cid)
    d.answer_text = lead + d.answer_text
    return d


# ------------------------------------------------------------------------------- records
def to_record(G: Graph, q: Mapping[str, Any], d: Draft, system: str, ms: float) -> dict[str, Any]:
    """A lean RunRecord-format dict: what metrics reads, nothing else."""
    edges = {
        e["id"]: {
            "from": e["from"],
            "to": e["to"],
            "kind": e["kind"],
            "citation": e["citation"],
            **({"key": e["key"]} if e.get("key") else {}),
        }
        for e in d.edges
    }
    claims = [
        {
            "text": f"{G.name(e['from'])} feeds {G.name(e['to'])} ({e['kind']}).",
            "edge_ids": [e["id"]],
            "chunk_ids": [],
        }
        for e in d.edges
    ]
    clar = (
        {"question": d.answer_text, "candidates": d.clarification}
        if d.clarification is not None
        else None
    )
    final = {
        "answer_text": d.answer_text,
        "claims": [] if d.refused or clar else claims,
        "refused": d.refused,
        "refusal_reason": d.refusal_reason,
        "clarification": clar,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": f"{system}-{q['id']}",
        "question": q["question"],
        "project": CORPUS,
        "provider": system,
        "model": "dlens-graph",
        "params": {"hybrid": False, "max_depth": MAX_DEPTH},
        "steps": [{"phase": "code", "results": [{"tool": "s0", "side_records": {"edges": edges}}]}],
        "ambiguity": d.ambiguity,
        "clarification": clar,
        "final_answer": final,
        "structured": {"reach_verdict": d.reach_verdict, "sets": d.sets},
        "stop_reason": "s0",
        "error": None,
        "timings": {"total_ms": round(ms, 1)},
        "tokens": {"llm_calls": 0, "cached_calls": 0, "sum_input": 0, "sum_output": 0},
    }


def run(system: str, questions: list[dict[str, Any]], G: Graph) -> list[dict[str, Any]]:
    answer = s0_gold if system == "s0-gold" else s0_linked
    out = []
    for q in questions:
        if q["type"] == "ask":
            continue  # M14: Ask is n/a for S0
        t0 = time.perf_counter()
        d = answer(G, q)
        out.append(to_record(G, q, d, system, (time.perf_counter() - t0) * 1000))
    return out


def git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def manifest(system: str, records: list[dict[str, Any]], records_file: Path) -> dict[str, Any]:
    text = QUESTIONS.read_text()
    return {
        "system": system,
        "view": "validated",
        "provider": system,
        "model": "dlens-graph",
        "records_file": records_file.name,
        "record_count": len(records),
        "questions_file": "eval/questions/dev.jsonl",
        "questions_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "git_commit": git_commit(),
        "hybrid": False,
        "linker": "link() without the hybrid stage" if system == "s0-linked" else None,
        "max_depth": MAX_DEPTH,
        "required": [r["run_id"].removeprefix(f"{system}-") for r in records],
        "note": "S0-linked (hybrid off)" if system == "s0-linked" else "S0-gold (no linker)",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--only", choices=["s0-gold", "s0-linked"])
    ns = ap.parse_args(argv)
    questions = [json.loads(x) for x in QUESTIONS.read_text().splitlines() if x.strip()]
    G = Graph.load(ROOT / CORPUS)
    ns.out.mkdir(parents=True, exist_ok=True)
    for system in [ns.only] if ns.only else ["s0-gold", "s0-linked"]:
        records = run(system, questions, G)
        path = ns.out / f"{system}-dev.jsonl"
        path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records))
        man = manifest(system, records, path)
        path.with_name(f"{system}-dev.manifest.json").write_text(
            json.dumps(man, indent=1, sort_keys=True) + "\n"
        )
        print(f"{system}: {len(records)} records → {path.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
