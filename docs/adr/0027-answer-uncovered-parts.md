# 0027. `uncovered_parts` on `Answer` (G2, multi-part questions)

- Status: Accepted (owner, 21 Oct 2026; S12b step 3; metrics-design v1.2 approved at STOP 1).
  Spec §0 row 35. Implemented in 0207837
- Date: 2026-10-20
- Amends: spec §8 answer schema (additive) and its "Multi-part and out-of-scope questions" note
- Implemented in: S12b (item B2)
- Evidence: docs/plans/s12-design.md "B2 + B5"; docs/plans/metrics-design.md M10 (v1.2 draft),
  Appendix D

## Context

Spec §8 (G2): a multi-part question's uncovered part is named plainly, never dropped. Metrics
v1.1 leaves "acknowledging the uncovered part" unscored until a structured field exists. S1 is
frozen and cannot emit a new field, and rule 12 requires one scoring rule for S1 and S4.

## Decision

- Additive `Answer.uncovered_parts: list[str]` (default empty) and the same field in
  `AnswerDraft` (required in the draft schema). Set by the LLM through one S4 prompt line (an
  S4-only appended line in `ALLOWED_DIFFERENCES`, exact text in s12-design v1.2; it carries no
  example drawn from dev gold, and a test checks it shares no content word with any dev
  `gold.out_of_scope`). `attach()` copies it. Code never adds, edits or removes an entry. Raw
  reads the draft; validated and augmented the final answer.
- **Scoring** (metrics-design v1.2 draft, M10): correct iff answered and either some
  `uncovered_parts` string contains a content word of `gold.out_of_scope`, or one answer sentence
  holds a content word and a coverage cue. Same stop list, suffix rule and identifier exclusion
  for both branches. A non-empty field without a content word (e.g. `["n/a"]`) does not pass.
  S1 and S0 are scored by the prose branch only. Every report shows the pass route
  (`field` / `prose` / `both` / `neither`) and, for S4, the share of non-multi-part answers with
  a non-empty field (spurious-field diagnostic).

## Consequences

- Old records load (empty list). The S4 prompt gains one line and the draft schema one property
  that S1 does not have, both recorded in the parity test's allowed differences.
- The pass-route table shows how much S4 gains from the field over the prose branch alone.

## Alternatives rejected

- A code detector of second intents: a cue list tuned on 3 dev questions.
- Scoring the field only, or any non-empty field: S1 could never pass (rule 12), and a filler
  entry would score.
- S1 v3 with the field (policy option (b)): moves the frozen baseline a second time.
