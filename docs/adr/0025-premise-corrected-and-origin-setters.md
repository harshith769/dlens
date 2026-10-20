# 0025. Who sets `premise_corrected`, and the exact claim `origin` values (amends ADR 0015)

- Status: Proposed (S12 Phase 1, 20 Oct 2026)
- Date: 2026-10-20
- Amends: ADR 0015 (additive `premise_corrected` and claim `origin`). It does not restate 0015;
  the two fields, their types and their additivity stay as 0015 decided.
- Implemented in: S12b (G3)
- Evidence: docs/plans/s12-design.md B3; docs/plans/metrics-design.md M3 rule 5, M10

## Context

ADR 0015 added `premise_corrected: bool` to `Answer` and `origin` (`model`, `repaired`,
`completed`, `augmented`) to each claim, but left open two things that scoring now depends on:
who may set `premise_corrected` (M10 counts it as an explicit rejection), and exactly when a claim
is `repaired` or `completed` when both happen. It also has no value for the claim validator
salvage writes itself (code's R9 verdict claim), which is part of S4-validated, not augmented.

## Decision (proposed)

1. **`premise_corrected` is set by the LLM only**, through a draft field and one S4 prompt line.
   Code never sets or overrides it in S12. The S4-raw view reads the draft value. There is no
   source field (unlike `reach_verdict`, ADR 0024), because code never writes it.
2. **`origin` values, exactly:**
   - `model`: the claim as the LLM drafted it, ids unchanged;
   - `repaired`: at least one id replaced by R2r;
   - `completed`: at least one edge added by R8c (wins over `repaired` when both apply);
   - `augmented`: created by coverage completion (G1); counted only in S4-augmented (ADR 0016);
   - **`verdict` (new value):** code's verdict claim added by validator salvage after an R9
     failure; counted in S4-validated.
3. Code sets `origin` where it already acts (attach, R2r, R8c, salvage, G1). No validator rule
   outcome changes.

## Consequences

- M10's `premise_corrected` branch measures the model, never code; S1 (no field) is scored on the
  same rule through its negated-mention branch.
- Metrics needs no change: M3 already filters `origin: augmented` per view; `verdict` claims stay
  in validated like any non-augmented claim.
- Old records load with defaults (`premise_corrected` false, `origin` absent → read as `model`).

## Alternatives rejected

- A code premise detector (with a source field): no general detector to trust, and one built
  from the 4 dev false-premise questions would be tuned on dev.
- Labelling salvage's verdict claim `augmented`: it would move a validator output out of
  S4-validated.
