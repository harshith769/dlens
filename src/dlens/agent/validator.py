"""Answer validator: INTERFACE ONLY (v0.2 session 3).

# ---------------------------------------------------------------------------------------------
# [H] The rules (spec §8) are hand-written by the owner in session 4. Until then ``validate`` is
# a pass-through: it never fails an answer. Rules to come:
#   1. every claim cites at least one edge or chunk id;
#   2. every cited id appears in a tool result from this conversation (ledger.emitted_ids);
#   3. every cited file and line range exists on disk and contains the column
#      (``star`` level: contains ``*``; ``s_`` excerpts: file and range exist);
#   4. on failure the loop drops failing claims and regenerates once (see agent/loop.py,
#      "REGENERATE ONCE"); if it fails again the answer returns with a warning flag.
# ---------------------------------------------------------------------------------------------

``confidence`` is the model's self-report and is never an input to validation.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from dlens.agent.answer import Answer, Ledger


class ValidationFailure(BaseModel):
    claim_index: int | None  # None: a failure of the answer as a whole
    rule: int
    item_id: str | None = None
    message: str


class ValidationResult(BaseModel):
    passed: bool
    failures: list[ValidationFailure] = Field(default_factory=list)
    cleaned_answer: Answer
    stub: bool = False  # True while the rules are not implemented


def validate(answer: Answer, ledger: Ledger) -> ValidationResult:
    """Check ``answer`` against the ledger. STUB: passes everything through unchanged."""
    del ledger  # used by the real rules (session 4)
    return ValidationResult(passed=True, cleaned_answer=answer, stub=True)
