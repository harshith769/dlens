# 0028. Structured `interpretation {from, to}` on `Answer`

- Status: Proposed (S12b step 1, 20 Oct 2026; owner decisions s12-design B2 + B5 (a) and the B5
  addition, 20 Oct 2026; views approved with the S12b plan, 20 Oct 2026)
- Date: 2026-10-20
- Amends: spec §8 answer schema (additive)
- Implemented in: S12b (item B5)
- Evidence: docs/plans/s12-design.md "B2 + B5"; docs/plans/metrics-design.md M9 (v1.2 draft),
  §18, Appendix D; s1-design B5; ADR 0024 (the source-field precedent)

## Context

S4's interpreted near-misses exist only as the code-written lead "Interpreted A as B." in
`answer_text`. Metrics §18 asked for a structured `{from, to}`; s1-design B5 deferred S1's side to
S12. 0 dev questions carry `gold.interpretation`; test questions may. The owner asked that this
ADR state which views count the code-set value, with a source field, as ADR 0024 did for
`reach_verdict`.

## Decision

- Additive fields on `Answer`, both default `null`:
  - `interpretation: {from: str, to: str} | null`: `from` = the id as the question wrote it,
    `to` = the graph column code read it as;
  - `interpretation_source: "code" | "llm" | null`: who set it; `null` when `interpretation` is
    null. In S12 every value is `code`.
- Set **by code** in `Agent.ask` from the same `entity.dotted_column` result that writes the lead
  sentence (which stays). One interpretation per answer: the first, if code made several (the
  lead keeps all of them). The LLM never sets it; `AnswerDraft` has no such field.
- **Views:** the interpretation is decided before the answer phase (it is the linker's reading
  of the question, not a correction of the model's draft), so it counts in **raw, validated and
  augmented** alike. Metrics reads it from `final_answer` in every view. This differs from
  `reach_verdict` (ADR 0024), where a `code` value replaces the model's own verdict after
  validation and is therefore excluded from raw.
- **Scoring** (metrics-design v1.2 draft, M9): correct iff answered and `interpretation.to` is
  the gold column, or the text has a lead "Interpreted A as B." with B the gold column, or the
  gold column is a non-negated mention (M3 rules 3–4). S1 and S0 are scored by the prose branches
  only. Every report shows the pass route.

## Consequences

- Old records and presets load (null). The UI can show the interpretation without parsing prose.
- A later LLM-set interpretation (not planned) would be visible through the source field; metrics
  v1.2 does not filter on it.

## Alternatives rejected

- Prose lead only: metrics would keep parsing a sentence code already knows as data.
- An LLM-set field: the interpretation is decided by code (amendment C of the linker design).
- Excluding a code value from raw (the ADR 0024 rule): raw would then score S4 without the
  linker reading that every S4 answer is built on, which no other view or system lacks.
