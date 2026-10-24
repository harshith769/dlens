"""Generate the 96 dev question candidates (S09, docs/plans/questions-design.md §3-§5).

uv run python scripts/gen_dev_questions.py          # writes eval/questions/review/dev_candidates.jsonl
uv run python scripts/gen_dev_questions.py --check  # exit 1 if the file on disk is stale

Targets come from the DEV pool only (eval/questions/pools.yml; asserted). Gold comes only from
lineage_spec.yml through dlens.gold_spec, plus traps.yml (tags, exposures) and the hand drafts in
eval/questions/review/ (ask_drafts.yml; the frozen v0.2 file v02_dev.jsonl). The graph, the
parser and the linker are never loaded. Project YAML descriptions are read only to word
`description` questions; they are never gold.

The output is NOT dev.jsonl: questions count only after the owner's review (scripts/check_review.py,
scripts/apply_review.py). Paraphrase slots carry the template text and the flag
`paraphrase_pending` until scripts/paraphrase_questions.py fills them.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from dlens import gold_spec as gs

ROOT = Path(__file__).parents[1]
SS = ROOT / "corpora" / "synthetic_shop"
SPEC = SS / "lineage_spec.yml"
TRAPS = SS / "traps.yml"
SCHEMAS = [SS / "models" / d / "schema.yml" for d in ("staging", "intermediate", "marts")]
QDIR = ROOT / "eval" / "questions"
POOLS = QDIR / "pools.yml"
REVIEW = QDIR / "review"
V02 = REVIEW / "v02_dev.jsonl"
ASKS = REVIEW / "ask_drafts.yml"
OUT = REVIEW / "dev_candidates.jsonl"
SALT = "s09-questions-v1:"
SPEC_REL = "lineage_spec.yml"

RFM_MODELS = {
    "dim_customer_rfm",
    "dim_customer_segments",
    "fct_segment_monthly",
    "fct_customer_leaderboard",
}
OUT_OF_SCOPE = ["who owns it", "how often is it refreshed", "how much does it cost to compute"]
STOP = {
    "the",
    "a",
    "an",
    "of",
    "for",
    "in",
    "on",
    "to",
    "and",
    "or",
    "is",
    "its",
    "it",
    "by",
    "per",
}
# D5 exception (owner to decide in the review): dev-11 (re-tagged trace/computed, owner Q1) and
# dev-17 (false premise) are both Trace questions on this column.
D5_TRACE_EXCEPTIONS = {"fct_orders.revenue_finance"}

# Unanswerable questions (hand-listed; each column must not exist in the spec).
UNANSWERABLE = [
    # (key, kind, mention, template, wording)
    ("shipping_cost", "dotted_near_miss", "int_order_shipping.shipping_cost", "impact", "identifier"),
    ("discount_total", "dotted_near_miss", "fct_orders.discount_total", "upstream", "identifier"),
    ("segment", "dotted_near_miss", "dim_customers.segment", "upstream", "identifier"),
    ("typo", "dotted_typo", "fct_daily_revenue.revnue_finance", "upstream", "identifier"),
    ("unknown_model", "unknown_model", "fct_returns.return_amount", "impact", "identifier"),
    ("gift_card", "bare", "gift card balance", "upstream", "name_words"),
    ("loyalty", "bare", "loyalty points", "impact", "name_words"),
    ("salary", "out_of_domain", "payroll.employee_salary", "upstream", "paraphrase"),
]  # fmt: skip


def h(text: str, salt: str = SALT) -> str:
    return hashlib.sha256((salt + text).encode()).hexdigest()


def trace_bucket(d: int | None) -> str | None:
    if d is None:
        return None
    return "1" if d <= 1 else "2-3" if d <= 3 else "4-5" if d <= 5 else "6+"


def impact_bucket(dd: int, has_indirect: bool) -> str | None:
    if dd == 0:
        return "indirect-only" if has_indirect else None
    return trace_bucket(dd)


def words(text: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", text.lower()) if w]


# ------------------------------------------------------------------------------------ context
@dataclass
class Ctx:
    v: gs.View
    depths: dict[str, int | None]
    dev: set[str]
    test: set[str]
    lines: dict[tuple[str, str], int]
    trap_cols: dict[str, set[str]]
    trap_edges: dict[str, set[tuple[str, str]]]
    exposures: dict[str, list[str]]
    descriptions: dict[str, str]
    by_bare: dict[str, list[str]] = field(default_factory=dict)
    _down: dict[tuple[str, bool], set[str]] = field(default_factory=dict)
    _up: dict[tuple[str, bool], set[str]] = field(default_factory=dict)

    def depth(self, c: str) -> int | None:
        return 0 if c in self.v.seed_columns else self.depths.get(c)

    def down(self, c: str, indirect: bool) -> set[str]:
        if (c, indirect) not in self._down:
            self._down[(c, indirect)] = gs.downstream(self.v, c, include_indirect=indirect)
        return self._down[(c, indirect)]

    def up(self, c: str, indirect: bool) -> set[str]:
        if (c, indirect) not in self._up:
            self._up[(c, indirect)] = gs.upstream(self.v, c, include_indirect=indirect)
        return self._up[(c, indirect)]

    def edge(self, f: str, t: str) -> dict[str, Any]:
        kind = next(str(e["kind"]) for e in self.v.direct if e["from"] == f and e["to"] == t)
        return {"from": f, "to": t, "kind": kind, "line": self.lines[(f, t)]}


def load_ctx() -> Ctx:
    spec_text = SPEC.read_text()
    v = gs.build_view(yaml.safe_load(spec_text))
    traps = yaml.safe_load(TRAPS.read_text())
    pools = yaml.safe_load(POOLS.read_text())["columns"]
    trap_cols: dict[str, set[str]] = defaultdict(set)
    trap_edges: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for t in [*traps["traps"], *traps.get("extras", [])]:
        for part in [t, *(t.get("instances") or []), *([t["pair"]] if "pair" in t else [])]:
            trap_cols[t["id"]] |= set(part.get("columns") or [])
            for e in part.get("edges") or []:
                f, to = e.split(" -> ")
                trap_cols[t["id"]].add(to)
                trap_edges[t["id"]].add((f, to))
            for p in part.get("paths") or []:
                trap_cols[t["id"]] |= {p[0], p[-1]}
                trap_edges[t["id"]] |= set(zip(p, p[1:], strict=False))
    trap_cols["doc_injection"] = {traps["doc_injection"]["column"]}
    exposures = {x["name"]: list(x["depends_on"]) for x in traps["exposures"]}
    descriptions: dict[str, str] = {}
    for f in SCHEMAS:
        for m in (yaml.safe_load(f.read_text()) or {}).get("models") or []:
            for c in m.get("columns") or []:
                if c.get("description"):
                    descriptions[f"{m['name']}.{c['name']}"] = " ".join(
                        str(c["description"]).split()
                    )
    ctx = Ctx(
        v=v,
        depths=gs.compute_depths(v),
        dev={c for c, x in pools.items() if x["split"] == "dev"},
        test={c for c, x in pools.items() if x["split"] == "test"},
        lines=gs.edge_lines(spec_text),
        trap_cols=dict(trap_cols),
        trap_edges=dict(trap_edges),
        exposures=exposures,
        descriptions=descriptions,
    )
    by_bare: dict[str, list[str]] = defaultdict(list)
    for c in sorted(v.model_columns | v.seed_columns):
        by_bare[c.split(".")[1]].append(c)
    ctx.by_bare = dict(by_bare)
    return ctx


# --------------------------------------------------------------------------------------- gold
def subgraph_edges(ctx: Ctx, nodes: set[str]) -> list[dict[str, Any]]:
    return [ctx.edge(f, t) for f, t in sorted(ctx.v.direct_pairs) if f in nodes and t in nodes]


def gold_inputs(ctx: Ctx, t: str) -> dict[str, Any]:
    return {
        "direct": [str(e["from"]) for e in gs.direct_inputs(ctx.v, t)],
        "indirect": [{"from": x.from_column, "type": x.type} for x in gs.indirect_inputs(ctx.v, t)],
    }


def gold_trace(ctx: Ctx, t: str) -> dict[str, Any]:
    up_d, up_a = ctx.up(t, False), ctx.up(t, True)
    return {
        "verdict": "answered",
        "inputs": gold_inputs(ctx, t),
        "upstream": {"direct": sorted(up_d), "all": sorted(up_a)},
        "sources": sorted(up_d & ctx.v.seed_columns),
        "paths": [gs.longest_path(ctx.v, t, ctx.depths)],
        "edges": subgraph_edges(ctx, up_d | {t}),
    }


def gold_computed(ctx: Ctx, t: str) -> dict[str, Any]:
    return {
        "verdict": "answered",
        "inputs": gold_inputs(ctx, t),
        "edges": [ctx.edge(str(e["from"]), t) for e in gs.direct_inputs(ctx.v, t)],
    }


def gold_impact(ctx: Ctx, s: str) -> dict[str, Any]:
    dn_d, dn_a = ctx.down(s, False), ctx.down(s, True)
    md, ma = gs.models_of(dn_d), gs.models_of(dn_a)
    return {
        "verdict": "answered",
        "downstream": {"direct": sorted(dn_d), "all": sorted(dn_a)},
        "models": {"direct": sorted(md), "all": sorted(ma)},
        "exposures": {
            "direct": gs.exposures_reached(md, ctx.exposures),
            "all": gs.exposures_reached(ma, ctx.exposures),
        },
        "edges": subgraph_edges(ctx, dn_d | {s}),
    }


def gold_premise(ctx: Ctx, p: str, t: str) -> dict[str, Any]:
    """False premise: the target's inputs, plus the premise's real path when it is upstream."""
    gold = gold_computed(ctx, t)
    up_d = p in ctx.up(t, False)
    gold["premise"] = {"edge": {"from": p, "to": t}, "direct_edge": (p, t) in ctx.v.direct_pairs,
                       "reaches_all": p in ctx.up(t, True)}  # fmt: skip
    if up_d:
        path = shortest_path(ctx, p, t, indirect=False)
        gold["premise"]["path"] = path
        extra = [ctx.edge(a, b) for a, b in zip(path, path[1:], strict=False)]
        gold["edges"] += [e for e in extra if e not in gold["edges"]]
    return gold


def shortest_path(ctx: Ctx, s: str, t: str, indirect: bool) -> list[str]:
    nxt: dict[str, set[str]] = defaultdict(set)
    for f, to in ctx.v.direct_pairs:
        nxt[f].add(to)
    if indirect:
        for x in ctx.v.pairs:
            nxt[x.from_column].add(x.to_column)
    prev: dict[str, str] = {}
    todo = deque([s])
    seen = {s}
    while todo:
        c = todo.popleft()
        if c == t:
            path = [t]
            while path[-1] != s:
                path.append(prev[path[-1]])
            return path[::-1]
        for n in sorted(nxt[c] - seen):
            seen.add(n)
            prev[n] = c
            todo.append(n)
    return []


def gold_reach(ctx: Ctx, s: str, t: str) -> dict[str, Any]:
    d = gs.reaches(ctx.v, s, t, include_indirect=False)
    a = gs.reaches(ctx.v, s, t, include_indirect=True)
    path = shortest_path(ctx, s, t, indirect=not d) if a else []
    direct_path_edges = [
        ctx.edge(f, to)
        for f, to in zip(path, path[1:], strict=False)
        if (f, to) in ctx.v.direct_pairs
    ]
    return {
        "verdict": "answered",
        "reach": {"from": s, "to": t, "direct": "yes" if d else "no", "all": "yes" if a else "no",
                  "path": path},
        "edges": direct_path_edges,
    }  # fmt: skip


# -------------------------------------------------------------------------------------- tags
def tags(ctx: Ctx, cols: Iterable[str], edges: Iterable[tuple[str, str]], deep: bool,
         exposures: bool) -> list[str]:  # fmt: skip
    cols, edges = set(cols), set(edges)
    out = {t for t, cs in ctx.trap_cols.items() if cs & cols}
    out |= {t for t, es in ctx.trap_edges.items() if es & edges}
    out.discard("deep_chain")  # decided by depth alone (>= 6 hops), not by sharing a path edge
    if deep:
        out.add("deep_chain")
    if exposures:
        out.add("exposures")
    return sorted(out)


def trace_tags(ctx: Ctx, t: str, extra: Iterable[str] = ()) -> list[str]:
    path = gs.longest_path(ctx.v, t, ctx.depths)
    inp = [(str(e["from"]), t) for e in gs.direct_inputs(ctx.v, t)]
    return tags(ctx, [t, *extra], [*zip(path, path[1:], strict=False), *inp],
                deep=(ctx.depth(t) or 0) >= 6, exposures=False)  # fmt: skip


def impact_tags(ctx: Ctx, s: str, gold: Mapping[str, Any]) -> list[str]:
    first = [(s, t) for f, t in ctx.v.direct_pairs if f == s]
    return tags(ctx, [s], first, deep=gs.downstream_depth(ctx.v, s) >= 6,
                exposures=bool(gold["exposures"]["all"]))  # fmt: skip


# ----------------------------------------------------------------------------------- wording
def rfm_family(c: str) -> bool:
    return c.split(".")[0] in RFM_MODELS


def model_words(model: str) -> str:
    return re.sub(r"^(stg|int|fct|dim)_", "", model).replace("_", " ")


def name_words(ctx: Ctx, c: str, *, bare_only: bool = False) -> str:
    model, col = c.split(".")
    text = col.replace("_", " ")
    if not bare_only and len(ctx.by_bare.get(col, [])) > 1:
        text += f" in {model_words(model)}"
    return text


def description_mention(ctx: Ctx, c: str, inputs: Iterable[str] = ()) -> str | None:
    """The column's YAML description as a mention, if usable (questions-design.md §1.1)."""
    desc = ctx.descriptions.get(c)
    if not desc or c in ctx.trap_cols.get("stale_doc", set()) | ctx.trap_cols["doc_injection"]:
        return None
    if sum(1 for d in ctx.descriptions.values() if d == desc) > 1:
        return None
    toks = words(desc)
    if len([w for w in toks if w not in STOP]) < 4:
        return None
    tokset = set(toks)
    for i in inputs:  # trace/computed: the description must not name an input
        if set(words(i.split(".")[1])) <= tokset:
            return None
    return f"the column documented as '{desc.rstrip('.')}'"


TEMPLATES = {
    "upstream": "Where does {t} come from?",
    "computed": "How is {t} computed?",
    "ambiguous": "Where does {t} come from?",
    "multi_part": "Where does {t} come from, and {oos}?",
    "false_premise": "Why does {t} include {p}?",
    "impact": "What is affected if {t} changes?",
    "impact_lineage": "Which columns are downstream of {t} in the lineage?",
    "impact_exposures": "Which dashboards are affected if {t} changes?",
    "yesno": "If {s} changes, does it affect {t}?",
    "yesno_lineage": "Is {t} downstream of {s} in the lineage?",
}


# ------------------------------------------------------------------------------------ builder
@dataclass
class Slot:
    row: str
    subtype: str
    wording: str
    bucket: str | None = None
    min_depth: int = 0
    variant: str = ""  # yesno: yes_direct | yes_indirect_only | no ; impact: exposures


@dataclass
class Builder:
    ctx: Ctx
    questions: list[dict[str, Any]] = field(default_factory=list)
    used_trace: Counter[str] = field(default_factory=Counter)
    used_impact: Counter[str] = field(default_factory=Counter)
    trap_count: Counter[str] = field(default_factory=Counter)
    next_id: int = 21
    next_spare: int = 1
    log: list[str] = field(default_factory=list)
    split: str = "dev"  # the pool targets come from (pools.yml): dev, or test for D5b drafts
    salt: str = SALT

    @property
    def pool(self) -> set[str]:
        return self.ctx.dev if self.split == "dev" else self.ctx.test

    def h(self, text: str) -> str:
        return h(text, self.salt)

    # -- bookkeeping -----------------------------------------------------------------------------
    def add(self, q: dict[str, Any], spare: bool = False) -> None:
        if spare:
            q["id"] = f"{self.split}-s{self.next_spare:02d}"
            q["spare"] = True
            self.next_spare += 1
        elif "id" not in q:
            q["id"] = f"{self.split}-{self.next_id:02d}"
            self.next_id += 1
        slot = "trace" if q["type"] == "trace" else "impact" if q["type"] == "impact" else None
        if not spare and slot == "trace":
            self.used_trace[q["target"]] += 1
        if not spare and slot == "impact":
            self.used_impact[q["target"]] += 1
        if not spare:
            self.trap_count.update(q["traps"])
        self.questions.append(q)

    def ordered(self, cands: Iterable[str], tag_fn: Any) -> list[str]:
        """Hash order, but candidates that add an under-covered trap (< 2 questions) first."""

        def key(c: str) -> tuple[int, str]:
            need = sum(1 for t in tag_fn(c) if self.trap_count[t] < 2)
            return (-need, self.h(c))

        return sorted(cands, key=key)

    def base(self, slot: Slot, qtype: str, target: str, question: str, mention: str,
             hop: int | None, traps: list[str], gold: dict[str, Any],
             expect: dict[str, Any]) -> dict[str, Any]:  # fmt: skip
        flags = []
        if slot.wording == "paraphrase":
            flags.append("paraphrase_pending")
        q: dict[str, Any] = {
            "corpus": "synthetic_shop", "split": self.split, "type": qtype, "subtype": slot.subtype,
            "question": question, "target": target, "mention": mention, "hop_depth": hop,
            "hop_bucket": slot.bucket if slot.bucket else trace_bucket(hop), "wording": slot.wording,
            "source": "template", "traps": traps,
            "stratum": f"{slot.row}|{slot.bucket or '-'}", "gold": gold, "expect": expect,
            "source_lines": sorted({f"{SPEC_REL}:{e['line']}" for e in gold.get("edges", [])},
                                   key=lambda s: int(s.split(":")[1]))[:40],
            "review_flags": flags,
        }  # fmt: skip
        if slot.wording == "paraphrase":
            q["template_question"] = question
        return q

    def mention_for(self, slot: Slot, c: str, inputs: Iterable[str] = ()) -> str | None:
        if slot.wording in ("identifier", "paraphrase"):
            return c
        if slot.wording == "name_words":
            return name_words(self.ctx, c, bare_only=slot.subtype == "ambiguous")
        return description_mention(self.ctx, c, inputs)

    # -- trace rows ------------------------------------------------------------------------------
    def trace_candidates(self, slot: Slot) -> list[str]:
        ctx = self.ctx
        out = []
        for c in self.pool & ctx.v.model_columns:
            d = ctx.depth(c)
            if trace_bucket(d) != slot.bucket or (d or 0) < slot.min_depth:
                continue
            if self.used_trace[c]:
                continue
            if slot.subtype == "computed" and not any(
                e["kind"] in ("TRANSFORMATION", "AGGREGATION") for e in gs.direct_inputs(ctx.v, c)
            ):
                continue
            out.append(c)
        return out

    def fill_trace(self, slot: Slot, spare: bool = False) -> bool:
        ctx = self.ctx
        if slot.subtype == "ambiguous":
            return self.fill_ambiguous(slot)
        for c in self.ordered(self.trace_candidates(slot), lambda c: trace_tags(ctx, c)):
            inputs = [str(e["from"]) for e in gs.direct_inputs(ctx.v, c)]
            mention = self.mention_for(slot, c, inputs)
            if mention is None:
                continue
            if slot.subtype == "computed":
                gold, tmpl = gold_computed(ctx, c), TEMPLATES["computed"]
                expect = {"verdict": "answered",
                          "must_cite": [[{"from": i, "to": c}] for i in inputs]}  # fmt: skip
                question = tmpl.format(t=mention)
            elif slot.subtype == "multi_part":
                gold = gold_trace(ctx, c)
                oos = OUT_OF_SCOPE[int(self.h(c), 16) % len(OUT_OF_SCOPE)]
                gold.update(verdict="partial", out_of_scope=oos)
                question = TEMPLATES["multi_part"].format(t=mention, oos=oos)
                expect = {"verdict": "answered",
                          "must_cite": [[{"from": i, "to": c}] for i in inputs]}  # fmt: skip
            else:
                gold = gold_trace(ctx, c)
                question = TEMPLATES["upstream"].format(t=mention)
                expect = {"verdict": "answered",
                          "must_cite": [[{"from": i, "to": c}] for i in inputs]}  # fmt: skip
            q = self.base(slot, "trace", c, question, mention, ctx.depth(c), trace_tags(ctx, c),
                          gold, expect)  # fmt: skip
            self.add(q, spare)
            return True
        return False

    def fill_ambiguous(self, slot: Slot) -> bool:
        ctx = self.ctx
        cands = []
        for bare, cols in ctx.by_bare.items():
            models = [c for c in cols if c in ctx.v.model_columns]
            if not 2 <= len(models) <= 4:
                continue
            target = max(models, key=lambda c: (ctx.depth(c) or 0, c))
            if target in self.pool and not self.used_trace[target]:
                if trace_bucket(ctx.depth(target)) == slot.bucket:
                    cands.append(target)
        for c in self.ordered(cands, lambda c: trace_tags(ctx, c)):
            bare = c.split(".")[1]
            models = [x for x in ctx.by_bare[bare] if x in ctx.v.model_columns]
            chain = all(x == c or x in ctx.up(c, False) for x in models)
            gold = gold_trace(ctx, c)
            gold.update(verdict="chain" if chain else "clarify", candidates=models)
            mention = name_words(ctx, c, bare_only=True)
            inputs = [str(e["from"]) for e in gs.direct_inputs(ctx.v, c)]
            expect: dict[str, Any] = (
                {"verdict": "chain", "downstream": c,
                 "must_cite": [[{"from": i, "to": c} for i in inputs]]}
                if chain else {"verdict": "clarification"}
            )  # fmt: skip
            q = self.base(slot, "trace", c, TEMPLATES["ambiguous"].format(t=mention), mention,
                          ctx.depth(c), trace_tags(ctx, c), gold, expect)  # fmt: skip
            self.add(q)
            return True
        return False

    def fill_false_premise(self, slot: Slot) -> bool:
        ctx = self.ctx
        lo, hi = (1, 3) if slot.bucket == "1-3" else (4, 99)
        cands = [
            c for c in self.pool & ctx.v.model_columns
            if lo <= (ctx.depth(c) or 0) <= hi and not self.used_trace[c]
        ]  # fmt: skip
        for c in self.ordered(cands, lambda c: trace_tags(ctx, c)):
            model = c.split(".")[0]
            parents = ctx.v.depends_on.get(model, [])
            pool = [
                f"{p}.{col}"
                for p in parents
                for col in (ctx.v.models.get(p) or ctx.v.seeds.get(p) or [])
            ]
            up_all = ctx.up(c, True)
            premises = sorted(
                (p for p in pool if p in self.pool and p not in up_all and p != c), key=self.h
            )
            if not premises:
                continue
            p = premises[0]
            mention = self.mention_for(slot, c)
            assert mention is not None
            gold = gold_premise(ctx, p, c)
            inputs = gold["inputs"]["direct"]
            expect = {"verdict": "answered", "or_refused": True,
                      "must_cite": [[{"from": i, "to": c} for i in inputs]],
                      "forbid_edges": [{"from": p, "to": c}]}  # fmt: skip
            q = self.base(slot, "trace", c, TEMPLATES["false_premise"].format(t=mention, p=p),
                          mention, ctx.depth(c), trace_tags(ctx, c, [p]), gold, expect)  # fmt: skip
            q["hop_bucket"] = trace_bucket(ctx.depth(c))
            self.add(q)
            return True
        return False

    # -- impact rows -----------------------------------------------------------------------------
    def impact_candidates(self, slot: Slot) -> list[str]:
        ctx = self.ctx
        out = []
        for c in self.pool:
            if self.used_impact[c]:
                continue
            dd = gs.downstream_depth(ctx.v, c)
            b = impact_bucket(dd, bool(ctx.down(c, True)))
            if b == slot.bucket:
                out.append(c)
        return out

    def impact_wording(self, s: str, gold: Mapping[str, Any]) -> str:
        if rfm_family(s) or any(rfm_family(c) for c in gold["downstream"]["all"]):
            return "impact_lineage"
        return "impact"

    def fill_impact(self, slot: Slot, spare: bool = False) -> bool:
        ctx = self.ctx

        def tag_fn(c: str) -> list[str]:
            return impact_tags(ctx, c, gold_impact(ctx, c))

        for s in self.ordered(self.impact_candidates(slot), tag_fn):
            gold = gold_impact(ctx, s)
            kind = self.impact_wording(s, gold)
            if slot.variant == "exposures":
                if kind == "impact_lineage" or not gold["exposures"]["all"]:
                    continue
                kind = "impact_exposures"
                gold["focus"] = "exposures"
            mention = self.mention_for(slot, s)
            if mention is None:
                continue
            first = sorted(t for f, t in ctx.v.direct_pairs if f == s)
            expect = {"verdict": "answered",
                      "must_cite": [[{"from": s, "to": t}] for t in first]}  # fmt: skip
            hop = gs.downstream_depth(ctx.v, s)
            q = self.base(slot, "impact", s, TEMPLATES[kind].format(t=mention), mention, hop,
                          impact_tags(ctx, s, gold), gold, expect)  # fmt: skip
            q["hop_bucket"] = slot.bucket
            self.add(q, spare)
            return True
        return False

    def fill_yesno(self, slot: Slot) -> bool:
        ctx = self.ctx
        sources = [
            c for c in self.pool
            if not self.used_impact[c] and ctx.down(c, True)
        ]  # fmt: skip
        for s in sorted(sources, key=self.h):
            dn_d, dn_a = ctx.down(s, False), ctx.down(s, True)
            if slot.variant == "yes_direct":
                ts = [t for t in dn_d if t in self.pool and len(shortest_path(ctx, s, t, False)) >= 3]
            elif slot.variant == "yes_indirect_only":
                ts = [t for t in dn_a - dn_d if t in self.pool]
            else:  # no: a plausible column in a model the source reaches, but not reached
                ms = gs.models_of(dn_d)
                ts = [
                    t for t in self.pool & ctx.v.model_columns
                    if t.split(".")[0] in ms and t not in dn_a and t != s
                ]  # fmt: skip
            if not ts:
                continue
            t = sorted(ts, key=lambda x: self.h(s + x))[0]
            gold = gold_reach(ctx, s, t)
            lineage = (
                rfm_family(s) or rfm_family(t) or any(rfm_family(c) for c in gold["reach"]["path"])
            )
            mention_t = self.mention_for(slot, t)
            mention_s = self.mention_for(slot, s)
            if mention_s is None or mention_t is None:
                continue
            kind = "yesno_lineage" if lineage else "yesno"
            verdict = gold["reach"]["all"]
            expect = {"verdict": "answered", "yes_no": verdict}
            question = TEMPLATES[kind].format(s=mention_s, t=mention_t)
            hop = gs.downstream_depth(ctx.v, s)
            q = self.base(slot, "impact", s, question, mention_s, hop,
                          tags(ctx, [s, t], [], deep=hop >= 6, exposures=False), gold, expect)  # fmt: skip
            q["hop_bucket"] = impact_bucket(hop, True)
            q["subtype"] = "yesno"
            if gold["reach"]["direct"] != gold["reach"]["all"]:
                q["review_flags"].append("verdict_differs_by_mode")
            self.add(q)
            return True
        return False

    # -- hand rows -------------------------------------------------------------------------------
    def add_asks(self) -> None:
        ctx = self.ctx
        for a in yaml.safe_load(ASKS.read_text())["asks"]:
            t = a["target"]
            assert t in ctx.dev, f"ask {a['key']}: {t} is not a dev-pool column"
            for m in re.findall(r"\b[a-z_0-9]+\.[a-z_0-9]+\b", a["question"]):
                assert m not in ctx.test, f"ask {a['key']} names test-pool column {m}"
            gold: dict[str, Any] = {"verdict": "answered", "facts": a["facts"]}
            if a.get("with_downstream"):
                gold["downstream"] = {"direct": sorted(ctx.down(t, False)),
                                      "all": sorted(ctx.down(t, True))}  # fmt: skip
            flags = ["paraphrase_pending"] if a["wording"] == "paraphrase" else []
            q: dict[str, Any] = {
                "corpus": "synthetic_shop", "split": "dev", "type": "ask", "subtype": "meaning",
                "question": a["question"], "target": t, "mention": t, "hop_depth": ctx.depth(t),
                "hop_bucket": trace_bucket(ctx.depth(t)), "wording": a["wording"], "source": "hand",
                "traps": sorted(a["traps"]), "stratum": "ask|-", "gold": gold,
                "expect": {"verdict": "answered", "hand_scored": True},
                "source_lines": [f["source"] for f in a["facts"]], "review_flags": flags,
                "ask_key": a["key"],
            }  # fmt: skip
            if a["wording"] == "paraphrase":
                q["template_question"] = a["question"]
            self.add(q)

    def add_unanswerable(self) -> None:
        ctx = self.ctx
        ids = ctx.v.model_columns | ctx.v.seed_columns
        for key, kind, mention, tmpl, wording in UNANSWERABLE:
            assert mention not in ids, f"unanswerable {key}: {mention} exists"
            bare = mention.split(".")[-1].replace(" ", "_")
            model = mention.split(".")[0] if "." in mention else None
            pool = (
                [f"{model}.{c}" for c in ctx.v.models.get(model, [])]
                if model in ctx.v.models
                else sorted(ids)
            )
            closest = difflib.get_close_matches(
                bare, [c.split(".")[1] for c in pool], n=3, cutoff=0.5
            )
            text = TEMPLATES["impact" if tmpl == "impact" else "upstream"].format(t=mention)
            flags = ["paraphrase_pending"] if wording == "paraphrase" else []
            q: dict[str, Any] = {
                "corpus": "synthetic_shop", "split": "dev", "type": "unanswerable",
                "subtype": kind, "question": text, "target": mention, "mention": mention,
                "hop_depth": None, "hop_bucket": None, "wording": wording, "source": "hand",
                "traps": ["near_duplicate_names"] if key == "shipping_cost" else [],
                "stratum": "unanswerable|-",
                "gold": {"verdict": "refused", "edges": [], "closest": closest},
                "expect": {"verdict": "refused"}, "source_lines": [], "review_flags": flags,
            }  # fmt: skip
            if wording == "paraphrase":
                q["template_question"] = text
            self.add(q)


# ----------------------------------------------------------------------------- existing 20
V02_RETAG = {  # v0.2 subtype -> (type, subtype, wording); owner Q1 and amendment 1
    "upstream": ("trace", "upstream", None),
    "abbreviation": ("trace", "upstream", "name_words"),
    "paraphrase": ("trace", "upstream", "paraphrase"),
    "ambiguous_chain": ("trace", "ambiguous", "name_words"),
    "false_premise": ("trace", "false_premise", None),
    "trap": ("trace", "upstream", None),
    "computed": ("trace", "computed", None),
    "downstream": ("impact", "downstream", None),
    "reachability": ("impact", "yesno", None),
    "nonexistent_column": ("unanswerable", "dotted_near_miss", None),
}
DOTTED = re.compile(r"\b[a-z_0-9]+\.[a-z_0-9]+\b")


def regold_v02(b: Builder, old: dict[str, Any]) -> dict[str, Any]:
    ctx = b.ctx
    qtype, subtype, relabel = V02_RETAG[old["subtype"]]
    t = old["target"]
    q = {k: old[k] for k in ("id", "corpus", "split", "question", "target")}
    flags: list[str] = []
    traps: list[str]
    if subtype in ("upstream", "ambiguous"):
        gold = gold_trace(ctx, t)
        traps = trace_tags(ctx, t)
        hop: int | None = ctx.depth(t)
        if subtype == "ambiguous":
            models = [x for x in ctx.by_bare[t.split(".")[1]] if x in ctx.v.model_columns]
            chain = all(x == t or x in ctx.up(t, False) for x in models)
            gold.update(verdict="chain" if chain else "clarify", candidates=models)
    elif subtype == "computed":
        gold, traps, hop = gold_computed(ctx, t), trace_tags(ctx, t), ctx.depth(t)
    elif subtype == "false_premise":
        p = old["expect"]["forbid_edges"][0]["from"]
        gold = gold_premise(ctx, p, t)
        traps, hop = trace_tags(ctx, t, [p]), ctx.depth(t)
    elif subtype == "downstream":
        gold = gold_impact(ctx, t)
        traps, hop = impact_tags(ctx, t, gold), gs.downstream_depth(ctx.v, t)
    elif subtype == "yesno":
        s, to = DOTTED.findall(old["question"])[:2]
        gold = gold_reach(ctx, s, to)
        hop = gs.downstream_depth(ctx.v, s)
        traps = tags(ctx, [s, to], [], deep=hop >= 6, exposures=False)
    else:
        gold = {"verdict": "refused", "edges": [], "closest": difflib.get_close_matches(
            t.split(".")[1], ctx.v.models.get(t.split(".")[0], []), n=3, cutoff=0.5)}  # fmt: skip
        traps, hop = [], None
    wording = relabel or old["wording"]
    q.update(type=qtype, subtype=subtype, mention=t if wording == "identifier" else None,
             hop_depth=hop, wording=wording, source="v0.2", traps=traps)  # fmt: skip
    if qtype == "trace":
        q["hop_bucket"] = trace_bucket(hop)
    elif qtype == "impact":
        q["hop_bucket"] = impact_bucket(hop or 0, True)
    else:
        q["hop_bucket"] = None
    q["stratum"] = "v0.2"
    q["gold"] = gold
    q["expect"] = old["expect"]
    q["source_lines"] = sorted({f"{SPEC_REL}:{e['line']}" for e in gold.get("edges", [])},
                               key=lambda s: int(s.split(":")[1]))[:40]  # fmt: skip
    # flags: every difference from the v0.2 record
    if (old["type"], old["subtype"]) != (qtype, subtype):
        flags.append(f"retagged: {old['type']}/{old['subtype']} -> {qtype}/{subtype}")
    if old["wording"] != wording:
        flags.append(f"wording: {old['wording']} -> {wording}")
    if old["hop_depth"] != hop:
        flags.append(f"hop_depth: {old['hop_depth']} -> {hop}")
    if sorted(old["traps"]) != traps:
        flags.append(f"traps: {sorted(old['traps'])} -> {traps}")
    old_pairs = {(e["from"], e["to"]) for e in old["gold"].get("edges", [])}
    new_pairs = {(e["from"], e["to"]) for e in gold.get("edges", [])}
    if old_pairs != new_pairs:
        flags.append(
            f"gold_changed: edges {len(old_pairs)} -> {len(new_pairs)} "
            f"(+{len(new_pairs - old_pairs)} / -{len(old_pairs - new_pairs)})"
        )
    if old["gold"].get("verdict") != gold.get("verdict"):
        flags.append(f"gold_changed: verdict {old['gold'].get('verdict')} -> {gold['verdict']}")
    if subtype == "yesno":
        flags.append(f"verdict: direct {gold['reach']['direct']}, all {gold['reach']['all']}")
    flags.append("gold_lines: v1 line numbers replaced by v2 lineage_spec.yml lines")
    if old["target"] in D5_TRACE_EXCEPTIONS and qtype == "trace":
        flags.append("d5_conflict: dev-11 and dev-17 are both Trace questions on this column")
    if wording != "identifier":
        q["mention"] = {"dev-14": "prod category on order items",
                        "dev-15": "number of orders per customer",
                        "dev-16": "previous order date"}.get(old["id"], t)  # fmt: skip
    q["review_flags"] = flags
    return q


# ------------------------------------------------------------------------------------- plan
# Final count table (questions-design.md §1, rebalanced around the re-bucketed v0.2 questions).
# Each entry: (row, bucket, subtype, wording, n, extra). Existing v0.2 questions are placed first
# and are NOT listed here.
PLAN: list[tuple[str, str | None, str, str, int, dict[str, Any]]] = [
    # Trace 1 (8): v0.2 dev-01, dev-02. Only 2 dev columns at 1 hop have a computed input.
    ("trace", "1", "computed", "identifier", 1, {}),
    ("trace", "1", "multi_part", "identifier", 1, {}),
    ("trace", "1", "upstream", "identifier", 1, {}),
    ("trace", "1", "upstream", "name_words", 1, {}),
    ("trace", "1", "upstream", "description", 1, {}),
    ("trace", "1", "upstream", "paraphrase", 1, {}),
    # Trace 2-3 (11): v0.2 dev-03, 04, 14, 20, 12 (computed)
    ("trace", "2-3", "computed", "description", 1, {}),
    ("trace", "2-3", "computed", "paraphrase", 2, {}),
    ("trace", "2-3", "ambiguous", "name_words", 1, {}),
    ("trace", "2-3", "multi_part", "identifier", 1, {}),
    ("trace", "2-3", "upstream", "description", 1, {}),
    # Trace 4-5 (11): v0.2 dev-05, 16 (ambiguous), 13 (computed). 2 dev columns have a computed input.
    ("trace", "4-5", "computed", "paraphrase", 1, {}),
    ("trace", "4-5", "multi_part", "identifier", 1, {}),
    ("trace", "4-5", "upstream", "identifier", 2, {}),
    ("trace", "4-5", "upstream", "name_words", 2, {}),  # no usable description at 4-5
    ("trace", "4-5", "upstream", "paraphrase", 2, {}),
    # Trace 6+ (11): v0.2 dev-06, 15 (paraphrase), 11 (computed); >= 3 new at 8-10 hops
    ("trace", "6+", "computed", "identifier", 2, {"min_depth": 8}),  # before upstream: 3 dev
    ("trace", "6+", "upstream", "identifier", 1, {"min_depth": 8}),  # columns at 8+ are computed
    ("trace", "6+", "computed", "paraphrase", 1, {}),
    ("trace", "6+", "ambiguous", "name_words", 1, {}),
    ("trace", "6+", "upstream", "name_words", 1, {}),
    ("trace", "6+", "upstream", "description", 1, {}),
    ("trace", "6+", "upstream", "paraphrase", 1, {}),
    # False premise (4): v0.2 dev-17 (6+), dev-18 (3)
    ("false_premise", "1-3", "false_premise", "identifier", 1, {}),
    ("false_premise", "4+", "false_premise", "paraphrase", 1, {}),
    # Impact (24): v0.2 dev-07 (2-3), dev-08 (6+), dev-09 (6+)
    ("impact", "1", "downstream", "identifier", 3, {}),
    ("impact", "1", "downstream", "name_words", 1, {}),
    ("impact", "1", "downstream", "description", 1, {}),
    ("impact", "1", "downstream", "paraphrase", 1, {}),
    ("impact", "2-3", "downstream", "identifier", 2, {}),
    ("impact", "2-3", "downstream", "name_words", 1, {}),
    ("impact", "2-3", "downstream", "description", 1, {}),
    ("impact", "2-3", "downstream", "paraphrase", 1, {}),
    ("impact", "4-5", "downstream", "identifier", 1, {"variant": "exposures"}),
    ("impact", "4-5", "downstream", "identifier", 1, {}),
    ("impact", "4-5", "downstream", "description", 2, {}),
    ("impact", "4-5", "downstream", "paraphrase", 1, {}),
    ("impact", "6+", "downstream", "identifier", 1, {}),
    ("impact", "6+", "downstream", "name_words", 1, {}),
    ("impact", "6+", "downstream", "paraphrase", 1, {}),
    ("impact", "indirect-only", "downstream", "identifier", 1, {}),
    ("impact", "indirect-only", "downstream", "paraphrase", 1, {}),
    # Yes/no (6): v0.2 dev-10 (no)
    ("yesno", None, "yesno", "identifier", 1, {"variant": "yes_direct"}),
    ("yesno", None, "yesno", "paraphrase", 1, {"variant": "yes_direct"}),
    ("yesno", None, "yesno", "identifier", 1, {"variant": "yes_indirect_only"}),
    ("yesno", None, "yesno", "name_words", 1, {"variant": "no"}),
    ("yesno", None, "yesno", "paraphrase", 1, {"variant": "no"}),
]
SPARES = [("trace", "4-5", "upstream"), ("trace", "6+", "upstream"), ("trace", "2-3", "upstream"),
          ("trace", "1", "upstream"), ("impact", "1", "downstream"), ("impact", "2-3", "downstream")]  # fmt: skip


def build() -> list[dict[str, Any]]:
    ctx = load_ctx()
    b = Builder(ctx)
    for line in V02.read_text().splitlines():
        b.add(regold_v02(b, json.loads(line)))
    # Description slots first inside each (row, bucket): they are the most constrained.
    plan = sorted(PLAN, key=lambda e: (PLAN.index(next(x for x in PLAN if x[:2] == e[:2])),
                                       e[3] != "description"))  # fmt: skip
    for row, bucket, subtype, wording, n, extra in plan:
        for _ in range(n):
            slot = Slot(row, subtype, wording, bucket, **extra)
            if row == "trace":
                ok = b.fill_trace(slot)
                if not ok and wording == "description":  # no usable description: fall back
                    slot.wording = "name_words"
                    ok = b.fill_trace(slot)
                    if ok:
                        b.questions[-1]["review_flags"].append("wording_fallback: description")
            elif row == "false_premise":
                ok = b.fill_false_premise(slot)
            elif row == "impact":
                ok = b.fill_impact(slot)
                if not ok and wording == "description":
                    slot.wording = "name_words"
                    ok = b.fill_impact(slot)
                    if ok:
                        b.questions[-1]["review_flags"].append("wording_fallback: description")
            else:
                ok = b.fill_yesno(slot)
            if not ok:
                raise SystemExit(f"no dev-pool candidate for {row} {bucket} {subtype} {wording}")
    b.add_asks()
    b.add_unanswerable()
    for row, bucket, subtype in SPARES:
        slot = Slot(row, subtype, "identifier", bucket)
        ok = b.fill_trace(slot, spare=True) if row == "trace" else b.fill_impact(slot, spare=True)
        if ok:
            spare = b.questions[-1]
            (b.used_trace if row == "trace" else b.used_impact)[spare["target"]] += 1
    check(b)
    return b.questions


def check(b: Builder) -> None:
    ctx = b.ctx
    main = [q for q in b.questions if not q.get("spare")]
    assert len(main) == 96, len(main)
    for q in b.questions:
        if q["type"] != "unanswerable":
            assert q["target"] in ctx.dev, f"{q['id']}: {q['target']} is not in the dev pool"
        for m in DOTTED.findall(q["question"]):
            assert m not in ctx.test, f"{q['id']} names test-pool column {m}"
    trace = Counter(q["target"] for q in main if q["type"] == "trace")
    impact = Counter(q["target"] for q in main if q["type"] == "impact")
    over = [c for c, n in trace.items() if n > 1 and c not in D5_TRACE_EXCEPTIONS]
    assert not over, f"D5: more than one trace question on {over}"
    assert all(n == 1 for n in impact.values()), "D5: more than one impact question"


ORDER = ["id", "spare", "corpus", "split", "type", "subtype", "question", "template_question",
         "target", "mention", "hop_depth", "hop_bucket", "wording", "source", "traps", "stratum",
         "ask_key", "gold", "expect", "source_lines", "review_flags"]  # fmt: skip


def render(questions: list[dict[str, Any]]) -> str:
    rows = []
    for q in questions:
        assert set(q) <= set(ORDER), set(q) - set(ORDER)
        rows.append(json.dumps({k: q[k] for k in ORDER if k in q}, ensure_ascii=False))
    return "\n".join(rows) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if the candidates are stale")
    args = ap.parse_args()
    text = render(build())
    if args.check:
        stale = not OUT.is_file() or OUT.read_text() != text
        print("dev_candidates.jsonl is stale" if stale else "dev_candidates.jsonl is fresh")
        return int(stale)
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
