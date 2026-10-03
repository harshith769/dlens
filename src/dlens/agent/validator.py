"""Answer validator (spec §8): rules R1-R7 plus the R2r id repair, all enforced in code.

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
  R6 prose_refs       file paths and "line N" written in prose match an attached citation

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

ID_PREFIXES = ("e_", "s_")
MIN_PREFIX_HEX = 7
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
# e_/s_ ids written in prose, including miscopies with a stray "_" (e_4b2_403a)
_PROSE_ID = re.compile(r"(?<![\w])[es]_[0-9a-f_]{6,10}(?![\w])")


class ValidationFailure(BaseModel):
    claim_index: int | None  # None: the answer_text itself
    rule: str  # R1 R2 R3 R4.hallucinated R4.unsupported R5 R6 R7 R8
    item_id: str | None = None
    message: str


class ValidationResult(BaseModel):
    passed: bool
    failures: list[ValidationFailure] = Field(default_factory=list)
    cleaned_answer: Answer
    repairs: list[dict[str, Any]] = Field(default_factory=list)  # {claim_index, from, to}
    dropped_claims: list[int] = Field(default_factory=list)  # claims that fail >= 1 rule
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
        if item_id.startswith("e_"):
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


def rule_connectivity(answer: Answer, ctx: ValidationContext) -> list[ValidationFailure]:
    """R8: a claim naming >= 2 in-graph columns must connect them all through its cited edges
    (one undirected component over the edges' from/to)."""
    out: list[ValidationFailure] = []
    for k, c in enumerate(answer.claims):
        cols = list(
            dict.fromkeys(
                e.key for e in ctx.entities(c.text) if e.kind == "column" and ctx.in_graph(e)
            )
        )
        if len(cols) < 2:
            continue
        known = [i for i in c.ids if ctx.ledger.record(i) is not None]
        if len(known) < len(c.ids) and not any(i.startswith("e_") for i in known):
            continue  # its edge ids failed R2 (counted there)
        parent: dict[str, str] = {}
        for i in c.edge_ids:
            rec = ctx.ledger.record(i)
            if rec is None or "from" not in rec:
                continue  # failed R2: counted there
            a, b = ctx.short(rec["from"]), ctx.short(rec["to"])
            parent.setdefault(a, a)
            parent.setdefault(b, b)
            parent[_find(parent, a)] = _find(parent, b)
        roots = {_find(parent, col) if col in parent else f"<{col}>" for col in cols}
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
    """Run R1-R7 (+R2r). The input answer is not modified; repairs are applied to the copy in
    ``cleaned_answer``. Refused and clarification answers are not checked (``skipped``)."""
    if answer.refused or answer.clarification is not None:
        return ValidationResult(passed=True, cleaned_answer=answer, skipped=True)
    ctx = ValidationContext.build(ledger, question)
    cleaned, repairs, r2 = rule_in_ledger(answer, ctx)
    failures = [
        *rule_cites(cleaned, ctx),
        *r2,
        *rule_on_disk(cleaned, ctx),
        *rule_known_nodes(cleaned, ctx),
        *rule_kind_consistency(cleaned, ctx),
        *rule_relevance(cleaned, ctx),
        *rule_connectivity(cleaned, ctx),
        *rule_prose_refs(cleaned, ctx),
    ]
    return ValidationResult(
        passed=not failures,
        failures=failures,
        cleaned_answer=cleaned,
        repairs=repairs,
        dropped_claims=sorted({f.claim_index for f in failures if f.claim_index is not None}),
        counts=dict(Counter(f.rule for f in failures)),
    )


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."


def salvage(result: ValidationResult, ledger: Ledger) -> Answer | None:
    """Keep only the passing claims, with ``validation_warning``. ``answer_text`` is rebuilt from
    the kept claims whenever a claim was dropped or the text itself failed, so a warned answer
    never states a relationship the validator rejected. None when no claim passes."""
    a = result.cleaned_answer
    keep = [c for k, c in enumerate(a.claims) if k not in set(result.dropped_claims)]
    if not keep:
        return None
    out = recite(a, ledger, keep)
    rebuild = bool(result.dropped_claims) or result.answer_text_failed
    text = " ".join(_sentence(c.text) for c in keep) if rebuild else a.answer_text
    return out.model_copy(update={"answer_text": text, "validation_warning": True})
