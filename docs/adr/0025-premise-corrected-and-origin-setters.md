# 0025. Who sets `premise_corrected`, and the exact claim `origin` values (amends ADR 0015)

- Status: Proposed (S12b step 1, 20 Oct 2026; owner decision s12-design B3, 20 Oct 2026)
- Date: 2026-10-20
- Amends: ADR 0015 (additive `premise_corrected` and claim `origin`). It does not restate 0015;
  the two fields, their types and their additivity stay as 0015 decided.
- Implemented in: S12b (G3, item B3)
- Evidence: docs/plans/s12-design.md B3; docs/plans/metrics-design.md M3 rule 5, M10 (v1.2 draft)

## Context

ADR 0015 added `premise_corrected: bool` to `Answer` and `origin` (`model`, `repaired`,
`completed`, `augmented`) to each claim, but left open who may set `premise_corrected` (M10
counts it as an explicit rejection) and exactly which value a claim gets when R2r and R8c both
act on it. It also has no value for the claim validator salvage writes itself (code's R9 verdict
claim), which belongs to S4-validated, not to S4-augmented.

## Decision

1. **`premise_corrected` is set by the LLM only.** `AnswerDraft` gains `premise_corrected: bool`
   (required in the draft schema, default false) and the S4 answer prompt gains one line (an
   S4-only appended line in the parity test's `ALLOWED_DIFFERENCES`, text in s12-design v1.2).
   `attach()` copies it. Code never sets or overrides it in S12. There is no source field
   (unlike `reach_verdict`, ADR 0024), because code never writes it. Raw reads the draft;
   validated and augmented read the final answer (the same value: no code path changes it).
2. **`origin` values, exactly** (`Claim.origin`, default `model`):
   - `model`: the claim as the LLM drafted it, ids unchanged;
   - `repaired`: at least one id replaced by R2r;
   - `completed`: at least one edge added by R8c; wins over `repaired` when both apply;
   - `augmented`: created by coverage completion (G1, item B1); counted only in S4-augmented
     (ADR 0016, metrics M3 rule 5);
   - **`verdict` (new value):** code's verdict claim added by validator salvage after an R9
     failure; counted in S4-validated.
3. Code sets `origin` only where it already acts (`attach`: `model`; R2r: `repaired`; R8c:
   `completed`; salvage: `verdict`; G1: `augmented`). **No validator rule outcome changes**; a
   test runs R1–R9 on the existing validator fixtures before and after and compares outcomes
   with the labels stripped.
4. **Scoring** (metrics-design v1.2 draft, M10): `premise_corrected` counts as a rejection only
   when the answer is answered and, in case O, does not keep a non-negated mention of the
   premise column; otherwise the prose (negated-mention) branch decides, for every system.

## Consequences

- M10's field branch measures the model, never code; S1 and S0 (no field) are scored by the same
  rule through the prose branch.
- Metrics reads `origin` as today (filters `augmented` per view); `verdict` claims stay in
  validated like any non-augmented claim.
- Old records load with defaults (`premise_corrected` false, `origin` absent → read as `model`).
- S4's draft schema is no longer byte-equal to S1's: the parity test lists the added property
  (`s4_schema_properties`, s12-design v1.2).

## Alternatives rejected

- A code premise detector (with a source field): no general detector to trust, and one built
  from the 4 dev false-premise questions would be tuned on dev.
- Labelling salvage's verdict claim `augmented`: it would move a validator output out of
  S4-validated.
