# 0028. Structured `interpretation {from, to}` on `Answer`

- Status: Proposed (S12 Phase 1, 20 Oct 2026)
- Date: 2026-10-20
- Amends: spec §8 answer schema (additive)
- Implemented in: S12b (B5)
- Evidence: docs/plans/s12-design.md "B2 + B5"; metrics-design M9, §18; s1-design B5

## Context

S4's interpreted near-misses exist only as the code-written lead "Interpreted A as B." in
`answer_text`. Metrics §18 asked for a structured `{from, to}`; s1-design B5 deferred S1's side to
S12. 0 dev questions carry `gold.interpretation`; test questions may.

## Decision (proposed)

- Additive `Answer.interpretation: {from: str, to: str} | null`, set **by code** from the same
  `entity.dotted_column` result that writes the lead sentence (which stays). The LLM never sets it.
- Scoring is decided separately (s12-design "B2 + B5" policy; metrics-design v1.2 draft): under
  the recommended policy the field, the lead sentence, or a non-negated mention of the gold column
  in an answered answer satisfies M9 for every system.

## Consequences

- Old records and presets load (null). The UI can show the interpretation without parsing prose.

## Alternatives rejected

- Prose lead only: metrics would keep parsing a sentence code already knows as data.
- An LLM-set field: the interpretation is decided by code (amendment C of the linker design).
