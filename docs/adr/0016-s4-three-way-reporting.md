# 0016. S4 reported raw / validated / augmented; yes/no scored on verdict

- Status: Accepted
- Date: 2026-10-04
- Source: docs/DLENS_SPEC.md, Section 0, rows 26 and 27
- Implemented in: S10 (verdict scoring in metrics), S12 (augmented view, G1)

## Context

The validator repairs, completes, regenerates and salvages; coverage completion (G1) will add claims from code. One S4 number would mix what the LLM did with what code added. Separately, dev-10 was a correct "No" with nothing to cite, so edge recall punished it.

## Decision

S4 is reported as three views:
- **S4 raw:** the agent's draft before the validator runs.
- **S4 validated:** after the full validator pipeline (R1–R9, R2r, R8c, regenerate-once, salvage). R8c-completed claims count here.
- **S4 augmented:** S4 validated plus G1 coverage-completion claims (`origin: augmented`).

These views are separate from the per-answer validator outcome labels (raw / repaired / completed / regenerated / salvaged), which stay. The view "S4 raw" is not the outcome "raw" (a draft that passed unchanged). Yes/no questions are scored on verdict accuracy.

## Consequences

- The no-validator ablation uses S4 raw at no extra cost.
- Readers see exactly how much code contributed.
- `metrics-design.md` must define all three views and verdict accuracy.

## Alternatives rejected

- Report only the final answer: hides code's contribution.
- Score yes/no by edge recall: penalises correct "No" answers.
