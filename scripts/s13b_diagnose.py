"""S13b step 0: read-only diagnosis of the post-pilot fixes F1-F6 (docs/plans/post-pilot-fixes.md).

Reads the committed S4 dev records (qwen and Gemini). For each question it rebuilds the ledger
in-process from the recorded tool results (``llm_payload``, ``side_records``) and re-runs the
validator of the checked-out code (e072c38) on the recorded draft(s). It makes no LLM call,
writes nothing under ``eval/runs`` and changes no source file. Candidate fixes are tried only in
this process (module attributes set and restored), never on disk.

Order (owner amendment A1): ledger rebuild fidelity first, then F1-F6, then A4 (Gemini key
safety), the agent-sha pins and A3 (existing tests that pin behaviour a fix would change).

"Gold-consistent" (the prep audit's caveat): every dotted mention of the claim is in the
question's gold node set for its primary mode. The relation the claim states is NOT checked.

    uv run --extra agent --extra retrieval python scripts/s13b_diagnose.py \\
        --out eval/reports/s13b/diagnosis.md

As a pytest plugin (A3), it applies one candidate change to the validator for a test run:
    S13B_PATCH='{"MIN_PREFIX_HEX": 5}' PYTHONPATH=scripts uv run pytest -p s13b_diagnose ...
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import traceback
from collections import Counter, deque
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "corpora" / "synthetic_shop"
COMPILED = CORPUS / "target" / "compiled" / "synthetic_shop"
RUNS = {
    "qwen": ROOT / "eval/runs/s4/s4-qwen3-4b-instruct-2507-q4-k-m-dev",
    "gemini": ROOT / "eval/runs/s4/s4-gemini-3-5-flash-lite-dev",
}
PILOT_SHA = "a6fb5b2e49fe9a104c3828c402d186196601c50c4ea25dadef0dbc982952b424"
HOP_RULE_MAX = 6  # F1 before-looking rule: the new bound may not exceed 6
F4_PREFIX = 5  # F4 before-looking rule: MIN_PREFIX_HEX = 5, no other value
SEARCH_UNBOUNDED = 50
SENTINEL = "S13B-SENTINEL-NOT-A-KEY-0123456789"
NO_EVIDENCE = "no lineage evidence"


# -- A3 pytest plugin: apply one candidate change for a test run --------------------------------


def pytest_configure(config: Any) -> None:  # pragma: no cover - only used as a plugin
    from dlens.agent import validator as v

    for name, value in json.loads(os.environ.get("S13B_PATCH", "{}")).items():
        setattr(v, name, value)


# -- inputs ----------------------------------------------------------------------------------------


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


@dataclass
class RebuiltLedger:
    """The ``Ledger`` protocol, rebuilt from a record's steps: every non-deduped tool result in
    order (code steps included), and the ids its payload showed that its side records hold,
    exactly as ``Toolbox.call`` registers them."""

    graph: Any
    project_dir: Path
    log: list[Any] = field(default_factory=list)
    _emitted: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_record(cls, graph: Any, record: Mapping[str, Any]) -> RebuiltLedger:
        from dlens.agent.tools.toolbox import ToolResult, _ids_in

        led = cls(graph, CORPUS)
        for step in record.get("steps") or []:
            for r in step.get("results") or []:
                if r.get("deduped"):
                    continue  # the loop does not re-run a deduped call: not in the log
                tr = ToolResult(
                    tool=r["tool"],
                    args=r.get("args") or {},
                    llm_payload=r.get("llm_payload") or {},
                    side_records=r.get("side_records") or {},
                    code_initiated=bool(r.get("code_initiated")),
                    rule=r.get("rule"),
                )
                if not tr.is_error:
                    shown = set(_ids_in(tr.llm_payload))
                    for kind in ("edges", "excerpts", "facts", "chunks"):
                        for item_id, rec in tr.side_records.get(kind, {}).items():
                            if item_id in shown:
                                led._emitted[item_id] = rec
                led.log.append(tr)
        return led

    @property
    def emitted_ids(self) -> frozenset[str]:
        return frozenset(self._emitted)

    def record(self, item_id: str) -> dict[str, Any] | None:
        return self._emitted.get(item_id)


@contextlib.contextmanager
def patched(obj: Any, **attrs: Any) -> Iterator[None]:
    old = {k: getattr(obj, k) for k in attrs}
    for k, val in attrs.items():
        setattr(obj, k, val)
    try:
        yield
    finally:
        for k, val in old.items():
            setattr(obj, k, val)


# -- per-question replay ---------------------------------------------------------------------------


@dataclass
class Round:
    name: str  # "first" | "second"
    answer: Any  # the attached Answer that was validated
    result: Any  # ValidationResult (re-run now)
    recorded: Mapping[str, Any]  # the record's validation summary


@dataclass
class Replay:
    model: str
    qid: str
    q: Mapping[str, Any]
    record: Mapping[str, Any]
    ledger: RebuiltLedger
    rounds: list[Round]
    mismatches: list[str]
    evidence_missing: list[str]

    @property
    def reliable(self) -> bool:
        return not self.mismatches


def _cmp_key(summary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "passed": summary.get("passed"),
        "failures": sorted(
            (str(f.get("claim_index")), f["rule"], str(f.get("item_id")))
            for f in summary.get("failures") or []
        ),
        "repairs": summary.get("repairs") or [],
        "completions": summary.get("completions") or [],
        "dropped_claims": summary.get("dropped_claims") or [],
    }


def replay(model: str, record: Mapping[str, Any], q: Mapping[str, Any], graph: Any) -> Replay:
    from dlens.agent.answer import AnswerDraft, attach
    from dlens.agent.loop import _parse_draft, _summary
    from dlens.agent.validator import validate

    led = RebuiltLedger.from_record(graph, record)
    ev = record.get("evidence") or {}
    missing = sorted(set(ev.get("ids") or []) - led.emitted_ids)
    partial = bool(ev.get("partial_evidence"))
    v = record.get("validation") or {}
    rounds: list[Round] = []
    mism: list[str] = []
    if v and record.get("draft") is not None:
        drafts: list[tuple[str, Any]] = [("first", AnswerDraft.model_validate(record["draft"]))]
        if v.get("second") is not None:
            try:
                drafts.append(("second", _parse_draft(record.get("regenerate_draft_raw") or "")))
            except Exception as e:  # noqa: BLE001 - reported as a mismatch
                mism.append(f"second draft does not parse now: {type(e).__name__}")
        for name, draft in drafts:
            ans = attach(draft, led, partial_evidence=partial)
            res = validate(ans, led, record["question"])
            rec_sum = v.get(name) or {}
            now, then = _cmp_key(_summary(res)), _cmp_key(rec_sum)
            for k in now:
                if now[k] != then[k]:
                    mism.append(f"{name}.{k}: recorded {then[k]} vs now {now[k]}")
            rounds.append(Round(name, ans, res, rec_sum))
    return Replay(model, q["id"], q, record, led, rounds, mism, missing)


# -- gold class (the prep audit's definition) --------------------------------------------------------


def gold_class(text: str, q: Mapping[str, Any], inv: Any, pa: Any) -> str:
    return str(pa.gold_class(pa.dotted(text, inv), pa.gold_nodes(q)))


def consistent(cls: str) -> bool:
    return cls == "consistent"


# -- F1 --------------------------------------------------------------------------------------------


def _bfs(adj: Mapping[str, list[tuple[str, str]]], src: set[str], dst: set[str]) -> int | None:
    seen = set(src)
    dq: deque[tuple[str, int]] = deque((s, 0) for s in sorted(src))
    while dq:
        x, d = dq.popleft()
        for y, _ in adj.get(x, []):
            if y in seen:
                continue
            if y in dst:
                return d + 1
            seen.add(y)
            dq.append((y, d + 1))
    return None


def graph_adjacency(ctx: Any) -> dict[str, list[tuple[str, str]]]:
    """Directed adjacency over every DERIVES (direct) edge of the whole graph, short names."""
    adj: dict[str, list[tuple[str, str]]] = {}
    for a, b in ctx.ledger.graph.nx_graph.edges():
        adj.setdefault(ctx.short(a), []).append((ctx.short(b), ""))
    return adj


def ledger_adjacency_all(ctx: Any) -> dict[str, list[tuple[str, str]]]:
    """Directed adjacency over every ledger edge, direct AND indirect (R8c never bridges the
    indirect ones; shown only to say why a claim has no direct path)."""
    from dlens.agent import validator as v

    adj: dict[str, list[tuple[str, str]]] = {}
    for i in sorted(ctx.ledger.emitted_ids):
        if i.startswith("e_") and (ends := v._edge_ends(i, ctx)) is not None:
            adj.setdefault(ends[0], []).append((ends[1], i))
    return adj


def f1_claim(rp: Replay, rnd: Round, k: int, inv: Any, pa: Any) -> dict[str, Any]:
    from dlens.agent import validator as v

    ctx = v.ValidationContext.build(rp.ledger, rp.record["question"])
    c = rnd.result.cleaned_answer.claims[k]
    cols = v._claim_columns(c, ctx)
    named = set(cols)
    anchor = any(set(ends) & named for i in c.edge_ids if (ends := v._edge_ends(i, ctx)))
    direct = bool(v._DIRECT.search(c.text))
    adj = v._ledger_adjacency(ctx)
    lengths: list[int] = []
    added: list[str] = []
    status, graph_hops = "connected", None
    links = v._link_ids(c)
    while True:  # _complete_one's loop, with an unbounded hop limit, to measure each bridge
        parent = v._components([*links, *added], ctx)
        root0 = v._root(parent, cols[0])
        if all(v._root(parent, col) == root0 for col in cols):
            break
        loose = next(v._root(parent, col) for col in cols if v._root(parent, col) != root0)
        here = {col for col in cols if v._root(parent, col) == root0}
        there = {col for col in cols if v._root(parent, col) == loose}
        paths = [
            p
            for p in (
                v._bridge(adj, there, here, SEARCH_UNBOUNDED),
                v._bridge(adj, here, there, SEARCH_UNBOUNDED),
            )
            if p is not None
        ]
        if not paths:
            gadj = graph_adjacency(ctx)
            hops = [h for h in (_bfs(gadj, there, here), _bfs(gadj, here, there)) if h]
            if hops:
                status, graph_hops = "path missing from the ledger", min(hops)
            else:
                iadj = ledger_adjacency_all(ctx)
                ih = [h for h in (_bfs(iadj, there, here), _bfs(iadj, here, there)) if h]
                status = (
                    f"no direct path; a path with indirect (JOIN/FILTER) edges in the ledger: {min(ih)} hops"
                    if ih
                    else "no directed path in the graph (direct) or the ledger (with indirect)"
                )
            break
        path = min(paths, key=len)
        lengths.append(len(path))
        added += [i for i in path if i not in added and i not in c.edge_ids]
    need = max(lengths) if lengths else None
    blockers = []
    if not anchor:
        blockers.append("no anchor")
    if status != "connected":
        blockers.append(status + (f" (graph: {graph_hops} hops)" if graph_hops is not None else ""))
    if need is not None and need > v.MAX_COMPLETION_HOPS:
        blockers.append(f"bridge {need} > {v.MAX_COMPLETION_HOPS}")
    if direct and need is not None and need > 1:
        blockers.append('"directly"')
    other = sorted({f.rule for f in rnd.result.failures if f.claim_index == k} - {"R8"})
    return {
        "model": rp.model,
        "id": rp.qid,
        "round": rnd.name,
        "k": k,
        "text": c.text,
        "ids": list(c.ids),
        "class": gold_class(c.text, rp.q, inv, pa),
        "anchor": anchor,
        "direct": direct,
        "status": status,
        "bridges": lengths,
        "need": need,
        "blockers": blockers or ["(none found)"],
        "other_rules": other,
        "reliable": rp.reliable,
    }


def _relaxed_complete_one(c: Any, cols: list[str], adj: Any, ctx: Any) -> list[str]:
    """F1 option (b): ``validator._complete_one`` with one change, the anchor test is "a cited
    edge OR a ledger edge touches a named column". The bound (4) and the "directly" guard stay."""
    from dlens.agent import validator as v

    named = set(cols)
    cited = any(set(ends) & named for i in c.edge_ids if (ends := v._edge_ends(i, ctx)))
    ledger = any(
        set(ends) & named
        for i in ctx.ledger.emitted_ids
        if i.startswith("e_") and (ends := v._edge_ends(i, ctx))
    )
    if not (cited or ledger):
        return []
    direct = bool(v._DIRECT.search(c.text))
    links = v._link_ids(c)
    added: list[str] = []
    while True:
        parent = v._components([*links, *added], ctx)
        root0 = v._root(parent, cols[0])
        if all(v._root(parent, col) == root0 for col in cols):
            return added
        loose = next(v._root(parent, col) for col in cols if v._root(parent, col) != root0)
        here = {col for col in cols if v._root(parent, col) == root0}
        there = {col for col in cols if v._root(parent, col) == loose}
        paths = [
            p
            for p in (
                v._bridge(adj, there, here, v.MAX_COMPLETION_HOPS),
                v._bridge(adj, here, there, v.MAX_COMPLETION_HOPS),
            )
            if p is not None
        ]
        if not paths:
            return []
        path = min(paths, key=len)
        if direct and len(path) > 1:
            return []
        added += [i for i in path if i not in added and i not in c.edge_ids]


def option_passes(rp: Replay, rnd: Round, k: int, option: str, bound: int) -> bool:
    """Would claim ``k`` of this round pass every rule under the option (re-run in-process)?"""
    from dlens.agent import validator as v

    change = {"a": {"MAX_COMPLETION_HOPS": bound}, "b": {"_complete_one": _relaxed_complete_one}}
    with patched(v, **change[option]):
        res = v.validate(rnd.answer, rp.ledger, rp.record["question"])
    return k not in res.dropped_claims


def option_c(row: Mapping[str, Any]) -> bool:
    """F1 option (c): R8 passes when the ledger's direct edges join the named columns by
    directed paths of any length (no anchor needed, no edges added; the "directly" guard kept),
    and the claim fails no rule other than R8."""
    if row["status"] != "connected" or row["other_rules"]:
        return False
    return not (row["direct"] and (row["need"] or 0) > 1)


# -- F2 --------------------------------------------------------------------------------------------


def sql_aliases(sql: str) -> dict[str, set[str]]:
    """alias -> what it names in one compiled model: a table (ref) name, ``<cte>`` or
    ``<derived>``. Read-only sqlglot parse of compiled SQL."""
    import sqlglot
    from sqlglot import exp

    out: dict[str, set[str]] = {}
    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
    except Exception:  # noqa: BLE001 - an unparseable file names no alias
        return out
    for t in tree.find_all(exp.Table):
        if t.alias:
            out.setdefault(t.alias.lower(), set()).add(t.name.lower())
    for cte in tree.find_all(exp.CTE):
        out.setdefault(cte.alias.lower(), set()).add("<cte>")
    for sq in tree.find_all(exp.Subquery):
        if sq.alias:
            out.setdefault(sq.alias.lower(), set()).add("<derived>")
    return out


def ledger_models(rp: Replay) -> set[str]:
    from dlens.agent import validator as v

    ctx = v.ValidationContext.build(rp.ledger, rp.record["question"])
    names = set(ctx.evidence_models)
    for i in rp.ledger.emitted_ids:
        if (ends := v._edge_ends(i, ctx)) is not None:
            names |= {e.rsplit(".", 1)[0] for e in ends}
    return {n for n in names if n in ctx.model_uids}


def compiled_sql(graph: Any, model: str, uids: Mapping[str, list[str]]) -> str:
    for uid in uids.get(model, []):
        f = (graph.model_info(uid) or {}).get("file")
        if f and (COMPILED / f).is_file():
            return (COMPILED / f).read_text()
    return ""


def f2_rows(rp: Replay, inv: Any, pa: Any) -> list[dict[str, Any]]:
    from dlens.agent import validator as v

    ctx = v.ValidationContext.build(rp.ledger, rp.record["question"])
    models = sorted(ledger_models(rp))
    per_file = {m: sql_aliases(compiled_sql(rp.ledger.graph, m, ctx.model_uids)) for m in models}
    aliases = {a for al in per_file.values() for a in al} - set(ctx.model_uids)
    real_r4 = v.rule_known_nodes

    def r4_skip_aliases(answer: Any, cx: Any) -> list[Any]:
        """F2 option (a), simulated: an alias token of a ledger model's compiled SQL that is not
        a model name is "not a node name" (neither hallucinated nor supported)."""
        return [
            f
            for f in real_r4(answer, cx)
            if not (f.rule == "R4.hallucinated" and str(f.item_id).rsplit(".", 1)[0] in aliases)
        ]

    rows = []
    for rnd in rp.rounds:
        if not any(f.rule == "R4.hallucinated" for f in rnd.result.failures):
            continue
        with patched(v, rule_known_nodes=r4_skip_aliases):
            sim = v.validate(rnd.answer, rp.ledger, rp.record["question"])
        for f in rnd.result.failures:
            if f.rule != "R4.hallucinated":
                continue
            token = str(f.item_id)
            qual, col = token.rsplit(".", 1) if "." in token else (token, "")
            maps: dict[str, set[str]] = {}
            for m, al in per_file.items():
                if qual in al:
                    maps[m] = al[qual]
            targets = set().union(*maps.values()) if maps else set()
            kinds = sorted(
                "ref" if t in ctx.model_uids else ("cte" if t == "<cte>" else "derived/other")
                for t in targets
            )
            col_ok = sorted(
                t for t in targets if t in ctx.model_uids and f"{t}.{col}" in ctx.short_cols
            )
            text = (
                rnd.answer.answer_text
                if f.claim_index is None
                else rnd.answer.claims[f.claim_index].text
            )
            rows.append(
                {
                    "model": rp.model,
                    "id": rp.qid,
                    "round": rnd.name,
                    "k": f.claim_index,
                    "token": token,
                    "alias_in": sorted(maps),
                    "targets": sorted(targets),
                    "kinds": kinds,
                    "is_model_name": qual in ctx.model_uids,
                    "multi": len(targets) > 1,
                    "col_in_target": col_ok,
                    "class": gold_class(text, rp.q, inv, pa) if f.claim_index is not None else "–",
                    "after_a": sorted(
                        {x.rule for x in sim.failures if x.claim_index == f.claim_index}
                    ),
                    "round_passes_a": sim.passed,
                    "reliable": rp.reliable,
                }
            )
    return rows


# -- F3 --------------------------------------------------------------------------------------------


def f3_row(rp: Replay) -> dict[str, Any] | None:
    from dlens.agent.validator import salvage

    if len(rp.rounds) < 2:
        return None
    first, second = rp.rounds
    if first.answer.refused or not second.answer.refused:
        return None
    kept = (
        salvage(first.result, rp.ledger) if not first.result.passed else first.result.cleaned_answer
    )
    final = rp.record.get("final_answer") or {}
    return {
        "model": rp.model,
        "id": rp.qid,
        "first_claims": len(first.answer.claims),
        "first_dropped": list(first.result.dropped_claims),
        "first_rules": dict(first.result.counts),
        "draft_verdict": first.answer.reach_verdict,
        "fact": (first.result.fact or {}).get("fact"),
        "today": "refused" if final.get("refused") else "answered",
        "salvage": None
        if kept is None
        else {
            "claims": [(c.origin, c.text) for c in kept.claims],
            "verdict": kept.reach_verdict,
            "source": kept.reach_verdict_source,
        },
    }


# -- F4 --------------------------------------------------------------------------------------------


def f4_rows(rp: Replay, inv: Any, pa: Any) -> list[dict[str, Any]]:
    from dlens.agent import validator as v

    gold = pa.gold_nodes(rp.q)
    ctx = v.ValidationContext.build(rp.ledger, rp.record["question"])
    rows = []
    for rnd in rp.rounds:
        for f in rnd.result.failures:
            if f.rule != "R2":
                continue
            bad = str(f.item_id)
            with patched(v, MIN_PREFIX_HEX=F4_PREFIX):
                cands = v.repair_candidates(bad, rp.ledger.emitted_ids)
                after = v.validate(rnd.answer, rp.ledger, rp.record["question"])
            ends = [list(e) for c in cands if (e := v._edge_ends(c, ctx)) is not None]
            in_gold = None if gold is None or not ends else all(x in gold for e in ends for x in e)
            after_rules = sorted({x.rule for x in after.failures if x.claim_index == f.claim_index})
            rows.append(
                {
                    "model": rp.model,
                    "id": rp.qid,
                    "round": rnd.name,
                    "k": f.claim_index,
                    "bad": bad,
                    "hex": len(bad) - 2,
                    "cands": cands,
                    "outcome": "repair"
                    if len(cands) == 1
                    else ("ambiguous" if len(cands) > 1 else "no match"),
                    "ends": ends,
                    "ends_in_gold": in_gold,
                    "after": after_rules,
                    "reliable": rp.reliable,
                }
            )
    return rows


# -- F6 --------------------------------------------------------------------------------------------


def searched(record: Mapping[str, Any]) -> bool:
    return any(
        r.get("tool") == "search_docs"
        for s in record.get("steps") or []
        for r in s.get("results") or []
    )


def llm_tool_calls(record: Mapping[str, Any]) -> int:
    return sum(
        len(s.get("tool_calls") or [])
        for s in record.get("steps") or []
        if s.get("phase") == "tool"
    )


def refusal_point(record: Mapping[str, Any]) -> str:
    err = record.get("error") or ""
    final = record.get("final_answer") or {}
    stop = record.get("stop_reason") or ""
    if stop.startswith("unknown_column"):
        return "before (unknown column, code refusal, no LLM call)"
    if err.startswith(NO_EVIDENCE):
        return "AT the new step's point (would trigger it)"
    if final.get("clarification"):
        return "after (clarification)"
    if final.get("refused"):
        return "after (answer phase ran: " + (err[:60] or "model refused") + ")"
    return "after (answered)"


def search_hits(questions: Sequence[str]) -> dict[str, list[tuple[str, float]]]:
    """search_docs on the question text with the S4 index (code only, no LLM)."""
    sys.path.insert(0, str(ROOT / "eval"))
    from dlens.agent.tools import Toolbox
    from systems.s4 import open_graph

    graph, index, _ = open_graph(CORPUS, hybrid=True)
    box = Toolbox(graph, CORPUS, index)
    out = {}
    for qtext in questions:
        box.reset()
        r = box.call("search_docs", {"query": qtext}, code=True, rule="s13b_diagnose")
        out[qtext] = [(h["id"], h.get("title", "")) for h in r.llm_payload.get("hits", [])]
    return out


# -- F5 / A4 ---------------------------------------------------------------------------------------


def a4_key_safety() -> dict[str, Any]:
    """A stub: the SDK's own ``raise_for_response`` on an httpx 400 whose request carries the
    key in the ``x-goog-api-key`` header and the URL; then the adapter's ``except`` path."""
    import httpx
    from google.genai import errors

    from dlens.agent.llm.gemini import GeminiProvider
    from dlens.agent.llm.types import Message, ProviderError

    req = httpx.Request(
        "POST",
        f"https://generativelanguage.googleapis.com/v1beta/models/m:generateContent?key={SENTINEL}",
        headers={"x-goog-api-key": SENTINEL},
    )
    resp = httpx.Response(
        400,
        json={
            "error": {"code": 400, "message": "API key not valid.", "status": "INVALID_ARGUMENT"}
        },
        request=req,
    )
    try:
        errors.APIError.raise_for_response(resp)
    except errors.APIError as e:
        sdk_err = e

    class Models:
        def generate_content(self, **_: Any) -> Any:
            raise sdk_err

    class Client:
        models = Models()

    prov = GeminiProvider("gemini-3.5-flash-lite", client=Client())
    try:
        prov.send([Message(role="user", content="q")], None)
    except ProviderError as pe:
        perr = pe
    text = {
        "str(ProviderError)": str(perr),
        "repr(ProviderError)": repr(perr),
        "str(__cause__)": str(perr.__cause__),
        "repr(__cause__)": repr(perr.__cause__),
        "formatted traceback (chained)": "".join(traceback.format_exception(perr)),
    }
    cause = perr.__cause__
    reach = getattr(getattr(getattr(cause, "response", None), "request", None), "headers", {})
    return {
        "sdk_class": type(sdk_err).__name__,
        "chained": cause is not None,
        "leaks_in_text": {k: SENTINEL in v for k, v in text.items()},
        "object_reachable": SENTINEL in str(dict(reach))
        or SENTINEL
        in str(
            getattr(getattr(cause, "response", None), "request", "") and cause.response.request.url  # type: ignore[union-attr]
        ),
    }


def adapter_catches() -> list[tuple[str, str]]:
    out = []
    for name in ("gemini", "openai_compat", "ollama"):
        src = (ROOT / f"src/dlens/agent/llm/{name}.py").read_text()
        for m in re.finditer(
            r"except\s+([^:]+):(?:\s*#\s*(.*))?\n(?:.*\n){0,6}?.*?\) from (\w+)", src
        ):
            out.append(
                (name, f"`except {m.group(1).strip()}` → ProviderError, `from {m.group(3)}`")
            )
    return out


# -- sha pins and A3 -------------------------------------------------------------------------------


def sha_pins() -> list[str]:
    hits = subprocess.run(
        [
            "git",
            "grep",
            "-n",
            "-e",
            "agent_code_sha256",
            "-e",
            "a6fb5b2e",
            "--",
            "tests",
            "scripts",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return [h for h in hits if not h.startswith("scripts/s13b_diagnose.py")]


def a3_run(patch: Mapping[str, Any]) -> list[str]:
    """Failing tests (node ids) with one candidate validator change applied in-process."""
    env = {
        **os.environ,
        "S13B_PATCH": json.dumps(patch),
        "PYTHONPATH": str(ROOT / "scripts"),
    }
    out = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "s13b_diagnose",
            "-p",
            "no:cacheprovider",
            "tests/unit/agent",
            "--no-header",
            "-rf",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    ).stdout
    return sorted({ln.split(" ", 2)[1] for ln in out.splitlines() if ln.startswith("FAILED ")})


# -- report ----------------------------------------------------------------------------------------


def esc(x: Any) -> str:
    return str(x).replace("|", "\\|").replace("\n", " ")


def table(head: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--no-search", action="store_true", help="skip the F6 search_docs probe")
    ap.add_argument("--no-a3", action="store_true", help="skip the A3 pytest runs")
    ns = ap.parse_args(argv)

    sys.path.insert(0, str(ROOT / "eval"))
    sys.path.insert(0, str(ROOT / "scripts"))
    import s13_prep_audit as pa

    import metrics as M  # noqa: N812
    from dlens.agent import validator as v
    from dlens.graph import load_or_build

    graph = load_or_build(CORPUS)
    inv, _ = M.load_inventory(CORPUS)
    qs = {q["id"]: q for q in load_jsonl(ROOT / "eval/questions/dev.jsonl")}
    by_text = {q["question"]: q for q in qs.values()}
    replays: dict[str, list[Replay]] = {}
    manifests: dict[str, dict[str, Any]] = {}
    for model, stem in RUNS.items():
        manifests[model] = json.loads(Path(f"{stem}.manifest.json").read_text())
        recs = load_jsonl(Path(f"{stem}.jsonl"))
        replays[model] = [
            replay(model, r, qs.get(r.get("question_id")) or by_text[r["question"]], graph)
            for r in recs
        ]
    diff_src = subprocess.run(
        ["git", "diff", "--stat", "e072c38", "--", "src"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()

    L: list[str] = [
        "# S13b step 0: diagnosis of post-pilot fixes F1–F6",
        "",
        f"> **Read-only diagnosis; no src change; agent sha unchanged ({PILOT_SHA[:8]}…{PILOT_SHA[-4:]}).**"
        " Dev records only; no LLM call; nothing written under `eval/runs`. Generated by"
        " `scripts/s13b_diagnose.py`.",
        "",
        f"`git diff --stat e072c38 -- src`: {'(empty)' if not diff_src else diff_src}",
        "",
        "Records: "
        + ", ".join(
            f"`{p.name}.jsonl` (sha `{manifests[m]['agent_code_sha256'][:8]}…`)"
            for m, p in RUNS.items()
        )
        + ".",
        "",
        '**Caveat (prep audit):** "gold-consistent" means every dotted mention of the claim is in'
        " the question's gold node set for its primary mode. It does **not** mean the stated"
        " relation was checked.",
        "",
        "## A1. Ledger rebuild fidelity (run first)",
        "",
        "For every record the ledger is rebuilt from the recorded tool results, and the e072c38"
        " validator is re-run on the recorded first draft and (if any) the regenerated draft."
        " Compared with the record: passed, failures (claim, rule, item), repairs, completions and"
        " dropped claims.",
        "",
    ]
    stop_a1 = False
    rows_a1 = []
    for model, rps in replays.items():
        validated = [rp for rp in rps if rp.rounds]
        bad = [rp for rp in validated if not rp.reliable]
        miss_ev = [rp for rp in rps if rp.evidence_missing]
        stop_a1 |= len(bad) > 5
        rows_a1.append(
            (model, len(rps), len(validated), len(validated) - len(bad), len(bad), len(miss_ev))
        )
    L += table(
        ["model", "records", "with validation", "match", "mismatch", "evidence ids not rebuilt"],
        rows_a1,
    )
    L.append("")
    for model, rps in replays.items():
        for rp in rps:
            if rp.mismatches or rp.evidence_missing:
                L.append(
                    f"- **{model} {rp.qid}: rebuild unreliable.** "
                    + "; ".join(
                        rp.mismatches + [f"evidence ids missing: {rp.evidence_missing}"]
                        if rp.evidence_missing
                        else rp.mismatches
                    )
                )
    if stop_a1:
        L += ["", "**More than 5 mismatches on a model: STOP 1 reports this first.**"]
    L.append("")
    reliable = {m: [rp for rp in rps if rp.reliable] for m, rps in replays.items()}
    unreliable_ids = {(m, rp.qid) for m, rps in replays.items() for rp in rps if not rp.reliable}

    # ---- F1
    f1 = [
        f1_claim(rp, rnd, f.claim_index, inv, pa)
        for rps in replays.values()
        for rp in rps
        for rnd in rp.rounds
        for f in rnd.result.failures
        if f.rule == "R8" and f.claim_index is not None
    ]
    applies = [
        r
        for r in f1
        if r["reliable"]
        and consistent(r["class"])
        and r["anchor"]
        and r["status"] == "connected"
        and r["need"] is not None
        and r["need"] > v.MAX_COMPLETION_HOPS
        and not (r["direct"] and r["need"] > 1)
    ]
    longest = max((r["need"] for r in applies), default=None)
    bound = min(longest, HOP_RULE_MAX) if longest else None
    insufficient = longest is not None and longest > HOP_RULE_MAX
    for r in f1:
        rp = next(x for x in replays[r["model"]] if x.qid == r["id"])
        rnd = next(x for x in rp.rounds if x.name == r["round"])
        r["a"] = option_passes(rp, rnd, r["k"], "a", bound) if bound else False
        r["b"] = option_passes(rp, rnd, r["k"], "b", v.MAX_COMPLETION_HOPS)
        r["c"] = option_c(r)
    L += [
        "## F1. R8: claims citing one edge of a multi-hop link",
        "",
        f"Every R8-failed claim on both models, both validation rounds: {len(f1)} claims."
        " Bridges are measured as R8c builds them (shortest directed path over this question's"
        " DIRECT ledger edges, component by component) but with no hop limit; `need` is the"
        " longest bridge the claim needs.",
        "",
    ]
    L += table(
        [
            "model",
            "id",
            "round",
            "#",
            "class",
            "anchor",
            "bridges",
            "blocker(s)",
            "other rules",
            "ids",
            "claim",
        ],
        [
            (
                r["model"],
                r["id"],
                r["round"],
                r["k"],
                r["class"],
                "yes" if r["anchor"] else "no",
                r["bridges"] or "–",
                "; ".join(r["blockers"]),
                ", ".join(r["other_rules"]) or "–",
                ", ".join(r["ids"]),
                r["text"],
            )
            for r in f1
        ],
    )
    L += [
        "",
        f"**Hop bound from the before-looking rule.** Gold-consistent claims (reliable rebuilds)"
        f" for which only the bound blocks completion: {len(applies)}; longest needed bridge:"
        f" {longest if longest is not None else 'none'}. Bound used for (a):"
        f" {bound if bound is not None else 'n/a (option (a) applies to no claim)'}"
        + (
            ". **Some needed bridge is longer than 6: option (a) alone is insufficient (no larger"
            " bound).**"
            if insufficient
            else "."
        ),
        "",
        "Options, re-run in-process on the same ledger (a claim passes when it is no longer"
        ' dropped). (a) `MAX_COMPLETION_HOPS` = the bound; (b) anchor relaxed to "a cited edge or'
        " a ledger edge touches a named column\", bound 4; (c) R8 passes when the ledger's direct"
        " edges join the named columns by directed paths of any length, no edges added, the"
        ' "directly" guard kept, and the claim fails no other rule. Unreliable rebuilds are'
        " counted separately.",
        "",
    ]
    rel = [r for r in f1 if r["reliable"]]
    trows = []
    for label, pred in (
        ("gold-consistent", lambda r: consistent(r["class"])),
        ("not consistent", lambda r: not consistent(r["class"])),
    ):
        grp = [r for r in rel if pred(r)]
        trows.append(
            (
                label,
                len(grp),
                sum(r["a"] for r in grp),
                sum(r["b"] for r in grp),
                sum(r["c"] for r in grp),
            )
        )
    trows.append(("rebuild unreliable (excluded)", len(f1) - len(rel), "–", "–", "–"))
    L += table(["claims", "n", f"(a) bound {bound}", "(b)", "(c)"], trows)
    L += ["", "Per model:", ""]
    L += table(
        ["model", "class", "n", "(a)", "(b)", "(c)"],
        [
            (m, c, len(g), sum(r["a"] for r in g), sum(r["b"] for r in g), sum(r["c"] for r in g))
            for m in RUNS
            for c in ("consistent", "other")
            if (
                g := [
                    r
                    for r in rel
                    if r["model"] == m and (consistent(r["class"]) == (c == "consistent"))
                ]
            )
        ],
    )
    L.append("")

    # ---- F2
    f2 = [row for rps in replays.values() for rp in rps for row in f2_rows(rp, inv, pa)]
    L += [
        "## F2. R4.hallucinated tokens",
        "",
        "Aliases come from a read-only sqlglot parse of the **compiled** SQL of every model in the"
        " question's ledger (table aliases → the table, i.e. the ref'd model; CTE names; derived"
        " tables). `alias in` = the ledger models whose file defines the qualifier as an alias.",
        "",
    ]
    L += table(
        [
            "model",
            "id",
            "round",
            "#",
            "token",
            "alias in",
            "names",
            "kind",
            "also a model name",
            "> 1 target",
            "column exists in target",
            "class",
            "under (a): rules left",
            "round passes under (a)",
        ],
        [
            (
                r["model"],
                r["id"],
                r["round"],
                "text" if r["k"] is None else r["k"],
                r["token"],
                ", ".join(r["alias_in"]) or "– (not an alias)",
                ", ".join(r["targets"]) or "–",
                ", ".join(sorted(set(r["kinds"]))) or "–",
                "yes" if r["is_model_name"] else "no",
                "yes" if r["multi"] else "no",
                ", ".join(r["col_in_target"]) or "–",
                r["class"],
                ", ".join(r["after_a"]) or "none",
                "yes" if r["round_passes_a"] else "no",
            )
            for r in f2
        ],
    )
    n_alias = sum(bool(r["alias_in"]) for r in f2)
    L += [
        "",
        f"{len(f2)} failures; {n_alias} on an alias token, {len(f2) - n_alias} not an alias.",
        "",
    ]

    # ---- F3
    f3 = [row for rps in replays.values() for rp in rps if (row := f3_row(rp))]
    L += ["## F3. A refused regenerate after a non-refused first draft", ""]
    if not f3:
        L.append("None.")
    for r in f3:
        sal = r["salvage"]
        L += [
            f"- **{r['model']} {r['id']}**: first draft {r['first_claims']} claims, dropped"
            f" {r['first_dropped']} ({r['first_rules']}), draft verdict `{r['draft_verdict']}`;"
            f" fact: {r['fact'] or 'none'}; today: {r['today']}.",
            "  - Under (a): "
            + (
                "salvage keeps nothing (still a refusal)."
                if sal is None
                else f"salvage keeps {len(sal['claims'])} claim(s): "
                + "; ".join(f"({o}) {t}" for o, t in sal["claims"])
                + f". reach_verdict `{sal['verdict']}` (source `{sal['source']}`)."
            ),
        ]
    L.append("")

    # ---- F4
    f4 = [row for rps in replays.values() for rp in rps for row in f4_rows(rp, inv, pa)]
    L += [
        "## F4. R2 failures and a 5-hex prefix",
        "",
        f"Candidates with `MIN_PREFIX_HEX = {F4_PREFIX}` (the before-looking value) in this"
        " question's ledger, uniqueness check kept. `after` = the claim's failing rules when the"
        " validator re-runs with that value.",
        "",
    ]
    L += table(
        [
            "model",
            "id",
            "round",
            "#",
            "bad id",
            "hex",
            "outcome at 5",
            "candidate(s)",
            "candidate ends",
            "ends in gold set",
            "after",
        ],
        [
            (
                r["model"],
                r["id"],
                r["round"],
                "text" if r["k"] is None else r["k"],
                r["bad"],
                r["hex"],
                r["outcome"],
                ", ".join(r["cands"]) or "–",
                "; ".join(" → ".join(e) for e in r["ends"]) or "–",
                {None: "n/a", True: "yes", False: "**no**"}[r["ends_in_gold"]],
                ", ".join(r["after"]) or "passes",
            )
            for r in f4
        ],
    )
    L += [
        "",
        "Outcomes: "
        + ", ".join(f"{k} {n}" for k, n in Counter(r["outcome"] for r in f4).items())
        + ".",
        "",
    ]

    # ---- F5 / A4
    a4 = a4_key_safety()
    L += ["## F5. Transport errors (from code)", ""]
    L += [f"- `{name}.py`: {what}" for name, what in adapter_catches()]
    L += [
        "",
        "`httpx.RemoteProtocolError` is an `httpx.TransportError`; the Gemini adapter's"
        " `except errors.APIError` does not catch it, so it escapes `ProviderError` handling.",
        "",
        "### A4. Key safety of `from exc` on APIError (report only, no change)",
        "",
        f"Stub: the SDK's own `APIError.raise_for_response` on an httpx 400 whose request has the"
        f" key in `x-goog-api-key` and in the URL query (a sentinel string, not a key), raised"
        f" through the adapter. SDK class: `{a4['sdk_class']}`; chained: {a4['chained']}.",
        "",
    ]
    L += table(
        ["text", "contains the key"],
        [(k, "**yes**" if b else "no") for k, b in a4["leaks_in_text"].items()],
    )
    L += [
        "",
        f"Object reachability: `ProviderError.__cause__.response.request` holds the header/URL:"
        f" **{'yes' if a4['object_reachable'] else 'no'}**.",
        "",
    ]

    # ---- F6
    no_ev = [
        rp
        for rps in replays.values()
        for rp in rps
        if (rp.record.get("error") or "").startswith(NO_EVIDENCE)
    ]
    unans = [rp for rps in replays.values() for rp in rps if rp.q["type"] == "unanswerable"]
    probe_q = sorted(
        {
            rp.record["question"]
            for rp in [*no_ev, *unans]
            if refusal_point(rp.record).startswith("AT")
        }
    )
    hits = {} if ns.no_search else search_hits(probe_q)
    L += [
        '## F6. "No lineage evidence" refusals',
        "",
        "Index: "
        + ", ".join(
            f"{m} hybrid={manifests[m]['hybrid']} ({manifests[m].get('index_status')})"
            for m in RUNS
        )
        + " (both runs had an index).",
        "",
    ]
    L += table(
        [
            "model",
            "id",
            "family",
            "subtype",
            "index",
            "search_docs called",
            "LLM tool calls",
            "stop_reason",
        ],
        [
            (
                rp.model,
                rp.qid,
                rp.q["type"],
                rp.q["subtype"],
                manifests[rp.model]["hybrid"],
                "yes" if searched(rp.record) else "no",
                llm_tool_calls(rp.record),
                rp.record.get("stop_reason"),
            )
            for rp in no_ev
        ],
    )
    fam = Counter((rp.model, rp.q["type"]) for rp in no_ev)
    L += [
        "",
        "By family: " + ", ".join(f"{m} {t} {n}" for (m, t), n in sorted(fam.items())) + ".",
        "",
    ]
    L += ["### Dev unanswerable questions: where they refuse today", ""]
    L += table(
        ["model", "id", "subtype", "today", "point vs the new step", "search_docs hits if it ran"],
        [
            (
                rp.model,
                rp.qid,
                rp.q["subtype"],
                "refused"
                if (rp.record.get("final_answer") or {}).get("refused")
                else (
                    "clarification"
                    if (rp.record.get("final_answer") or {}).get("clarification")
                    else "answered"
                ),
                refusal_point(rp.record),
                (
                    ", ".join(i for i, _ in hits.get(rp.record["question"], [])[:3])
                    + f" ({len(hits.get(rp.record['question'], []))} hits)"
                )
                if rp.record["question"] in hits
                else "–",
            )
            for rp in unans
        ],
    )
    trig = [rp for rp in unans if refusal_point(rp.record).startswith("AT")]
    L += [
        "",
        f"Unanswerable questions that reach the new step's point today: {len(trig)}"
        + (
            f" ({', '.join(f'{rp.model} {rp.qid}' for rp in trig)}). search_docs always returns"
            " up to k hits (no score threshold), so for these the answer phase would run on docs."
            " **F6 threshold rule: STOP applies if F6 (a) is approved.**"
            if trig
            else ". No unanswerable dev question would reach it."
        ),
        "",
    ]

    # ---- sha pins
    L += ["## Agent-sha pins and `check_s4_repro.py`", ""]
    L += [f"- `{h}`" for h in sha_pins()]
    repro = (ROOT / "scripts/check_s4_repro.py").read_text()
    L += [
        "",
        "`check_s4_repro.py` reads "
        + (
            "a manifest"
            if "manifest" in repro.split('"""', 2)[2]
            else "**only the two record files**"
        )
        + " and "
        + (
            "checks the agent sha."
            if "agent_code_sha256" in repro
            else "**never reads the agent sha**: two record files from different shas are compared field"
            " by field and fail on the first record difference, not on the sha."
        ),
        "",
    ]

    # ---- A3
    L += ["## A3. Existing tests that pin behaviour a fix would change", ""]
    if ns.no_a3:
        L.append("(skipped: --no-a3)")
    else:
        base = a3_run({})
        L.append(f"Baseline (`tests/unit/agent`, no change): failing {base or 'none'}.")
        for label, patch in (
            (f"F4 MIN_PREFIX_HEX={F4_PREFIX}", {"MIN_PREFIX_HEX": F4_PREFIX}),
            *(
                ((f"F1(a) MAX_COMPLETION_HOPS={bound}", {"MAX_COMPLETION_HOPS": bound}),)
                if bound
                else ()
            ),
        ):
            fails = sorted(set(a3_run(patch)) - set(base))
            L.append(
                f"- **{label}:** "
                + (
                    ", ".join(f"`{x}`" for x in fails)
                    if fails
                    else "no existing test changes outcome."
                )
            )
        L += [
            "- F2, F3, F5, F6 are code changes, not constants; their pinned tests are found by"
            " reading (listed in the summary).",
        ]
    L.append("")
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.write_text("\n".join(L) + "\n")
    print(
        f"wrote {ns.out.name}; A1 mismatches:",
        {m: sum(not rp.reliable for rp in rps if rp.rounds) for m, rps in replays.items()},
        "unreliable:",
        sorted(unreliable_ids),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
