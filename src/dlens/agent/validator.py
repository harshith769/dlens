"""Answer validator (spec §8): rules R1-R9 plus R2r id repair and R8c citation completion,
all enforced in code.

Rules run in this order on a copy of the answer (the raw draft is never modified); R6 runs last:

  R1 cites            every claim cites >= 1 id
  R2 in_ledger        every cited id was emitted by a tool for THIS question
  R2r repair          ... unless it is a unique, same-prefix, 1-edit (or >=7-hex-prefix) miscopy
  R3 on_disk          every cited citation still holds on disk (range exists, contains the column)
  R4 known_nodes      every model.column / model name in the prose is in the graph (hallucinated)
                      and in this question's evidence (unsupported)
  R5 kind_consistency kind words in a claim ("aggregated", "renamed") match a cited edge's kind
  R7 relevance        a claim that names entities cites at least one id that touches one of them
  R8 connectivity     a claim naming >= 2 columns connects them all through its cited edges
  R8c completion      ... after code adds the shortest connecting path (<= 4 hops) from this
                      question's emitted edges; not for "directly" claims over > 1 hop
  R9 verdict          if code made a reachability fact (r_ id), the yes/no verdict in the first
                      sentence of answer_text matches it
  R6 prose_refs       file paths and "line N" written in prose match an attached citation

r_ ids (reachability facts) are accepted by R2, re-checked on the graph by R3, and count as
touching (R7) and connecting (R8) both of their columns.

Each rule is a function ``rule_*(answer, ctx) -> list[ValidationFailure]``; ``ctx`` is a
``ValidationContext`` built once per call from the ledger (graph, evidence, emitted ids, files read
fresh from disk). ``confidence`` is the model's self-report and is never an input to any rule.
See docs/explain/validator.md.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from dlens.agent.answer import Answer, Claim, Ledger
from dlens.agent.tools.provenance import Citation, contains_word, safe_read, text_sha1
from dlens.agent.tools.reach import check, fact_record

ID_PREFIXES = ("e_", "s_", "r_")
LINK_PREFIXES = ("e_", "r_")  # ids with from/to columns: edges and reachability facts
MIN_PREFIX_HEX = 7
MAX_COMPLETION_HOPS = 4  # R8c: longest bridge citation completion may add
_DIRECT = re.compile(r"\bdirect(ly)?\b", re.IGNORECASE)  # "indirectly" does not match
FILE_EXTENSIONS = {"sql", "csv", "yml", "yaml", "md"}

# R5: kind words -> edge kinds that make the word true. One table, documented in validator.md.
KIND_WORDS: list[tuple[str, re.Pattern[str], frozenset[str]]] = [
    ("aggregation", re.compile(r"\baggregat\w*"), frozenset({"AGGREGATION"})),
    (
        "sum/count/avg",
        re.compile(r"\b(sum|sums|summed|summing|count|counts|counted|avg|average[sd]?)\b"),
        frozenset({"AGGREGATION", "TRANSFORMATION"}),  # "the sum of a and b" is often a + b
    ),
    ("rename", re.compile(r"\brenam\w*"), frozenset({"RENAME"})),
    (
        "identity",
        re.compile(
            r"\b(identity|unchanged|as-is|same (value|column)s?|pass(es|ed)? through|"
            r"passed straight through)\b"
        ),
        frozenset({"IDENTITY", "RENAME"}),
    ),
    (
        "transformation",
        re.compile(r"\b(transform\w*|computed?|computes|calculat\w*)\b"),
        frozenset({"TRANSFORMATION", "AGGREGATION"}),
    ),
]

_CHAIN = re.compile(r"(?<![\w/.-])([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)")
_PATH = re.compile(r"(?<![\w/])((?:[\w.-]+/)*[\w.-]+\.(?:sql|csv|yml|yaml))\b", re.IGNORECASE)
_LINES = re.compile(r"\blines?\s+(\d+)(?:\s*(?:-|–|to)\s*(\d+))?", re.IGNORECASE)
_WORD = re.compile(r"\b[A-Za-z_]\w*\b")
# e_/s_/r_ ids written in prose, including miscopies with a stray "_" (e_4b2_403a)
_PROSE_ID = re.compile(r"(?<![\w])[esr]_[0-9a-f_]{6,10}(?![\w])")

# R9: the verdict of the first sentence of answer_text (HEURISTIC, docs/explain/validator.md).
# An explicit leading "Yes"/"No" wins; else a negation means no; else a reach verb means yes.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_YES_WORD = re.compile(r"^\W*yes\b", re.IGNORECASE)
_NO_WORD = re.compile(r"^\W*no\b", re.IGNORECASE)
_NEGATION = re.compile(r"\b(not|never|cannot|no|none|neither)\b|n't\b", re.IGNORECASE)
_REACH_VERB = re.compile(
    r"\b(affect|impact|depend|feed|flow|reach|chang|propagat|influenc)\w*", re.IGNORECASE
)


class ValidationFailure(BaseModel):
    claim_index: int | None  # None: the answer_text itself
    rule: str  # R1 R2 R3 R4.hallucinated R4.unsupported R5 R6 R7 R8 R9
    item_id: str | None = None
    message: str


class ValidationResult(BaseModel):
    passed: bool
    failures: list[ValidationFailure] = Field(default_factory=list)
    cleaned_answer: Answer
    repairs: list[dict[str, Any]] = Field(default_factory=list)  # {claim_index, from, to}
    completions: list[dict[str, Any]] = Field(default_factory=list)  # {claim_index, added}
    dropped_claims: list[int] = Field(default_factory=list)  # claims that fail >= 1 rule
    fact: dict[str, Any] | None = None  # the reachability fact's ledger record, if any (R9)
    counts: dict[str, int] = Field(default_factory=dict)
    regenerated: bool = False  # set by the loop
    warning: bool = False  # set by the loop when it had to salvage
    skipped: bool = False  # refused / clarification answers are not checked

    @property
    def answer_text_failed(self) -> bool:
        return any(f.claim_index is None for f in self.failures)


# -- entities (shared by R4 and R7) -------------------------------------------------------------


@dataclass(frozen=True)
class Entity:
    text: str  # as written, lower-cased
    kind: str  # "column" (model.column) or "model"
    key: str  # "model.column" or "model", lower-case


@dataclass
class ValidationContext:
    ledger: Ledger
    question: str = ""
    model_uids: dict[str, list[str]] = field(default_factory=dict)  # name -> uids
    short_cols: dict[str, list[str]] = field(default_factory=dict)  # model.column -> full ids
    evidence_short: set[str] = field(default_factory=set)
    evidence_models: set[str] = field(default_factory=set)  # names
    evidence_sql: str = ""  # every SQL line a tool showed, lower-case
    question_entities: set[str] = field(default_factory=set)  # in-graph keys named in question
    fact: dict[str, Any] | None = None  # the r_ reachability fact's record (R9), if code made one
    _files: dict[str, str | None] = field(default_factory=dict)

    @classmethod
    def build(cls, ledger: Ledger, question: str = "") -> ValidationContext:
        ctx = cls(ledger=ledger, question=question)
        g = ledger.graph
        for uid in g.model_ids():
            name = (g.model_info(uid) or {}).get("name", uid).lower()
            ctx.model_uids.setdefault(name, []).append(uid)
        for cid in g.columns():
            ctx.short_cols.setdefault(ctx.short(cid), []).append(cid)
        ctx._collect_evidence()
        ctx.question_entities = {e.key for e in ctx.entities(question) if ctx.in_graph(e)}
        facts = sorted(i for i in ledger.emitted_ids if i.startswith("r_"))
        ctx.fact = ledger.record(facts[0]) if facts else None
        return ctx

    # graph helpers
    def model_name(self, uid: str) -> str:
        return (self.ledger.graph.model_info(uid) or {}).get("name", uid).lower()

    def short(self, cid: str) -> str:
        g = self.ledger.graph
        return f"{self.model_name(g.model_of(cid))}.{g.nx_graph.nodes[cid]['name']}".lower()

    def in_graph(self, e: Entity) -> bool:
        return e.key in (self.short_cols if e.kind == "column" else self.model_uids)

    def read(self, file: str) -> str | None:
        """Fresh (per validation) and path-traversal safe."""
        if file not in self._files:
            self._files[file] = safe_read(Path(self.ledger.project_dir), file)
        return self._files[file]

    def _add_column(self, text: str) -> None:
        key = text.lower()
        if key in self.short_cols:
            self.evidence_short.add(key)
            self.evidence_models.add(key.rsplit(".", 1)[0])
            return
        g = self.ledger.graph
        if g.has_column(key):
            self.evidence_short.add(self.short(key))
            self.evidence_models.add(self.model_name(g.model_of(key)))

    def _collect_evidence(self) -> None:
        for r in self.ledger.log:
            if "error" in r.llm_payload:
                continue
            p, side = r.llm_payload, r.side_records
            if isinstance(side.get("column"), str):
                self._add_column(side["column"])
            for rec in side.get("edges", {}).values():
                self._add_column(rec["from"])
                self._add_column(rec["to"])
            for col in side.get("columns", {}).values():
                self._add_column(col["id"])
            for name in p.get("models", []):
                self.evidence_models.add(str(name).lower())
            for c in p.get("candidates", []):
                if c.get("kind") == "column":
                    self._add_column(c["id"])
                else:
                    self.evidence_models.add(str(c["id"]).lower())
            if r.tool == "get_model_sql":
                self.evidence_models.add(str(p.get("model", "")).lower())
                self.evidence_sql += "\n" + "\n".join(p.get("excerpt", [])).lower()

    def entities(self, text: str) -> list[Entity]:
        """Dotted model.column chains and bare model names (those containing "_") in prose."""
        found: list[Entity] = []
        masked = _PATH.sub(lambda m: " " * len(m.group(0)), text)
        for m in _CHAIN.finditer(masked):
            segs = m.group(1).split(".")
            if segs[-1].lower() in FILE_EXTENSIONS:
                continue
            model, col = segs[-2].lower(), segs[-1].lower()
            if model not in self.model_uids and "_" not in model and "_" not in col:
                continue  # "e.g", "i.e"
            found.append(Entity(m.group(1).lower(), "column", f"{model}.{col}"))
        masked = _CHAIN.sub(lambda m: " " * len(m.group(0)), masked)
        for m in _WORD.finditer(masked):
            w = m.group(0).lower()
            if "_" in w and w in self.model_uids:
                found.append(Entity(w, "model", w))
        return list(dict.fromkeys(found))

    def touches(self, item_id: str, e: Entity) -> bool:
        """R7: does the cited id's record touch entity ``e``?"""
        rec = self.ledger.record(item_id)
        if rec is None or not self.in_graph(e):
            return False
        g = self.ledger.graph
        model = e.key.rsplit(".", 1)[0] if e.kind == "column" else e.key
        if item_id.startswith(LINK_PREFIXES):  # an edge, or a fact about its two columns
            ends = [rec["from"], rec["to"]]
            if e.kind == "column" and any(self.short(c) == e.key for c in ends):
                return True
            return e.kind == "model" and any(self.model_name(g.model_of(c)) == model for c in ends)
        cite = rec.get("citation", {})
        files = {(g.model_info(u) or {}).get("file") for u in self.model_uids.get(model, [])}
        if cite.get("file") in files:
            return True
        if e.kind == "column":
            text = self.read(cite.get("file", "")) or ""
            chunk = "\n".join(text.splitlines()[cite["line_start"] - 1 : cite["line_end"]])
            return contains_word(chunk, e.key.rsplit(".", 1)[1])
        return False


# -- R2r: id repair ------------------------------------------------------------------------------


def within_one_edit(a: str, b: str) -> bool:
    """Levenshtein distance <= 1 (one substitution, insertion or deletion)."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    if len(a) == len(b):
        return a[i + 1 :] == b[i + 1 :]
    return a[i:] == b[i + 1 :]


def repair_candidates(bad: str, emitted: Iterable[str]) -> list[str]:
    """Emitted ids a miscopied ``bad`` id could stand for: same prefix, and either one edit away
    or ``bad`` is a prefix of it with >= 7 hex characters."""
    prefix = bad[:2]
    if prefix not in ID_PREFIXES:
        return []
    hexpart = bad[2:]
    out = []
    for cand in emitted:
        if not cand.startswith(prefix):
            continue
        is_prefix = len(hexpart) >= MIN_PREFIX_HEX and cand.startswith(bad) and cand != bad
        if within_one_edit(bad, cand) or is_prefix:
            out.append(cand)
    return sorted(set(out))


def _with_ids(claim: Claim, ids: list[str]) -> Claim:
    edges = [i for i in ids if i.startswith("e_")]
    return Claim(text=claim.text, edge_ids=edges, chunk_ids=[i for i in ids if i not in edges])


def recite(answer: Answer, ledger: Ledger, claims: list[Claim]) -> Answer:
    """``answer`` with ``claims``, and subgraph/citations recomputed from the ledger."""
    citations: dict[str, Citation] = {}
    subgraph: list[str] = []
    for c in claims:
        for i in c.ids:
            rec = ledger.record(i)
            if rec is not None and "citation" in rec:
                citations[i] = Citation.model_validate(rec["citation"])
        subgraph += [e for e in c.edge_ids if e not in subgraph]
    return answer.model_copy(
        update={"claims": claims, "citations": citations, "subgraph": subgraph}
    )


def _check_id(
    item_id: str, emitted: frozenset[str], k: int | None
) -> tuple[str | None, ValidationFailure | None]:
    """R2/R2r for one id: (repaired id or None, failure or None)."""
    if item_id in emitted:
        return None, None
    cands = repair_candidates(item_id, emitted)
    if len(cands) == 1:
        return cands[0], None
    why = (
        "no emitted id is a unique 1-edit match"
        if not cands
        else f"{len(cands)} emitted ids match; ambiguous, not repaired"
    )
    return None, ValidationFailure(
        claim_index=k,
        rule="R2",
        item_id=item_id,
        message=f"{item_id} was not emitted by a tool in this question ({why})",
    )


def _check_prose_ids(
    text: str,
    emitted: frozenset[str],
    k: int | None,
    repairs: list[dict[str, Any]],
    failures: list[ValidationFailure],
) -> str:
    """R2 for e_/s_ tokens written in prose; uniquely repairable ones are rewritten."""

    def fix(m: re.Match[str]) -> str:
        token = m.group(0)
        to, failure = _check_id(token, emitted, k)
        if failure is not None:
            failures.append(failure)
        if to is None:
            return token
        repairs.append({"claim_index": k, "from": token, "to": to, "in": "text"})
        return to

    return _PROSE_ID.sub(fix, text)


def rule_in_ledger(
    answer: Answer, ctx: ValidationContext
) -> tuple[Answer, list[dict[str, Any]], list[ValidationFailure]]:
    """R2 + R2r, for cited ids and for e_/s_ ids written in the prose. Returns the answer with
    unique repairs applied (prose ids rewritten), the repairs and the failures."""
    emitted = ctx.ledger.emitted_ids
    repairs: list[dict[str, Any]] = []
    failures: list[ValidationFailure] = []
    claims: list[Claim] = []
    for k, c in enumerate(answer.claims):
        ids: list[str] = []
        for i in c.ids:
            to, failure = _check_id(i, emitted, k)
            if to is not None:
                repairs.append({"claim_index": k, "from": i, "to": to})
            if failure is not None:
                failures.append(failure)
            ids.append(to or i)
        text = _check_prose_ids(c.text, emitted, k, repairs, failures)
        claims.append(_with_ids(c.model_copy(update={"text": text}), list(dict.fromkeys(ids))))
    answer_text = _check_prose_ids(answer.answer_text, emitted, None, repairs, failures)
    out = recite(answer.model_copy(update={"answer_text": answer_text}), ctx.ledger, claims)
    return out, repairs, failures


# -- rules ---------------------------------------------------------------------------------------


def rule_cites(answer: Answer, ctx: ValidationContext) -> list[ValidationFailure]:
    """R1: every claim cites at least one id."""
    return [
        ValidationFailure(claim_index=k, rule="R1", message="claim cites no edge or chunk id")
        for k, c in enumerate(answer.claims)
        if not c.ids
    ]


def rule_on_disk(answer: Answer, ctx: ValidationContext) -> list[ValidationFailure]:
    """R3: each in-ledger id's citation (from the ledger) still holds in the file on disk."""
    out: list[ValidationFailure] = []
    for k, c in enumerate(answer.claims):
        for i in c.ids:
            rec = ctx.ledger.record(i)
            if rec is None:
                continue  # R2's job
            problem = _citation_problem(i, rec, ctx)
            if problem:
                out.append(ValidationFailure(claim_index=k, rule="R3", item_id=i, message=problem))
    return out


def _citation_problem(item_id: str, rec: dict[str, Any], ctx: ValidationContext) -> str | None:
    if item_id.startswith("r_"):
        return _fact_problem(rec, ctx)
    cite = rec.get("citation") or {}
    file, a, b = cite.get("file", ""), cite.get("line_start", 0), cite.get("line_end", 0)
    text = ctx.read(file)
    if text is None:
        return f"{file!r} is missing or outside the project"
    lines = text.splitlines()
    if not 1 <= a <= b <= max(len(lines), 1):
        return f"lines {a}-{b} are outside {file} ({len(lines)} lines)"
    chunk = "\n".join(lines[a - 1 : b])
    if item_id.startswith("s_"):
        want = rec.get("text_sha1")
        if want and text_sha1(text, a, b) != want:
            return f"{file}:{a}-{b} changed since the tool showed it"
        return None
    name = str(rec.get("to", "")).rsplit(".", 1)[-1]
    level = cite.get("level")
    if level == "line" and not contains_word(chunk, name):
        return f"{file}:{a}-{b} does not contain {name!r}"
    if level == "star" and "*" not in chunk:
        return f"{file}:{a}-{b} does not contain the '*' that produces {name!r}"
    if level == "model":
        if file.lower().endswith(".csv"):
            header = [h.strip().strip('"').lower() for h in (lines[0] if lines else "").split(",")]
            if name.lower() not in header:
                return f"{file} header has no column {name!r}"
        elif not contains_word(text, name):
            return f"{file} does not mention {name!r}"
    return None


def _fact_problem(rec: dict[str, Any], ctx: ValidationContext) -> str | None:
    """R3 for an r_ fact: re-run the reachability check on the graph and compare."""
    g = ctx.ledger.graph
    if not (g.has_column(rec.get("from", "")) and g.has_column(rec.get("to", ""))):
        return "the graph check's columns are not in the graph"
    fresh = fact_record(g, check(g, rec["from"], rec["to"]))
    keys = ("fact_id", "reaches", "hops", "reverse_hops", "path")
    if any(fresh[k] != rec.get(k) for k in keys):
        return f"the graph check no longer holds: now {fresh['fact']!r}"
    return None


def _texts(answer: Answer) -> list[tuple[int | None, str]]:
    return [(None, answer.answer_text)] + [(k, c.text) for k, c in enumerate(answer.claims)]


def rule_known_nodes(answer: Answer, ctx: ValidationContext) -> list[ValidationFailure]:
    """R4: identifiers in prose exist in the graph (else hallucinated) and in this question's
    evidence (else unsupported; the question's own in-graph identifiers are exempt)."""
    out: list[ValidationFailure] = []
    for k, text in _texts(answer):
        for e in ctx.entities(text):
            if e.text in ctx.evidence_sql:
                continue  # shown verbatim in a SQL excerpt (e.g. a CTE column)
            if not ctx.in_graph(e):
                out.append(
                    ValidationFailure(
                        claim_index=k,
                        rule="R4.hallucinated",
                        item_id=e.key,
                        message=f"{e.key} is not a {e.kind} in this project",
                    )
                )
                continue
            seen = e.key in (ctx.evidence_short if e.kind == "column" else ctx.evidence_models)
            if not seen and e.key not in ctx.question_entities:
                out.append(
                    ValidationFailure(
                        claim_index=k,
                        rule="R4.unsupported",
                        item_id=e.key,
                        message=f"{e.key} exists but no tool returned it for this question",
                    )
                )
    return out


def rule_kind_consistency(answer: Answer, ctx: ValidationContext) -> list[ValidationFailure]:
    """R5: a kind word in a claim needs a cited edge of a compatible kind (KIND_WORDS)."""
    out: list[ValidationFailure] = []
    for k, c in enumerate(answer.claims):
        kinds = {
            str(rec["kind"])
            for i in c.edge_ids
            if (rec := ctx.ledger.record(i)) is not None and "kind" in rec
        }
        if not kinds:
            continue
        low = c.text.lower()
        for group, pattern, allowed in KIND_WORDS:
            m = pattern.search(low)
            if m and not kinds & allowed:
                out.append(
                    ValidationFailure(
                        claim_index=k,
                        rule="R5",
                        item_id=m.group(0),
                        message=f"says {m.group(0)!r} ({group}) but cites only "
                        f"{sorted(kinds)} edges",
                    )
                )
    return out


def rule_relevance(answer: Answer, ctx: ValidationContext) -> list[ValidationFailure]:
    """R7: a claim naming entities must cite at least one id that touches one of them."""
    out: list[ValidationFailure] = []
    for k, c in enumerate(answer.claims):
        named = [e for e in ctx.entities(c.text) if ctx.in_graph(e)]
        known = [i for i in c.ids if ctx.ledger.record(i) is not None]
        if not named or not known:
            continue  # no entity named, or every id already failed R2 (counted there)
        if not any(ctx.touches(i, e) for i in known for e in named):
            out.append(
                ValidationFailure(
                    claim_index=k,
                    rule="R7",
                    item_id=",".join(e.key for e in named),
                    message="none of the cited ids involves " + ", ".join(e.key for e in named),
                )
            )
    return out


def _find(parent: dict[str, str], x: str) -> str:
    """Union-find root, with path halving."""
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def _claim_columns(c: Claim, ctx: ValidationContext) -> list[str]:
    """R8's subject: the distinct in-graph model.column ids a claim names."""
    return list(
        dict.fromkeys(e.key for e in ctx.entities(c.text) if e.kind == "column" and ctx.in_graph(e))
    )


def _link_ids(c: Claim) -> list[str]:
    """R8's links: the cited edges, plus cited r_ facts (each connects its two columns)."""
    return [*c.edge_ids, *(i for i in c.chunk_ids if i.startswith("r_"))]


def _r8_exempt(c: Claim, ctx: ValidationContext) -> bool:
    """Every cited edge id failed R2 (counted there), so R8 has nothing to check."""
    known = [i for i in c.ids if ctx.ledger.record(i) is not None]
    return len(known) < len(c.ids) and not any(i.startswith(LINK_PREFIXES) for i in known)


def _edge_ends(item_id: str, ctx: ValidationContext) -> tuple[str, str] | None:
    rec = ctx.ledger.record(item_id)
    if rec is None or "from" not in rec:
        return None
    return ctx.short(rec["from"]), ctx.short(rec["to"])


def _components(edge_ids: Iterable[str], ctx: ValidationContext) -> dict[str, str]:
    """Union-find parents over the edges' endpoints (undirected)."""
    parent: dict[str, str] = {}
    for i in edge_ids:
        ends = _edge_ends(i, ctx)
        if ends is None:
            continue  # failed R2: counted there
        a, b = ends
        parent.setdefault(a, a)
        parent.setdefault(b, b)
        parent[_find(parent, a)] = _find(parent, b)
    return parent


def _root(parent: dict[str, str], col: str) -> str:
    return _find(parent, col) if col in parent else f"<{col}>"


def rule_connectivity(answer: Answer, ctx: ValidationContext) -> list[ValidationFailure]:
    """R8: a claim naming >= 2 in-graph columns must connect them all through its cited edges
    (one undirected component over the edges' from/to). A cited r_ fact links its two columns,
    whatever it says: "No, X does not reach Y" citing it is about exactly those columns."""
    out: list[ValidationFailure] = []
    for k, c in enumerate(answer.claims):
        cols = _claim_columns(c, ctx)
        if len(cols) < 2 or _r8_exempt(c, ctx):
            continue
        parent = _components(_link_ids(c), ctx)
        roots = {_root(parent, col) for col in cols}
        if len(roots) > 1:
            out.append(
                ValidationFailure(
                    claim_index=k,
                    rule="R8",
                    item_id=",".join(cols),
                    message="the cited edges do not connect " + ", ".join(cols),
                )
            )
    return out


Adjacency = dict[str, list[tuple[str, str]]]  # node -> [(next node, edge id)], downstream


def _ledger_adjacency(ctx: ValidationContext) -> Adjacency:
    """Directed (from -> to) adjacency over every edge this question's tools emitted. Sorted,
    so completion is deterministic."""
    adj: Adjacency = {}
    for i in sorted(ctx.ledger.emitted_ids):
        if i.startswith("e_") and (ends := _edge_ends(i, ctx)) is not None:
            adj.setdefault(ends[0], []).append((ends[1], i))
    return adj


def _bridge(
    adj: Adjacency, sources: set[str], targets: set[str], max_hops: int
) -> list[str] | None:
    """Edge ids of a shortest DIRECTED path (<= max_hops) from any source to any target."""
    prev: dict[str, tuple[str, str] | None] = {s: None for s in sorted(sources)}
    frontier, hops = sorted(sources), 0
    while frontier and hops < max_hops:
        hops += 1
        nxt: list[str] = []
        for x in frontier:
            for y, i in adj.get(x, []):
                if y in prev:
                    continue
                prev[y] = (x, i)
                if y in targets:
                    path: list[str] = []
                    node: str = y
                    while (step := prev[node]) is not None:
                        node, edge_id = step
                        path.append(edge_id)
                    return path[::-1]
                nxt.append(y)
        frontier = nxt
    return None


def complete_citations(
    answer: Answer, ctx: ValidationContext
) -> tuple[Answer, list[dict[str, Any]]]:
    """R8c: for a claim that would fail R8, add the missing connecting edges from this
    question's ledger. All or nothing per claim; otherwise the claim is unchanged and R8 fails
    it. Conditions (docs/explain/validator.md, R8c):

    * anchor: at least one of the claim's own cited edges touches a column it names, so
      completion can never make an unrelated citation relevant (R7 stays meaningful);
    * every bridge is a shortest DIRECTED lineage path (either direction, <= 4 hops) between
      two columns the claim names, so siblings that only share a descendant stay unconnected;
    * "direct"/"directly" in the claim forbids any bridge longer than one hop.

    Completed edges are ordinary cited edges afterwards: R3, R5 and R7 check them like any
    other. Returns the answer and the completions ``{claim_index, added}``."""
    adj: Adjacency | None = None
    completions: list[dict[str, Any]] = []
    claims: list[Claim] = []
    for k, c in enumerate(answer.claims):
        cols = _claim_columns(c, ctx)
        if len(cols) < 2 or _r8_exempt(c, ctx):
            claims.append(c)
            continue
        adj = _ledger_adjacency(ctx) if adj is None else adj
        added = _complete_one(c, cols, adj, ctx)
        if not added:
            claims.append(c)
            continue
        claims.append(_with_ids(c, list(dict.fromkeys([*c.ids, *added]))))
        completions.append({"claim_index": k, "added": added})
    if not completions:
        return answer, []
    return recite(answer, ctx.ledger, claims), completions


def _complete_one(c: Claim, cols: list[str], adj: Adjacency, ctx: ValidationContext) -> list[str]:
    """The edge ids to add so that every column in ``cols`` is connected, or [] if R8 already
    passes, there is no anchor, a column cannot be bridged, or the "directly" guard applies."""
    named = set(cols)
    links = _link_ids(c)
    # the anchor must be an EDGE: an r_ fact (maybe "X does NOT reach Y") never anchors a bridge
    if not any(set(ends) & named for i in c.edge_ids if (ends := _edge_ends(i, ctx))):
        return []  # no anchor: the claim's own citations touch none of its columns
    direct = bool(_DIRECT.search(c.text))
    added: list[str] = []
    while True:
        parent = _components([*links, *added], ctx)
        root0 = _root(parent, cols[0])
        if all(_root(parent, col) == root0 for col in cols):
            return added
        loose_root = next(_root(parent, col) for col in cols if _root(parent, col) != root0)
        here = {col for col in cols if _root(parent, col) == root0}
        there = {col for col in cols if _root(parent, col) == loose_root}
        paths = [
            p
            for p in (
                _bridge(adj, there, here, MAX_COMPLETION_HOPS),
                _bridge(adj, here, there, MAX_COMPLETION_HOPS),
            )
            if p is not None
        ]
        if not paths:
            return []
        path = min(paths, key=len)
        if direct and len(path) > 1:
            return []
        added += [i for i in path if i not in added and i not in c.edge_ids]


def answer_verdict(text: str) -> str | None:
    """ "yes", "no" or None from the FIRST sentence of ``text`` (heuristic, see validator.md)."""
    first = _SENTENCE_END.split(text.strip(), maxsplit=1)[0]
    if _YES_WORD.search(first):
        return "yes"
    if _NO_WORD.search(first) or _NEGATION.search(first):
        return "no"
    return "yes" if _REACH_VERB.search(first) else None


def fact_verdict(fact: dict[str, Any]) -> str:
    return "yes" if fact["reaches"] else "no"


def rule_verdict(answer: Answer, ctx: ValidationContext) -> list[ValidationFailure]:
    """R9: when code made a reachability fact, the answer_text's yes/no verdict must match it
    (no verdict in its first sentence fails too). A claim that cites the r_ id must not state
    the opposite verdict (a claim with no verdict is fine: it may describe the path)."""
    if ctx.fact is None:
        return []
    rid, want = ctx.fact["fact_id"], fact_verdict(ctx.fact)

    def failure(k: int | None, why: str) -> ValidationFailure:
        msg = f"{why}, but the graph check says: {ctx.fact['fact'] if ctx.fact else ''}"
        return ValidationFailure(claim_index=k, rule="R9", item_id=rid, message=msg)

    out: list[ValidationFailure] = []
    said = answer_verdict(answer.answer_text)
    if said != want:
        out.append(
            failure(
                None, "no yes/no verdict in the first sentence" if said is None else f"says {said}"
            )
        )
    for k, c in enumerate(answer.claims):
        said = answer_verdict(c.text) if rid in c.ids else None
        if said is not None and said != want:
            out.append(failure(k, f"cites {rid} but says {said}"))
    return out


def rule_prose_refs(answer: Answer, ctx: ValidationContext) -> list[ValidationFailure]:
    """R6: file paths and line numbers written in prose must match an attached citation."""
    out: list[ValidationFailure] = []
    all_ids = [i for c in answer.claims for i in c.ids]
    for k, text in _texts(answer):
        ids = all_ids if k is None else answer.claims[k].ids
        cites = [
            Citation.model_validate(rec["citation"])
            for i in ids
            if (rec := ctx.ledger.record(i)) is not None and "citation" in rec
        ]
        for m in _PATH.finditer(text):
            path = m.group(1)
            if not any(c.file == path or c.file.endswith("/" + path) for c in cites):
                out.append(
                    ValidationFailure(
                        claim_index=k,
                        rule="R6",
                        item_id=path,
                        message=f"mentions {path} but no attached citation is in that file",
                    )
                )
        for m in _LINES.finditer(text):
            lo = int(m.group(1))
            hi = int(m.group(2)) if m.group(2) else lo
            ok = any(c.level != "model" and c.line_start <= lo and hi <= c.line_end for c in cites)
            if not ok:
                out.append(
                    ValidationFailure(
                        claim_index=k,
                        rule="R6",
                        item_id=m.group(0),
                        message=f"mentions {m.group(0)!r} but no attached citation covers it",
                    )
                )
    return out


# -- entry points --------------------------------------------------------------------------------


def validate(answer: Answer, ledger: Ledger, question: str = "") -> ValidationResult:
    """Run R1-R9 (+R2r repair, +R8c completion). The input answer is not modified; repairs and
    completions are applied to the copy in ``cleaned_answer``. Refused and clarification answers
    are not checked (``skipped``)."""
    if answer.refused or answer.clarification is not None:
        return ValidationResult(passed=True, cleaned_answer=answer, skipped=True)
    ctx = ValidationContext.build(ledger, question)
    cleaned, repairs, r2 = rule_in_ledger(answer, ctx)
    cleaned, completions = complete_citations(cleaned, ctx)  # then re-checked by every rule
    failures = [
        *rule_cites(cleaned, ctx),
        *r2,
        *rule_on_disk(cleaned, ctx),
        *rule_known_nodes(cleaned, ctx),
        *rule_kind_consistency(cleaned, ctx),
        *rule_relevance(cleaned, ctx),
        *rule_connectivity(cleaned, ctx),
        *rule_verdict(cleaned, ctx),
        *rule_prose_refs(cleaned, ctx),
    ]
    return ValidationResult(
        passed=not failures,
        failures=failures,
        cleaned_answer=cleaned,
        repairs=repairs,
        completions=completions,
        dropped_claims=sorted({f.claim_index for f in failures if f.claim_index is not None}),
        counts=dict(Counter(f.rule for f in failures)),
        fact=ctx.fact,
    )


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."


def verdict_claim(fact: dict[str, Any]) -> Claim:
    """Code's own verdict sentence for a yes/no reachability question, citing the r_ fact."""
    head = "Yes" if fact["reaches"] else "No"
    return Claim(text=f"{head}: {fact['fact']}", chunk_ids=[fact["fact_id"]])


def salvage(result: ValidationResult, ledger: Ledger) -> Answer | None:
    """Keep only the passing claims, with ``validation_warning``. ``answer_text`` is rebuilt from
    the kept claims whenever a claim was dropped or the text itself failed, so a warned answer
    never states a relationship the validator rejected. When code made a reachability fact, a
    rebuilt text leads with code's verdict claim (citing the r_ id), so an R9 failure ends with
    the graph's yes/no. None when no claim passes (and there is no fact)."""
    a = result.cleaned_answer
    keep = [c for k, c in enumerate(a.claims) if k not in set(result.dropped_claims)]
    rebuild = bool(result.dropped_claims) or result.answer_text_failed
    fact = result.fact
    if fact is not None and rebuild and not any(fact["fact_id"] in c.ids for c in keep):
        keep = [verdict_claim(fact), *keep]
    if not keep:
        return None
    out = recite(a, ledger, keep)
    text = " ".join(_sentence(c.text) for c in keep) if rebuild else a.answer_text
    return out.model_copy(update={"answer_text": text, "validation_warning": True})
