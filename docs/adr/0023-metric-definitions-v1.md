# 0023. Benchmark metric definitions v1

- Status: Accepted (owner, 19 Oct 2026: every decision in docs/plans/metrics-design.md v1.0;
  amended to v1.1 the same day: M7 "no" verdicts, M9 clarify, R3 diagnostic)
- Date: 2026-10-19
- Amends: spec §11.3 (S0 rows), §11.4 (metric list and meanings)
- Implemented in: S10 (D3, D2 S0 part): `eval/metrics.py`, `eval/systems/s0.py`
- Evidence: docs/plans/metrics-design.md (decisions M1–M16, Appendices A–C, change log)

## Context

Spec §11.4 listed metric names (node-set P/R/F1, path exact match, hallucinated-node rate,
citation validity, refusal and verdict accuracy, bootstrap CIs) without definitions, and said
they must be defined in an owner-approved design doc before `eval/metrics.py` exists. The S09
question set stores gold in two modes (direct, direct + indirect) wherever they differ (50 of
96 dev questions), S1 (vector RAG) cites chunks, not edges, and yes/no answers have no
structured verdict yet. Each of these needed a decision before any number could be compared.

## Decision

The definitions in docs/plans/metrics-design.md v1.0 are the benchmark's metrics. In short:
- **One prose extractor for every system** (dotted ids filtered against the gold inventory, a
  fixed negation rule with a tested sentence list, CTE references kept apart); structured
  extraction is an S0/S4 diagnostic only.
- **Primary mode per question from its wording family** (Appendix A: trace family direct,
  impact family direct + indirect); both modes are always computed and reported.
- **Headline sets:** trace upstream = upstream closure F1; computed / false premise = strict
  inputs F1; impact = columns, models, exposures scored separately. **Node-set F1** (the resume
  line) pools 68 dev questions: trace F1 (44) and impact F1 (24).
- **Yes/no** is scored only on a structured `reach_verdict` (S11/S12 field); prose heuristics are
  diagnostics.
- **Path exact match is renamed path node coverage** (order-free); McNemar uses "question fully
  correct".
- **Citation validity** is re-checked on disk by metrics itself (direct edge → `to` column,
  indirect → `from` column, clause key only under a CTE / derived-alias guard); an answered
  answer with no citation is invalid, except one whose own structured verdict is "no" (n/a:
  nothing to cite, v1.1); citation coverage is reported.
- **Refusals / clarifications** read the schema fields; a clarify-gold question is also correct
  when the answer names every gold candidate (v1.1); false-refusal rate is added; false-premise
  rejection needs positive evidence (a negated mention or `premise_corrected`).
- **Aggregation:** macro over questions; a non-answer on an answerable question scores 0 even on
  an empty gold set; bootstrap 1,000×, seed 20261019, CI only for n ≥ 10; exact McNemar.
- **S0 is two systems:** S0-gold (no linker) and S0-linked (linker, no LLM, same hybrid flag as
  the S4 runs it is compared with).

## Consequences

- metrics.py imports only `dlens.gold_spec`, the standard library and a YAML parser; a test
  enforces that it never imports the system under test.
- S4 cannot score on yes/no or indirect-only gold until S12 adds `reach_verdict` and indirect
  traversal in its tools; S1 must emit `reach_verdict`, refusals and clarifications through the
  schema fields and `model.column` ids (S11). The full list is metrics-design.md §18.
- Every scored report names the metrics-design version and `metrics.py` `__version__`. A metric
  bug is fixed with a test and a change-log line, never to move a result.
- The three questions raised by the first scoring (S10) were decided by the owner in v1.1:
  correct "No" verdicts with nothing to cite are n/a for per-answer citation validity; a
  clarify-gold question accepts a clarification or a per-candidate answer naming every candidate
  (spec §8 and dev.jsonl unchanged); the R3-disagreement diagnostic counts only ids R3 checked.
