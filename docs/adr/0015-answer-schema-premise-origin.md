# 0015. Answer schema: premise_corrected and claim origin (additive)

- Status: Accepted
- Date: 2026-10-04
- Source: docs/DLENS_SPEC.md, Section 0, row 25
- Implemented in: S12 (G3)

## Context

The UI deferred a "corrected premise" badge because the agent had no real signal for it. Three-way S4 reporting needs to know which claims the model drafted and which code added.

## Decision

Add `premise_corrected: bool` to `Answer`, and `origin` to each claim: `model`, `repaired` (R2r), `completed` (R8c) or `augmented` (coverage completion). Both are additive; no existing field changes. `confidence` stays only for compatibility and is never used.

## Consequences

- The UI badge comes from a field, not a heuristic.
- S4-raw / validated / augmented can be computed from the run record.
- Section 7 public interfaces stay stable; old run records load with defaults.

## Alternatives rejected

- Infer origin by diffing draft and final answer: fragile.
- Remove `confidence`: breaks the schema for no gain.
