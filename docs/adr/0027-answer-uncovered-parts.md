# 0027. `uncovered_parts` on `Answer` (G2, multi-part questions)

- Status: Proposed (S12 Phase 1, 20 Oct 2026)
- Date: 2026-10-20
- Amends: spec §8 answer schema (additive) and its "Multi-part and out-of-scope questions" note
- Implemented in: S12b (B2)
- Evidence: docs/plans/s12-design.md "B2 + B5"; metrics-design M10

## Context

Spec §8 (G2): a multi-part question's uncovered part is named plainly, never dropped. M10 leaves
"acknowledging the uncovered part" unscored until a structured field exists. S1 is frozen and
cannot emit a new field, and rule 12 requires one scoring rule for S1 and S4.

## Decision (proposed)

- Additive `Answer.uncovered_parts: list[str]` (default empty), set by the LLM through a draft
  field and one S4 prompt line ("If part of the question is outside lineage, list it…"). Code
  never invents an entry.
- Scoring is decided separately (s12-design "B2 + B5" policy; metrics-design v1.2 draft): under
  the recommended policy the field **or** a prose statement of the out-of-scope intent satisfies
  M10 for every system.

## Consequences

- Old records load (empty list). The S4 prompt gains one line that S1 does not have, recorded as
  an allowed difference in the parity test.

## Alternatives rejected

- A code detector of second intents: a cue list tuned on 3 dev questions.
- Scoring the field only: S1 could never pass (rule 12), unless S1 is re-run (the policy's
  option (b)).
