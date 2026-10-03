# 0003. Ablations need almost no LLM calls

- Status: Accepted
- Date: 2026-10-03
- Source: docs/DLENS_SPEC.md, Section 0, row 3

## Context

The original ablation design would cost about 2,500 calls.

## Decision

Run graph ablations through S0, linker ablations through the linker metric, and reuse logged S4 drafts for the no-validator ablation.

## Consequences

To be expanded in week 2 (spec Section 14).
