"""Answer schema (spec §8) and how a draft becomes a cited answer.

Two shapes:
* ``AnswerDraft`` is what the LLM writes in the answer phase (structured output, ``DRAFT_SCHEMA``).
  Each claim carries one ``ids`` list; the model never types a file or a line.
* ``Answer`` is what DLens returns. Code splits ``ids`` into ``edge_ids`` (``e_``) and
  ``chunk_ids`` (``s_`` excerpts and anything else, so nothing is dropped before the validator),
  computes ``subgraph`` and attaches citations from the Toolbox ledger.

``confidence`` is the model's self-report. It is shown to the user and logged, but the validator
and the benchmark scoring never use it.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from dlens.agent.tools.provenance import Citation

Confidence = Literal["high", "medium", "low"]


class DraftClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    ids: list[str] = Field(default_factory=list)


class AnswerDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer_text: str
    claims: list[DraftClaim] = Field(default_factory=list)
    confidence: Confidence = Field(
        description="The model's self-report; never used by the validator or scoring."
    )
    refused: bool = False
    refusal_reason: str | None = None


# Hand-written and flat (no $ref) so Ollama's grammar compiler and Gemini both accept it.
# tests/unit/agent/loop/test_answer.py keeps it in step with AnswerDraft.
DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer_text": {"type": "string"},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["text", "ids"],
                "additionalProperties": False,
            },
        },
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "refused": {"type": "boolean"},
        "refusal_reason": {"type": ["string", "null"]},
    },
    "required": ["answer_text", "claims", "confidence", "refused"],
    "additionalProperties": False,
}


class Claim(BaseModel):
    text: str
    edge_ids: list[str] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)  # excerpt ids (s_) live here

    @property
    def ids(self) -> list[str]:
        return [*self.edge_ids, *self.chunk_ids]


class Clarification(BaseModel):
    question: str
    candidates: list[str]


class Answer(BaseModel):
    answer_text: str
    claims: list[Claim] = Field(default_factory=list)
    subgraph: list[str] = Field(default_factory=list)  # edge ids used by the claims
    confidence: Confidence = Field(
        default="low",
        description="The model's self-report; never used by the validator or scoring.",
    )
    refused: bool = False
    # Additive fields (v0.2, spec §8 note)
    refusal_reason: str | None = None
    clarification: Clarification | None = None
    partial_evidence: bool = False
    citations: dict[str, Citation] = Field(default_factory=dict)  # attached by code, per id

    @classmethod
    def refusal(cls, reason: str) -> Answer:
        return cls(
            answer_text=f"I can't answer this: {reason}", refused=True, refusal_reason=reason
        )


class Ledger(Protocol):
    """What answer building and the validator need from a conversation (``Toolbox`` fits)."""

    @property
    def emitted_ids(self) -> frozenset[str]: ...

    def record(self, item_id: str) -> dict[str, Any] | None: ...


def attach(draft: AnswerDraft, ledger: Ledger, *, partial_evidence: bool = False) -> Answer:
    """Split ids, compute the subgraph and attach citations from the ledger. Ids the ledger does
    not know get no citation (the validator decides what to do with them)."""
    claims: list[Claim] = []
    subgraph: list[str] = []
    citations: dict[str, Citation] = {}
    for c in draft.claims:
        ids = list(dict.fromkeys(i.strip() for i in c.ids if i.strip()))
        edges = [i for i in ids if i.startswith("e_")]
        claims.append(
            Claim(text=c.text, edge_ids=edges, chunk_ids=[i for i in ids if i not in edges])
        )
        subgraph += [e for e in edges if e not in subgraph]
        for i in ids:
            rec = ledger.record(i)
            if rec is not None and "citation" in rec:
                citations[i] = Citation.model_validate(rec["citation"])
    return Answer(
        answer_text=draft.answer_text,
        claims=claims,
        subgraph=subgraph,
        confidence=draft.confidence,
        refused=draft.refused,
        refusal_reason=draft.refusal_reason,
        partial_evidence=partial_evidence,
        citations=citations,
    )


def marker(item_id: str, cite: Citation | None) -> str:
    if cite is None:
        return f"[?{item_id}]"
    if cite.level == "model":
        return f"[{cite.file}]"
    lines = (
        str(cite.line_start)
        if cite.line_start == cite.line_end
        else (f"{cite.line_start}-{cite.line_end}")
    )
    return f"[{cite.file}:{lines}]"


def render(answer: Answer) -> str:
    """Human-readable answer: text, claims with [file:line] markers, then the citation list."""
    out = [answer.answer_text.strip()]
    if answer.clarification is not None:
        out += [f"  - {c}" for c in answer.clarification.candidates]
    if answer.claims:
        out += ["", "Claims:"]
        for c in answer.claims:
            marks = " ".join(marker(i, answer.citations.get(i)) for i in c.ids) or "[no citation]"
            out.append(f"  - {c.text.strip()} {marks}")
    if answer.citations:
        out += ["", "Citations:"]
        for i, cite in answer.citations.items():
            out.append(f"  {i}  {marker(i, cite)[1:-1]}  ({cite.level})")
    if answer.partial_evidence:
        out += [
            "",
            "Note: evidence was trimmed to fit the token budget; the answer may be partial.",
        ]
    return "\n".join(out)
