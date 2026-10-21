"""Benchmark metrics (S10, v0.3 D3): implements docs/plans/metrics-design.md v1.2 exactly.

Every definition here is the owner's decision in that document; section names (M1-M16) point at
it. Imports are limited on purpose: the gold spec helpers (``dlens.gold_spec``), the standard
library and PyYAML (a parser for lineage_spec.yml / traps.yml; ``dlens.gold_spec`` reads no
files). Nothing from ``dlens.lineage``, ``dlens.agent``, ``dlens.retrieval`` or ``dlens.graph``:
metrics never grades a system with the system's own engine.

Pipeline: run records → one adapter per record format (S0 and S4: ``from_record``; S1:
``from_s1_record``) → ``Prediction`` → per-question scorers → aggregation and statistics →
JSON / Markdown stamped with both versions.

    uv run python eval/metrics.py --records eval/runs/s0/s0-gold-dev.jsonl --system s0 \\
        --out eval/reports/s0_gold_dev
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from dlens import gold_spec as gs

__version__ = "1.3.0"
DESIGN_VERSION = "1.2"  # docs/plans/metrics-design.md
SEED = 20261019  # M13
RESAMPLES = 1000  # M13
MIN_CI_N = 10  # M13: a CI is shown only for n >= 10
ROOT = Path(__file__).resolve().parents[1]

# ------------------------------------------------------------------------------ inventory (M8)
DBT_PREFIXES = ("stg_", "int_", "fct_", "dim_", "raw_", "mart_", "base_")
STOP = {"e.g", "i.e", "etc", "vs", "cf", "al"}
_CTE = re.compile(r"\b([A-Za-z_]\w*)\s+as\s*\(", re.I)
_DERIVED = re.compile(r"\)\s+as\s+([A-Za-z_]\w*)", re.I)


def relation_names(sql: str) -> set[str]:
    """CTE names (``<name> as (``) and derived-table aliases (``) as <name>`` that are also used
    as a qualifier ``<name>.`` in the same text): the M7 (iv-k+) guard and the M8 (a+) list. The
    qualifier test keeps column aliases such as ``cast(x as int) as amount`` out."""
    names = {m.lower() for m in _CTE.findall(sql)}
    for m in _DERIVED.findall(sql):
        if re.search(rf"(?<![\w.]){re.escape(m)}\.\w", sql, re.I):
            names.add(m.lower())
    return names


@dataclass
class Inventory:
    """The gold-spec inventory (M8): columns, model, seed and exposure names, and the CTE /
    derived-table names found by a plain regex over the corpus model SQL (never the engine)."""

    columns: set[str]
    models: set[str]
    seeds: set[str]
    exposures: set[str]
    ctes: set[str] = field(default_factory=set)


def load_inventory(corpus_dir: Path) -> tuple[Inventory, gs.View]:
    spec = yaml.safe_load((corpus_dir / "lineage_spec.yml").read_text())
    traps = yaml.safe_load((corpus_dir / "traps.yml").read_text())
    view = gs.build_view(spec)
    ctes: set[str] = set()
    for f in sorted((corpus_dir / "models").rglob("*.sql")):
        ctes |= relation_names(f.read_text())
    inv = Inventory(
        columns={c.lower() for c in view.model_columns | view.seed_columns},
        models={m.lower() for m in view.models},
        seeds={s.lower() for s in view.seeds},
        exposures={str(x["name"]).lower() for x in traps.get("exposures") or []},
        ctes=ctes - {m.lower() for m in view.models} - {s.lower() for s in view.seeds},
    )
    return inv, view


# ------------------------------------------------------------------------- mentions (M2, M3)
@dataclass(frozen=True)
class Mention:
    node: str  # model.column, model name or exposure name (lower case)
    kind: str  # column | model | exposure | unknown (hallucination candidate) | cte
    negated: bool


_PATH = re.compile(r"\S*/\S*|(?<![\w.])[\w.]+\.(?:sql|yml|yaml|csv|py|md|json|txt)(?!\w)", re.I)
_ABBREV = re.compile(r"(?<![\w.])(e\.g|i\.e|etc|vs|cf|al)\.", re.I)
_DOTTED = re.compile(r"(?<![\w.])([A-Za-z_]\w*(?:\.[A-Za-z_]\w*){1,3})(?!\w)")
_INTERP = re.compile(r"Interpreted\s+(\S+)\s+as\s+(\S+?)\.(?=\s|$)")
_SENT = re.compile(r"[.!?;]+(?=\s|$)")
_TOKEN = re.compile(r"\x00\d+\x00|[A-Za-z0-9']+|,|[^\sA-Za-z0-9',]")
BOUNDARY = {"but", "however", "whereas", "while", "including", "plus"}
RELATIVE = {"which", "that", "who"}
PRE_CUES = {"not", "no", "never", "without", "neither", "nor", "except", "excluding"}
PRE_PAIRS = {("rather", "than"), ("instead", "of"), ("other", "than")}
POST_ONE = {"isn't", "aren't", "wasn't", "doesn't", "didn't", "never"}
POST_TWO = {
    ("is", "not"),
    ("are", "not"),
    ("was", "not"),
    ("does", "not"),
    ("did", "not"),
    ("is", "never"),
    ("no", "longer"),
    ("has", "no"),
}
VALUE_WORDS = {"null", "nullable", "empty", "zero", "negative", "unique", "missing", "blank"}


def short_id(token: str) -> str:
    """M2: lower case, quotes stripped, fully-qualified ids cut to their last two parts."""
    parts = token.replace('"', "").replace("`", "").lower().split(".")
    return ".".join(parts[-2:])


def classify(token: str, inv: Inventory) -> str | None:
    """M3 rule 1 identifier filter: the mention kind of a dotted token, or None (plain text)."""
    key = short_id(token)
    model = key.split(".")[0]
    if key in STOP or model in STOP:
        return None
    if key in inv.columns:
        return "column"
    if model in inv.ctes:
        return "cte"
    if model in inv.models or model in inv.seeds or "_" in model or model.startswith(DBT_PREFIXES):
        return "unknown"
    return None


def question_ids(text: str, inv: Inventory) -> set[str]:
    """Dotted ids the question itself writes (exempt from the hallucination count, M8)."""
    return {short_id(t) for t in _DOTTED.findall(text) if classify(t, inv) is not None}


def interpretations(text: str) -> list[tuple[str, str]]:
    """``(A, B)`` of each code-written lead "Interpreted A as B." (M3 rule 3, M9)."""
    return [(short_id(a), short_id(b)) for a, b in _INTERP.findall(text)]


def _clauses(tokens: list[str]) -> list[int]:
    """Clause id of each token (M3 rule 4): boundary words open a new clause; a relative clause
    ", which / that / who … ," is its own clause and the main clause resumes after it."""
    ids: list[int] = []
    clause, nxt, stack = 0, 1, []
    for i, tok in enumerate(tokens):
        after = tokens[i + 1] if i + 1 < len(tokens) else ""
        if tok == "," and after in RELATIVE:
            stack.append(clause)
            clause, nxt = nxt, nxt + 1
        elif tok == "," and stack:
            ids.append(clause)
            clause = stack.pop()
            continue
        elif tok in BOUNDARY or (tok == "instead" and after != "of"):
            clause, nxt, stack = nxt, nxt + 1, []
        ids.append(clause)
    return ids


def _voided(tokens: list[str], ids: list[int], start: int) -> bool:
    """Value-word exemption: a value word after the cue, in its clause, before the next mention."""
    for q in range(start + 1, len(tokens)):
        if ids[q] != ids[start] or tokens[q].startswith("\x00"):
            return False
        if tokens[q] in VALUE_WORDS:
            return True
    return False


def _pre_negated(tokens: list[str], ids: list[int], i: int, void: bool = True) -> bool:
    """A pre-mention cue in the mention's clause (M3 rule 4). ``void=False`` (M9 v1.2 identity
    branch): the value-word exemption does not apply."""
    for p in range(i):
        if ids[p] != ids[i]:
            continue
        tok, after = tokens[p], tokens[p + 1]
        cue = (
            (tok in PRE_CUES and not (tok == "not" and after == "only"))
            or "n't" in tok
            or (tok, after) in PRE_PAIRS
        )
        if cue and not (void and _voided(tokens, ids, p)):
            return True
    return False


def _post_negated(tokens: list[str], ids: list[int], i: int) -> bool:
    j = i + 1
    if j < len(tokens) and tokens[j] in ("itself", "column"):
        j += 1
    if j >= len(tokens) or ids[j] != ids[i]:
        return False
    two = (tokens[j], tokens[j + 1]) if j + 1 < len(tokens) else None
    hit = tokens[j] in POST_ONE or (two in POST_TWO and ids[j + 1] == ids[i])
    return hit and not _voided(tokens, ids, j)


@dataclass
class Extraction:
    mentions: list[Mention]
    interpretations: list[tuple[str, str]]

    def nodes(self, kind: str, *, negated: bool | None = None) -> set[str]:
        """Distinct nodes of a kind; ``negated=False``: kept nodes (any non-negated mention),
        ``negated=True``: nodes whose every mention is negated."""
        seen = {m.node for m in self.mentions if m.kind == kind}
        kept = {m.node for m in self.mentions if m.kind == kind and not m.negated}
        if negated is None:
            return seen
        return seen - kept if negated else kept


def extract(text: str, inv: Inventory, identity: bool = False) -> Extraction:
    """M3: mentions of columns, models and exposures in prose, each with its negation flag.
    ``identity=True`` (M9 v1.2 mention branch): only pre-mention cues negate; the post-mention
    rule and the value-word exemption do not apply."""
    text = text.replace("’", "'").replace('"', "")
    interp = interpretations(text)
    text = _INTERP.sub(lambda m: m.group(2) + ".", text)
    text = _PATH.sub(" ", text)
    text = _ABBREV.sub(lambda m: m.group(1).replace(".", "") + " ", text)
    found: list[tuple[str, str]] = []

    def hold(node: str, kind: str) -> str:
        found.append((node, kind))
        return f" \x00{len(found) - 1}\x00 "

    def dotted(m: re.Match[str]) -> str:
        kind = classify(m.group(1), inv)
        return m.group(0) if kind is None else hold(short_id(m.group(1)), kind)

    text = _DOTTED.sub(dotted, text)
    names = sorted(inv.models | inv.exposures, key=len, reverse=True)
    spaced = {x.replace("_", " "): x for x in inv.exposures}
    alts = [re.escape(n) for n in names] + [re.escape(s) for s in spaced]
    if alts:
        bare = re.compile(r"(?<![\w.\x00])(" + "|".join(alts) + r")(?![\w\x00]|\.\w)", re.I)

        def bare_name(m: re.Match[str]) -> str:
            name = spaced.get(m.group(1).lower(), m.group(1).lower())
            return hold(name, "exposure" if name in inv.exposures else "model")

        text = bare.sub(bare_name, text)
    mentions: list[Mention] = []
    for sentence in _SENT.split(text):
        tokens = [t if t.startswith("\x00") else t.lower() for t in _TOKEN.findall(sentence)]
        if len(tokens) > 1 and tokens[0] in ("yes", "no") and tokens[1] == ",":
            tokens = tokens[2:]
        ids = _clauses(tokens)
        for i, tok in enumerate(tokens):
            if tok.startswith("\x00"):
                node, kind = found[int(tok.strip("\x00"))]
                if identity:
                    neg = _pre_negated(tokens, ids, i, void=False)
                else:
                    neg = _pre_negated(tokens, ids, i) or _post_negated(tokens, ids, i)
                mentions.append(Mention(node, kind, neg))
    return Extraction(mentions, interp)


# ------------------------------------------------------- field-or-prose rules (M9 / M10, v1.2)
OOS_STOP = frozenset(
    """a an the it its this that these those is are was were be been being do does did done to of
    for in on at by with from and or as i you we they them their who whom whose what which when
    where why how much many can could would should will there here come comes came compute
    computes computed computing derive derives derived depend depends use uses used feed feeds
    column columns model models table tables lineage source sources upstream downstream""".split()
)
OOS_SUFFIXES = ("", "s", "es", "d", "ed", "er", "ers", "ership", "ing")
COVERAGE_CUES = frozenset(
    "not no never without neither nor cannot unable outside beyond unknown unavailable".split()
)
_WORDS = re.compile(r"[\w']+")


def content_words(out_of_scope: str) -> list[str]:
    """M10 v1.2: the gold out-of-scope text's word tokens minus the stop list."""
    return [w for w in re.findall(r"[a-z']+", out_of_scope.lower()) if w not in OOS_STOP]


def word_matches(token: str, word: str) -> bool:
    """M10 v1.2 suffix rule: ``token`` is the word's base plus one of ``OOS_SUFFIXES``."""
    base = word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word
    return any(token == base + x for x in OOS_SUFFIXES)


def plain_words(text: str) -> list[str]:
    """Lower-case words of ``text`` with identifiers removed (M10 v1.2): paths, every dotted
    candidate (2-4 parts) and every token containing ``_``."""
    text = _PATH.sub(" ", text.replace("’", "'"))
    text = _DOTTED.sub(" ", text)
    return [w.lower() for w in _WORDS.findall(text) if "_" not in w]


def _sentences(text: str) -> list[list[str]]:
    """M3's sentence split; each sentence's plain words with a leading "Yes," / "No," removed."""
    text = _INTERP.sub(lambda m: m.group(0) + " ", text.replace("’", "'").replace('"', ""))
    out = []
    for s in _SENT.split(text):
        if re.match(r"\s*(yes|no)\s*,", s, re.I):
            s = s.split(",", 1)[1]
        out.append(plain_words(s))
    return out


def coverage_sentence(words: list[str], content: Sequence[str]) -> bool:
    """M10 v1.2 prose branch: one sentence (plain words) holds a content word and a cue."""
    has_word = any(word_matches(t, w) for t in words for w in content)
    cue = any(
        (t in COVERAGE_CUES or "n't" in t)
        and not (t == "not" and i + 1 < len(words) and words[i + 1] == "only")
        for i, t in enumerate(words)
    ) or any(words[i : i + 3] == ["out", "of", "scope"] for i in range(len(words)))
    return has_word and cue


def _route(field_ok: bool, prose_ok: bool) -> str:
    return {(True, True): "both", (True, False): "field", (False, True): "prose"}.get(
        (field_ok, prose_ok), "neither"
    )


def uncovered_part(pred: Prediction, out_of_scope: str) -> tuple[bool, str]:
    """M10 v1.2: answered, and a field string with a content word or a sentence with a content
    word and a coverage cue. Returns (correct, pass route)."""
    if pred.kind != "answered":
        return False, "neither"
    content = content_words(out_of_scope)
    field_ok = any(
        word_matches(t, w) for s in pred.uncovered_parts for t in plain_words(s) for w in content
    )
    texts = [pred.answer_text, *(c.get("text", "") for c in pred.claims)]
    prose_ok = any(coverage_sentence(s, content) for x in texts for s in _sentences(x))
    route = _route(field_ok, prose_ok)
    return route != "neither", route


def interpretation_ok(pred: Prediction, column: str, inv: Inventory) -> tuple[bool, str]:
    """M9 v1.2: answered, and the structured ``interpretation.to``, a lead "Interpreted A as B."
    with B = the gold column, or a mention of it that no pre-mention cue negates."""
    if pred.kind != "answered":
        return False, "neither"
    want = short_id(column)
    field_ok = pred.interpretation is not None and short_id(pred.interpretation[1]) == want
    lead = any(b == want for _, b in interpretations(pred.answer_text))
    kept = extract(pred.text, inv, identity=True).nodes("column", negated=False)
    route = _route(field_ok, lead or want in kept)
    return route != "neither", route


def premise_rejection(
    pred: Prediction, premise: str, ex: Extraction, upstream_case: bool
) -> tuple[str, str]:
    """M10 v1.2 false premise: (bucket, pass route). Field branch: ``premise_corrected`` and
    answered and, in case O, no kept mention of the premise column; prose branch: answered and
    every mention of it negated."""
    answered = pred.kind == "answered"
    kept = premise in ex.nodes("column", negated=False)
    field_ok = bool(pred.premise_corrected) and answered and (upstream_case or not kept)
    prose_ok = answered and premise in ex.nodes("column", negated=True)
    route = _route(field_ok, prose_ok)
    if route != "neither":
        return "rejected", route
    if upstream_case:
        return "not_rejected", route
    mentioned = premise in ex.nodes("column")
    return ("asserted" if answered and mentioned else "silent"), route


# ------------------------------------------------------------------------------ mode (M4)
PROVENANCE = re.compile(r"\b(come[s]? from|computed|calculated|derived|origin(ally)?|source)\b")
EFFECT = re.compile(
    r"\b(affect(s|ed)?|change[sd]?|impact|show up|depend(s)? on|downstream|in the lineage"
    r"|feed(s)? into)\b"
)
TRACE_FAMILY = {"upstream", "computed", "ambiguous", "multi_part", "false_premise"}
IMPACT_FAMILY = {"downstream", "yesno"}


def wording_cue(question: str) -> str | None:
    """ "P" (provenance), "E" (effect / dependency), "both" or None."""
    t = question.lower()
    p, e = bool(PROVENANCE.search(t)), bool(EFFECT.search(t))
    return "both" if p and e else "P" if p else "E" if e else None


def primary_mode(q: Mapping[str, Any]) -> str | None:
    """M4 (a) as approved in Appendix A: the question family fixes the mode; the wording cue is
    recorded and agrees with the family on every dev question except dev-50 (an effect cue on a
    false-premise question), which Appendix A resolves by family. None for Ask / unanswerable."""
    sub = q["subtype"]
    if sub in TRACE_FAMILY:
        return "direct"
    if sub in IMPACT_FAMILY:
        return "all"
    return None


# ------------------------------------------------------------------------ records (adapters)
INDIRECT_KINDS = set(gs.INDIRECT_TYPES)


@dataclass
class EdgeInfo:
    from_column: str
    to_column: str
    kind: str
    key: str | None = None
    citation: dict[str, Any] | None = None


@dataclass
class Prediction:
    """One answer of one system / view, in the shape every scorer reads (M3)."""

    kind: str  # answered | refused | clarification | missing | crashed
    answer_text: str = ""
    claims: list[dict[str, Any]] = field(default_factory=list)  # {text, ids}
    citations: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: dict[str, EdgeInfo] = field(default_factory=dict)
    clarification: list[str] = field(default_factory=list)
    reach_verdict: str | None = None
    premise_corrected: bool | None = None
    uncovered_parts: list[str] = field(default_factory=list)  # ADR 0027 (S4 only)
    interpretation: tuple[str, str] | None = None  # ADR 0028 (from, to), code-set
    ambiguity: dict[str, Any] | None = None  # S4 diagnostic only (M9)
    r3_failed: set[str] = field(default_factory=set)
    r3_checked: set[str] = field(default_factory=set)  # ids the validator's R3 ran on
    truncated: bool = False
    total_ms: float | None = None
    tokens: dict[str, int] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n".join([self.answer_text, *(c.get("text", "") for c in self.claims)])

    @property
    def cited_ids(self) -> list[str]:
        return list(dict.fromkeys(i for c in self.claims for i in c.get("ids", [])))


def _ledger(record: Mapping[str, Any]) -> tuple[dict[str, EdgeInfo], dict[str, Any], bool]:
    edges: dict[str, EdgeInfo] = {}
    cits: dict[str, Any] = {}
    truncated = False
    for step in record.get("steps") or []:
        for res in step.get("results") or []:
            truncated |= bool((res.get("llm_payload") or {}).get("truncated"))
            for eid, e in ((res.get("side_records") or {}).get("edges") or {}).items():
                edges[eid] = EdgeInfo(
                    short_id(e["from"]), short_id(e["to"]), str(e["kind"]), e.get("key")
                )
                if e.get("citation"):
                    cits[eid] = e["citation"]
                    edges[eid].citation = e["citation"]
    return edges, cits, truncated


def _claims(answer: Mapping[str, Any]) -> list[dict[str, Any]]:
    out = []
    for c in answer.get("claims") or []:
        ids = c.get("ids") or [*c.get("edge_ids", []), *c.get("chunk_ids", [])]
        out.append({"text": c.get("text", ""), "ids": list(ids), "origin": c.get("origin")})
    return out


def _r3_failed(record: Mapping[str, Any]) -> set[str]:
    v = record.get("validation") or {}
    out: set[str] = set()
    for rnd in (v.get("first"), v.get("second")):
        for f in (rnd or {}).get("failures") or []:
            if f.get("rule") == "R3" and f.get("item_id"):
                out.add(f["item_id"])
    return out


def _r3_checked(record: Mapping[str, Any], edges: Mapping[str, EdgeInfo]) -> set[str]:
    """Ids R3 actually ran on (v1.1): only when the record has a validation that was not skipped,
    and only ledger ids (emitted by a tool). A miscopied id fails R2 and never reaches R3."""
    v = record.get("validation") or {}
    if not v or v.get("skipped"):
        return set()
    final = record.get("final_answer") or {}
    return (
        set((record.get("evidence") or {}).get("ids") or [])
        | set(edges)
        | set(final.get("citations") or {})
    )


def from_record(record: Mapping[str, Any], view: str = "validated") -> Prediction:
    """Adapter for the ``RunRecord`` JSON format (S4; S0 writes the same format). Views (M3):
    ``raw`` = the pre-validation ``draft``; ``validated`` = ``final_answer``; ``augmented`` =
    validated plus claims with ``origin: augmented`` (S12b G1). ``uncovered_parts`` and
    ``premise_corrected`` come from the view's answer; ``interpretation`` from the final answer in
    every view (ADR 0028)."""
    edges, cits, truncated = _ledger(record)
    final = record.get("final_answer")
    base = Prediction(
        kind="crashed",
        edges=edges,
        ambiguity=record.get("ambiguity"),
        r3_failed=_r3_failed(record),
        r3_checked=_r3_checked(record, edges),
        truncated=truncated,
        total_ms=(record.get("timings") or {}).get("total_ms"),
        tokens=dict(record.get("tokens") or {}),
    )
    if final is None:
        return base
    answer: Mapping[str, Any] = final
    if view == "raw" and record.get("draft") is not None:
        answer = record["draft"]
    clar = final.get("clarification") or record.get("clarification")
    if clar:
        base.kind = "clarification"
        base.clarification = [short_id(c) for c in clar.get("candidates") or []]
        return base
    base.kind = "refused" if answer.get("refused") else "answered"
    base.answer_text = answer.get("answer_text", "")
    claims = _claims(answer)
    if view != "augmented":
        claims = [c for c in claims if c.get("origin") != "augmented"]
    base.claims = claims
    base.citations = {**cits, **(final.get("citations") or {})}
    base.reach_verdict = reach_verdict(record, view)
    base.premise_corrected = answer.get("premise_corrected")
    base.uncovered_parts = [str(x) for x in answer.get("uncovered_parts") or []]
    interp = final.get("interpretation")  # every view: code-set before the answer (ADR 0028)
    if interp:
        base.interpretation = (str(interp["from"]), str(interp["to"]))
    return base


def reach_verdict(record: Mapping[str, Any], view: str = "validated") -> str | None:
    """M5's one accessor. The ADR 0024 ``Answer`` fields (``reach_verdict`` +
    ``reach_verdict_source``), else S0's record-level ``structured.reach_verdict``. The raw view
    counts only the LLM's own value: the pre-validation ``draft`` (the model's by definition), or a
    final answer whose verdict source is ``llm``."""
    final = record.get("final_answer") or {}
    rv: str | None
    if view == "raw":
        draft = record.get("draft")
        if draft is not None:
            rv = draft.get("reach_verdict")
        else:
            rv = final.get("reach_verdict") if final.get("reach_verdict_source") == "llm" else None
        return rv
    rv = final.get("reach_verdict")
    if rv is None:
        rv = (record.get("structured") or {}).get("reach_verdict")
    return rv


def from_s1_record(record: Mapping[str, Any], view: str = "validated") -> Prediction:
    """Adapter for S1 (vector RAG, docs/plans/s1-design.md) records: RunRecord format, chunk
    citations (``c_``) attached by code from the S1 ledger in ``final_answer.citations``, no
    validator. S1 has one view (validated = its final answer) and never cites an edge."""
    if view != "validated":
        raise ValueError(f"S1 has no {view!r} view: it has no validator (only 'validated')")
    pred = from_record(record, view)
    edge_ids = [i for i in pred.cited_ids if i.startswith("e_")]
    if pred.edges or edge_ids:
        raise ValueError(f"S1 record cites edges, which S1 cannot see: {edge_ids[:3]}")
    return pred


def adapter_for(system: str) -> Callable[[Mapping[str, Any], str], Prediction]:
    """The record adapter for a system label (M3: one adapter per record format)."""
    return from_s1_record if system.lower().startswith("s1") else from_record


class JoinError(ValueError):
    pass


def join(
    records: Iterable[Mapping[str, Any]], questions: Sequence[Mapping[str, Any]]
) -> dict[str, Mapping[str, Any]]:
    """M12: records joined to questions on the exact question text. Unmatched or duplicate
    records fail the scoring run, naming the texts."""
    by_text = {q["question"]: q["id"] for q in questions}
    out: dict[str, Mapping[str, Any]] = {}
    unmatched, dupes = [], []
    for r in records:
        qid = by_text.get(r.get("question", ""))
        if qid is None:
            unmatched.append(r.get("question", ""))
        elif qid in out:
            dupes.append(r.get("question", ""))
        else:
            out[qid] = r
    if unmatched or dupes:
        raise JoinError(f"unmatched records: {unmatched}; duplicate records: {dupes}")
    return out


# ------------------------------------------------------------------------ set metrics (M12)
def prf(pred: set[str], gold: set[str]) -> tuple[float, float, float]:
    """P, R, F1 of an answered prediction: empty gold and empty prediction = 1; one side empty
    = 0 (M12)."""
    if not pred and not gold:
        return 1.0, 1.0, 1.0
    if not pred or not gold:
        return 0.0, 0.0, 0.0
    tp = len(pred & gold)
    p, r = tp / len(pred), tp / len(gold)
    return p, r, (2 * p * r / (p + r) if tp else 0.0)


def tolerant_prf(pred: set[str], gold: set[str], closure: set[str]) -> tuple[float, float, float]:
    """M1 (t): recall over the gold inputs; a prediction is wrong only outside the closure."""
    if not pred and not gold:
        return 1.0, 1.0, 1.0
    if not pred or not gold:
        return 0.0, 0.0, 0.0
    p = len(pred & (closure | gold)) / len(pred)
    r = len(pred & gold) / len(gold)
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def norm(items: Iterable[str]) -> set[str]:
    return {short_id(x) if "." in x else x.lower() for x in items}


def gold_set(gold: Mapping[str, Any], name: str, mode: str) -> set[str]:
    if name == "inputs":
        inputs = gold["inputs"]
        out = norm(inputs["direct"])
        if mode == "all":
            out |= norm(x["from"] for x in inputs["indirect"])
        return out
    return norm(gold[name][mode])


# -------------------------------------------------------------------------- citations (M7)
def required_column(edge: EdgeInfo) -> str:
    """M7 (iv): a direct edge needs its ``to`` column; an indirect edge its ``from`` column."""
    col = edge.from_column if edge.kind in INDIRECT_KINDS else edge.to_column
    return col.split(".")[-1]


def _contains(lines: str, word: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(word)}(?!\w)", lines, re.I))


@dataclass
class CitationCheck:
    valid: bool
    reason: str
    macro: bool = False


def check_citation(
    cid: str,
    cit: Mapping[str, Any] | None,
    edge: EdgeInfo | None,
    claim_columns: set[str],
    project: Path,
) -> CitationCheck:
    """M7: independent on-disk re-check of one citation (never imports the validator)."""
    if cit is None:
        return CitationCheck(False, "no citation attached")
    root = project.resolve()
    path = (root / str(cit.get("file", ""))).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return CitationCheck(False, "file missing or outside the project")
    text = path.read_text(errors="replace")
    all_lines = text.splitlines()
    a, b = int(cit.get("line_start", 0)), int(cit.get("line_end", 0))
    if not 1 <= a <= b <= len(all_lines):
        return CitationCheck(False, "line range out of bounds")
    lines = "\n".join(all_lines[a - 1 : b])
    level = cit.get("level", "line")
    need = required_column(edge) if edge else None
    if level == "model":
        jinja = "{{" in text or "{%" in text
        named = need is not None and _contains(text, need)
        return CitationCheck(False, "model-level citation", macro=jinja and not named)
    if level == "star":
        return CitationCheck("*" in lines, "ok (star)" if "*" in lines else "star without *")
    if edge is not None:
        assert need is not None
        if _contains(lines, need):
            return CitationCheck(True, "ok")
        if edge.kind in INDIRECT_KINDS and edge.key and "." in edge.key:
            rel = edge.key.split(".")[-2].lower()
            if rel in relation_names(text) and _contains(lines, edge.key.split(".")[-1]):
                return CitationCheck(True, "ok (clause key, iv-k+)")
        return CitationCheck(False, f"cited lines lack {need}")
    if any(_contains(lines, c.split(".")[-1]) for c in claim_columns):
        return CitationCheck(True, "ok (excerpt)")
    return CitationCheck(False, "excerpt names no column of its claim")


def score_citations(pred: Prediction, inv: Inventory, project: Path) -> dict[str, Any]:
    """Per-citation, per-answer, coverage, r_ facts, macro bucket and R3 disagreements (M7)."""
    checked = valid = facts = macro = disagree = 0
    reasons: Counter[str] = Counter()
    seen: dict[str, CitationCheck] = {}
    cited_claims = 0
    for claim in pred.claims:
        ids = [i for i in claim.get("ids", []) if i]
        if ids:
            cited_claims += 1
        cols = extract(claim.get("text", ""), inv).nodes("column")
        for cid in ids:
            if cid.startswith("r_"):
                facts += 1
                continue
            if cid in seen:
                continue
            res = check_citation(cid, pred.citations.get(cid), pred.edges.get(cid), cols, project)
            seen[cid] = res
            checked += 1
            valid += res.valid
            macro += res.macro
            reasons[res.reason] += 1
            if cid in pred.r3_checked:  # v1.1: only ids the R3 check ran on
                disagree += res.valid == (cid in pred.r3_failed)
    answered = pred.kind == "answered"
    # M7 v1.1: the system's own "no" verdict with no file citation is n/a (nothing to cite);
    # never the gold verdict. With citations, they are checked as usual.
    no_nothing_to_cite = pred.reach_verdict == "no" and checked == 0
    answer_valid = (
        (checked > 0 and valid == checked) if answered and not no_nothing_to_cite else None
    )
    return {
        "checked": checked,
        "valid": valid,
        "r_facts": facts,
        "macro": macro,
        "r3_disagree": disagree,
        "claims": len(pred.claims),
        "claims_cited": cited_claims,
        "answer_valid": answer_valid,
        "invalid": {k: v for k, v in reasons.items() if not k.startswith("ok")},
    }


# --------------------------------------------------------------------- per-question (M1-M12)
def linker_test_flagged(questions: Sequence[Mapping[str, Any]], cases: Path) -> set[str]:
    """M13 (b): target or yes/no endpoints are linker-test gold columns (21 dev questions)."""
    gold: set[str] = set()
    for line in cases.read_text().splitlines():
        if line.strip():
            c = json.loads(line)
            if c.get("split") == "linker-test":
                gold |= {str(g).lower() for g in c.get("gold") or []}
    out = set()
    for q in questions:
        cols = {str(q.get("target") or "").lower()}
        reach = q["gold"].get("reach")
        if reach:
            cols |= {reach["from"].lower(), reach["to"].lower()}
        if cols & gold:
            out.add(q["id"])
    return out


def composite(q: Mapping[str, Any]) -> str | None:
    """M16: which composite F1 a question enters ("trace", "impact" or None)."""
    sub, verdict = q["subtype"], q["gold"]["verdict"]
    if sub in ("upstream", "computed", "multi_part", "false_premise"):
        return "trace"
    if sub == "ambiguous" and verdict == "chain":
        return "trace"
    if sub == "downstream":
        return "impact"
    return None


def score_question(
    q: Mapping[str, Any],
    pred: Prediction,
    inv: Inventory,
    view: gs.View,
    project: Path,
) -> dict[str, Any]:
    """One row: every applicable metric (None = not applicable), in the primary mode, plus the
    per-mode values and the diagnostics."""
    gold, sub, qtype = q["gold"], q["subtype"], q["type"]
    target = short_id(q["target"]) if q.get("target") else None
    mode = primary_mode(q)
    ex = extract(pred.text, inv) if pred.kind in ("answered", "refused") else Extraction([], [])
    kept_cols = ex.nodes("column", negated=False)
    pred_cols = kept_cols - ({target} if target else set())
    pred_models = ({c.split(".")[0] for c in pred_cols} & inv.models) | ex.nodes(
        "model", negated=False
    )
    pred_exp = ex.nodes("exposure", negated=False)
    answered = pred.kind == "answered"
    row: dict[str, Any] = {
        "id": q["id"],
        "type": qtype,
        "subtype": sub,
        "mode": mode,
        "cue": wording_cue(q["question"]),
        "kind": pred.kind,
        "verdict_gold": gold["verdict"],
        "composite": composite(q),
        "truncated": pred.truncated,
        "negation_removed": len(ex.nodes("column", negated=True) | ex.nodes("model", negated=True)),
        "cte_refs": len(ex.nodes("cte")),
        "metrics": {},
        "modes": {},
        "diag": {},
    }
    m: dict[str, Any] = row["metrics"]

    # interpretation (M9 v1.2): field, lead or a pre-cue-kept mention; gates the set metrics
    interp_ok = True
    if gold.get("interpretation"):
        interp_ok, route = interpretation_ok(pred, gold["interpretation"]["column"], inv)
        m["interpretation_correct"] = float(interp_ok)
        row["diag"]["route_interpretation"] = route

    def setf(name: str, pred_set: set[str], gold_name: str) -> None:
        for md in ("direct", "all"):
            g = gold_set(gold, gold_name, md)
            f = prf(pred_set, g)[2] if answered and interp_ok else 0.0
            row["modes"][f"{name}_{md}"] = f
        m[name] = row["modes"][f"{name}_{mode}"]

    # M9 verdicts
    if qtype == "unanswerable":
        m["refusal_correct"] = float(pred.kind == "refused")
    else:
        if gold["verdict"] in ("answered", "chain", "partial", "clarify"):
            m["false_refusal"] = float(pred.kind == "refused")
    chain_ok = True
    if sub == "ambiguous" and gold["verdict"] == "chain":
        chain_ok = answered and target in kept_cols
        m["chain_correct"] = float(chain_ok)
        amb = pred.ambiguity or {}
        row["diag"]["ambiguity_mode_ok"] = (
            amb.get("mode") == "chain" and short_id(str(amb.get("downstream", ""))) == target
        )
    if sub == "ambiguous" and gold["verdict"] == "clarify":
        # M9 v1.1: a clarification listing every gold candidate, or an answer naming every gold
        # candidate as a non-negated mention; answering only one candidate is the failure.
        cands = norm(gold["candidates"])
        m["clarify_correct"] = float(
            (pred.kind == "clarification" and cands <= set(pred.clarification))
            or (answered and cands <= kept_cols)
        )

    # M1 set metrics
    if sub in ("upstream", "multi_part") or (sub == "ambiguous" and gold["verdict"] == "chain"):
        setf("upstream_f1", pred_cols, "upstream")
        srcs = norm(gold.get("sources") or [])
        row["diag"]["sources_f1"] = prf(pred_cols, srcs)[2] if answered else 0.0
        row["diag"]["inputs_f1"] = (
            prf(pred_cols, gold_set(gold, "inputs", mode or "direct"))[2] if answered else 0.0
        )
        if not chain_ok:
            m["upstream_f1"] = 0.0
            row["modes"] = {k: 0.0 for k in row["modes"]}
        m["headline_f1"] = m["upstream_f1"]
    if sub in ("computed", "false_premise"):
        setf("inputs_f1", pred_cols, "inputs")
        assert target is not None and mode is not None
        closure = norm(gs.upstream(view, q["target"], include_indirect=mode == "all"))
        g = gold_set(gold, "inputs", mode)
        m["inputs_f1_tolerant"] = tolerant_prf(pred_cols, g, closure)[2] if answered else 0.0
        m["headline_f1"] = m["inputs_f1"]
    if sub == "downstream":
        setf("columns_f1", pred_cols, "downstream")
        setf("models_f1", pred_models, "models")
        setf("exposures_f1", pred_exp, "exposures")
        m["headline_f1"] = m["exposures_f1" if gold.get("focus") == "exposures" else "columns_f1"]

    # M10 false premise
    if sub == "false_premise":
        assert mode is not None
        prem = short_id(gold["premise"]["edge"]["from"])
        upstream_case = gs.reaches(
            view,
            gold["premise"]["edge"]["from"],
            gold["premise"]["edge"]["to"],
            include_indirect=mode == "all",
        )
        bucket, route = premise_rejection(pred, prem, ex, upstream_case)
        row["diag"]["route_premise"] = route
        row["diag"]["premise_case"] = "U" if upstream_case else "O"
        row["diag"]["premise_bucket"] = bucket
        m["premise_rejected"] = float(bucket == "rejected")

    # M10 v1.2 multi-part: the uncovered part, field or prose (its own row, in no composite)
    if sub == "multi_part" and gold.get("out_of_scope"):
        ok, route = uncovered_part(pred, gold["out_of_scope"])
        m["uncovered_part_correct"] = float(ok)
        row["diag"]["route_uncovered"] = route

    # spurious-field diagnostics (M10 v1.2, not scored)
    if answered:
        row["diag"]["uncovered_nonempty"] = bool(pred.uncovered_parts)
        row["diag"]["premise_flag"] = bool(pred.premise_corrected)

    # M5 yes/no: structured verdict only
    if sub == "yesno":
        assert mode is not None
        want = gold["reach"][mode]
        m["yesno_correct"] = float(answered and pred.reach_verdict == want)
        row["modes"]["yesno_direct"] = float(
            answered and pred.reach_verdict == gold["reach"]["direct"]
        )
        row["modes"]["yesno_all"] = float(answered and pred.reach_verdict == gold["reach"]["all"])
        row["diag"]["heuristic_verdict"] = heuristic_yes_no(pred.answer_text)

    # M6 path node coverage (+ ordered exact match diagnostic)
    # a clarify question's correct answer has no path (metrics-design change log, 19 Oct 2026)
    if gold.get("paths") and gold["verdict"] != "clarify":
        kept_any = kept_cols | ({target} if target and answered else set())
        cov = any(set(norm(p)) <= kept_any for p in gold["paths"]) if answered else False
        m["path_node_coverage"] = float(cov and chain_ok)
        cited = {(e.from_column, e.to_column) for i, e in pred.edges.items() if i in pred.cited_ids}
        row["diag"]["path_ordered_em"] = answered and any(
            all((a, b) in cited for a, b in zip(norm_list(p), norm_list(p)[1:], strict=False))
            for p in gold["paths"]
        )

    # structured diagnostic: endpoints of cited edges (S0 / S4)
    if pred.edges and "headline_f1" in m:
        ends = {
            n
            for i in pred.cited_ids
            if (e := pred.edges.get(i))
            for n in (e.from_column, e.to_column)
        } - ({target} if target else set())
        row["diag"]["structured_nodes"] = len(ends)

    # M6 McNemar binary: question fully correct
    if "headline_f1" in m:
        m["fully_correct"] = float(m["headline_f1"] == 1.0)
    for k in ("yesno_correct", "refusal_correct", "clarify_correct"):
        if k in m:
            m["fully_correct"] = m[k]

    # M8 hallucination
    own = question_ids(q["question"], inv)
    dotted = {mm.node for mm in ex.mentions if mm.kind in ("column", "unknown")}
    halluc = {mm.node for mm in ex.mentions if mm.kind == "unknown"} - own
    if dotted:
        m["hallucination_rate"] = len(halluc) / len(dotted)
    if answered:
        m["has_hallucination"] = float(bool(halluc))
    row["diag"]["hallucinated"] = sorted(halluc)

    # M7 citations
    if pred.kind in ("answered", "refused"):
        c = score_citations(pred, inv, project)
        row["citations"] = c
        if c["answer_valid"] is not None:
            m["citation_valid_answer"] = float(c["answer_valid"])
        if c["claims"]:
            m["citation_coverage"] = c["claims_cited"] / c["claims"]

    # Ask: hand-scored only (M11)
    if qtype == "ask":
        for k in [
            k
            for k in m
            if k
            not in (
                "false_refusal",
                "hallucination_rate",
                "has_hallucination",
                "citation_valid_answer",
                "citation_coverage",
            )
        ]:
            del m[k]
    return row


def norm_list(path: Sequence[str]) -> list[str]:
    return [short_id(p) for p in path]


_YES = re.compile(r"^\W*(yes)\b", re.I)
_NO = re.compile(r"^\W*(no)\b|\b(does not|doesn't|is not|isn't|not affect|no path)\b", re.I)


def heuristic_yes_no(answer_text: str) -> str | None:
    """LABELLED DIAGNOSTIC ONLY (M5): yes / no from the first sentence. Never a headline."""
    first = re.split(r"(?<=[.!?])\s", answer_text.strip(), maxsplit=1)[0]
    if _YES.search(first):
        return "yes"
    if _NO.search(first):
        return "no"
    return None


# ------------------------------------------------------------------------ statistics (M13)
def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def bootstrap_ci(
    values: Sequence[float], seed: int = SEED, resamples: int = RESAMPLES
) -> tuple[float, float] | None:
    """Percentile 95% CI of the mean (nearest rank); None below the minimum cell size."""
    if len(values) < MIN_CI_N:
        return None
    rng = random.Random(seed)
    means = sorted(mean(rng.choices(values, k=len(values))) for _ in range(resamples))
    lo = means[math.ceil(0.025 * resamples) - 1]
    hi = means[math.ceil(0.975 * resamples) - 1]
    return lo, hi


def paired_bootstrap(
    a: Mapping[str, float], b: Mapping[str, float], seed: int = SEED, resamples: int = RESAMPLES
) -> dict[str, Any]:
    """Mean of b − a over the questions both have, with a percentile 95% CI (M13)."""
    ids = sorted(set(a) & set(b))
    diffs = [b[i] - a[i] for i in ids]
    rng = random.Random(seed)
    means = sorted(mean(rng.choices(diffs, k=len(diffs))) for _ in range(resamples))
    return {
        "n": len(ids),
        "diff": mean(diffs) if diffs else None,
        "ci": (means[math.ceil(0.025 * resamples) - 1], means[math.ceil(0.975 * resamples) - 1])
        if diffs
        else None,
    }


def mcnemar_exact(a: Mapping[str, bool], b: Mapping[str, bool]) -> dict[str, Any]:
    """Exact two-sided McNemar on the discordant pairs (M13)."""
    ids = set(a) & set(b)
    only_a = sum(1 for i in ids if a[i] and not b[i])
    only_b = sum(1 for i in ids if b[i] and not a[i])
    n = only_a + only_b
    if n == 0:
        return {"b": only_a, "c": only_b, "p": 1.0}
    k = min(only_a, only_b)
    p = min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2**n)
    return {"b": only_a, "c": only_b, "p": p}


def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile (M15)."""
    if not values:
        return None
    s = sorted(values)
    return s[max(0, math.ceil(q / 100 * len(s)) - 1)]


# ------------------------------------------------------------------------- run scoring (M12)
@dataclass
class Questions:
    items: list[dict[str, Any]]
    sha256: str


def load_questions(path: Path) -> Questions:
    text = path.read_text()
    items = [json.loads(line) for line in text.splitlines() if line.strip()]
    return Questions(items, hashlib.sha256(text.encode()).hexdigest())


def score_run(
    records: Sequence[Mapping[str, Any]],
    questions: Sequence[Mapping[str, Any]],
    *,
    corpus_dir: Path,
    view: str = "validated",
    required: Iterable[str] | None = None,
    flagged: set[str] | None = None,
    adapter: Callable[[Mapping[str, Any], str], Prediction] | None = None,
) -> dict[str, Any]:
    """Score one run. ``required``: question ids that must have a record (a missing one counts
    0 and marks the run incomplete); by default every non-Ask question."""
    inv, gview = load_inventory(corpus_dir)
    joined = join(records, questions)
    need = (
        set(required)
        if required is not None
        else {q["id"] for q in questions if q["type"] != "ask"}
    )
    rows = []
    missing = []
    for q in questions:
        rec = joined.get(q["id"])
        if rec is None:
            if q["id"] not in need:
                continue
            missing.append(q["id"])
            pred = Prediction(kind="missing")
        else:
            pred = (adapter or from_record)(rec, view)
        row = score_question(q, pred, inv, gview, corpus_dir)
        row["linker_test_seen"] = q["id"] in (flagged or set())
        rows.append(row)
    return {
        "rows": rows,
        "missing": missing,
        "complete": not missing,
        "summary": summarise(rows, questions),
    }


METRIC_ORDER = [
    "node_f1",
    "trace_f1",
    "impact_f1",
    "upstream_f1",
    "inputs_f1",
    "inputs_f1_tolerant",
    "columns_f1",
    "models_f1",
    "exposures_f1",
    "yesno_correct",
    "refusal_correct",
    "false_refusal",
    "chain_correct",
    "clarify_correct",
    "interpretation_correct",
    "premise_rejected",
    "uncovered_part_correct",
    "path_node_coverage",
    "fully_correct",
    "hallucination_rate",
    "has_hallucination",
    "citation_valid_answer",
    "citation_coverage",
]


def _values(rows: Sequence[Mapping[str, Any]], name: str) -> list[float]:
    out = []
    for r in rows:
        mm = r["metrics"]
        if name == "node_f1":
            v = mm.get("headline_f1") if r["composite"] else None
        elif name in ("trace_f1", "impact_f1"):
            v = mm.get("headline_f1") if r["composite"] == name[:-3] else None
        else:
            v = mm.get(name)
        if v is not None:
            out.append(float(v))
    return out


def stat(values: Sequence[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "mean": mean(values) if values else None,
        "ci": bootstrap_ci(values) if values else None,
    }


def summarise(
    rows: Sequence[Mapping[str, Any]], questions: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    qmeta = {q["id"]: q for q in questions}
    overall = {name: stat(_values(rows, name)) for name in METRIC_ORDER}
    breakdown: dict[str, dict[str, Any]] = {}
    for dim in ("hop_bucket", "wording", "type", "subtype", "source", "trap", "linker_test_seen"):
        groups: dict[str, list[Mapping[str, Any]]] = {}
        for r in rows:
            q = qmeta[r["id"]]
            if dim == "trap":
                keys = list(q.get("traps") or []) or ["none"]
            elif dim == "linker_test_seen":
                keys = [str(r.get("linker_test_seen", False))]
            else:
                keys = [str(q.get(dim))]
            for k in keys:
                groups.setdefault(k, []).append(r)
        breakdown[dim] = {k: stat(_values(g, "node_f1")) for k, g in sorted(groups.items())}
    cites = [r["citations"] for r in rows if "citations" in r]
    routes = {
        rule: dict(
            Counter(r["diag"][f"route_{rule}"] for r in rows if f"route_{rule}" in r["diag"])
        )
        for rule in ("interpretation", "uncovered", "premise")
    }
    spurious = {
        "uncovered_nonempty": [
            r["diag"]["uncovered_nonempty"]
            for r in rows
            if r["subtype"] != "multi_part" and "uncovered_nonempty" in r["diag"]
        ],
        "premise_flag": [
            r["diag"]["premise_flag"]
            for r in rows
            if r["subtype"] != "false_premise" and "premise_flag" in r["diag"]
        ],
    }
    return {
        "pass_routes": routes,
        "spurious_fields": {k: {"n": len(v), "flagged": sum(v)} for k, v in spurious.items()},
        "metrics": overall,
        "node_f1_by": breakdown,
        "negation_removed": sum(r["negation_removed"] for r in rows),
        "cte_refs": sum(r["cte_refs"] for r in rows),
        "truncated": [r["id"] for r in rows if r["truncated"]],
        "citations": {
            "checked": sum(c["checked"] for c in cites),
            "valid": sum(c["valid"] for c in cites),
            "r_facts": sum(c["r_facts"] for c in cites),
            "macro": sum(c["macro"] for c in cites),
            "r3_disagree": sum(c["r3_disagree"] for c in cites),
        },
    }


def attach_costs(
    result: dict[str, Any],
    records: Sequence[Mapping[str, Any]],
    questions: Sequence[Mapping[str, Any]],
) -> None:
    """M15: latency from uncached runs only; tokens and LLM calls per question."""
    joined = join(records, questions)
    lat, tok, calls, cached = [], [], [], 0
    for r in joined.values():
        t = r.get("tokens") or {}
        if t.get("cached_calls", 0):
            cached += 1
        else:
            ms = (r.get("timings") or {}).get("total_ms")
            if ms is not None:
                lat.append(float(ms))
        tok.append(float(t.get("sum_input", 0) + t.get("sum_output", 0)))
        calls.append(float(t.get("llm_calls", 0)))
    result["summary"]["latency_ms"] = {
        "p50": percentile(lat, 50),
        "p95": percentile(lat, 95),
        "n_uncached": len(lat),
        "n_cached": cached,
    }
    result["summary"]["tokens"] = {
        "mean": mean(tok) if tok else None,
        "p95": percentile(tok, 95),
        "llm_calls_mean": mean(calls) if calls else None,
    }


# ----------------------------------------------------------------------------- manifest (M15)
def manifest_path(records: Path) -> Path:
    return records.with_name(records.stem + ".manifest.json")


def legacy_manifest(
    records: Path, rows: Sequence[Mapping[str, Any]], system: str
) -> dict[str, Any]:
    """A manifest built once from the records' own fields (pre-S10 S4 smoke records only)."""
    first = rows[0] if rows else {}
    return {
        "system": system,
        "provider": first.get("provider"),
        "model": first.get("model"),
        "records_file": records.name,
        "record_count": len(rows),
        "hybrid": None,
        "note": "legacy: built by metrics.py from the records (pre-S10 run, no manifest)",
    }


# --------------------------------------------------------------------------------- rendering
def _fmt(s: Mapping[str, Any]) -> str:
    if s["mean"] is None:
        return "–"
    ci = s["ci"]
    tail = f" [{ci[0]:.2f}, {ci[1]:.2f}]" if ci else ""
    return f"{s['mean']:.3f}{tail} (n={s['n']})"


def render_markdown(result: Mapping[str, Any], title: str) -> str:
    s = result["summary"]
    v = result["versions"]
    lines = [
        f"# {title}",
        "",
        f"metrics-design {v['design']} · metrics.py {v['metrics']} · dev.jsonl sha256 "
        f"{result['questions_sha256'][:12]} · bootstrap {RESAMPLES}×, seed {SEED}, CI only for "
        f"n ≥ {MIN_CI_N}",
        "",
        f"Manifest: `{json.dumps(result['manifest'], sort_keys=True)}`",
        "",
        f"Complete: {result['complete']}"
        + (f" (missing: {', '.join(result['missing'])})" if result["missing"] else ""),
        "",
        "| metric | mean [95% CI] (n) |",
        "|---|---|",
    ]
    for name in METRIC_ORDER:
        lines.append(f"| {name} | {_fmt(s['metrics'][name])} |")
    c = s["citations"]
    lines += [
        "",
        f"Citations checked {c['checked']}, valid {c['valid']}, r_ facts {c['r_facts']}, "
        f"model-level macro bucket {c['macro']}, disagreements with R3 {c['r3_disagree']}.",
        f"Mentions removed by the negation rule: {s['negation_removed']}. CTE references: "
        f"{s['cte_refs']}. Truncated payloads: {', '.join(s['truncated']) or 'none'}.",
    ]
    if "tokens" in s:
        lat, tok = s["latency_ms"], s["tokens"]
        lines.append(
            f"Latency p50 {lat['p50']} ms, p95 {lat['p95']} ms over {lat['n_uncached']} uncached "
            f"runs ({lat['n_cached']} cached, excluded). Tokens/question mean {tok['mean']}, "
            f"LLM calls/question mean {tok['llm_calls_mean']}."
        )
    lines += [
        "",
        "## Pass routes (metrics-design v1.2: field / prose / both / neither)",
        "",
        "| rule | field | prose | both | neither | n |",
        "|---|---|---|---|---|---|",
    ]
    for rule, counts in s["pass_routes"].items():
        cells = [str(counts.get(k, 0)) for k in ("field", "prose", "both", "neither")]
        lines.append(f"| {rule} | {' | '.join(cells)} | {sum(counts.values())} |")
    sp = s["spurious_fields"]
    lines += [
        "",
        "Spurious-field diagnostics (not scored; answered predictions): non-empty "
        f"`uncovered_parts` on non-multi-part questions {sp['uncovered_nonempty']['flagged']} / "
        f"{sp['uncovered_nonempty']['n']}; `premise_corrected = true` on non-false-premise "
        f"questions {sp['premise_flag']['flagged']} / {sp['premise_flag']['n']}.",
    ]
    lines += ["", "## node-set F1 by breakdown", ""]
    for dim, groups in s["node_f1_by"].items():
        lines.append(
            f"**{dim}**: " + "; ".join(f"{k} {_fmt(g)}" for k, g in groups.items() if g["n"])
        )
        lines.append("")
    lines += ["## Per question (values below 1.0, and every miss)", ""]
    lines.append("| id | subtype | mode | kind | metric | value |")
    lines.append("|---|---|---|---|---|---|")
    for r in result["rows"]:
        for k, val in r["metrics"].items():
            bad = (
                k in ("hallucination_rate", "has_hallucination", "false_refusal") and val > 0
            ) or (
                k not in ("hallucination_rate", "has_hallucination", "false_refusal") and val < 1.0
            )
            if bad:
                lines.append(
                    f"| {r['id']} | {r['subtype']} | {r['mode']} | {r['kind']} | {k} | {val:.3f} |"
                )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--records", type=Path, required=True)
    ap.add_argument("--system", required=True, help="label, e.g. s0-gold, s0-linked, s4")
    ap.add_argument("--view", default="validated", choices=["raw", "validated", "augmented"])
    ap.add_argument("--questions", type=Path, default=ROOT / "eval/questions/dev.jsonl")
    ap.add_argument("--corpus", type=Path, default=ROOT / "corpora/synthetic_shop")
    ap.add_argument("--out", type=Path, required=True, help="output path without extension")
    ap.add_argument("--title", default=None)
    ap.add_argument(
        "--legacy-manifest",
        action="store_true",
        help="pre-S10 records only: build the manifest from the records' own fields",
    )
    ns = ap.parse_args(argv)
    if adapter_for(ns.system) is from_s1_record and ns.view != "validated":
        print(f"metrics: S1 has no {ns.view!r} view (no validator)", file=sys.stderr)
        return 2
    records = [json.loads(x) for x in ns.records.read_text().splitlines() if x.strip()]
    mpath = manifest_path(ns.records)
    if mpath.exists():
        manifest = json.loads(mpath.read_text())
    elif ns.legacy_manifest:
        manifest = legacy_manifest(ns.records, records, ns.system)
    else:
        print(f"metrics: no manifest next to {ns.records.name}", file=sys.stderr)
        return 2
    qs = load_questions(ns.questions)
    flagged = linker_test_flagged(qs.items, ROOT / "eval/linker/cases.jsonl")
    result = score_run(
        records,
        qs.items,
        corpus_dir=ns.corpus,
        view=ns.view,
        flagged=flagged,
        required=manifest.get("required"),
        adapter=adapter_for(ns.system),
    )
    attach_costs(result, records, qs.items)
    result.update(
        {
            "system": ns.system,
            "view": ns.view,
            "manifest": manifest,
            "questions_sha256": qs.sha256,
            "versions": {"design": DESIGN_VERSION, "metrics": __version__},
        }
    )
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.with_suffix(".json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    title = ns.title or f"{ns.system} ({ns.view}) on {ns.questions.name}"
    ns.out.with_suffix(".md").write_text(render_markdown(result, title))
    print(json.dumps({k: _fmt(v) for k, v in result["summary"]["metrics"].items()}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
