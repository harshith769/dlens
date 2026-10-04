# 0017. Perturbation oracle as a third source of truth

- Status: Accepted
- Date: 2026-10-04
- Source: docs/DLENS_SPEC.md, Section 0, row 28
- Implemented in: S05 (A4)

## Context

Both the gold spec and the parser are now AI-written, so "isn't your gold biased toward your parser?" needs evidence, not process alone.

## Decision

On the synthetic corpus, `eval/oracle/perturb.py` perturbs each source column's values in DuckDB, re-runs the compiled models and records which output columns change. Changes missing from gold are spec bugs or SQL drift (fix the spec, never the parser). Unchanged gold edges are listed, not failed (expected for some FILTER/JOIN cases). Disagreements and decisions go in `corpora/synthetic_shop/ORACLE_REPORT.md`.

## Consequences

- A dynamic check neither the spec author nor the parser controls.
- Synthetic corpus only (needs data we generate).
- Owner time to decide each disagreement.

## Alternatives rejected

- Rely on design-first gold only: no independent evidence.
- Second parser as oracle: shares sqlglot's blind spots; C1 already compares with dbt-colibri.
